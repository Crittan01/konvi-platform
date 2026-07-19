"""BLOQUE 0 · MFA OBLIGATORIO (D1/D2/D3, 2026-07-18) — enforcement de ENROLAMIENTO.

Distinto del step-up de enforce_mfa: los write-roles (owner/manager) DEBEN tener un
factor MFA verificado tras la gracia, o sus mutaciones se rechazan con 403. Rollout por
env (MFA_MANDATORY_ENABLED, default false → no-op). FAIL-OPEN ante outage del Auth admin.
Gracia: deadline = max(created_at, MFA_MANDATORY_START) + MFA_MANDATORY_GRACE_DAYS.
Ver services/api/dependencies/auth.py.
"""
import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SECRET_KEY", "test-key")
sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from fastapi import HTTPException  # noqa: E402
from dependencies import auth as A  # noqa: E402


def _ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class _Base(unittest.TestCase):
    def setUp(self):
        A._MFA_CACHE.clear()
        # Enforcement ACTIVO + gracia 14d por defecto para estos tests.
        self._env = patch.dict(
            os.environ, {"MFA_MANDATORY_ENABLED": "true", "MFA_MANDATORY_GRACE_DAYS": "14"},
            clear=False,
        )
        self._env.start()
        os.environ.pop("MFA_MANDATORY_START", None)

    def tearDown(self):
        self._env.stop()
        os.environ.pop("MFA_MANDATORY_START", None)
        A._MFA_CACHE.clear()


class EnforceCoreTests(_Base):
    """_enforce_mfa_enrollment_for: el núcleo de la política."""

    def test_disabled_is_noop(self):
        """ENABLED=false → no-op TOTAL: ni siquiera consulta factores."""
        with patch.dict(os.environ, {"MFA_MANDATORY_ENABLED": "false"}), \
             patch.object(A, "_lookup_mfa_state_cached",
                          side_effect=AssertionError("no debe consultar con enforcement off")):
            A._enforce_mfa_enrollment_for("owner", "u1")  # no lanza

    def test_operator_not_forced(self):
        """operator NO está en MFA_MANDATORY_ROLES → no-op sin lookup (D1)."""
        with patch.object(A, "_lookup_mfa_state_cached",
                          side_effect=AssertionError("operator no debe forzarse")):
            A._enforce_mfa_enrollment_for("operator", "u1")  # no lanza

    def test_no_sub_is_noop(self):
        with patch.object(A, "_lookup_mfa_state_cached",
                          side_effect=AssertionError("sin sub no debe consultar")):
            A._enforce_mfa_enrollment_for("owner", "")  # no lanza

    def test_enrolled_passes(self):
        """Con factor verificado → pasa aunque la gracia haya vencido hace mucho."""
        with patch.object(A, "_lookup_mfa_state_cached", return_value=(True, _ago(999))):
            A._enforce_mfa_enrollment_for("owner", "u1")  # no lanza

    def test_not_enrolled_within_grace_passes(self):
        with patch.object(A, "_lookup_mfa_state_cached", return_value=(False, _ago(1))):
            A._enforce_mfa_enrollment_for("manager", "u1")  # no lanza (gracia vigente)

    def test_not_enrolled_past_grace_403(self):
        with patch.object(A, "_lookup_mfa_state_cached", return_value=(False, _ago(30))):
            with self.assertRaises(HTTPException) as cm:
                A._enforce_mfa_enrollment_for("owner", "u1")
            self.assertEqual(cm.exception.status_code, 403)
            self.assertIn("dos pasos", cm.exception.detail.lower())

    def test_lookup_outage_fail_open(self):
        """Outage del Auth admin → FAIL-OPEN (no encerrar por un blip de infra)."""
        with patch.object(A, "_lookup_mfa_state_cached",
                          side_effect=A._MfaLookupError("auth admin down")):
            A._enforce_mfa_enrollment_for("owner", "u1")  # no lanza


class GraceWindowTests(_Base):
    """_within_mfa_grace: cálculo del deadline = max(created, START) + grace_days."""

    def test_recent_created_within(self):
        self.assertTrue(A._within_mfa_grace(_ago(1)))

    def test_old_created_past(self):
        self.assertFalse(A._within_mfa_grace(_ago(30)))

    def test_exactly_at_grace_boundary_within(self):
        # created hace 13d con gracia 14 → aún dentro.
        self.assertTrue(A._within_mfa_grace(_ago(13)))

    def test_start_floor_extends_grace_for_old_users(self):
        """MFA_MANDATORY_START da a TODOS gracia desde el flip, aunque sean viejos."""
        with patch.dict(os.environ, {"MFA_MANDATORY_START": _ago(1)}):
            # created hace 999d pero START hace 1d → deadline = START+14 → futuro.
            self.assertTrue(A._within_mfa_grace(_ago(999)))

    def test_start_in_past_beyond_grace_is_past(self):
        with patch.dict(os.environ, {"MFA_MANDATORY_START": _ago(60)}):
            self.assertFalse(A._within_mfa_grace(_ago(999)))

    def test_no_anchor_conservative_within(self):
        """Sin created_at ni START parseables → conservador: dentro (no bloquear)."""
        os.environ.pop("MFA_MANDATORY_START", None)
        self.assertTrue(A._within_mfa_grace(None))

    def test_unparseable_created_falls_back(self):
        os.environ.pop("MFA_MANDATORY_START", None)
        self.assertTrue(A._within_mfa_grace("no-es-fecha"))

    def test_z_suffix_parsed(self):
        z = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertFalse(A._within_mfa_grace(z))


class DependencyTests(_Base):
    """enforce_mfa_enrollment: dependencia standalone (extrae role/sub del JWT)."""

    def test_owner_past_grace_403(self):
        with patch.object(A, "_extract_jwt_payload",
                          return_value={"app_metadata": {"role": "owner"}, "sub": "u1"}), \
             patch.object(A, "_lookup_mfa_state_cached", return_value=(False, _ago(30))):
            with self.assertRaises(HTTPException) as cm:
                asyncio.run(A.enforce_mfa_enrollment(object()))
            self.assertEqual(cm.exception.status_code, 403)

    def test_operator_passes(self):
        with patch.object(A, "_extract_jwt_payload",
                          return_value={"app_metadata": {"role": "operator"}, "sub": "u1"}), \
             patch.object(A, "_lookup_mfa_state_cached",
                          side_effect=AssertionError("operator no se consulta")):
            asyncio.run(A.enforce_mfa_enrollment(object()))  # no lanza

    def test_unknown_role_treated_as_operator(self):
        with patch.object(A, "_extract_jwt_payload",
                          return_value={"app_metadata": {"role": "hacker"}, "sub": "u1"}), \
             patch.object(A, "_lookup_mfa_state_cached",
                          side_effect=AssertionError("rol inválido → operator, no se consulta")):
            asyncio.run(A.enforce_mfa_enrollment(object()))  # no lanza


class RoleGateIntegrationTests(_Base):
    """require_write_role / require_owner_role: el enforcement va DENTRO de los gates
    de rol → cubre exactamente las mutaciones de write-roles, sin tocar reads. El `sub`
    se extrae del request SOLO con MFA activo (no introduce dependencia auth nueva)."""

    def test_write_role_owner_not_enrolled_past_grace_403(self):
        with patch.object(A, "_extract_jwt_payload", return_value={"sub": "u1"}), \
             patch.object(A, "_lookup_mfa_state_cached", return_value=(False, _ago(30))):
            with self.assertRaises(HTTPException) as cm:
                asyncio.run(A.require_write_role(request=object(), role="owner"))
            self.assertEqual(cm.exception.status_code, 403)

    def test_write_role_owner_enrolled_passes(self):
        with patch.object(A, "_extract_jwt_payload", return_value={"sub": "u1"}), \
             patch.object(A, "_lookup_mfa_state_cached", return_value=(True, _ago(999))):
            out = asyncio.run(A.require_write_role(request=object(), role="owner"))
            self.assertEqual(out, "owner")

    def test_write_role_operator_403_by_role_before_mfa(self):
        """operator sigue rechazado por ROL (no llega al chequeo MFA)."""
        with patch.object(A, "_lookup_mfa_state_cached",
                          side_effect=AssertionError("no debe llegar a MFA para operator")):
            with self.assertRaises(HTTPException) as cm:
                asyncio.run(A.require_write_role(request=object(), role="operator"))
            self.assertEqual(cm.exception.status_code, 403)
            self.assertIn("owner o manager", cm.exception.detail)

    def test_write_role_disabled_does_not_touch_jwt(self):
        """MFA off (default): el gate NO extrae el JWT del request → un test que solo
        mockea el rol NO recibe 401 espurio (la regresión que rompió finance/claims)."""
        with patch.dict(os.environ, {"MFA_MANDATORY_ENABLED": "false"}), \
             patch.object(A, "_extract_jwt_payload",
                          side_effect=AssertionError("no debe tocar el JWT con MFA off")), \
             patch.object(A, "_lookup_mfa_state_cached", return_value=(False, _ago(30))):
            out = asyncio.run(A.require_write_role(request=object(), role="owner"))
            self.assertEqual(out, "owner")

    def test_write_role_no_jwt_resolvable_does_not_lock(self):
        """MFA on pero request sin JWT resoluble (override en test) → sub vacío → no-op
        (no encerrar; el 401 real lo daría el gate de auth primario)."""
        with patch.object(A, "_extract_jwt_payload",
                          side_effect=HTTPException(status_code=401, detail="no jwt")), \
             patch.object(A, "_lookup_mfa_state_cached",
                          side_effect=AssertionError("sin sub no debe consultar")):
            out = asyncio.run(A.require_write_role(request=object(), role="owner"))
            self.assertEqual(out, "owner")

    def test_owner_role_manager_403_by_role_before_mfa(self):
        with patch.object(A, "_lookup_mfa_state_cached",
                          side_effect=AssertionError("no debe llegar a MFA para manager")):
            with self.assertRaises(HTTPException) as cm:
                asyncio.run(A.require_owner_role(request=object(), role="manager"))
            self.assertEqual(cm.exception.status_code, 403)

    def test_owner_role_owner_not_enrolled_past_grace_403(self):
        with patch.object(A, "_extract_jwt_payload", return_value={"sub": "u1"}), \
             patch.object(A, "_lookup_mfa_state_cached", return_value=(False, _ago(30))):
            with self.assertRaises(HTTPException) as cm:
                asyncio.run(A.require_owner_role(request=object(), role="owner"))
            self.assertEqual(cm.exception.status_code, 403)


class CacheShapeRegressionTests(_Base):
    """El refactor a _lookup_mfa_state_cached (tupla 3) no rompe enforce_mfa (step-up)."""

    def test_lookup_state_returns_pair_and_caches(self):
        class _User:
            factors = [{"status": "verified"}]
            created_at = _ago(5)

        class _Resp:
            user = _User()

        class _Client:
            class auth:
                class admin:
                    @staticmethod
                    def get_user_by_id(_sub):
                        return _Resp()

        A._MFA_CACHE.clear()
        with patch.object(A, "_get_service_client", return_value=_Client()):
            has, created = A._lookup_mfa_state_cached("uZ")
            self.assertTrue(has)
            self.assertEqual(created, _User.created_at)
            # segunda llamada = cache hit (no re-consulta): rompe el client → aún sirve.
        self.assertTrue(A._lookup_verified_mfa_cached("uZ"))  # desde cache, sin client

    def test_verified_wrapper_still_fail_open(self):
        class _Boom:
            class auth:
                class admin:
                    @staticmethod
                    def get_user_by_id(_sub):
                        raise RuntimeError("down")

        A._MFA_CACHE.clear()
        with patch.object(A, "_get_service_client", return_value=_Boom()):
            self.assertFalse(A._user_has_verified_mfa("uB"))


if __name__ == "__main__":
    unittest.main()
