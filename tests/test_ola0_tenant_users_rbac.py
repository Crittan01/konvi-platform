"""OLA 0 (auditoría 2026-07-13) — guard estático de la RLS de tenant_users.

El CRITICAL de la auditoría fue la policy `FOR ALL USING (tenant_id=...)` sin check
de rol → escalada operator/manager→owner por UPDATE directo vía PostgREST. La
migración 20260713000000 la reemplazó por SELECT-miembros + INSERT/UPDATE/DELETE
owner-only (verificado empíricamente contra prod con SET request.jwt.claims).

Este test es un guard estático (el harness RLS ejecutable a nivel DB va en la Ola 1,
pgTAP): asegura que la migración exista con escrituras role-gated y que NO reintroduzca
una policy de escritura permisiva sin check de rol owner.
"""
import re
import unittest
from pathlib import Path

_MIG = (Path(__file__).resolve().parents[1]
        / "supabase/migrations/20260713000000_ola0_tenant_users_rbac_hardening.sql")


class TenantUsersRbacMigrationGuard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        raw = _MIG.read_text()
        cls.sql = raw
        # SQL sin líneas de comentario (los comentarios describen la policy VIEJA
        # vulnerable con 'FOR ALL USING' y darían falsos positivos).
        cls.code = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("--"))

    def test_migracion_existe(self):
        self.assertTrue(_MIG.exists())

    def test_dropea_la_policy_for_all_vulnerable(self):
        self.assertIn('DROP POLICY IF EXISTS "Tenant Isolation — tenant_users"', self.sql)

    def test_escrituras_son_owner_only(self):
        # cada policy de escritura debe exigir el claim de rol owner.
        for cmd in ("INSERT", "UPDATE", "DELETE"):
            m = re.search(rf"FOR {cmd}\b(.*?)(?=CREATE POLICY|COMMENT ON|\Z)", self.sql, re.S)
            self.assertIsNotNone(m, f"falta policy FOR {cmd}")
            body = m.group(1)
            self.assertIn("'app_metadata' ->> 'role') = 'owner'", body,
                          f"policy {cmd} no exige rol owner (riesgo de escalada)")

    def test_update_tiene_with_check(self):
        # sin WITH CHECK, un owner podría mover una fila fuera de la condición;
        # y es la defensa que impide setear valores prohibidos.
        m = re.search(r"FOR UPDATE(.*?)(?=CREATE POLICY|COMMENT ON|\Z)", self.sql, re.S)
        self.assertIn("WITH CHECK", m.group(1))

    def test_no_reintroduce_for_all_permisivo(self):
        # No debe haber una policy FOR ALL sin check de rol (la clase del bug).
        # Se ignora el texto de comentarios (describe la policy vieja).
        for m in re.finditer(r"FOR ALL(.*?)(?=CREATE POLICY|COMMENT ON|\Z)", self.code, re.S):
            self.assertIn("'role') = 'owner'", m.group(1),
                          "FOR ALL sin check de rol reintroduce la escalada")


if __name__ == "__main__":
    unittest.main()
