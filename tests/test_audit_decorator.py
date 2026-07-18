"""
Rev. 72 — tests del decorator @audit_log.

Cubre:
- write_audit_event inserta payload con shape correcto.
- audit_log decorator extrae user_email/user_id del JWT.
- Si supabase/tenant_id faltan en kwargs, el decorator no rompe.
- Si el insert falla, el handler retorna OK igual (fire-and-forget).
- entity_id se extrae de path params *_id o de result.id / result['id'].
"""
import asyncio
import inspect
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from dependencies.audit import (  # noqa: E402
    audit_log,
    write_audit_event,
    _extract_entity_id,
    _safe_jsonable,
)


class WriteAuditEventTests(unittest.TestCase):

    def test_basic_payload(self):
        sb = MagicMock()
        write_audit_event(
            supabase=sb,
            tenant_id="t-1",
            action="created",
            entity_type="order",
            entity_id="ord-42",
            user_email="user@x.com",
            user_id="u-1",
            payload={"total": 100},
        )
        sb.table.assert_called_once_with("audit_log")
        insert_call = sb.table.return_value.insert.call_args
        body = insert_call.args[0]
        self.assertEqual(body["tenant_id"], "t-1")
        self.assertEqual(body["entity_type"], "order")
        self.assertEqual(body["entity_id"], "ord-42")
        self.assertEqual(body["action"], "created")
        self.assertEqual(body["user_email"], "user@x.com")

    def test_insert_failure_swallowed(self):
        """Si el insert falla, no propaga excepción (fire-and-forget)."""
        sb = MagicMock()
        sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("boom")
        # No debería lanzar
        write_audit_event(
            supabase=sb, tenant_id="t-1", action="created", entity_type="order"
        )

    def test_entity_id_none_serialized_as_none(self):
        sb = MagicMock()
        write_audit_event(supabase=sb, tenant_id="t", action="x", entity_type="y", entity_id=None)
        body = sb.table.return_value.insert.call_args.args[0]
        self.assertIsNone(body["entity_id"])


class ExtractEntityIdTests(unittest.TestCase):

    def test_path_param_takes_precedence(self):
        kwargs = {"order_id": "ord-1", "tenant_id": "t-1"}
        self.assertEqual(_extract_entity_id(kwargs, {"id": "result-id"}), "ord-1")

    def test_skips_tenant_id_and_user_id(self):
        kwargs = {"tenant_id": "t-1", "user_id": "u-1"}
        self.assertIsNone(_extract_entity_id(kwargs, None))

    def test_result_dict_id_fallback(self):
        kwargs = {}
        self.assertEqual(_extract_entity_id(kwargs, {"id": "abc"}), "abc")

    def test_result_obj_id_fallback(self):
        class Obj:
            id = "xyz"
        self.assertEqual(_extract_entity_id({}, Obj()), "xyz")

    def test_no_id_anywhere_returns_none(self):
        self.assertIsNone(_extract_entity_id({}, None))


class SafeJsonableTests(unittest.TestCase):

    def test_pydantic_model_serialized(self):
        from pydantic import BaseModel

        class M(BaseModel):
            x: int = 1
            y: str = "ok"

        out = _safe_jsonable(M())
        self.assertEqual(out, {"x": 1, "y": "ok"})

    def test_nested_dict(self):
        self.assertEqual(_safe_jsonable({"a": [1, 2], "b": {"c": "ok"}}),
                         {"a": [1, 2], "b": {"c": "ok"}})

    def test_unsupported_returns_none(self):
        class Weird:
            pass
        self.assertIsNone(_safe_jsonable(Weird()))


class AuditLogDecoratorTests(unittest.IsolatedAsyncioTestCase):

    async def test_decorator_inserts_after_handler_success(self):
        sb = MagicMock()

        @audit_log(entity_type="order", action="created")
        async def fake_handler(*, request, tenant_id, supabase, body):
            return {"id": "ord-99", "total": 50}

        # request es opcional; mock simple. JWT no se valida (usuario no es kw clave aquí).
        request_mock = MagicMock()
        with patch("dependencies.audit._extract_jwt_payload", return_value={"sub": "u-1", "email": "u@x.com"}):
            result = await fake_handler(
                request=request_mock,
                tenant_id="t-1",
                supabase=sb,
                body={"foo": "bar"},
            )
        self.assertEqual(result["id"], "ord-99")
        # audit_log fue llamado
        sb.table.assert_called_with("audit_log")
        body = sb.table.return_value.insert.call_args.args[0]
        self.assertEqual(body["entity_type"], "order")
        self.assertEqual(body["action"], "created")
        self.assertEqual(body["entity_id"], "ord-99")
        self.assertEqual(body["user_email"], "u@x.com")

    async def test_decorator_skips_if_no_supabase(self):
        @audit_log(entity_type="x", action="created")
        async def fake_handler(**_):
            return {"id": "z"}
        # Sin supabase ni tenant_id → no rompe, retorna result.
        result = await fake_handler()
        self.assertEqual(result["id"], "z")

    async def test_decorator_propagates_handler_exception(self):
        sb = MagicMock()

        @audit_log(entity_type="order", action="created")
        async def fake_handler(**_):
            raise ValueError("handler failed")

        with self.assertRaises(ValueError):
            await fake_handler(request=MagicMock(), tenant_id="t", supabase=sb)
        # No insert (handler falló antes)
        sb.table.assert_not_called()


class AuditLogDecoratorSyncTests(unittest.TestCase):
    """async-agnostic (Wave 3): @audit_log ahora soporta handlers `def` (threadpool)."""

    def test_wrapper_preserves_sync_nature(self):
        # CLAVE: el wrapper de un handler def debe seguir siendo def (NO coroutine),
        # si no Starlette no lo corre en el threadpool y no sirve para el HOL fix.
        @audit_log(entity_type="x", action="y")
        def sync_handler(**_):
            return {}
        self.assertFalse(inspect.iscoroutinefunction(sync_handler))

    def test_wrapper_preserves_async_nature(self):
        @audit_log(entity_type="x", action="y")
        async def async_handler(**_):
            return {}
        self.assertTrue(inspect.iscoroutinefunction(async_handler))

    def test_sync_handler_audits_after_success(self):
        sb = MagicMock()

        @audit_log(entity_type="product", action="updated")
        def sync_handler(*, request, tenant_id, supabase, body):
            return {"id": "prod-7"}

        with patch("dependencies.audit._extract_jwt_payload", return_value={"sub": "u-1", "email": "u@x.com"}):
            result = sync_handler(request=MagicMock(), tenant_id="t-1", supabase=sb, body={})
        self.assertEqual(result["id"], "prod-7")
        sb.table.assert_called_with("audit_log")
        body = sb.table.return_value.insert.call_args.args[0]
        self.assertEqual(body["entity_type"], "product")
        self.assertEqual(body["action"], "updated")
        self.assertEqual(body["entity_id"], "prod-7")

    def test_sync_handler_skips_if_no_supabase(self):
        @audit_log(entity_type="x", action="created")
        def sync_handler(**_):
            return {"id": "z"}
        self.assertEqual(sync_handler()["id"], "z")

    def test_sync_handler_propagates_exception(self):
        sb = MagicMock()

        @audit_log(entity_type="order", action="created")
        def sync_handler(**_):
            raise ValueError("boom")
        with self.assertRaises(ValueError):
            sync_handler(request=MagicMock(), tenant_id="t", supabase=sb)
        sb.table.assert_not_called()  # no audita si el handler falló


if __name__ == "__main__":
    unittest.main()
