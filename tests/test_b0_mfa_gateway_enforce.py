"""BLOQUE 0 · P1 — enforce_mfa: el gateway FastAPI exige AAL2 si el user tiene MFA.

Antes: el middleware de Next gateaba MFA, pero la API pública FastAPI no → un token
AAL1 (password sin 2º factor) operaba contra la API directa, saltándose el MFA.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "test")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from fastapi import HTTPException
from dependencies import auth as A


def _mfa_gated_paths():
    """Paths (path, method) cuyo dependency chain incluye enforce_mfa en la app real.

    Cubre ambos niveles: dependencies por-endpoint (r.dependencies[*].dependency) y
    heredadas del include_router (_MFA_GATE → r.dependant.dependencies[*].call)."""
    import main
    gated = set()
    for r in main.app.routes:
        fns = [getattr(d, "dependency", None) for d in (getattr(r, "dependencies", []) or [])]
        fns += [getattr(d, "call", None) for d in getattr(getattr(r, "dependant", None), "dependencies", []) or []]
        if A.enforce_mfa in fns:
            for m in getattr(r, "methods", None) or []:
                gated.add((getattr(r, "path", ""), m))
    return gated


def _req():
    # enforce_mfa solo usa _extract_jwt_payload(request) → lo parcheamos; el request
    # real no importa para el test unitario.
    return object()


class MfaGatewayEnforceTests(unittest.TestCase):
    def test_aal2_pasa_sin_lookup(self):
        with patch.object(A, "_extract_jwt_payload", return_value={"aal": "aal2", "sub": "u1"}), \
             patch.object(A, "_user_has_verified_mfa", side_effect=AssertionError("no debe consultar factores en aal2")):
            asyncio.run(A.enforce_mfa(_req()))  # no lanza

    def test_aal1_con_mfa_verificado_rechaza_401(self):
        with patch.object(A, "_extract_jwt_payload", return_value={"aal": "aal1", "sub": "u1"}), \
             patch.object(A, "_user_has_verified_mfa", return_value=True):
            with self.assertRaises(HTTPException) as cm:
                asyncio.run(A.enforce_mfa(_req()))
            self.assertEqual(cm.exception.status_code, 401)

    def test_aal1_sin_mfa_pasa(self):
        """Usuario sin MFA activado: aal1 es aceptable (no rompe a quien no lo activó)."""
        with patch.object(A, "_extract_jwt_payload", return_value={"aal": "aal1", "sub": "u2"}), \
             patch.object(A, "_user_has_verified_mfa", return_value=False):
            asyncio.run(A.enforce_mfa(_req()))  # no lanza

    def test_sin_claim_aal_trata_como_aal1(self):
        with patch.object(A, "_extract_jwt_payload", return_value={"sub": "u3"}), \
             patch.object(A, "_user_has_verified_mfa", return_value=True):
            with self.assertRaises(HTTPException):
                asyncio.run(A.enforce_mfa(_req()))

    def test_lookup_factores_cachea_y_falla_open(self):
        """Fail-open ante error del Auth admin (no bloquear por infra caída)."""
        A._MFA_CACHE.clear()

        class _Boom:
            class auth:
                class admin:
                    @staticmethod
                    def get_user_by_id(_sub):
                        raise RuntimeError("auth admin down")
        with patch.object(A, "_get_service_client", return_value=_Boom()):
            self.assertFalse(A._user_has_verified_mfa("uX"))  # fail-open → False


class MfaGateWiringTests(unittest.TestCase):
    """BLOQUE 0 (review) — el gate MFA cubre los crown jewels y NO gatea lo que debe
    permanecer accesible en grace/recovery. Regresión contra el bypass detectado en review:
    offboarding export/request-deletion + SAR (PII) + sic-report (crédito) estaban sin MFA."""

    @classmethod
    def setUpClass(cls):
        cls.gated = _mfa_gated_paths()

    def test_crown_jewels_gateados(self):
        must = {
            ("/api/v1/tenant/offboarding/export", "POST"),
            ("/api/v1/tenant/offboarding/request-deletion", "POST"),
            ("/api/v1/contacts/{contact_id}/data-subject-request", "POST"),
            ("/api/v1/contacts/{contact_id}/data-subject-request/printable", "GET"),
            ("/api/v1/sic-report", "GET"),
        }
        self.assertTrue(must <= self.gated, f"faltan gateados: {must - self.gated}")

    def test_recovery_paths_no_gateados(self):
        """status/cancel-deletion (deben correr en grace) y el router mfa (para completar
        el 2º factor) NO deben exigir AAL2, o se crea un deadlock de recuperación."""
        gated_paths = {p for p, _ in self.gated}
        self.assertNotIn("/api/v1/tenant/offboarding/status", gated_paths)
        self.assertNotIn("/api/v1/tenant/offboarding/cancel-deletion", gated_paths)
        self.assertFalse(
            any(p.startswith("/api/v1/mfa") for p in gated_paths),
            "el router mfa no debe estar gateado por enforce_mfa",
        )


if __name__ == "__main__":
    unittest.main()
