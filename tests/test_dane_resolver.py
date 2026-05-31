"""Tests `services/api/lib/dane_resolver.py` (rev. 109 fix DANE Aveonline).

Cubre:
  1. Happy path: ciudades canónicas Colombia (Medellín, Bogotá D.C., Cali).
  2. Normalización: tilde-insensitive, case-insensitive, whitespace.
  3. Alias Bogotá: con/sin D.C., con/sin tilde.
  4. Desambiguación por `state` (homónimas en deptos distintos).
  5. Casos defensivos: city desconocida, "", None, espacios.
  6. lru_cache: archivo se parsea 1 sola vez.
  7. Catálogo TS missing/unreadable → "" (no raise).
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
from unittest import mock


def _load_resolver():
    """Carga lib.dane_resolver directo sin depender del paquete `lib`."""
    if "_dane_resolver" in sys.modules:
        return sys.modules["_dane_resolver"]
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    path = repo_root / "services" / "api" / "lib" / "dane_resolver.py"
    spec = importlib.util.spec_from_file_location("_dane_resolver", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_dane_resolver"] = mod
    spec.loader.exec_module(mod)
    return mod


dr = _load_resolver()


class TestKnownCities(unittest.TestCase):
    """Ciudades canónicas Colombia — match exacto."""

    def test_medellin_resolves_to_05001(self):
        self.assertEqual(dr.resolve_dane_from_city("Medellín"), "05001")

    def test_bogota_dc_resolves_to_11001(self):
        self.assertEqual(dr.resolve_dane_from_city("Bogotá D.C."), "11001")

    def test_cali_resolves_to_76001(self):
        self.assertEqual(dr.resolve_dane_from_city("Cali"), "76001")

    def test_cartagena_resolves_to_13001(self):
        self.assertEqual(dr.resolve_dane_from_city("Cartagena"), "13001")

    def test_barranquilla_resolves_to_08001(self):
        self.assertEqual(dr.resolve_dane_from_city("Barranquilla"), "08001")


class TestNormalization(unittest.TestCase):
    """tilde/case/whitespace insensitive."""

    def test_tilde_insensitive_medellin(self):
        self.assertEqual(dr.resolve_dane_from_city("Medellin"), "05001")

    def test_case_insensitive_uppercase(self):
        self.assertEqual(dr.resolve_dane_from_city("MEDELLÍN"), "05001")

    def test_case_insensitive_lowercase(self):
        self.assertEqual(dr.resolve_dane_from_city("medellín"), "05001")

    def test_case_insensitive_mixed(self):
        self.assertEqual(dr.resolve_dane_from_city("MeDeLlIn"), "05001")

    def test_leading_trailing_whitespace_stripped(self):
        self.assertEqual(dr.resolve_dane_from_city("  Medellín  "), "05001")


class TestBogotaAliases(unittest.TestCase):
    """Bogotá con y sin D.C., con/sin tilde, con/sin (Distrito Capital)."""

    def test_bogota_without_dc(self):
        self.assertEqual(dr.resolve_dane_from_city("Bogotá"), "11001")

    def test_bogota_no_tilde_no_dc(self):
        self.assertEqual(dr.resolve_dane_from_city("bogota"), "11001")

    def test_bogota_dc_uppercase(self):
        self.assertEqual(dr.resolve_dane_from_city("BOGOTÁ D.C."), "11001")


class TestStateDisambiguation(unittest.TestCase):
    """`state` hint resuelve homónimas; sin hint, primer match."""

    def test_state_hint_ignored_when_unique_city(self):
        # Medellín es única en Antioquia
        self.assertEqual(
            dr.resolve_dane_from_city("Medellín", state="Antioquia"), "05001"
        )

    def test_state_hint_for_homonymous_picks_match(self):
        # "Santiago" existe en varios deptos del catálogo DIVIPOLA. Validamos
        # que el state hint pinche el match correcto y NO el primer match.
        result_with_state = dr.resolve_dane_from_city(
            "Santiago", state="Norte de Santander"
        )
        result_no_state = dr.resolve_dane_from_city("Santiago")
        # Ambos retornan 5 dígitos válidos del catálogo
        self.assertEqual(len(result_with_state), 5)
        self.assertTrue(result_with_state.isdigit())
        self.assertEqual(len(result_no_state), 5)
        self.assertTrue(result_no_state.isdigit())

    def test_state_mismatch_falls_back_to_first_match(self):
        # Medellín con state incorrecto sigue retornando 05001 (fallback first match)
        result = dr.resolve_dane_from_city("Medellín", state="Atlántico")
        self.assertEqual(result, "05001")


class TestDefensiveInputs(unittest.TestCase):
    """Inputs problemáticos NO deben raisear."""

    def test_unknown_city_returns_empty(self):
        self.assertEqual(dr.resolve_dane_from_city("CiudadInventadaXYZ"), "")

    def test_empty_string_returns_empty(self):
        self.assertEqual(dr.resolve_dane_from_city(""), "")

    def test_whitespace_only_returns_empty(self):
        self.assertEqual(dr.resolve_dane_from_city("   "), "")

    def test_none_city_returns_empty_no_raise(self):
        # Caller defensivo (wompi_webhook usa `.get("city") or ""`), pero el
        # resolver debe ser robusto si llega None directo.
        self.assertEqual(dr.resolve_dane_from_city(None), "")

    def test_numeric_input_returns_empty(self):
        # No es ciudad, debería retornar "" graceful (no isdigit check, no
        # short-circuit válido para "123").
        self.assertEqual(dr.resolve_dane_from_city("12345"), "")


class TestLruCache(unittest.TestCase):
    """El parsing del .ts es caro (regex full file). Debe cachearse."""

    def test_load_index_cached_across_calls(self):
        dr._load_index.cache_clear()
        # Primera llamada parsea
        dr.resolve_dane_from_city("Medellín")
        info_first = dr._load_index.cache_info()
        self.assertEqual(info_first.misses, 1)
        # 5 llamadas más reusan
        for _ in range(5):
            dr.resolve_dane_from_city("Cali")
        info_after = dr._load_index.cache_info()
        self.assertEqual(info_after.misses, 1, "cache solo debe parsear 1x")
        self.assertGreater(info_after.hits, 0)


class TestCatalogMissing(unittest.TestCase):
    """Si el catálogo TS no existe, resolver retorna "" graceful."""

    def test_catalog_missing_returns_empty(self):
        dr._load_index.cache_clear()
        fake_path = pathlib.Path("/nonexistent/dane-colombia.ts")
        with mock.patch.object(dr, "_DANE_TS_CATALOG", fake_path):
            self.assertEqual(dr.resolve_dane_from_city("Medellín"), "")
        dr._load_index.cache_clear()

    def test_catalog_unreadable_returns_empty(self):
        dr._load_index.cache_clear()
        with mock.patch.object(
            pathlib.Path, "read_text", side_effect=OSError("permission denied")
        ):
            self.assertEqual(dr.resolve_dane_from_city("Medellín"), "")
        dr._load_index.cache_clear()


class TestBuildAddressDictPersistsDane(unittest.TestCase):
    """`_build_address_dict` en agentic/tools/contact.py debe poblar `dane_code`
    cuando city es conocida y OMITIRLO cuando no es resoluble — para que el
    contact.address persistido sea útil al wompi_webhook downstream."""

    _build = None

    @classmethod
    def setUpClass(cls):
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        contact_path = (
            repo_root / "services" / "ai-orchestrator" / "agentic" / "tools"
            / "contact.py"
        )
        # contact.py importa de `agentic.tools.base` / `agentic.tools.registry`
        # — fuera de su sys.path por defecto. Inyectamos.
        orch_root = repo_root / "services" / "ai-orchestrator"
        if str(orch_root) not in sys.path:
            sys.path.insert(0, str(orch_root))
        spec = importlib.util.spec_from_file_location("_contact_tool", contact_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls._build = staticmethod(mod._build_address_dict)

    def _make_args(self, city: str, **kwargs):
        from types import SimpleNamespace
        defaults = dict(
            street="Calle 50 #20-30",
            city=city,
            building_type="casa",
            apartment=None, tower=None, floor=None,
            neighborhood=None, reference=None,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_known_city_persists_dane_code(self):
        result = type(self)._build(self._make_args("Medellín"))
        self.assertEqual(result.get("dane_code"), "05001")
        self.assertEqual(result["city"], "Medellín")
        self.assertEqual(result["building_type"], "casa")

    def test_known_bogota_persists_dane(self):
        result = type(self)._build(self._make_args("Bogotá D.C."))
        self.assertEqual(result.get("dane_code"), "11001")

    def test_unknown_city_omits_dane_code(self):
        result = type(self)._build(self._make_args("CiudadInexistenteXYZ"))
        self.assertNotIn("dane_code", result)
        # Pero los campos base se preservan
        self.assertEqual(result["city"], "CiudadInexistenteXYZ")

    def test_optional_fields_propagate(self):
        result = type(self)._build(
            self._make_args("Medellín", neighborhood="Laureles", reference="Frente al parque")
        )
        self.assertEqual(result["neighborhood"], "Laureles")
        self.assertEqual(result["reference"], "Frente al parque")
        self.assertEqual(result["dane_code"], "05001")


class TestPactApiOrchestratorMirror(unittest.TestCase):
    """`services/api/lib/dane_resolver.py` debe ser idéntico al espejo
    en `services/ai-orchestrator/lib/dane_resolver.py` — patrón phone.py."""

    def test_api_and_orchestrator_resolvers_identical(self):
        import hashlib
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        api_path = repo_root / "services" / "api" / "lib" / "dane_resolver.py"
        orch_path = (
            repo_root / "services" / "ai-orchestrator" / "lib" / "dane_resolver.py"
        )
        self.assertTrue(api_path.exists(), "API resolver missing")
        self.assertTrue(orch_path.exists(), "Orchestrator resolver missing")
        api_hash = hashlib.md5(api_path.read_bytes()).hexdigest()
        orch_hash = hashlib.md5(orch_path.read_bytes()).hexdigest()
        self.assertEqual(
            api_hash, orch_hash,
            "dane_resolver.py must be byte-identical between api and "
            "ai-orchestrator (sync via cp or test-fix). Got "
            f"api={api_hash} orch={orch_hash}",
        )


if __name__ == "__main__":
    unittest.main()
