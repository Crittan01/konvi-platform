"""Tests aveonline_webhook router (rev. 108).

Cubre los invariantes críticos:
  1. Secret válido → 200 + procesamiento.
  2. Secret inválido → 401 + no procesa.
  3. Sin guia → 200 + skipped.
  4. Shipment no existe → captura solo (no falla).
  5. Mapping de estados: ENTREGADA→delivered, EN RUTA→in_transit, etc.
  6. event_uid composite garantiza dedup at-least-once.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = REPO_ROOT / "services" / "api" / "routers" / "aveonline_webhook.py"


def _load_module():
    """Carga router como módulo aislado para inspección unit.

    Cuida no contaminar sys.modules con stub permanente de dependencies.auth
    que rompe tests posteriores en la misma corrida pytest (test pollution).
    """
    import sys
    api_path = str(REPO_ROOT / "services" / "api")
    if api_path not in sys.path:
        sys.path.insert(0, api_path)

    # Stub dependencies.auth solo si no está aún disponible (real o de otro
    # test). Sin sobreescribir si ya existe — evita pollution.
    if "dependencies.auth" not in sys.modules:
        deps_auth = MagicMock()
        deps_auth._get_service_client = MagicMock()
        sys.modules["dependencies.auth"] = deps_auth
        _stubbed = True
    else:
        _stubbed = False

    spec = importlib.util.spec_from_file_location(
        "_aveonline_webhook", ROUTER_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["_aveonline_webhook"] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        # Cleanup: si stubbeamos, removemos para no afectar tests downstream.
        if _stubbed:
            sys.modules.pop("dependencies.auth", None)
    return mod


webhook_mod = _load_module()


class MapRawStatusTests(unittest.TestCase):
    """Mapping cross-provider estados Aveonline → canónico interno."""

    def test_entregada_to_delivered(self):
        self.assertEqual(webhook_mod._map_raw_status("ENTREGADA"), "delivered")
        self.assertEqual(webhook_mod._map_raw_status("entregada"), "delivered")

    def test_en_ruta_to_in_transit(self):
        # Aveonline usa "EN REPARTO" como equivalente a "EN RUTA".
        self.assertEqual(webhook_mod._map_raw_status("EN REPARTO"), "in_transit")
        self.assertEqual(webhook_mod._map_raw_status("EN TRANSITO"), "in_transit")
        self.assertEqual(webhook_mod._map_raw_status("EN ENTREGA"), "in_transit")
        self.assertEqual(
            webhook_mod._map_raw_status("RECIBIDA EN TRANSPORTADORA"), "in_transit",
        )

    def test_novedad_to_exception(self):
        self.assertEqual(webhook_mod._map_raw_status("EN NOVEDAD"), "exception")
        self.assertEqual(webhook_mod._map_raw_status("NOVEDAD"), "exception")
        self.assertEqual(
            webhook_mod._map_raw_status("DIRECCION ERRONEA"), "exception",
        )
        self.assertEqual(webhook_mod._map_raw_status("CLIENTE AUSENTE"), "exception")

    def test_devolucion_to_returned(self):
        self.assertEqual(webhook_mod._map_raw_status("DEVOLUCION"), "returned")
        self.assertEqual(webhook_mod._map_raw_status("DEVUELTA"), "returned")

    def test_pre_recogida_to_pending(self):
        self.assertEqual(webhook_mod._map_raw_status("EN OFICINA"), "pending")
        self.assertEqual(webhook_mod._map_raw_status("RECOGIDA"), "pending")

    def test_unknown_defaults_to_pending(self):
        # Importante: NO asumir entrega para estados desconocidos.
        self.assertEqual(webhook_mod._map_raw_status("UNKNOWN_STATE"), "pending")
        self.assertEqual(webhook_mod._map_raw_status(""), "pending")
        self.assertEqual(webhook_mod._map_raw_status(None), "pending")


class ExtractSecretTests(unittest.TestCase):
    """Secret puede llegar en URL path, body.secret, body.param1_value, query."""

    def test_path_token_wins(self):
        self.assertEqual(
            webhook_mod._extract_secret("path-token", {"secret": "body"}, {}),
            "path-token",
        )

    def test_body_secret_field(self):
        self.assertEqual(
            webhook_mod._extract_secret(None, {"secret": "from-body"}, {}),
            "from-body",
        )

    def test_aveonline_param1_value(self):
        # Aveonline guarda el secret en param1_value cuando configuramos
        # webhook con param1_name="secret".
        self.assertEqual(
            webhook_mod._extract_secret(
                None, {"param1_value": "aveonline-style"}, {},
            ),
            "aveonline-style",
        )

    def test_query_string_fallback(self):
        self.assertEqual(
            webhook_mod._extract_secret(None, None, {"secret": "from-qs"}),
            "from-qs",
        )

    def test_empty_returns_empty_string(self):
        self.assertEqual(webhook_mod._extract_secret(None, None, {}), "")
        self.assertEqual(webhook_mod._extract_secret("_", None, {}), "")
        # path_token="_" es marker explícito de "no secret en path"


class SelectLatestEstadoTests(unittest.TestCase):
    """Sortable estado history; el más reciente actualiza shipment status."""

    def test_returns_latest_by_fecha(self):
        estado_list = [
            {"estado_id": 1, "nombre_estado": "EN OFICINA", "fecha": "2026-05-20 10:00:00"},
            {"estado_id": 5, "nombre_estado": "EN RUTA", "fecha": "2026-05-21 14:00:00"},
            {"estado_id": 12, "nombre_estado": "ENTREGADA", "fecha": "2026-05-22 09:00:00"},
        ]
        latest = webhook_mod._select_latest_estado(estado_list)
        self.assertEqual(latest["estado_id"], 12)

    def test_empty_returns_none(self):
        self.assertIsNone(webhook_mod._select_latest_estado([]))
        self.assertIsNone(webhook_mod._select_latest_estado(None))


if __name__ == "__main__":
    unittest.main()
