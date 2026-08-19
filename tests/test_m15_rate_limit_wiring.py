"""M15 (auditoría 2026-08-02) — wiring del rate-limit de escritura estándar.

Endpoints verificados SIN `RL_WRITE_DEFAULT` (el patrón del repo:
`dependencies=[Depends(RL_WRITE_DEFAULT)]` en el decorador, igual que
products/purchases/coupons/knowledge_base):
  · expenses.py            POST / + POST /{id}/reverse
  · product_attribute_definitions.py  POST / + PATCH + DELETE
  · settings.py            POST /maintenance/idempotency-cleanup
  · integrations.py        aveonline webhook configure/rotate/delete +
                           carriers PUT/DELETE/seed

Este test INTROSPECCIONA `router.routes[*].dependencies` (version-agnóstico:
no toca main.app ni el include_router lazy de FastAPI 0.139) y falla si un
revert quita la dependencia de cualquiera de los 12 endpoints.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from dependencies.security import RL_WRITE_DEFAULT  # noqa: E402


def _endpoints_con_rl(router):
    """{nombre_de_endpoint} de las rutas del router que declaran
    Depends(RL_WRITE_DEFAULT) a nivel decorador."""
    out = set()
    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        deps = getattr(route, "dependencies", None) or []
        if any(getattr(d, "dependency", None) is RL_WRITE_DEFAULT for d in deps):
            out.add(endpoint.__name__)
    return out


class M15RateLimitWiringTests(unittest.TestCase):
    def test_expenses_write_endpoints(self):
        from routers import expenses
        rl = _endpoints_con_rl(expenses.router)
        faltan = {"create_expense", "reverse_expense"} - rl
        self.assertFalse(faltan, f"expenses sin RL_WRITE_DEFAULT: {faltan}")

    def test_product_attribute_definitions_write_endpoints(self):
        from routers import product_attribute_definitions as pad
        rl = _endpoints_con_rl(pad.router)
        faltan = {
            "create_attribute_definition",
            "patch_attribute_definition",
            "delete_attribute_definition",
        } - rl
        self.assertFalse(faltan, f"product_attribute_definitions sin RL: {faltan}")

    def test_settings_idempotency_cleanup(self):
        from routers import settings
        rl = _endpoints_con_rl(settings.router)
        self.assertIn(
            "cleanup_idempotency", rl,
            "settings maintenance/idempotency-cleanup sin RL_WRITE_DEFAULT",
        )

    def test_integrations_aveonline_write_endpoints(self):
        from routers import integrations
        rl = _endpoints_con_rl(integrations.router)
        faltan = {
            "aveonline_webhook_configure",
            "aveonline_webhook_rotate",
            "aveonline_webhook_delete",
            "bulk_upsert_aveonline_carriers",
            "delete_aveonline_carrier",
            "seed_aveonline_carriers",
        } - rl
        self.assertFalse(faltan, f"integrations aveonline/* sin RL: {faltan}")


if __name__ == "__main__":
    unittest.main()
