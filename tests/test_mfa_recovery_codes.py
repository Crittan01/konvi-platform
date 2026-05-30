"""Tests `services/api/lib/mfa_recovery_codes.py` (rev. 109 J.2.4.3).

Cubre:
  1. generate_codes — formato, count, entropía.
  2. _hash_code/_verify_code — bcrypt round-trip.
  3. regenerate_for_user — invoca RPC con hashes correctos.
  4. verify_and_consume — happy path + miss + plaintext malformado.
  5. list_remaining — count desde DB.
  6. clear_all_for_user — delete + return count.

NO requiere DB real — fake Supabase + skip tests bcrypt-pesados con SLOW_TESTS.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "services" / "api" / "lib" / "mfa_recovery_codes.py"

SLOW_TESTS = os.environ.get("SLOW_TESTS") == "1"


def _load():
    spec = importlib.util.spec_from_file_location("_mfa_rc", LIB_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_mfa_rc"] = mod
    spec.loader.exec_module(mod)
    return mod


mfa = _load()


# ─── Fake Supabase ─────────────────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, data=None, count=None, raise_with=None):
        self._data = data or []
        self._count = count
        self._raise = raise_with

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def delete(self): return self

    def execute(self):
        if self._raise:
            raise self._raise
        return SimpleNamespace(data=self._data, count=self._count)


class _FakeRpcCall:
    def __init__(self, reg, fn, args, result=None):
        self._reg = reg
        self._fn = fn
        self._args = args
        self._result = result

    def execute(self):
        self._reg.append({"fn": self._fn, "args": self._args})
        return SimpleNamespace(data=self._result)


class _FakeSupabase:
    def __init__(self, table_data=None, table_count=None, rpc_results=None):
        self._table_data = table_data or {}
        self._table_count = table_count or {}
        self._rpc_results = rpc_results or {}
        self.rpc_calls = []

    def table(self, name):
        return _FakeQuery(
            data=self._table_data.get(name, []),
            count=self._table_count.get(name),
        )

    def rpc(self, fn, args=None):
        return _FakeRpcCall(self.rpc_calls, fn, args, self._rpc_results.get(fn))


# ─── Tests ─────────────────────────────────────────────────────────────────


class GenerateCodesTests(unittest.TestCase):
    def test_genera_count_correcto(self):
        codes = mfa.generate_codes(num=8)
        self.assertEqual(len(codes), 8)

    def test_formato_con_guiones(self):
        codes = mfa.generate_codes(num=1)
        c = codes[0]
        self.assertEqual(len(c), 19)  # 4-4-4-4 + 3 guiones
        parts = c.split("-")
        self.assertEqual(len(parts), 4)
        for p in parts:
            self.assertEqual(len(p), 4)

    def test_codes_son_unicos(self):
        codes = mfa.generate_codes(num=20)
        self.assertEqual(len(set(codes)), 20, "Códigos repetidos detectados")

    def test_codes_uppercase(self):
        codes = mfa.generate_codes(num=3)
        for c in codes:
            self.assertEqual(c, c.upper())

    def test_rango_invalido(self):
        with self.assertRaises(mfa.MFARecoveryCodesError):
            mfa.generate_codes(num=0)
        with self.assertRaises(mfa.MFARecoveryCodesError):
            mfa.generate_codes(num=100)


@unittest.skipUnless(SLOW_TESTS, "bcrypt lento — habilitar con SLOW_TESTS=1")
class BcryptRoundTripTests(unittest.TestCase):
    def test_hash_verify_match(self):
        plaintext = "ABCD-1234-EFGH-5678"
        h = mfa._hash_code(plaintext)
        self.assertTrue(mfa._verify_code(plaintext, h))

    def test_hash_verify_mismatch(self):
        plaintext = "ABCD-1234-EFGH-5678"
        h = mfa._hash_code(plaintext)
        self.assertFalse(mfa._verify_code("WRONG-CODE-HERE-NOPE", h))

    def test_hash_idempotente(self):
        plaintext = "TEST-CODE-PLEASE-MATCH"
        h1 = mfa._hash_code(plaintext)
        h2 = mfa._hash_code(plaintext)
        # Hashes distintos (salt diferente), pero ambos verifican el plaintext.
        self.assertNotEqual(h1, h2)
        self.assertTrue(mfa._verify_code(plaintext, h1))
        self.assertTrue(mfa._verify_code(plaintext, h2))


class RegenerateForUserTests(unittest.TestCase):
    @unittest.skipUnless(SLOW_TESTS, "bcrypt lento")
    def test_invoca_rpc_con_hashes(self):
        sb = _FakeSupabase(rpc_results={"fn_regenerate_mfa_recovery_codes": 8})
        codes = mfa.regenerate_for_user(sb, "user-uuid", num=8)
        self.assertEqual(len(codes), 8)
        self.assertEqual(len(sb.rpc_calls), 1)
        rpc = sb.rpc_calls[0]
        self.assertEqual(rpc["fn"], "fn_regenerate_mfa_recovery_codes")
        self.assertEqual(rpc["args"]["p_user_id"], "user-uuid")
        # Hashes son strings bcrypt $2b$...
        hashes = rpc["args"]["p_code_hashes"]
        self.assertEqual(len(hashes), 8)
        for h in hashes:
            self.assertTrue(h.startswith("$2"))

    def test_rpc_error_propaga(self):
        from types import SimpleNamespace

        class _FailRpc:
            def __init__(self, fn, args):
                self.fn = fn
                self.args = args

            def execute(self):
                raise Exception("DB connection lost")

        class _SB:
            def rpc(self, fn, args=None):
                return _FailRpc(fn, args)

        with self.assertRaises(mfa.MFARecoveryCodesError):
            mfa.regenerate_for_user(_SB(), "user-uuid", num=8)


class VerifyAndConsumeTests(unittest.TestCase):
    def test_plaintext_vacio_retorna_false(self):
        sb = _FakeSupabase()
        self.assertFalse(mfa.verify_and_consume(sb, "u", ""))

    def test_plaintext_muy_corto(self):
        sb = _FakeSupabase()
        self.assertFalse(mfa.verify_and_consume(sb, "u", "abc"))

    def test_no_hay_codes_no_usados(self):
        sb = _FakeSupabase(table_data={"mfa_recovery_codes": []})
        self.assertFalse(mfa.verify_and_consume(sb, "u", "ABCD-1234-EFGH-5678"))

    @unittest.skipUnless(SLOW_TESTS, "bcrypt lento")
    def test_match_consume_atomico(self):
        plaintext = "ABCD-1234-EFGH-5678"
        h = mfa._hash_code(plaintext)
        sb = _FakeSupabase(
            table_data={"mfa_recovery_codes": [{"code_hash": h}]},
            rpc_results={"fn_consume_mfa_recovery_code": True},
        )
        result = mfa.verify_and_consume(sb, "u", plaintext)
        self.assertTrue(result)
        # Verificar RPC consume invocada con el hash matched.
        rpc = sb.rpc_calls[0]
        self.assertEqual(rpc["fn"], "fn_consume_mfa_recovery_code")
        self.assertEqual(rpc["args"]["p_code_hash"], h)

    @unittest.skipUnless(SLOW_TESTS, "bcrypt lento")
    def test_no_match_retorna_false(self):
        plaintext_real = "REAL-CODE-IN-DB"
        h = mfa._hash_code(plaintext_real)
        sb = _FakeSupabase(table_data={"mfa_recovery_codes": [{"code_hash": h}]})
        result = mfa.verify_and_consume(sb, "u", "WRONG-CODE-NOPE")
        self.assertFalse(result)
        # NO RPC consume invocada (no hubo match).
        self.assertEqual(len(sb.rpc_calls), 0)


class ListRemainingTests(unittest.TestCase):
    def test_retorna_count(self):
        sb = _FakeSupabase(table_count={"mfa_recovery_codes": 5})
        self.assertEqual(mfa.list_remaining(sb, "u"), 5)

    def test_count_none_retorna_0(self):
        sb = _FakeSupabase(table_count={"mfa_recovery_codes": None})
        self.assertEqual(mfa.list_remaining(sb, "u"), 0)


class ClearAllForUserTests(unittest.TestCase):
    def test_delete_retorna_count(self):
        sb = _FakeSupabase(table_data={
            "mfa_recovery_codes": [{"id": 1}, {"id": 2}, {"id": 3}],
        })
        self.assertEqual(mfa.clear_all_for_user(sb, "u"), 3)


if __name__ == "__main__":
    unittest.main()
