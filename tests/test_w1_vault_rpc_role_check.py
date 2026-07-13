"""W1 (auditoría 2026-07-13) — guard estático del role-check de los Vault RPCs.

HIGH: los 5 pgsec_* (read/update/delete/upsert/create) autorizaban por MEMBRESÍA →
un OPERATOR podía descifrar los secrets del tenant (access_token WhatsApp, bot_token
Telegram, refresh_token MeLi) vía PostgREST RPC directo. La migración 20260713010000
añadió `AND role IN ('owner','manager')` (verificado empíricamente contra prod:
owner puede_leer=true, operator puede_leer=false; aplicada + ledger repaired).

Guard estático (el harness RLS ejecutable a nivel DB llega también en W1): asegura que
los 5 RPCs exijan rol owner/manager y NO reintroduzcan el check membership-only.
"""
import re
import unittest
from pathlib import Path

_MIG = (Path(__file__).resolve().parents[1]
        / "supabase/migrations/20260713010000_w1_vault_rpc_role_check.sql")
_RPCS = ["pgsec_read_secret", "pgsec_update_secret", "pgsec_delete_secret",
         "pgsec_upsert_secret", "pgsec_create_secret"]


class VaultRpcRoleCheckGuard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        raw = _MIG.read_text()
        cls.sql = raw
        # SQL sin comentarios: el comentario de cabecera describe el check VIEJO
        # vulnerable (membership sin rol) y contaría como falso positivo.
        cls.code = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("--"))

    def test_migracion_existe(self):
        self.assertTrue(_MIG.exists())

    def test_los_5_rpcs_se_recrean(self):
        for rpc in _RPCS:
            self.assertIn(f"FUNCTION {rpc}(", self.sql, f"falta {rpc}")

    def test_cada_membership_check_exige_rol_owner_manager(self):
        # Robusto por conteo: cada uno de los 5 RPCs tiene EXACTAMENTE un check de
        # membresía (`user_id = auth.uid()`) y un filtro de rol. Si son iguales (y ==5),
        # ningún check quedó membership-only (= sin el filtro de rol → hueco operator).
        n_membership = len(re.findall(r"user_id\s*=\s*auth\.uid\(\)", self.code))
        n_role = self.code.count("role IN ('owner', 'manager')")
        self.assertEqual(n_membership, 5, f"esperados 5 checks de membresía, hay {n_membership}")
        self.assertEqual(
            n_role, n_membership,
            f"{n_membership} checks de membresía pero solo {n_role} con filtro de rol "
            "→ algún RPC quedó membership-only (hueco operator)",
        )


if __name__ == "__main__":
    unittest.main()
