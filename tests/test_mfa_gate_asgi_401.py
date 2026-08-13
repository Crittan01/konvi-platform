"""Regresión de SEGURIDAD (2026-07-21) — los gates MFA DISPARAN 401 vía ASGI/DI.

Contexto (forense del workflow ci-venv-isolation-analysis + hallazgo del PR #134):
  El gate MFA sobre movimiento de dinero y datos personales tenía dos coberturas:
  (a) tests UNITARIOS (test_b0_mfa_gateway_enforce::MfaGatewayEnforceTests) que
      llaman `enforce_mfa(_req())` como FUNCIÓN → prueban la LÓGICA;
  (b) MfaGateWiringTests que INTROSPECCIONA `route.dependencies[*].dependency` /
      `route.dependant.dependencies[*].call` → prueba el CABLEADO a las rutas reales.
  Faltaba una tercera: que los gates DISPAREN un 401 cuando FastAPI los invoca como
  dependencia real a través del stack ASGI + inyección de dependencias — no como una
  llamada de función suelta. Ese es el nivel donde vive el riesgo que la introspección
  (b) no ve y que se rompe con cada refactor de internos de FastAPI (fue lo que reventó
  en #134 con 0.139, aunque el enforcement en runtime seguía activo).

Este test cierra esa tercera cobertura de forma VERSION-AGNÓSTICA y DETERMINISTA:
monta los gates REALES de producción (`enforce_mfa`, `enforce_mfa_strict`,
`enforce_mfa_internal_or_user`) como `Depends(...)` en una app mínima y afirma, vía
TestClient, que una identidad AAL1 CON MFA verificado recibe 401 — y que un usuario
AAL1 SIN MFA pasa (200). No lee ningún interno de FastAPI → sobrevive a 0.139 y a
cualquier refactor.

Por qué app mínima y NO main.app: golpear las rutas reales por TestClient resultó
frágil al orden de los tests — el estado async/event-loop que dejan otros tests que
usan `asyncio.run` (p.ej. test_telegram) hace que ciertos gates (internal_or_user,
strict) propaguen una excepción antes de responder. La app mínima monta los MISMOS
gates de producción sin @audit_log/middleware/estado global cross-ruta → determinista.
El CABLEADO gate↔ruta-real lo cubre MfaGateWiringTests (son complementarios: DI-firing
+ wiring); de-brittle de esa introspección va en el split de venv (cuando corra 0.139).
"""
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "test-internal-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Los GATES REALES de producción — exactamente los objetos que las rutas crown-jewel
# montan como Depends. Si su lógica regresa (no lanza 401) para un AAL1+MFA, este test
# lo caza.
from dependencies.auth import enforce_mfa, enforce_mfa_strict  # noqa: E402
from dependencies.internal_auth import enforce_mfa_internal_or_user  # noqa: E402

# Identidad AAL1 (password sin 2º factor) VÁLIDA. Es la que el gate debe rechazar
# cuando el usuario TIENE un factor MFA verificado (step-up no completado).
_AAL1_OWNER = {"aal": "aal1", "sub": "u1", "app_metadata": {"tenant_id": "t1", "role": "owner"}}

# Frase presente en el detail de los tres gates: "…verificación en dos pasos (MFA)…".
_MFA_MARK = "dos pasos"

# Los tres gates que protegen las crown-jewels, con el path real que cada uno cubre:
#   enforce_mfa                 → PATCH /orders/{id}  (dinero, user-only)
#   enforce_mfa_internal_or_user→ payment-link / generate-shipping-guide (dinero, dual-auth)
#   enforce_mfa_strict          → offboarding export / request-deletion (PII, fail-closed)
_GATES = [
    ("enforce_mfa", enforce_mfa),
    ("enforce_mfa_internal_or_user", enforce_mfa_internal_or_user),
    ("enforce_mfa_strict", enforce_mfa_strict),
]


def _app_with_gate(gate):
    """App mínima que monta UN gate de producción como Depends, sin nada más que
    pueda 401/500 (ni @audit_log, ni tenant/role/rate-limit) → el ÚNICO decisor es
    el gate. El body devuelve 200: si el gate NO dispara, la respuesta es 200."""
    app = FastAPI()

    @app.post("/gated", dependencies=[Depends(gate)])
    async def _gated():  # noqa: ANN202
        return {"ok": True}

    return app


def _hit(gate, has_mfa: bool):
    """Envía un POST a la ruta gateada con identidad AAL1 + estado MFA controlado.
    `_extract_jwt_payload` es lo que el gate lee del request; los lookups MFA se
    fuerzan. Devuelve (status, detail)."""
    with patch("dependencies.auth._extract_jwt_payload", return_value=_AAL1_OWNER), \
         patch("dependencies.auth._user_has_verified_mfa", return_value=has_mfa), \
         patch("dependencies.auth._lookup_verified_mfa_cached", return_value=has_mfa):
        client = TestClient(_app_with_gate(gate), raise_server_exceptions=True)
        resp = client.post("/gated", json={})
        ct = resp.headers.get("content-type", "")
        detail = (resp.json() or {}).get("detail", "") if ct.startswith("application/json") else resp.text
        return resp.status_code, (detail if isinstance(detail, str) else str(detail))


class MfaGateAsgiFiresTests(unittest.TestCase):
    """Prueba de DISPARO a través de la inyección de dependencias real de FastAPI —
    lo que las llamadas-de-función directas (tests unitarios) NO ejercen."""

    def test_aal1_con_mfa_verificado_dispara_401_en_cada_gate(self):
        """AAL1 + factor MFA verificado → 401 con el mensaje del gate, en los 3 gates."""
        for name, gate in _GATES:
            with self.subTest(gate=name):
                status, detail = _hit(gate, has_mfa=True)
                self.assertEqual(status, 401, f"{name}: se esperaba 401, fue {status} (detail={detail!r})")
                self.assertIn(_MFA_MARK, detail, f"{name}: el 401 no trae el mensaje del gate MFA: {detail!r}")

    def test_aal1_sin_mfa_pasa_el_gate(self):
        """Contraste ('test the test' + anti-sobre-bloqueo): un usuario AAL1 que NO
        activó MFA NO debe ser bloqueado → el gate pasa y el body responde 200. Esto
        prueba que el 401 de arriba lo produce la DECISIÓN del gate (no un 401 fijo),
        y que el gate no rompe a quien no activó el 2º factor (su invariante)."""
        for name, gate in _GATES:
            with self.subTest(gate=name):
                status, detail = _hit(gate, has_mfa=False)
                self.assertEqual(status, 200, f"{name}: AAL1 sin MFA debió pasar (200), fue {status} ({detail!r})")


if __name__ == "__main__":
    unittest.main()
