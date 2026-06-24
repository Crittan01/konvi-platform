"""A7 RBAC — marketplace (5 endpoints mutantes) + ai_agents (/suggest) deben
exigir owner/manager (require_write_role), no operator.

Finiquito A7 2026-06-24. Antes estos endpoints solo tenían get_current_tenant →
un operator podía vincular/importar/borrar listings de MeLi y disparar
sugerencias AI (acciones de gestión de canal/config = manager-level).

Test binario por introspección: cada ruta objetivo DEBE tener require_write_role
en su cadena de dependencias. El comportamiento 403→operator del dependency ya
está cubierto en test_rbac_runtime.py.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from dependencies.auth import require_write_role  # noqa: E402
from routers import marketplace, ai_agents  # noqa: E402


def _route_deps(router, path: str, method: str):
    """Devuelve los callables de dependencia de una ruta (path, method)."""
    method = method.upper()
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return [d.call for d in route.dependant.dependencies]
    raise AssertionError(f"Ruta no encontrada: {method} {path}")


class MarketplaceRBACTests(unittest.TestCase):
    # (path, method) de los 5 endpoints que MUTAN estado del canal MeLi.
    MUTATING = [
        ("/marketplace/link", "POST"),
        ("/marketplace/link/{listing_id}", "DELETE"),
        ("/marketplace/{listing_id}/status", "PATCH"),
        ("/marketplace/{listing_id}/sync-stock", "PATCH"),
        ("/marketplace/import", "POST"),
    ]

    def test_mutating_endpoints_require_write_role(self):
        for path, method in self.MUTATING:
            with self.subTest(endpoint=f"{method} {path}"):
                deps = _route_deps(marketplace.router, path, method)
                self.assertIn(
                    require_write_role, deps,
                    f"{method} {path} NO exige require_write_role (operator podría mutarlo)",
                )

    def test_listings_read_endpoint_not_gated_by_write_role(self):
        # GET /listings es lectura — NO debe exigir write role (operator puede ver).
        deps = _route_deps(marketplace.router, "/marketplace/listings", "GET")
        self.assertNotIn(require_write_role, deps)


class AiAgentsRBACTests(unittest.TestCase):
    def test_suggest_requires_write_role(self):
        deps = _route_deps(ai_agents.router, "/ai-agents/suggest", "POST")
        self.assertIn(
            require_write_role, deps,
            "POST /ai-agents/suggest NO exige require_write_role (configurar agente AI = manager)",
        )

    def test_templates_list_is_public_read(self):
        # GET /ai-agents/templates son globales estáticos — público, sin write role.
        deps = _route_deps(ai_agents.router, "/ai-agents/templates", "GET")
        self.assertNotIn(require_write_role, deps)


if __name__ == "__main__":
    unittest.main()
