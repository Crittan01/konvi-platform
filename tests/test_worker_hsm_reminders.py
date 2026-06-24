"""Tests cron HSM reminders worker.py
(Sem 7 F2 item 6.b / 2026-05-17).

Cubre:
  - `_try_send_payment_reminder_hsm`: HSM fallback fuera CSW
       * Template no APPROVED → return False + métrica hsm_not_approved
       * Template APPROVED + send OK → return True + idempotencia + outbound persistido
       * Order sin checkout_url → return False
  - `_send_cart_abandoned_reminders_if_due`: cron carts >24h
       * Sin consent_given → skip + métrica skipped_no_consent
       * Con consent + template approved → envía + marca idempotencia
       * Sin template approved → skip + métrica hsm_not_approved
       * No reintenta si abandoned_reminder_sent_at no NULL (idempotencia)

Mocks Supabase (FakeSupabase consistente con otros tests del repo) +
mock send_whatsapp_template via monkeypatch.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

# Stub vault_helper (worker.py importa whatsapp_sender que lo importa)
if "vault_helper" not in sys.modules:
    vault_stub = type(sys)("vault_helper")

    class _StubVaultHelper:
        def __init__(self, sb):
            pass

    vault_stub.VaultHelper = _StubVaultHelper  # type: ignore
    vault_stub.resolve_secret = lambda v, c, f: c.get(f, "")  # type: ignore
    sys.modules["vault_helper"] = vault_stub


# Importamos sólo los símbolos que necesitamos del worker para tests
# unitarios — la clase OrchestratorWorker entera incluye init Supabase
# real, vamos a montar una instancia con .supabase reemplazado por fake.


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ─── Fake Supabase ──────────────────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, store, op="select", payload=None):
        self._store = store
        self._op = op
        self._payload = payload
        self._filters: list = []
        self._is_null: list = []
        self._in_list: tuple | None = None
        self._lt: list = []
        self._gte: list = []
        self._order: list = []
        self._limit_n: int | None = None

    def select(self, *a, **k):
        return _FakeQuery(self._store, op="select")

    def update(self, payload):
        return _FakeQuery(self._store, op="update", payload=payload)

    def insert(self, payload):
        return _FakeQuery(self._store, op="insert", payload=payload)

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def is_(self, col, val):
        self._is_null.append((col, val))
        return self

    def in_(self, col, lst):
        self._in_list = (col, lst)
        return self

    def lt(self, col, val):
        self._lt.append((col, val))
        return self

    def gte(self, col, val):
        self._gte.append((col, val))
        return self

    def order(self, col, **k):
        self._order.append((col, k.get("desc", False)))
        return self

    def limit(self, n):
        self._limit_n = n
        return self

    def _matches(self, row):
        for op, col, val in self._filters:
            if row.get(col) != val:
                return False
        for col, val in self._is_null:
            if val == "null" and row.get(col) is not None:
                return False
        if self._in_list:
            col, lst = self._in_list
            if row.get(col) not in lst:
                return False
        for col, val in self._lt:
            if not (row.get(col) and row.get(col) < val):
                return False
        for col, val in self._gte:
            if not (row.get(col) and row.get(col) >= val):
                return False
        return True

    def execute(self):
        if self._op == "select":
            rows = [r for r in self._store if self._matches(r)]
            for col, desc in reversed(self._order):
                rows = sorted(rows, key=lambda r: r.get(col) or "", reverse=desc)
            if self._limit_n is not None:
                rows = rows[: self._limit_n]
            return SimpleNamespace(data=rows)
        if self._op == "update":
            updated = []
            for row in self._store:
                if self._matches(row):
                    for k, v in self._payload.items():
                        row[k] = v
                    updated.append(row)
            return SimpleNamespace(data=updated)
        if self._op == "insert":
            self._store.append(dict(self._payload))
            return SimpleNamespace(data=[self._payload])
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self):
        self._tables: dict[str, list[dict]] = {
            "orders": [],
            "payments": [],
            "contacts": [],
            "messages": [],
            "conversation_carts": [],
            "conversation_cart_items": [],
            "conversations": [],
            "whatsapp_templates": [],
            "tenant_integrations": [],
        }

    def table(self, name):
        return _FakeQuery(self._tables.setdefault(name, []))


def _build_worker(fake_sb):
    """Carga worker.OrchestratorWorker con .supabase reemplazado por fake.
    Evita iniciar Supabase real porque tests no tienen env vars.

    A6.2.5 finiquito 2026-06-23 (super-audit worwkgukx HIGH gap): ANTES este
    helper hacía `del sys.modules["worker"]` SIN restaurar, dejando una
    instancia recargada en sys.modules. Otros tests que importaron `worker` a
    nivel módulo (test_r01_stock_release.py) terminaban con `OrchestratorWorker`
    de la instancia VIEJA pero su `patch("worker.create_client")` aplicaba a la
    NUEVA → create_client real se invocaba → 2 fallos cross-test que
    `unittest discover` enmascaraba y pytest exponía. Ahora restauramos el
    módulo original en finally (aislamiento entre tests).
    """
    os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://stub.test")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "stub_key")

    # Pre-stub supabase.create_client para que el constructor no haga llamada real
    import supabase as _sp
    _saved_worker = sys.modules.get("worker")
    try:
        with patch.object(_sp, "create_client", return_value=fake_sb):
            if "worker" in sys.modules:
                del sys.modules["worker"]
            import worker as _w  # type: ignore
            instance = _w.OrchestratorWorker()
            instance.supabase = fake_sb  # garantizar
            return _w, instance
    finally:
        # Restaurar el módulo worker original (si existía) para NO contaminar
        # otros tests que lo importaron a nivel módulo. El _w retornado sigue
        # siendo la instancia recargada que este test usa localmente.
        if _saved_worker is not None:
            sys.modules["worker"] = _saved_worker


# ─── _try_send_payment_reminder_hsm ─────────────────────────────────────────


class TrySendPaymentReminderHSMTests(unittest.TestCase):
    def setUp(self):
        self.sb = _FakeSupabase()
        # Seed order + payment + contact
        self.sb._tables["orders"].append({
            "id": "order_xyz",
            "tenant_id": "tenant-A",
            "total_amount": 87500.0,
            "contact_id": "contact_1",
        })
        self.sb._tables["payments"].append({
            "tenant_id": "tenant-A",
            "order_id": "order_xyz",
            "checkout_url": "https://wompi.co/p/abc123",
            "created_at": "2026-05-17T10:00:00Z",
        })
        self.sb._tables["contacts"].append({
            "id": "contact_1",
            "first_name": "Camila",
            "full_name": "Camila Pérez",
            "consent_given": True,
        })
        self.now_dt = datetime.now(timezone.utc)
        self.worker_mod, self.w = _build_worker(self.sb)

    def test_template_not_approved_returns_false(self):
        async def fake_send_template(*a, **kw):
            return None, self.worker_mod.TEMPLATE_ERR_TEMPLATE_NOT_APPROVED

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template):
            result = _run(self.w._try_send_payment_reminder_hsm(
                order_id="order_xyz",
                tenant_id="tenant-A",
                conversation_id="conv_1",
                customer_phone="573125555555",
                now_dt=self.now_dt,
            ))
        self.assertFalse(result)
        self.assertEqual(self.w._metrics["payment_reminders_hsm_not_approved"], 1)

    def test_template_approved_send_ok_returns_true(self):
        captured = {}

        async def fake_send_template(*a, **kw):
            captured["body_params"] = kw.get("body_params")
            captured["template_name"] = kw.get("template_name")
            return "wamid.hsm_OK_123", None

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template):
            result = _run(self.w._try_send_payment_reminder_hsm(
                order_id="order_xyz",
                tenant_id="tenant-A",
                conversation_id="conv_1",
                customer_phone="573125555555",
                now_dt=self.now_dt,
            ))
        self.assertTrue(result)
        self.assertEqual(captured["template_name"], "payment_reminder_v1")
        # body_params = [nombre, order_number, total formateado (sin "COP"
        # post Sem 7 F2 cierre 2026-05-20 — P5), checkout_url]
        self.assertEqual(captured["body_params"][0], "Camila")
        self.assertEqual(captured["body_params"][1], "ORDER_XY")
        self.assertEqual(captured["body_params"][2], "$87.500")
        self.assertEqual(captured["body_params"][3], "https://wompi.co/p/abc123")
        self.assertEqual(self.w._metrics["payment_reminders_sent_via_hsm"], 1)
        # Idempotencia: payment_reminder_sent_at debe estar set
        self.assertIsNotNone(self.sb._tables["orders"][0].get("payment_reminder_sent_at"))
        # Outbound persistido en messages
        self.assertEqual(len(self.sb._tables["messages"]), 1)
        self.assertEqual(self.sb._tables["messages"][0]["content_type"], "template")

    def test_order_sin_checkout_url_returns_false(self):
        # Quitar payment
        self.sb._tables["payments"].clear()

        async def fake_send_template(*a, **kw):
            return "wamid.never_called", None

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template) as mock_send:
            result = _run(self.w._try_send_payment_reminder_hsm(
                order_id="order_xyz",
                tenant_id="tenant-A",
                conversation_id="conv_1",
                customer_phone="573125555555",
                now_dt=self.now_dt,
            ))
        self.assertFalse(result)
        mock_send.assert_not_called()

    def test_customer_sin_first_name_usa_cliente_default(self):
        self.sb._tables["contacts"][0]["first_name"] = ""
        self.sb._tables["contacts"][0]["full_name"] = ""
        captured = {}

        async def fake_send_template(*a, **kw):
            captured["body_params"] = kw.get("body_params")
            return "wamid.x", None

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template):
            _run(self.w._try_send_payment_reminder_hsm(
                order_id="order_xyz",
                tenant_id="tenant-A",
                conversation_id="conv_1",
                customer_phone="573125555555",
                now_dt=self.now_dt,
            ))
        self.assertEqual(captured["body_params"][0], "cliente")

    def test_hsm_falla_meta_increments_failed_metric(self):
        async def fake_send_template(*a, **kw):
            return None, "META_RATE_LIMIT"

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template):
            result = _run(self.w._try_send_payment_reminder_hsm(
                order_id="order_xyz",
                tenant_id="tenant-A",
                conversation_id="conv_1",
                customer_phone="573125555555",
                now_dt=self.now_dt,
            ))
        self.assertFalse(result)
        self.assertEqual(self.w._metrics["payment_reminders_hsm_failed"], 1)


# ─── _send_cart_abandoned_reminders_if_due ───────────────────────────────────


class CartAbandonedCronTests(unittest.TestCase):
    def setUp(self):
        self.sb = _FakeSupabase()
        self.worker_mod, self.w = _build_worker(self.sb)
        # Reset last_at para que disparen inmediatamente
        self.w._last_cart_abandoned_at = 0

    def _seed_cart(self, *, cart_id="cart_1", consent=True, hours_ago=25,
                   has_contact=True, reminder_sent=False, status="abandoned"):
        cart_updated_at = (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).isoformat()
        self.sb._tables["conversation_carts"].append({
            "id": cart_id,
            "tenant_id": "tenant-A",
            "conversation_id": "conv_X",
            "contact_id": "contact_1" if has_contact else None,
            "status": status,
            "updated_at": cart_updated_at,
            "abandoned_reminder_sent_at": (
                datetime.now(timezone.utc).isoformat() if reminder_sent else None
            ),
            "conversations": {"customer_phone": "573125555555"},
        })
        if has_contact:
            self.sb._tables["contacts"].append({
                "id": "contact_1",
                "consent_given": consent,
                "first_name": "Camila",
            })
        self.sb._tables["conversation_cart_items"].append({
            "cart_id": cart_id,
            "product_title": "Jabón artesanal de coco",
            "quantity": 2,
        })

    def test_sin_consent_skip_marketing(self):
        self._seed_cart(consent=False)

        async def fake_send_template(*a, **kw):
            return "wamid.never", None

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template) as mock_send:
            _run(self.w._send_cart_abandoned_reminders_if_due())
        mock_send.assert_not_called()
        self.assertEqual(self.w._metrics["cart_abandoned_reminders_skipped_no_consent"], 1)
        # Idempotencia marcada
        self.assertIsNotNone(self.sb._tables["conversation_carts"][0]["abandoned_reminder_sent_at"])

    def test_con_consent_template_approved_envia(self):
        self._seed_cart(consent=True)
        captured = {}

        async def fake_send_template(*a, **kw):
            captured["body_params"] = kw.get("body_params")
            captured["template_name"] = kw.get("template_name")
            return "wamid.cart_OK", None

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template):
            _run(self.w._send_cart_abandoned_reminders_if_due())
        self.assertEqual(captured["template_name"], "cart_abandoned_24h_v1")
        self.assertEqual(captured["body_params"][0], "Camila")
        self.assertIn("Jabón artesanal de coco x2", captured["body_params"][1])
        self.assertEqual(captured["body_params"][2], "10%")
        self.assertEqual(self.w._metrics["cart_abandoned_reminders_sent"], 1)

    def test_template_not_approved_skip(self):
        self._seed_cart(consent=True)

        async def fake_send_template(*a, **kw):
            return None, self.worker_mod.TEMPLATE_ERR_TEMPLATE_NOT_APPROVED

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template):
            _run(self.w._send_cart_abandoned_reminders_if_due())
        self.assertEqual(self.w._metrics["cart_abandoned_reminders_hsm_not_approved"], 1)
        # Idempotencia marcada — no reintentar cada 5min
        self.assertIsNotNone(self.sb._tables["conversation_carts"][0]["abandoned_reminder_sent_at"])

    def test_cart_dentro_24h_no_se_procesa(self):
        """Carrito <24h NO debe disparar HSM (free-form lo cubre)."""
        self._seed_cart(consent=True, hours_ago=12)  # solo 12h

        async def fake_send_template(*a, **kw):
            return "wamid.x", None

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template) as mock_send:
            _run(self.w._send_cart_abandoned_reminders_if_due())
        mock_send.assert_not_called()

    def test_cart_mas_de_72h_no_se_procesa(self):
        """Carrito >72h se considera demasiado viejo — no enviar."""
        self._seed_cart(consent=True, hours_ago=100)  # >72h

        async def fake_send_template(*a, **kw):
            return "wamid.x", None

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template) as mock_send:
            _run(self.w._send_cart_abandoned_reminders_if_due())
        mock_send.assert_not_called()

    def test_reminder_ya_enviado_no_reintenta(self):
        """Idempotencia: si abandoned_reminder_sent_at no es NULL, skip."""
        self._seed_cart(consent=True, reminder_sent=True)

        async def fake_send_template(*a, **kw):
            return "wamid.x", None

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template) as mock_send:
            _run(self.w._send_cart_abandoned_reminders_if_due())
        mock_send.assert_not_called()

    def test_disabled_flag_no_corre(self):
        self.w._cart_abandoned_enabled = False
        self._seed_cart(consent=True)

        async def fake_send_template(*a, **kw):
            return "wamid.x", None

        with patch.object(self.worker_mod, "send_whatsapp_template",
                          side_effect=fake_send_template) as mock_send:
            _run(self.w._send_cart_abandoned_reminders_if_due())
        mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
