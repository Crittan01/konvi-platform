"""Tests `services/api/lib/contact_cleanup.py` (Sem 7 F2 cierre 2026-05-19).

Bug founder UAT 2026-05-19 (conv 056490b8): tras eliminar contact desde UI,
carts históricos persisten en DB → cart-recovery flow contamina próxima conv.

Helper compartido `purge_contact_completely` ejecuta cascade completo,
usado por endpoint API y script CLI.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from lib.contact_cleanup import (  # noqa: E402
    purge_contact_completely,
    _safe_delete,
    _collect_contact_resources,
    _check_active_wompi_payment_links,
    PurgeBlockedError,
)


class _FakeQuery:
    """Mock chainable de supabase.table(...).select/delete/.eq/.in_/.execute()."""
    def __init__(self, returns_data=None, raises=None):
        self._returns = returns_data or []
        self._raises = raises
        self.calls: list[tuple] = []

    def select(self, *args, **kwargs):
        self.calls.append(("select", args, kwargs))
        return self

    def delete(self):
        self.calls.append(("delete",))
        return self

    def update(self, data):
        self.calls.append(("update", data))
        return self

    def eq(self, col, val):
        self.calls.append(("eq", col, val))
        return self

    def in_(self, col, val):
        self.calls.append(("in_", col, val))
        return self

    def single(self):
        self.calls.append(("single",))
        return self

    def limit(self, n):
        self.calls.append(("limit", n))
        return self

    def or_(self, clause):
        self.calls.append(("or_", clause))
        return self

    def gte(self, col, val):
        self.calls.append(("gte", col, val))
        return self

    def execute(self):
        if self._raises:
            raise self._raises
        return MagicMock(data=self._returns)


class _FakeSupabase:
    """Mock supabase client. Cada tabla puede devolver datos custom."""

    def __init__(self):
        self.tables: dict[str, _FakeQuery] = {}
        self.table_calls: list[str] = []

    def set_table(self, name: str, returns=None, raises=None):
        self.tables[name] = _FakeQuery(returns_data=returns, raises=raises)

    def table(self, name: str):
        self.table_calls.append(name)
        if name not in self.tables:
            self.tables[name] = _FakeQuery(returns_data=[])
        return self.tables[name]


class PurgeContactCompletelyTests(unittest.TestCase):

    def test_raises_si_falta_tenant_id(self):
        sb = _FakeSupabase()
        with self.assertRaises(ValueError):
            purge_contact_completely(sb, "", "contact-1")

    def test_raises_si_falta_contact_id(self):
        sb = _FakeSupabase()
        with self.assertRaises(ValueError):
            purge_contact_completely(sb, "tenant-1", "")

    def test_purge_idempotente_sin_recursos(self):
        """Contact sin conversations/orders/carts: solo borra el contact."""
        sb = _FakeSupabase()
        # Tablas con data=[] → counts=0.
        out = purge_contact_completely(sb, "tenant-1", "contact-1")
        self.assertEqual(out["orders_found"], 0)
        self.assertEqual(out["carts_found"], 0)
        self.assertEqual(out["conversations_found"], 0)
        self.assertEqual(out["payments_deleted"], 0)
        self.assertEqual(out["shipments_deleted"], 0)
        self.assertEqual(out["carts_deleted"], 0)
        self.assertEqual(out["orders_deleted"], 0)
        self.assertEqual(out["conversations_deleted"], 0)

    def test_contacto_con_ordenes_preserva_historial_y_anonimiza(self):
        """BLOQUE A (retención legal): contact CON órdenes → orders/payments/shipments
        PRESERVADOS + contact ANONIMIZADO (no borrado); pero los vectores de contaminación
        del bot (carts/conversations) SÍ se borran. Cód. Comercio Art. 60 / E.T. Art. 632."""
        sb = _FakeSupabase()
        sb.set_table("contacts", returns=[{"phone": "573125835649"}])
        sb.set_table("conversations", returns=[{"id": "conv-1"}, {"id": "conv-2"}])
        sb.set_table("orders", returns=[{"id": "ord-1"}])
        sb.set_table("conversation_carts", returns=[{"id": "cart-1"}])

        out = purge_contact_completely(sb, "tenant-1", "contact-1")
        self.assertTrue(out["phone_resolved"])
        self.assertEqual(out["orders_found"], 1)
        self.assertTrue(out["has_orders"])
        self.assertTrue(out["retention_applied"])
        # historial contable PRESERVADO (no se borra)
        self.assertEqual(out["orders_deleted"], 0)
        self.assertEqual(out["payments_deleted"], 0)
        self.assertEqual(out["shipments_deleted"], 0)
        self.assertEqual(out["order_items_deleted"], 0)
        # contact ANONIMIZADO, no borrado (preserva el FK orders.contact_id)
        self.assertFalse(out["contact_deleted"])
        self.assertTrue(out["contact_anonymized"])

    def test_contacto_sin_ordenes_cascade_fisico(self):
        """BLOQUE A: contact SIN órdenes (sin historial contable) → cascade físico completo,
        incluida la fila contact (comportamiento previo al fix de retención)."""
        sb = _FakeSupabase()
        sb.set_table("contacts", returns=[{"phone": "573000000000"}])
        sb.set_table("conversations", returns=[{"id": "conv-1"}])
        # sin orders (default [])
        out = purge_contact_completely(sb, "tenant-1", "contact-1")
        self.assertFalse(out["has_orders"])
        self.assertFalse(out["retention_applied"])
        self.assertTrue(out["contact_deleted"])
        self.assertNotIn("contact_anonymized", out)

    def test_summary_tiene_keys_estandares(self):
        """El dict de salida tiene contract estable."""
        sb = _FakeSupabase()
        out = purge_contact_completely(sb, "tenant-1", "contact-1")
        expected_keys = {
            "tenant_id", "contact_id",
            "phone_resolved",
            "errors",
            "orders_found", "carts_found", "conversations_found",
            "payments_deleted", "shipments_deleted",
            "cart_events_deleted", "cart_items_deleted",
            "carts_deleted",
            "order_items_deleted", "orders_deleted",
            "messages_deleted", "reads_deleted",
            "conversations_deleted",
            "contact_deleted",
        }
        self.assertTrue(expected_keys.issubset(set(out.keys())),
                        f"missing: {expected_keys - set(out.keys())}")

    def test_errors_se_acumulan_cuando_query_falla(self):
        """Sem 7 F2 cierre — Bug runtime founder UAT 2026-05-19:
        DELETE silente 400 enmascaraba el problema. Ahora cuando una
        operación falla, summary['errors'] contiene el detalle. NUNCA
        falsea count=0 sin reporte. (Se usa conversation_carts — que se borra
        SIEMPRE — porque payments ahora se preservan si hay órdenes.)"""
        sb = _FakeSupabase()
        sb.set_table("contacts", returns=[{"phone": "573111111111"}])
        sb.set_table("conversation_carts", raises=Exception("permission denied"))
        out = purge_contact_completely(sb, "tenant-1", "contact-1")
        self.assertIsInstance(out["errors"], list)
        joined = " ".join(out["errors"])
        self.assertIn("permission denied", joined)


class CollectContactResourcesTests(unittest.TestCase):

    def test_recolecta_ids_correctamente(self):
        sb = _FakeSupabase()
        sb.set_table("conversations", returns=[
            {"id": "c1"}, {"id": "c2"}, {"id": "c3"},
        ])
        sb.set_table("orders", returns=[{"id": "o1"}, {"id": "o2"}])
        sb.set_table("conversation_carts", returns=[{"id": "ct1"}])

        # Sem 7 F2 cierre — conversations lookup requiere phone.
        out = _collect_contact_resources(
            sb, "t1", "ct1", phone="573125835649",
        )
        self.assertEqual(out["conversation_ids"], ["c1", "c2", "c3"])
        self.assertEqual(out["order_ids"], ["o1", "o2"])
        self.assertEqual(out["cart_ids"], ["ct1"])

    def test_conversation_ids_vacio_sin_phone(self):
        """Sin phone (contact ya borrado o sin teléfono), conversations
        no se pueden resolver — retorna lista vacía."""
        sb = _FakeSupabase()
        sb.set_table("conversations", returns=[{"id": "c1"}])
        out = _collect_contact_resources(sb, "t1", "ct1", phone=None)
        self.assertEqual(out["conversation_ids"], [])

    def test_skip_table_inexistente(self):
        """Si una tabla aún no existe (migración pendiente en algún ambiente)
        el helper retorna lista vacía sin levantar excepción."""
        sb = _FakeSupabase()
        sb.set_table("conversations", raises=Exception("table not found"))
        out = _collect_contact_resources(
            sb, "t1", "c1", phone="573125835649",
        )
        self.assertEqual(out["conversation_ids"], [])


class SafeDeleteTests(unittest.TestCase):
    """Contract: _safe_delete retorna tupla (count, error_msg) — Sem 7 F2
    cierre 2026-05-19 (transparencia: distinguir "no data" de "query fail")."""

    def test_delete_simple_eq(self):
        sb = _FakeSupabase()
        sb.set_table("orders", returns=[{"id": "o1"}, {"id": "o2"}])
        count, err = _safe_delete(sb, "orders", "contact_id", "c1")
        self.assertEqual(count, 2)
        self.assertIsNone(err)

    def test_delete_in_list(self):
        sb = _FakeSupabase()
        sb.set_table("payments", returns=[{"id": "p1"}])
        count, err = _safe_delete(sb, "payments", "order_id", ["o1", "o2"], in_list=True)
        self.assertEqual(count, 1)
        self.assertIsNone(err)

    def test_delete_lista_vacia_no_ejecuta(self):
        """Si in_list con lista vacía → (0, None) sin tocar DB."""
        sb = _FakeSupabase()
        count, err = _safe_delete(sb, "payments", "order_id", [], in_list=True)
        self.assertEqual(count, 0)
        self.assertIsNone(err)

    def test_delete_si_tabla_falla_retorna_error_msg(self):
        """Cuando query falla (tabla no existe / columna inválida / RLS),
        retorna (0, str(exc)) para que caller pueda reportarlo (no falso 0)."""
        sb = _FakeSupabase()
        sb.set_table("missing_table", raises=Exception("relation does not exist"))
        count, err = _safe_delete(sb, "missing_table", "id", "x")
        self.assertEqual(count, 0)
        self.assertIsNotNone(err)
        self.assertIn("relation does not exist", err)


class WompiPaymentLinkGuardTests(unittest.TestCase):
    """Sem 7 F2 cierre 2026-05-21 — Capa A: guard pre-purge contra links Wompi
    activos. Wompi NO permite invalidar payment_links; única defensa contra
    pago tardío en link huérfano = bloquear purga cuando hay link <30 min."""

    def test_sin_orders_returns_lista_vacia(self):
        sb = _FakeSupabase()
        # No orders → no payments posibles.
        out = _check_active_wompi_payment_links(sb, "tenant-1", "contact-1")
        self.assertEqual(out, [])

    def test_orders_sin_payments_pending_returns_vacia(self):
        sb = _FakeSupabase()
        sb.set_table("orders", returns=[{"id": "ord-1"}])
        # payments default returns=[] → sin pending activos.
        out = _check_active_wompi_payment_links(sb, "tenant-1", "contact-1")
        self.assertEqual(out, [])

    def test_payment_pending_activo_se_reporta(self):
        sb = _FakeSupabase()
        sb.set_table("orders", returns=[{"id": "ord-1"}])
        sb.set_table("payments", returns=[
            {
                "id": "pay-1",
                "order_id": "ord-1",
                "wompi_link_id": "link-xyz",
                "checkout_url": "https://checkout.wompi.co/l/link-xyz",
                "status": "pending",
                "created_at": "2026-05-21T19:00:00Z",
            },
        ])
        out = _check_active_wompi_payment_links(sb, "tenant-1", "contact-1")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["payment_id"], "pay-1")
        self.assertEqual(out[0]["wompi_link_id"], "link-xyz")
        self.assertIn("checkout.wompi.co", out[0]["checkout_url"])

    def test_orders_lookup_falla_degrade_gracefully(self):
        """Si SELECT orders falla, no bloquea (operador opera ciego pero
        mejor que false-positive bloqueo total)."""
        sb = _FakeSupabase()
        sb.set_table("orders", raises=Exception("permission denied"))
        out = _check_active_wompi_payment_links(sb, "tenant-1", "contact-1")
        self.assertEqual(out, [])

    def test_payments_lookup_falla_degrade_gracefully(self):
        sb = _FakeSupabase()
        sb.set_table("orders", returns=[{"id": "ord-1"}])
        sb.set_table("payments", raises=Exception("rls"))
        out = _check_active_wompi_payment_links(sb, "tenant-1", "contact-1")
        self.assertEqual(out, [])


class PurgeBlockedByActiveWompiLinkTests(unittest.TestCase):
    """`purge_contact_completely` levanta `PurgeBlockedError` cuando hay link
    Wompi activo. La excepción incluye `pending_payments` para que el endpoint
    API la propague al UI con detalle."""

    def test_bloqueado_si_hay_link_activo(self):
        sb = _FakeSupabase()
        sb.set_table("orders", returns=[{"id": "ord-1"}])
        sb.set_table("payments", returns=[
            {
                "id": "pay-1",
                "order_id": "ord-1",
                "wompi_link_id": "link-xyz",
                "checkout_url": "https://checkout.wompi.co/l/link-xyz",
                "status": "pending",
                "created_at": "2026-05-21T19:00:00Z",
            },
        ])
        with self.assertRaises(PurgeBlockedError) as ctx:
            purge_contact_completely(sb, "tenant-1", "contact-1")
        self.assertEqual(len(ctx.exception.pending_payments), 1)
        self.assertIn("Wompi", ctx.exception.reason)

    def test_skip_wompi_guard_bypassa(self):
        """`skip_wompi_guard=True` permite cascade aún con links activos
        (script CLI admin que SABE qué hace)."""
        sb = _FakeSupabase()
        sb.set_table("orders", returns=[{"id": "ord-1"}])
        sb.set_table("payments", returns=[
            {
                "id": "pay-1",
                "order_id": "ord-1",
                "wompi_link_id": "link-xyz",
                "checkout_url": "https://checkout.wompi.co/l/link-xyz",
                "status": "pending",
                "created_at": "2026-05-21T19:00:00Z",
            },
        ])
        # NO levanta — bypass del guard.
        out = purge_contact_completely(
            sb, "tenant-1", "contact-1", skip_wompi_guard=True,
        )
        self.assertIn("orders_found", out)


if __name__ == "__main__":
    unittest.main()
