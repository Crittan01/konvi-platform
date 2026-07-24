"""F-doc (Fase 6, validación docs oficiales) — contrato real de postgrest 2.28.3.

Dos hechos verificados contra el source instalado, base de F18/F19/F63:
  1. `.maybe_single().execute()` retorna None (el objeto completo) en 0 filas — NO
     un objeto con .data=None. Por eso todo guard debe ser `if not res or not res.data`.
  2. `.insert()/.update()` devuelven SyncQueryRequestBuilder SIN .select()/.single()
     (el chain '.insert().select().single()' lanza AttributeError → endpoint roto).

Este test fija esos contratos + prueba que un handler con maybe_single devuelve 404
(no 500 por AttributeError) cuando la fila no existe.
"""
import asyncio
import inspect
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from fastapi import HTTPException  # noqa: E402
from routers import claims  # noqa: E402


class PostgrestLibraryContractTests(unittest.TestCase):
    def test_maybe_single_returns_none_on_zero_rows(self):
        from postgrest._sync.request_builder import SyncMaybeSingleRequestBuilder
        src = inspect.getsource(SyncMaybeSingleRequestBuilder.execute)
        # El contrato del que dependen los guards None-safe.
        self.assertIn("return None", src)

    def test_insert_builder_has_no_single(self):
        """El footgun que este contrato previene es `.insert()/.update() … .single()`
        (→ AttributeError → endpoint roto). El guard REAL y version-agnóstico es que el
        insert/update builder NO expone `.single`: verdad en postgrest 2.28.3 (supabase
        2.28) Y en 2.31 (supabase 2.31, lo que corre prod). `.select` SÍ cambió (2.31 lo
        agregó al insert builder), pero eso no reintroduce el footgun porque `.single`
        sigue ausente — por eso el contrato se ancla en `.single`, no en `.select`."""
        from postgrest._sync.request_builder import SyncQueryRequestBuilder
        self.assertFalse(hasattr(SyncQueryRequestBuilder, "single"),
                         "el insert/update builder no debe exponer .single (footgun)")


class MaybeSingleNoneReturns404Tests(unittest.IsolatedAsyncioTestCase):
    async def test_get_claim_missing_returns_404_not_500(self):
        """maybe_single().execute() → None (fila ausente) debe dar 404, no
        AttributeError → 500. Guard: 'if not res or not res.data'."""
        supabase = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = None  # ← postgrest 2.28.3: 0 filas → None
        supabase.table.return_value = chain

        with self.assertRaises(HTTPException) as ctx:
            claims.get_claim(
                claim_id="claim-missing", tenant_id="t-1", supabase=supabase,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_get_claim_found_returns_row(self):
        supabase = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = types.SimpleNamespace(
            data={"id": "claim-1", "status": "open"},
        )
        supabase.table.return_value = chain
        result = claims.get_claim(
            claim_id="claim-1", tenant_id="t-1", supabase=supabase,
        )
        self.assertEqual(result["id"], "claim-1")


if __name__ == "__main__":
    unittest.main()
