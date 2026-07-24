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


def _api_main():
    """El módulo main de la API (con `.app`), robusto a la ambigüedad de sys.modules['main']
    (hay 3 main.py: api/connector/orchestrator). No re-ejecuta main.py."""
    _m = sys.modules.get("main")
    if _m is None or not hasattr(_m, "app"):
        sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")
        sys.modules.pop("main", None)
        import main as _m
    return _m


def _mfa_gated_endpoints():
    """{nombre_de_endpoint: set(nombres de gate MFA)} — la introspección del wiring MFA,
    VERSION-AGNÓSTICA de FastAPI.

    Por qué NO se lee `main.app.routes` plano (como antes): FastAPI 0.139 cambió
    `include_router` a LAZY — ya NO aplana las rutas en `app.routes`, las envuelve en
    objetos `_IncludedRouter` (rutas con path RELATIVO; el prefijo y las `dependencies`
    del include viven en `include_context`, no en cada sub-ruta). El código de prod corre
    0.139 (api/ai-orchestrator pinnean 0.139.0); el CI las testeaba bajo 0.128.8 (venv
    compartido, connector gana) → esta introspección pasaba por accidente. Este helper
    funciona idéntico bajo 0.128.8 (plano) y 0.139 (lazy): verificado, mismo mapa de gates.
    Ver docs/reports/ci_sec_hardening_2026_07_24.md §5.

    Se identifica por NOMBRE DE ENDPOINT (no por path): el path completo no es recuperable
    bajo 0.139 (prefijo opaco), pero la identidad de la función + su gate SÍ. Reúne los
    gates de 3 fuentes: dependencies por-ruta, walk recursivo del `dependant`, y las
    `dependencies` de los `include_context` que envuelven la ruta (gate a nivel router)."""
    main = _api_main()
    from dependencies.internal_auth import enforce_mfa_internal_or_user
    GATES = {A.enforce_mfa, A.enforce_mfa_strict, enforce_mfa_internal_or_user}

    def _deps(lst):
        return {getattr(d, "dependency", None) for d in (lst or [])} & GATES

    def _tree_calls(dependant):
        found, seen = set(), set()

        def w(d):
            if d is None or id(d) in seen:
                return
            seen.add(id(d))
            if getattr(d, "call", None) in GATES:
                found.add(d.call)
            for s in getattr(d, "dependencies", []) or []:
                w(s)

        w(dependant)
        return found

    out, seen = {}, set()

    def rec(routes, inherited):
        for r in routes:
            if id(r) in seen:
                continue
            seen.add(id(r))
            if type(r).__name__ == "_IncludedRouter":  # FastAPI 0.139 lazy include
                ctx = getattr(r, "include_context", None)
                inc = _deps(getattr(ctx, "dependencies", None)) if ctx else set()
                inner = (getattr(ctx, "included_router", None) if ctx else None) \
                    or getattr(r, "original_router", None)
                if inner is not None:
                    rec(getattr(inner, "routes", []), inherited | inc)
            elif hasattr(r, "dependant") and hasattr(r, "endpoint"):
                g = inherited | _tree_calls(getattr(r, "dependant", None)) \
                    | _deps(getattr(r, "dependencies", None))
                ep = getattr(getattr(r, "endpoint", None), "__name__", "")
                out.setdefault(ep, set()).update(x.__name__ for x in g)

    rec(main.app.routes, set())
    return out


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


class MfaInternalOrUserTests(unittest.TestCase):
    """BLOQUE 0 (orders) — enforce_mfa_internal_or_user: NO-OP para el bot
    (X-Internal-Service-Secret válido), delega a enforce_mfa para llamadas de usuario.
    Garantiza que gatear /orders/{id}/payment-link (dual-auth) NO rompe al orchestrator."""

    @staticmethod
    def _req(headers):
        return type("R", (), {"headers": headers})()

    def test_llamada_interna_del_bot_no_enforca_mfa(self):
        from dependencies import internal_auth as I
        old = I.INTERNAL_SERVICE_SECRET
        I.INTERNAL_SERVICE_SECRET = "sekret"
        try:
            with patch.object(I, "enforce_mfa", side_effect=AssertionError("no debe enforcar MFA al bot")):
                req = self._req({"X-Internal-Service-Secret": "sekret"})
                asyncio.run(I.enforce_mfa_internal_or_user(req))  # no lanza → skip
        finally:
            I.INTERNAL_SERVICE_SECRET = old

    def test_llamada_de_usuario_delega_a_enforce_mfa(self):
        from dependencies import internal_auth as I
        old = I.INTERNAL_SERVICE_SECRET
        I.INTERNAL_SERVICE_SECRET = "sekret"
        try:
            sentinel = HTTPException(status_code=401, detail="delegó")
            with patch.object(I, "enforce_mfa", side_effect=sentinel):
                req = self._req({})  # sin secret interno → path de usuario
                with self.assertRaises(HTTPException) as cm:
                    asyncio.run(I.enforce_mfa_internal_or_user(req))
                self.assertEqual(cm.exception.detail, "delegó")
        finally:
            I.INTERNAL_SERVICE_SECRET = old


class MfaGateWiringTests(unittest.TestCase):
    """BLOQUE 0 (review) — el gate MFA cubre los crown jewels y NO gatea lo que debe
    permanecer accesible en grace/recovery. Regresión contra el bypass detectado en review:
    offboarding export/request-deletion + SAR (PII) + sic-report (crédito) estaban sin MFA."""

    @classmethod
    def setUpClass(cls):
        # {endpoint: set(gate_names)}. Keyed por endpoint (no path) para ser
        # version-agnóstico (ver _mfa_gated_endpoints).
        cls.gated = _mfa_gated_endpoints()

    # Crown-jewels money/PII/crédito, por FUNCIÓN de endpoint (estable cross-versión):
    #   export_data/request_deletion → offboarding export/request-deletion
    #   data_subject_request(_printable) → SAR PII · sic_report → reporte de crédito
    #   create_payment_link/patch_order/generate_shipping_guide_endpoint → money-movement
    _CROWN = {"export_data", "request_deletion", "data_subject_request",
              "data_subject_request_printable", "sic_report"}
    _MONEY = {"create_payment_link", "patch_order", "generate_shipping_guide_endpoint"}
    # Recuperación/grace — NUNCA deben exigir AAL2 (o deadlock de recuperación):
    _RECOVERY = {"offboarding_status", "cancel_deletion", "count_recovery_codes",
                 "regenerate_recovery_codes", "verify_recovery_code", "clear_recovery_codes",
                 "recovery_reset_totp", "recovery_change_password"}

    def test_crown_jewels_gateados(self):
        faltan = {ep for ep in self._CROWN if not self.gated.get(ep)}
        self.assertFalse(faltan, f"crown-jewels sin gate MFA: {faltan}")

    def test_offboarding_crownjewels_son_fail_closed(self):
        """Ancla la propiedad de seguridad: export (PII) + request-deletion (borrado) usan
        enforce_mfa_strict (FAIL-CLOSED), NO el gate amplio fail-open. Un revert
        strict→enforce_mfa debe ROMPER este test (el de arriba usa la unión y no lo pillaría)."""
        for ep in ("export_data", "request_deletion"):
            self.assertIn("enforce_mfa_strict", self.gated.get(ep, set()),
                          f"{ep} no es fail-closed (falta enforce_mfa_strict)")

    def test_orders_money_movement_gateado(self):
        """payment-link (dual-auth, internal-aware) + PATCH (user-only) money-movement
        + generate-shipping-guide (Ola 0 — guía REAL Aveonline = dinero, internal-aware)."""
        faltan = {ep for ep in self._MONEY if not self.gated.get(ep)}
        self.assertFalse(faltan, f"money-movement sin gate MFA: {faltan}")

    def test_recovery_paths_no_gateados(self):
        """status/cancel-deletion (deben correr en grace) y el router mfa (para completar
        el 2º factor) NO deben exigir AAL2, o se crea un deadlock de recuperación."""
        gateados = {ep for ep in self._RECOVERY if self.gated.get(ep)}
        self.assertFalse(gateados, f"paths de recuperación gateados (deadlock): {gateados}")


class MfaStrictFailClosedTests(unittest.TestCase):
    """W1 — enforce_mfa_strict: FAIL-CLOSED en operaciones crown-jewel (export PII,
    borrado de cuenta). Ante incertidumbre DENIEGA; sin forzar MFA a quien no lo activó."""

    def _run(self, payload, lookup=None, lookup_exc=None):
        with patch.object(A, "_extract_jwt_payload", return_value=payload):
            if lookup_exc is not None:
                cm = patch.object(A, "_lookup_verified_mfa_cached", side_effect=lookup_exc)
            else:
                cm = patch.object(A, "_lookup_verified_mfa_cached", return_value=lookup)
            with cm:
                return asyncio.run(A.enforce_mfa_strict(_req()))

    def test_aal2_pasa(self):
        self.assertIsNone(self._run({"aal": "aal2", "sub": "u1"}, lookup=True))

    def test_aal1_con_mfa_rechaza_401(self):
        with self.assertRaises(HTTPException) as cm:
            self._run({"aal": "aal1", "sub": "u1"}, lookup=True)
        self.assertEqual(cm.exception.status_code, 401)

    def test_aal1_sin_mfa_pasa(self):
        # no forzar MFA a quien no lo activó (aal1 + sin factor verificado)
        self.assertIsNone(self._run({"aal": "aal1", "sub": "u1"}, lookup=False))

    def test_lookup_caido_fail_closed_503(self):
        # DIFERENCIA vs enforce_mfa (fail-open): aquí el outage DENIEGA
        with self.assertRaises(HTTPException) as cm:
            self._run({"aal": "aal1", "sub": "u1"}, lookup_exc=A._MfaLookupError("auth admin down"))
        self.assertEqual(cm.exception.status_code, 503)

    def test_sin_sub_rechaza_401(self):
        with self.assertRaises(HTTPException) as cm:
            self._run({"aal": "aal1", "sub": ""}, lookup=False)
        self.assertEqual(cm.exception.status_code, 401)

    def test_enforce_mfa_amplio_sigue_fail_open(self):
        # contraste: el gate amplio NO debe romper por un outage
        with patch.object(A, "_extract_jwt_payload", return_value={"aal": "aal1", "sub": "u1"}), \
             patch.object(A, "_lookup_verified_mfa_cached", side_effect=A._MfaLookupError("down")):
            self.assertIsNone(asyncio.run(A.enforce_mfa(_req())))


if __name__ == "__main__":
    unittest.main()
