"""UAT endpoint `POST /integrations/aveonline/guide-dry-run` — schema real de tenants.

Regresión del bug encontrado en la UAT de guía real 2026-08-03: el endpoint
pedía columnas planas `shipping_origin_city/state/dane/address/nit/phone/email,
idagente` de `tenants`, que NO existen (PostgREST 400). El origen vive en el
jsonb `tenants.shipping_origin` y el `idagente` en las credenciales de la
integración (mismo patrón que `aveonline_client.generate_guide`).

Verifica:
  • El select de tenants pide el jsonb (no columnas planas inexistentes).
  • sender/origin se construyen desde el jsonb + columnas planas de contacto,
    igual que el flujo real (wompi_webhook._generate_shipping_guide_async).
  • diagnostics.tenant_idagente viene de las credenciales, no de tenants.
  • Tenant sin shipping_origin completo → 422 (validación del flujo real).
  • simulate=False con kill-switch/master off → se fuerza simulate=True.
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))


def _purge_foreign_integrations(service_dir: str = "api") -> None:
    """El paquete `integrations` existe en services/api Y services/ai-orchestrator.

    Si otro test de la suite (mismo proceso pytest) ya cargó el paquete del
    OTRO servicio en sys.modules, lo purgo para que los imports de ESTE archivo
    resuelvan al servicio correcto sin importar el orden de colección.
    (Fallo real en CI 2026-08-07: '_Sb' object has no attribute 'rpc' bajo xdist.)
    """
    for name in [n for n in list(sys.modules)
                 if n == "integrations" or n.startswith("integrations.")]:
        mod = sys.modules[name]
        paths = [getattr(mod, "__file__", None),
                 *(getattr(mod, "__path__", None) or [])]
        paths = [str(p).replace("\\", "/") for p in paths if p]
        if not any(f"/services/{service_dir}/" in p for p in paths):
            del sys.modules[name]


_purge_foreign_integrations("api")

from fastapi import HTTPException  # noqa: E402

import integrations.aveonline_client as ave_mod  # noqa: E402,F401 — ver _call
from routers.integrations import (  # noqa: E402
    AveonlineGuideDryRunReq,
    aveonline_guide_dry_run,
)

TID = "tenant-abc"
ORDER_ID = "order-12345678"


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, sb, table):
        self._sb = sb
        self._table = table

    def select(self, cols="*", *_a, **_k):
        self._sb.selects[self._table] = cols
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _Res(self._sb.rows.get(self._table))


class _Sb:
    """Supabase falso mínimo: una fila precargada por tabla."""

    def __init__(self, rows):
        self.rows = rows
        self.selects = {}

    def table(self, name):
        return _Q(self, name)


class _FakeAveClient:
    """Sustituye AveonlineClient: captura generate_guide, creds con idagente."""

    last = None

    def __init__(self, supabase=None, tenant_id=None):
        self.calls = {}
        _FakeAveClient.last = self

    async def _load_credentials(self, force_refresh=False):
        return {"idagente": "AG-9001", "empresa_id": "E-1"}

    async def generate_guide(self, **kwargs):
        self.calls["generate_guide"] = kwargs
        return {"ok": True, "tracking_number": "999000111", "label_url": "https://x/l.pdf"}


def _rows(tenant):
    return {
        "orders": {
            "id": ORDER_ID,
            "total_amount": 15000,
            "shipping_cost": 5000,
            "contacts": {
                "name": "UAT Contact",
                "phone": "3001112233",
                "email": "uat@x.co",
                "shipping_phone": None,
                "document_type": "CC",
                "document_number": "123456",
                "address": {
                    "street": "Cra 1 # 1-1",
                    "city": "Bogotá",
                    "state": "Cundinamarca",
                    "dane_code": "11001",
                },
            },
        },
        "conversation_carts": [{
            "shipping_meta": {
                "rate_id": "T1",
                "carrier": "SERVIENTREGA",
                "dane_code": "11001",
                "service_level": "estandar",
                "weight_inputs": {
                    "weight_kg": 0.7, "length_cm": 20,
                    "width_cm": 12, "height_cm": 6,
                },
            },
        }],
        "tenants": tenant,
        "tenant_shipping_provider_config": {"real_guides_enabled": False},
    }


def _tenant_ok():
    return {
        "id": TID,
        "name": "Shop",
        "nit": "900123",
        "telefono_contacto": "3001112233",
        "email_contacto": "shop@x.co",
        "shipping_origin": {
            "city": "Bogotá", "state": "Cundinamarca", "street": "Cra 1 # 1-1",
            "dane_code": "11001", "name": "Bodega", "phone": "3001112233",
        },
    }


class GuideDryRunTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, sb, simulate=True):
        req = AveonlineGuideDryRunReq(order_id=ORDER_ID, simulate=simulate)
        # El endpoint lazy-importa AveonlineClient EN CALL TIME → el patch debe
        # caer sobre la copia que sys.modules resuelva AHÍ (si tests/agentic corrió
        # antes, `integrations.aveonline_client` puede ser la copia del orchestrator
        # y patchear `ave_mod` — resuelto en import time — no surte efecto).
        import integrations.aveonline_client as runtime_ave_mod

        with patch.object(runtime_ave_mod, "AveonlineClient", _FakeAveClient):
            return await aveonline_guide_dry_run(
                req=req, tenant_id=TID, role="owner", supabase=sb,
            )

    async def test_select_pide_jsonb_no_columnas_planas(self):
        """Regresión: el select de tenants NO puede pedir shipping_origin_city
        ni idagente (columnas inexistentes → PostgREST 400)."""
        sb = _Sb(_rows(_tenant_ok()))
        r = await self._call(sb)
        self.assertTrue(r["ok"])
        cols = sb.selects["tenants"]
        self.assertIn("shipping_origin", cols)
        for legacy in (
            "shipping_origin_city", "shipping_origin_state", "shipping_origin_dane",
            "shipping_origin_address", "shipping_origin_nit", "shipping_origin_phone",
            "shipping_origin_email", "idagente",
        ):
            self.assertNotIn(legacy, cols)

    async def test_payload_desde_jsonb_como_flujo_real(self):
        sb = _Sb(_rows(_tenant_ok()))
        r = await self._call(sb)
        self.assertTrue(r["ok"])
        call = _FakeAveClient.last.calls["generate_guide"]
        sender = call["sender"]
        self.assertEqual(sender["nit"], "900123")                # tenants.nit
        self.assertEqual(sender["nombre"], "Bodega")             # jsonb name
        self.assertEqual(sender["direccion"], "Cra 1 # 1-1")     # jsonb street
        self.assertEqual(sender["telefono"], "3001112233")       # telefono_contacto
        self.assertEqual(sender["email"], "shop@x.co")           # email_contacto
        origin = call["origin"]
        self.assertEqual(origin["dane"], "11001")                # jsonb dane_code
        self.assertEqual(origin["city"], "BOGOTA(CUNDINAMARCA)")  # formato canónico
        # diagnostics: idagente desde credenciales de la integración
        self.assertEqual(r["diagnostics"]["tenant_idagente"], "AG-9001")
        self.assertFalse(r["diagnostics"]["warning_idagente_missing"])
        # package reusó weight_inputs cotizados (F5)
        self.assertEqual(call["package"]["weight_kg"], 0.7)

    async def test_tenant_sin_shipping_origin_completo_422(self):
        tenant = _tenant_ok()
        tenant["shipping_origin"] = {"city": "Bogotá"}  # sin street
        sb = _Sb(_rows(tenant))
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_simulate_false_con_master_off_fuerza_simulado(self):
        """Kill-switch fail-safe: simulate=False pedido pero
        AVEONLINE_GENERATE_REAL_GUIDES != true → effective_simulate=True."""
        sb = _Sb(_rows(_tenant_ok()))
        env = {k: v for k, v in os.environ.items()
               if k != "AVEONLINE_GENERATE_REAL_GUIDES"}
        with patch.dict(os.environ, env, clear=True):
            r = await self._call(sb, simulate=False)
        self.assertTrue(r["ok"])
        self.assertTrue(r["diagnostics"]["simulate"])
        self.assertFalse(r["diagnostics"]["simulate_requested"])
        self.assertTrue(_FakeAveClient.last.calls["generate_guide"]["simulate"])

    async def test_cart_sin_rate_id_no_carrier_selected(self):
        rows = _rows(_tenant_ok())
        rows["conversation_carts"] = [{"shipping_meta": {}}]
        sb = _Sb(rows)
        r = await self._call(sb)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "NO_CARRIER_SELECTED")


if __name__ == "__main__":
    unittest.main()
