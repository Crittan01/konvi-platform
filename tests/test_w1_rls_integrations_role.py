"""W1 (auditoría 2026-07-13) — guard de la RLS role-aware de integraciones/notificaciones.

tenant_integrations + notification_settings tenían `FOR ALL USING(tenant_id)` sin rol →
operator reescribía config de integración / chat_id Telegram vía PostgREST. La migración
20260713020000 las pasó a SELECT-miembros + escrituras owner/manager (verificado en prod:
operator lee pero escrituras=0; owner escribe). Guard estático anti-regresión.
"""
import re
import unittest
from pathlib import Path

_MIG = (Path(__file__).resolve().parents[1]
        / "supabase/migrations/20260713020000_w1_rls_integrations_notifications_role.sql")


class RlsIntegrationsRoleGuard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        raw = _MIG.read_text()
        cls.code = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("--"))

    def test_dropea_las_for_all_role_blind(self):
        # Debe DROP de la vieja "Tenant Isolation" en ambas tablas.
        self.assertEqual(
            self.code.count('DROP POLICY IF EXISTS "Tenant Isolation"'), 2)

    def test_ambas_tablas_select_member_y_write_privileged(self):
        for tbl in ("tenant_integrations", "notification_settings"):
            self.assertRegex(self.code, rf"{tbl}_select_member[\s\S]*?FOR SELECT")
            self.assertRegex(self.code, rf"{tbl}_write_privileged[\s\S]*?FOR ALL")

    def test_escrituras_exigen_owner_o_manager_con_with_check(self):
        # 2 policies de escritura, cada una con el filtro de rol en USING + WITH CHECK
        # = 4 ocurrencias del clause de rol y 2 WITH CHECK.
        self.assertEqual(
            self.code.count("role') IN ('owner', 'manager')"), 4,
            "esperadas 4 (2 policies × USING+WITH CHECK) con filtro owner/manager")
        self.assertEqual(len(re.findall(r"FOR ALL", self.code)), 2)
        # "WITH CHECK (" (con paréntesis) = solo las 2 policies; el texto del
        # COMMENT ON también dice "WITH CHECK" pero sin el paréntesis de apertura.
        self.assertEqual(self.code.count("WITH CHECK ("), 2)


if __name__ == "__main__":
    unittest.main()
