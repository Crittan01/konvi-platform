"""BLOQUE M1 — cota de memoria del cache HMAC del connector (DoS defense).

El endpoint del connector es internet-facing. Una request con `sha256=xx` a
/webhook/{uuid-aleatorio} dispara la resolución del secret del tenant → cachea
None (negative cache) ANTES de que falle el HMAC. El TTL de `_cache_get` es lazy
(solo evict al re-acceder), así que un flood de UUIDs aleatorios —que nunca se
re-acceden— crecía el cache sin límite. `_cache_put` ahora aplica maxsize +
barrido activo + evicción del más viejo. Este test lo blinda.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_PATH = REPO_ROOT / "services" / "connector-whatsapp"


def _load_meta():
    if str(CONNECTOR_PATH) not in sys.path:
        sys.path.insert(0, str(CONNECTOR_PATH))
    spec = importlib.util.spec_from_file_location(
        "_test_cache_bound_meta", str(CONNECTOR_PATH / "dependencies" / "meta.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_cache_bound_meta"] = mod
    spec.loader.exec_module(mod)
    return mod


_meta = _load_meta()


class HmacCacheBoundTests(unittest.TestCase):

    def test_flood_de_uuids_no_crece_sin_limite(self):
        cache = {}
        # Simula el flood: 10x el maxsize de negative-cache entries (value=None).
        n = _meta._CACHE_MAXSIZE * 10
        for i in range(n):
            _meta._cache_put(cache, f"attacker-uuid-{i}", None)
        self.assertLessEqual(
            len(cache), _meta._CACHE_MAXSIZE,
            f"cache creció a {len(cache)} > maxsize {_meta._CACHE_MAXSIZE}",
        )

    def test_entradas_recientes_sobreviven_al_flood(self):
        cache = {}
        # Inserta una entrada válida reciente, luego floodea.
        _meta._cache_put(cache, "tenant-valido", "secret-xyz")
        for i in range(_meta._CACHE_MAXSIZE * 3):
            _meta._cache_put(cache, f"flood-{i}", None)
        # La entrada válida es de las MÁS VIEJAS → puede haber sido evictada por el
        # flood (correcto: LRU/FIFO). Lo que garantizamos es la COTA, no retención
        # de la más vieja. Verificamos que las últimas insertadas sobreviven.
        hit, val = _meta._cache_get(cache, f"flood-{_meta._CACHE_MAXSIZE * 3 - 1}")
        self.assertTrue(hit)
        self.assertIsNone(val)
        self.assertLessEqual(len(cache), _meta._CACHE_MAXSIZE)

    def test_sweep_elimina_expirados(self):
        import time
        cache = {}
        # Entrada ya expirada (expiry en el pasado).
        cache["viejo"] = ("v", time.time() - 1)
        _meta._sweep_expired(cache)
        self.assertNotIn("viejo", cache)


if __name__ == "__main__":
    unittest.main()
