"""Test de paridad cross-service del `aveonline_client.py`.

Rev. 107. El cliente Aveonline vive en DOS ubicaciones byte-equal:
  • services/api/integrations/aveonline_client.py (master)
  • services/ai-orchestrator/integrations/aveonline_client.py (copia)

Patrón "shared code via duplicación deliberada" justificado porque api y
ai-orchestrator son procesos separados sin packaging Python compartido
(mismo patrón que `llm_embed.py` rev. 106).

Este test detecta drift: si un commit modifica solo uno de los archivos,
falla con mensaje explícito indicando comando de re-sync. Previene que
una mejora en api/ no se propague a ai-orchestrator/ (o viceversa) y
deje los servicios con comportamiento divergente.

Cuando se consolide el package compartido `packages/python-shared/`
(plan K Sem 12), este test se reemplaza por importar de un solo lugar.
"""
import hashlib
import os
import unittest


_MASTER_PATH = (
    "/home/ansible/workspaces/commerce-ops-platform/"
    "services/api/integrations/aveonline_client.py"
)
_COPY_PATH = (
    "/home/ansible/workspaces/commerce-ops-platform/"
    "services/ai-orchestrator/integrations/aveonline_client.py"
)


class AveonlineClientParityTests(unittest.TestCase):

    def test_master_y_copia_byte_equal(self):
        """MD5(master) == MD5(copy). Si falla, drift detectado."""
        with open(_MASTER_PATH, "rb") as f:
            master_hash = hashlib.md5(f.read()).hexdigest()
        with open(_COPY_PATH, "rb") as f:
            copy_hash = hashlib.md5(f.read()).hexdigest()
        self.assertEqual(
            master_hash, copy_hash,
            "Drift detectado en aveonline_client.py.\n"
            f"  master ({_MASTER_PATH}): {master_hash}\n"
            f"  copia  ({_COPY_PATH}): {copy_hash}\n"
            "Re-sincronizar con:\n"
            f"  cp {_MASTER_PATH} {_COPY_PATH}",
        )

    def test_ambos_archivos_existen(self):
        """Verifica que ambos archivos están presentes en el repo."""
        self.assertTrue(
            os.path.isfile(_MASTER_PATH),
            f"Master file missing: {_MASTER_PATH}",
        )
        self.assertTrue(
            os.path.isfile(_COPY_PATH),
            f"Copy file missing: {_COPY_PATH}",
        )

    def test_master_y_copia_tienen_misma_api_publica(self):
        """Validación semántica: ambos exponen las mismas clases/funciones
        públicas. Backup en caso de modificación parcial accidental que
        afecte API sin cambiar MD5 (improbable pero defensivo)."""
        import sys

        # Importar master (api).
        sys.path.insert(
            0,
            "/home/ansible/workspaces/commerce-ops-platform/services/api",
        )
        import importlib
        if "integrations.aveonline_client" in sys.modules:
            del sys.modules["integrations.aveonline_client"]
        master_mod = importlib.import_module("integrations.aveonline_client")
        master_api = {
            name for name in dir(master_mod)
            if not name.startswith("_") or name in (
                "_normalize_for_match", "_resolve_rate_id_fuzzy",  # ejemplo
            )
        }

        # Cleanup sys.modules + path para importar copia.
        del sys.modules["integrations.aveonline_client"]
        sys.path.pop(0)
        sys.path.insert(
            0,
            "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
        )
        copy_mod = importlib.import_module("integrations.aveonline_client")
        copy_api = {name for name in dir(copy_mod) if not name.startswith("_")}

        # Public API debe coincidir.
        master_public = {n for n in dir(master_mod) if not n.startswith("_")}
        self.assertEqual(
            master_public, copy_api,
            f"API pública divergente.\n"
            f"  Solo en master: {master_public - copy_api}\n"
            f"  Solo en copia:  {copy_api - master_public}",
        )


if __name__ == "__main__":
    unittest.main()
