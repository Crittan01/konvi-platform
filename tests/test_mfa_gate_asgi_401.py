"""Regresión de SEGURIDAD (2026-07-21) — el gate MFA DISPARA en las rutas reales.

Contexto (forense del workflow ci-venv-isolation-analysis + hallazgo del PR #134):
  El único guardián del gate MFA sobre las rutas de movimiento de dinero y de datos
  personales era `test_b0_mfa_gateway_enforce.py::MfaGateWiringTests`, que
  INTROSPECCIONA `route.dependencies[*].dependency` / `route.dependant.dependencies
  [*].call` — atributos PRIVADOS de FastAPI. Eso verifica el CABLEADO (el gate está
  atado a la ruta) pero NO el DISPARO (que ante un request real devuelva 401). Y esa
  introspección se ROMPE cuando FastAPI cambia sus internos (lo vimos en #134 con
  fastapi 0.139: los tests de wiring fallan aunque el enforcement en runtime siga
  activo). api/ai-orchestrator ya pinnean 0.139 en requirements.txt; el día que el CI
  corra esos tests bajo su versión real (ver split de venv), la introspección se rompe.

Este test cierra el hueco de forma VERSION-AGNÓSTICA: monta la app REAL (main.app) con
TestClient y afirma que un request de una identidad AAL1 CON MFA verificado recibe 401
en las rutas crown-jewel. No lee ningún interno de FastAPI → sobrevive a cualquier
refactor del framework; si el enforcement dejara de dispararse, ESTE test lo caza (la
introspección no).

Diseño (por qué el 401 es atribuible al GATE y no a otra capa de auth):
  `_extract_jwt_payload` es la ÚNICA fuente de identidad (get_current_tenant/role y el
  propio enforce_mfa la llaman). Parcheándola con un AAL1 owner VÁLIDO, todas las capas
  de auth quedan satisfechas → el único 401 posible viene del gate MFA. Se prueba con el
  CONTRASTE: con MFA verificado=True el gate DEBE 401; con MFA verificado=False (usuario
  que NO activó MFA) el gate NO debe disparar — el request pasa el gate y cae en el body
  (503/422/500) o en un 401 de OTRA razón (distinto detail). El discriminador es
  "401 AND detail contiene 'dos pasos'": separa limpiamente gate-disparó de no-disparó,
  y de paso ancla que el gate NO sobre-bloquea a quien no activó MFA (su diseño).
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "test-internal-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Identidad AAL1 (password sin 2º factor) VÁLIDA: owner con tenant → satisface
# get_current_tenant/get_current_role. Es exactamente el token que el gate MFA debe
# rechazar cuando el usuario TIENE un factor MFA verificado (step-up no completado).
_AAL1_OWNER = {"aal": "aal1", "sub": "u1", "app_metadata": {"tenant_id": "t1", "role": "owner"}}

# Rutas crown-jewel que DEBEN estar gateadas por MFA (movimiento de dinero + datos
# personales irreversibles). Mismo conjunto que ancla MfaGateWiringTests, pero aquí
# se verifica el DISPARO real, no el cableado.
_GATED = [
    ("POST", "/api/v1/orders/ORD/payment-link"),
    ("PATCH", "/api/v1/orders/ORD"),
    ("POST", "/api/v1/orders/ORD/generate-shipping-guide"),
    ("POST", "/api/v1/tenant/offboarding/export"),
    ("POST", "/api/v1/tenant/offboarding/request-deletion"),
]

# Frase presente en el detail de AMBOS gates (enforce_mfa y enforce_mfa_strict):
# "…verificación en dos pasos (MFA)…". Discrimina el 401-del-gate de cualquier otro 401.
_MFA_MARK = "dos pasos"


def _fake_service_client():
    """Service client para el gate de offboarding (reject_if_tenant_deleting):
    tenants query → 0 filas → tenant NO en borrado → no interfiere."""
    sb = MagicMock()
    chain = MagicMock()
    chain.execute.return_value = SimpleNamespace(data=[])
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value = chain
    return sb


def _patched(has_mfa: bool):
    """Context manager con la identidad AAL1 válida + estado MFA controlado + las
    capas transversales (rate-limit/plan) desactivadas para que NO corten antes del
    gate. Lo único que puede 401-con-'dos pasos' es el gate MFA."""
    patchers = [
        patch("dependencies.auth._extract_jwt_payload", return_value=_AAL1_OWNER),
        patch("dependencies.auth._user_has_verified_mfa", return_value=has_mfa),
        patch("dependencies.auth._lookup_verified_mfa_cached", return_value=has_mfa),
        patch("dependencies.auth._get_service_client", return_value=_fake_service_client()),
        patch("dependencies.security.RATE_LIMIT_ENABLED", False),
        patch("dependencies.plans.PLAN_ENFORCEMENT_ENABLED", False),
    ]
    return patchers


def _run(has_mfa: bool, method: str, path: str):
    ps = _patched(has_mfa)
    for p in ps:
        p.start()
    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        resp = client.request(method, path, json={})
        ct = resp.headers.get("content-type", "")
        detail = (resp.json() or {}).get("detail", "") if ct.startswith("application/json") else resp.text
        return resp.status_code, (detail if isinstance(detail, str) else str(detail))
    finally:
        for p in reversed(ps):
            p.stop()


class MfaGateAsgiFiresTests(unittest.TestCase):
    """Prueba de DISPARO (no de cableado) — request real por el stack ASGI completo."""

    def test_aal1_con_mfa_verificado_recibe_401_en_todas_las_crown_jewels(self):
        """Identidad AAL1 + factor MFA verificado → 401 del gate en cada ruta."""
        for method, path in _GATED:
            with self.subTest(route=f"{method} {path}"):
                status, detail = _run(True, method, path)
                self.assertEqual(status, 401, f"{method} {path}: se esperaba 401 del gate MFA, detail={detail!r}")
                self.assertIn(
                    _MFA_MARK, detail,
                    f"{method} {path}: el 401 NO es del gate MFA (detail={detail!r}) — "
                    f"otra capa de auth cortó antes; el test dejaría de probar el gate",
                )

    def test_aal1_sin_mfa_no_es_bloqueado_por_el_gate(self):
        """Contraste ('test the test' + anti-sobre-bloqueo): un usuario AAL1 que NO
        activó MFA NO debe recibir el 401 del gate — el request pasa el gate (y cae en
        el body con 5xx/422, o en un 401 de OTRA razón). Prueba que el 401 de arriba es
        atribuible ESPECÍFICAMENTE al gate MFA, y que el gate no rompe a quien no activó
        el 2º factor (su invariante de diseño)."""
        for method, path in _GATED:
            with self.subTest(route=f"{method} {path}"):
                status, detail = _run(False, method, path)
                gate_fired = status == 401 and _MFA_MARK in detail
                self.assertFalse(
                    gate_fired,
                    f"{method} {path}: el gate disparó para un usuario SIN MFA "
                    f"(status={status}, detail={detail!r}) — sobre-bloqueo o falso positivo",
                )


if __name__ == "__main__":
    unittest.main()
