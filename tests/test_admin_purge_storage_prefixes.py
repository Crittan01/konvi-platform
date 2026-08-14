"""G8a — purge_tenant_storage.py cubre AMBOS prefijos del tenant.

Antes el script admin (purga física vía Storage API) solo listaba/borraba
'{tenant_id}/' → los objetos bajo 'inbox-attachments/{tenant_id}/' sobrevivían
al hard-delete. Ahora itera los 2 prefijos por bucket.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "admin"))

import purge_tenant_storage as pts  # noqa: E402


class _FakeBucket:
    """Emula sb.storage.from_(bucket).list()/.remove() con un árbol en memoria."""
    def __init__(self, objects: list[str]):
        self._objects = objects  # rutas completas tipo 'inbox-attachments/t1/conv/1.png'
        self.removed: list[str] = []
        self.listed_paths: list[str] = []

    def list(self, path, options=None):
        self.listed_paths.append(path)
        # Devuelve archivos directos bajo `path` (sin subcarpetas para el test)
        prefix = f"{path}/" if path else ""
        out = []
        for obj in self._objects:
            if not obj.startswith(prefix):
                continue
            rest = obj[len(prefix):]
            if "/" in rest:
                # subcarpeta: devolver como placeholder de carpeta (id None)
                folder_name = rest.split("/", 1)[0]
                out.append({"id": None, "name": folder_name})
            else:
                out.append({"id": "x", "name": rest})
        # dedup de placeholders de carpeta
        seen = set()
        dedup = []
        for e in out:
            key = (e["id"], e["name"])
            if key not in seen:
                seen.add(key)
                dedup.append(e)
        return dedup

    def remove(self, batch):
        self.removed.extend(batch)
        for obj in batch:
            if obj in self._objects:
                self._objects.remove(obj)


def _sb_with(objects: list[str]):
    bucket = _FakeBucket(objects)
    sb = MagicMock()
    sb.storage.from_ = MagicMock(return_value=bucket)
    return sb, bucket


class PurgeAmbosPrefijosTests(unittest.TestCase):
    def test_lista_y_borra_los_dos_prefijos(self):
        objects = [
            "t-1/logo/logo.png",
            "inbox-attachments/t-1/conv-1/img.png",
            "t-2/logo/logo.png",                        # otro tenant: intacto
            "inbox-attachments/t-2/conv-9/x.png",       # otro tenant: intacto
        ]
        sb, bucket = _sb_with(objects)
        report = pts.purge_tenant_storage(sb, "t-1", buckets=("b",), dry_run=False)

        self.assertEqual(report["b"]["listed"], 2)
        self.assertEqual(report["b"]["removed"], 2)
        # borró solo los del tenant objetivo, en ambos prefijos
        self.assertIn("t-1/logo/logo.png", bucket.removed)
        self.assertIn("inbox-attachments/t-1/conv-1/img.png", bucket.removed)
        self.assertNotIn("t-2/logo/logo.png", bucket.removed)
        self.assertNotIn("inbox-attachments/t-2/conv-9/x.png", bucket.removed)
        # se listaron los 2 prefijos del tenant
        self.assertIn("t-1", bucket.listed_paths)
        self.assertIn("inbox-attachments/t-1", bucket.listed_paths)

    def test_dry_run_cuenta_sin_borrar(self):
        objects = ["t-1/a.png", "inbox-attachments/t-1/c/b.png"]
        sb, bucket = _sb_with(objects)
        report = pts.purge_tenant_storage(sb, "t-1", buckets=("b",), dry_run=True)
        self.assertEqual(report["b"]["listed"], 2)
        self.assertEqual(report["b"]["removed"], 0)
        self.assertEqual(bucket.removed, [])

    def test_bucket_protegido_nunca_se_lista(self):
        sb, bucket = _sb_with([])
        report = pts.purge_tenant_storage(
            sb, "t-1", buckets=("offboarding-archive",), dry_run=False
        )
        self.assertEqual(report, {})  # el bucket protegido ni se toca


if __name__ == "__main__":
    unittest.main()
