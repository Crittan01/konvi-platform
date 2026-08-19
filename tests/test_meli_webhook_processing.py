"""Tests del procesamiento de notificaciones MeLi (money-path marketplace).

Complementa test_meli_webhook_origin.py (IP allowlist) y
test_meli_webhook_alert_and_dedup.py (alerta + dedup RPC). Acá se prueba lo que
pasa DESPUÉS de aceptar el webhook:

  • Validación anti-spoof del `resource` por tópico (SSRF sobre la API MeLi).
  • Resolución de tenant por meli user_id.
  • _process_order: creación (orden + items + contacto + consent audit) y
    actualización con rank de estados MONOTÓNICO (un orders_v2 tardío NO
    retrocede shipped/delivered → confirmed).
  • Decremento de stock al pagar (idempotente vía RPC) y reposición al cancelar.
  • _process_shipment: avance de estado + persistencia de tracking.
  • _process_notification: routing por tópico + guards (sin tenant/token).
  • Endpoint: dedup → 200 duplicate, evento nuevo → background task.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "services" / "api"))


def _reload_module(env: dict | None = None):
    """Recarga meli_webhook con env opcional (mismo patrón que test_meli_webhook_origin)."""
    for k, v in (env or {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    from routers import meli_webhook as mw
    return importlib.reload(mw)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Supabase falso genérico (store de filas + grabación de writes) ──────────


class _Q:
    def __init__(self, sb, table):
        self._sb = sb
        self._table = table
        self._filters = []
        self._op = "select"
        self._payload = None
        self._single = False
        self._maybe = False

    def select(self, *a, **k):
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._payload = payload
        return self

    def eq(self, c, v):
        self._filters.append(("eq", c, v))
        return self

    def in_(self, c, vals):
        self._filters.append(("in", c, vals))
        return self

    def like(self, c, p):
        self._filters.append(("like", c, p))
        return self

    def limit(self, n):
        return self

    def order(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    def maybe_single(self):
        self._maybe = True
        return self

    def execute(self):
        return self._sb._exec(self)


class _Sb:
    """Mini-Supabase: filas por tabla, eq/in_/like sobre ellas, writes grabados."""

    def __init__(self, tables=None, rpc_handler=None):
        self._tables = tables or {}
        self._rpc_handler = rpc_handler
        self.inserts = []
        self.updates = []
        self.upserts = []
        self.rpc_calls = []
        self.fail = {}  # (table, op) → excepción a lanzar

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params=None):
        self.rpc_calls.append((name, params))
        data = None
        if self._rpc_handler:
            data = self._rpc_handler(name, params)

        class _Exec:
            def execute(self_inner):
                if isinstance(data, Exception):
                    raise data
                return SimpleNamespace(data=data)

        return _Exec()

    def _match(self, rows, filters):
        for op, c, v in filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(c)) == str(v)]
            elif op == "in":
                rows = [r for r in rows if r.get(c) in v]
            elif op == "like":
                pat = str(v)
                if pat.endswith("%"):
                    rows = [r for r in rows if str(r.get(c) or "").startswith(pat[:-1])]
                else:
                    rows = [r for r in rows if pat in str(r.get(c) or "")]
        return rows

    def _exec(self, q):
        exc = self.fail.get((q._table, q._op))
        if exc:
            raise exc
        rows = [dict(r) for r in self._tables.get(q._table, [])]
        if q._op == "select":
            rows = self._match(rows, q._filters)
            if q._single or q._maybe:
                return SimpleNamespace(data=rows[0] if rows else None)
            return SimpleNamespace(data=rows)
        if q._op == "insert":
            self.inserts.append((q._table, q._payload))
            n = sum(1 for t, _ in self.inserts if t == q._table)
            payload = q._payload
            if isinstance(payload, list):
                data = [dict(p, id=p.get("id", f"{q._table}-{n}-{i}"))
                        for i, p in enumerate(payload)]
            else:
                data = [dict(payload, id=payload.get("id", f"{q._table}-{n}"))]
            return SimpleNamespace(data=data)
        if q._op == "upsert":
            self.upserts.append((q._table, q._payload))
            return SimpleNamespace(data=[dict(q._payload, id=q._payload.get("id", f"{q._table}-u1"))])
        if q._op == "update":
            self.updates.append((q._table, q._payload, q._filters))
            return SimpleNamespace(data=[])
        raise AssertionError(f"op desconocida {q._op}")


def _updates_for(sb, table):
    return [p for t, p, _ in sb.updates if t == table]


def _inserts_for(sb, table):
    return [p for t, p in sb.inserts if t == table]


# ─── Resource anti-spoof ─────────────────────────────────────────────────────


class ResourceValidationTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})

    def test_recursos_validos(self):
        self.assertTrue(self.mw._is_valid_resource("orders_v2", "/orders/12345"))
        self.assertTrue(self.mw._is_valid_resource("items", "/items/MCO123"))
        self.assertTrue(self.mw._is_valid_resource("shipments", "/shipments/999"))

    def test_path_traversal_rechazado(self):
        self.assertFalse(self.mw._is_valid_resource("orders_v2", "/orders/../users/me"))
        self.assertFalse(self.mw._is_valid_resource("orders_v2", "/users/me"))

    def test_endpoint_distinto_rechazado(self):
        self.assertFalse(self.mw._is_valid_resource("orders_v2", "/items/MCO1"))
        self.assertFalse(self.mw._is_valid_resource("shipments", "/orders/1"))

    def test_query_string_y_fragment_rechazados(self):
        self.assertFalse(self.mw._is_valid_resource("orders_v2", "/orders/1?admin=true"))
        self.assertFalse(self.mw._is_valid_resource("orders_v2", "/orders/1#x"))

    def test_topico_desconocido_y_vacios(self):
        self.assertFalse(self.mw._is_valid_resource("questions", "/orders/1"))
        self.assertFalse(self.mw._is_valid_resource("orders_v2", ""))
        self.assertFalse(self.mw._is_valid_resource("", "/orders/1"))


# ─── Resolución de tenant ────────────────────────────────────────────────────


class FindTenantTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})

    def test_match_por_meta_user_id(self):
        sb = _Sb({"tenant_integrations": [
            {"tenant_id": "t-otro", "provider": "mercadolibre", "status": "connected", "meta": {"user_id": 111}},
            {"tenant_id": "t-1", "provider": "mercadolibre", "status": "connected", "meta": {"user_id": 222}},
        ]})
        # Coerción str/int: MeLi manda user_id numérico o string indistinto.
        self.assertEqual(_run(self.mw._find_tenant_by_meli_user("222", sb)), "t-1")

    def test_sin_match_retorna_none(self):
        sb = _Sb({"tenant_integrations": [
            {"tenant_id": "t-1", "provider": "mercadolibre", "status": "connected", "meta": {"user_id": 111}},
        ]})
        self.assertIsNone(_run(self.mw._find_tenant_by_meli_user("999", sb)))


# ─── Decremento / reposición de stock ────────────────────────────────────────


class StockTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})
        p = patch.object(self.mw, "_schedule_meli_sync")
        self.sync = p.start()
        self.addCleanup(p.stop)

    def test_decrement_agrega_por_variacion_y_sincroniza(self):
        sb = _Sb(
            {"order_items": [
                {"order_id": "o1", "tenant_id": "t1", "variation_id": "v1", "quantity": 2},
                {"order_id": "o1", "tenant_id": "t1", "variation_id": "v1", "quantity": 1},
                {"order_id": "o1", "tenant_id": "t1", "variation_id": "v2", "quantity": 3},
            ]},
            rpc_handler=lambda name, params: 7 if name == "rpc_stock_decrement" else None,
        )
        self.mw._decrement_stock_for_meli_order("o1", "t1", sb)

        calls = [p for n, p in sb.rpc_calls if n == "rpc_stock_decrement"]
        self.assertEqual(len(calls), 2, "2 variaciones → 2 RPC atómicas")
        v1 = next(p for p in calls if p["p_variation_id"] == "v1")
        self.assertEqual(v1["p_qty"], 3, "2 líneas de la misma variante se agregan (colapsa idempotency)")
        self.assertEqual(v1["p_reason"], "sale")
        self.assertEqual(self.sync.call_count, 2, "cada decremento exitoso programa sync a MeLi")

    def test_decrement_rpc_falla_continua_con_las_demas(self):
        def handler(name, params):
            if params["p_variation_id"] == "v1":
                raise RuntimeError("rpc down")
            return 4
        sb = _Sb(
            {"order_items": [
                {"order_id": "o1", "tenant_id": "t1", "variation_id": "v1", "quantity": 1},
                {"order_id": "o1", "tenant_id": "t1", "variation_id": "v2", "quantity": 1},
            ]},
            rpc_handler=handler,
        )
        with self.assertLogs("routers.meli_webhook", level="ERROR"):
            self.mw._decrement_stock_for_meli_order("o1", "t1", sb)
        self.sync.assert_called_once_with("v2", 4, sb)

    def test_decrement_select_falla_no_propaga(self):
        sb = _Sb()
        sb.fail[("order_items", "select")] = RuntimeError("db down")
        with self.assertLogs("routers.meli_webhook", level="ERROR"):
            self.mw._decrement_stock_for_meli_order("o1", "t1", sb)
        self.sync.assert_not_called()

    def test_restore_lee_movimientos_y_repone(self):
        sb = _Sb(
            {"stock_movements": [
                {"tenant_id": "t1", "order_id": "o1", "variation_id": "v1", "delta": -2, "reason": "sale"},
                {"tenant_id": "t1", "order_id": "o1", "variation_id": "v1", "delta": -1, "reason": "reservation_consumed"},
                {"tenant_id": "t1", "order_id": "o1", "variation_id": "v2", "delta": -3, "reason": "sale"},
                # otro reason no aplica (mi mock filtra in_ pero verifiquemos qty):
            ]},
            rpc_handler=lambda name, params: 9 if name == "rpc_stock_restore" else None,
        )
        self.mw._restore_stock_for_meli_order("o1", "t1", sb)

        calls = [p for n, p in sb.rpc_calls if n == "rpc_stock_restore"]
        self.assertEqual(len(calls), 2)
        v1 = next(p for p in calls if p["p_variation_id"] == "v1")
        self.assertEqual(v1["p_qty"], 3, "sale + reservation_consumed se agregan")
        self.assertEqual(v1["p_reason"], "cancellation_refund")
        self.assertEqual(self.sync.call_count, 2)

    def test_restore_rpc_falla_continua(self):
        def handler(name, params):
            raise RuntimeError("rpc down")
        sb = _Sb(
            {"stock_movements": [
                {"tenant_id": "t1", "order_id": "o1", "variation_id": "v1", "delta": -1, "reason": "sale"},
            ]},
            rpc_handler=handler,
        )
        with self.assertLogs("routers.meli_webhook", level="ERROR"):
            self.mw._restore_stock_for_meli_order("o1", "t1", sb)
        self.sync.assert_not_called()


# ─── _process_order ──────────────────────────────────────────────────────────

_ORDER_PAYLOAD = {
    "id": 555111,
    "status": "paid",
    "total_amount": 89000.0,
    "buyer": {
        "first_name": "Ana", "last_name": "Ruiz", "nickname": "anaru",
        "billing_info": {"phone": "+57 300 111 2233"},
    },
    "order_items": [
        {"item": {"id": "MCO1", "title": "Jabón avena"}, "quantity": 2, "unit_price": 25000.0},
        {"item": {"id": "MCO2", "title": "Shampoo"}, "quantity": 1, "unit_price": 39000.0},
    ],
}


class ProcessOrderCreateTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})
        p_sync = patch.object(self.mw, "_schedule_meli_sync")
        self.sync = p_sync.start()
        self.addCleanup(p_sync.stop)
        p_fetch = patch.object(self.mw, "_fetch_meli_resource", new=AsyncMock(return_value=dict(_ORDER_PAYLOAD)))
        self.fetch = p_fetch.start()
        self.addCleanup(p_fetch.stop)

    def _sb(self):
        return _Sb(
            {
                "marketplace_listings": [
                    {"tenant_id": "t1", "provider": "mercadolibre", "external_id": "MCO1", "variation_id": "var-1"},
                ],
                "order_items": [
                    # id sintético de la orden insertada por el mock (1er insert de orders = orders-1)
                    {"order_id": "orders-1", "tenant_id": "t1", "variation_id": "var-1", "quantity": 2},
                ],
            },
            rpc_handler=lambda name, params: 5 if name == "rpc_stock_decrement" else None,
        )

    def test_crea_orden_items_contacto_y_descuenta_stock(self):
        sb = self._sb()
        _run(self.mw._process_order("/orders/555111", "t1", "tok", sb))

        # Orden con identidad de canal estable.
        order_ins = _inserts_for(sb, "orders")
        self.assertEqual(len(order_ins), 1)
        self.assertEqual(order_ins[0]["status"], "confirmed", "paid → confirmed")
        self.assertEqual(order_ins[0]["source"], "mercadolibre")
        self.assertEqual(order_ins[0]["external_order_id"], "555111")
        self.assertIn("MeLi order #555111", order_ins[0]["notes"])
        self.assertIn("contact_id", order_ins[0], "buyer con teléfono → contacto vinculado")

        # Items: MCO1 resuelve variación, MCO2 queda sin vínculo.
        items_ins = _inserts_for(sb, "order_items")
        self.assertEqual(len(items_ins), 1)
        rows = items_ins[0]
        self.assertEqual(len(rows), 2)
        mco1 = next(r for r in rows if r["title"] == "Jabón avena")
        self.assertEqual(mco1["variation_id"], "var-1")
        mco2 = next(r for r in rows if r["title"] == "Shampoo")
        self.assertIsNone(mco2["variation_id"])

        # Contacto con consent trazable + audit append-only.
        contact_ups = [p for t, p in sb.upserts if t == "contacts"]
        self.assertEqual(len(contact_ups), 1)
        self.assertEqual(contact_ups[0]["phone"], "573001112233", "canon digits-only (rev. 104)")
        self.assertEqual(contact_ups[0]["consent_source"], "marketplace_meli")
        audit = _inserts_for(sb, "consent_audit_log")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["event"], "granted")

        # Llega pagada → decremento de stock vía RPC.
        dec = [p for n, p in sb.rpc_calls if n == "rpc_stock_decrement"]
        self.assertEqual(len(dec), 1)
        self.assertEqual(dec[0]["p_variation_id"], "var-1")

    def test_orden_sin_telefono_no_crea_contacto(self):
        payload = dict(_ORDER_PAYLOAD)
        payload["buyer"] = {"first_name": "Ana", "last_name": "Ruiz", "nickname": "anaru"}
        self.fetch.return_value = payload
        sb = self._sb()
        _run(self.mw._process_order("/orders/555111", "t1", "tok", sb))

        self.assertEqual([p for t, p in sb.upserts if t == "contacts"], [])
        order_ins = _inserts_for(sb, "orders")
        self.assertNotIn("contact_id", order_ins[0])

    def test_orden_pending_no_descuenta_stock(self):
        payload = dict(_ORDER_PAYLOAD)
        payload["status"] = "payment_required"
        self.fetch.return_value = payload
        sb = self._sb()
        _run(self.mw._process_order("/orders/555111", "t1", "tok", sb))

        self.assertEqual(_inserts_for(sb, "orders")[0]["status"], "pending")
        self.assertEqual([n for n, _ in sb.rpc_calls if n == "rpc_stock_decrement"], [])

    def test_fetch_falla_no_escribe_nada(self):
        self.fetch.return_value = None
        sb = self._sb()
        _run(self.mw._process_order("/orders/555111", "t1", "tok", sb))
        self.assertEqual(sb.inserts, [])


class ProcessOrderUpdateTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})
        p_sync = patch.object(self.mw, "_schedule_meli_sync")
        p_sync.start()
        self.addCleanup(p_sync.stop)
        p_fetch = patch.object(self.mw, "_fetch_meli_resource", new=AsyncMock(return_value=dict(_ORDER_PAYLOAD)))
        self.fetch = p_fetch.start()
        self.addCleanup(p_fetch.stop)

    def _sb_con_existente(self, status):
        return _Sb({
            "orders": [{
                "id": "o-exist", "tenant_id": "t1", "status": status,
                "source": "mercadolibre", "external_order_id": "555111",
            }],
            "order_items": [
                {"order_id": "o-exist", "tenant_id": "t1", "variation_id": "var-1", "quantity": 1},
            ],
            "stock_movements": [
                {"tenant_id": "t1", "order_id": "o-exist", "variation_id": "var-1", "delta": -1, "reason": "sale"},
            ],
        }, rpc_handler=lambda name, params: 3)

    def test_pending_a_paid_avanza_y_descuenta(self):
        sb = self._sb_con_existente("pending")
        _run(self.mw._process_order("/orders/555111", "t1", "tok", sb))

        upd = _updates_for(sb, "orders")
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0]["status"], "confirmed")
        self.assertEqual(len([n for n, _ in sb.rpc_calls if n == "rpc_stock_decrement"]), 1)

    def test_paid_tardio_no_retrocede_delivered_pero_descuenta(self):
        """orders_v2 con status='paid' persiste durante TODO el fulfillment: un
        webhook tardío NO debe regresar delivered → confirmed (rank monotónico).
        El decremento SÍ corre (idempotente) porque es la 1ª vez que se sabe pagada."""
        sb = self._sb_con_existente("delivered")
        _run(self.mw._process_order("/orders/555111", "t1", "tok", sb))

        self.assertEqual(_updates_for(sb, "orders"), [], "rank monotónico: delivered(4) > confirmed(1)")
        self.assertEqual(len([n for n, _ in sb.rpc_calls if n == "rpc_stock_decrement"]), 1)

    def test_cancelada_desde_confirmed_repone_stock(self):
        payload = dict(_ORDER_PAYLOAD)
        payload["status"] = "cancelled"
        self.fetch.return_value = payload
        sb = self._sb_con_existente("confirmed")
        _run(self.mw._process_order("/orders/555111", "t1", "tok", sb))

        upd = _updates_for(sb, "orders")
        self.assertEqual(upd[0]["status"], "cancelled")
        restore = [p for n, p in sb.rpc_calls if n == "rpc_stock_restore"]
        self.assertEqual(len(restore), 1, "cancelación de orden pagada repone el stock")

    def test_cancelada_desde_pending_no_repone(self):
        payload = dict(_ORDER_PAYLOAD)
        payload["status"] = "cancelled"
        self.fetch.return_value = payload
        sb = self._sb_con_existente("pending")
        _run(self.mw._process_order("/orders/555111", "t1", "tok", sb))

        self.assertEqual(_updates_for(sb, "orders")[0]["status"], "cancelled")
        self.assertEqual([n for n, _ in sb.rpc_calls if n == "rpc_stock_restore"], [],
                         "pending nunca se decrementó → nada que reponer")

    def test_paid_sobre_cancelada_no_reabre_ni_descuenta(self):
        sb = self._sb_con_existente("cancelled")
        _run(self.mw._process_order("/orders/555111", "t1", "tok", sb))

        self.assertEqual(_updates_for(sb, "orders"), [], "cancelled es terminal (rank 5)")
        self.assertEqual([n for n, _ in sb.rpc_calls if n == "rpc_stock_decrement"], [])


class FindMeliOrderTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})
        # El feature-detect se cachea en el módulo; reset entre tests.
        self.mw._ORDERS_CHANNEL_COLS["available"] = None

    def test_lookup_por_identidad_de_canal(self):
        sb = _Sb({"orders": [
            {"id": "o1", "tenant_id": "t1", "status": "pending",
             "source": "mercadolibre", "external_order_id": "555"},
        ]})
        found = self.mw._find_meli_order(sb, "t1", "555")
        self.assertEqual(found["id"], "o1")

    def test_fallback_a_notes_legacy(self):
        mw = self.mw
        mw._ORDERS_CHANNEL_COLS["available"] = None
        sb = _Sb({"orders": [
            {"id": "o-legacy", "tenant_id": "t1", "status": "pending",
             "notes": "MeLi order #555 · vendedor: anaru"},
        ]})
        # Columnas de canal NO disponibles (migración pendiente) → match por notes.
        sb.fail[("orders", "select")] = None  # sin error: el probe devuelve filas…
        mw._ORDERS_CHANNEL_COLS["available"] = False
        found = mw._find_meli_order(sb, "t1", "555")
        self.assertEqual(found["id"], "o-legacy")

    def test_no_encontrada_retorna_none_sin_explotar(self):
        self.mw._ORDERS_CHANNEL_COLS["available"] = False
        sb = _Sb()
        self.assertIsNone(self.mw._find_meli_order(sb, "t1", "999"))

    def test_probe_de_columnas_cachea_resultado(self):
        mw = self.mw
        mw._ORDERS_CHANNEL_COLS["available"] = None
        sb = _Sb()
        self.assertTrue(mw._orders_channel_cols_available(sb))
        # Segunda llamada: cache, sin nueva consulta (el mock explotaría si fallara).
        sb.fail[("orders", "select")] = RuntimeError("no debería consultarse")
        self.assertTrue(mw._orders_channel_cols_available(sb))
        mw._ORDERS_CHANNEL_COLS["available"] = None


# ─── _process_shipment ───────────────────────────────────────────────────────

_SHIPMENT_PAYLOAD = {
    "id": 777,
    "status": "shipped",
    "order_id": 555111,
    "tracking_number": "TRK-1",
    "tracking_url": "http://meli/track/TRK-1",
    "shipping_option": {"name": "Servientrega"},
    "estimated_delivery_final": {"date": "2026-08-10T00:00:00.000-05:00"},
}


class ProcessShipmentTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})
        p_fetch = patch.object(
            self.mw, "_fetch_meli_resource",
            new=AsyncMock(return_value=dict(_SHIPMENT_PAYLOAD)),
        )
        self.fetch = p_fetch.start()
        self.addCleanup(p_fetch.stop)
        self.mw._ORDERS_CHANNEL_COLS["available"] = None

    def _sb(self, status="confirmed"):
        return _Sb({"orders": [{
            "id": "o1", "tenant_id": "t1", "status": status,
            "source": "mercadolibre", "external_order_id": "555111",
        }]})

    def test_shipment_avanza_orden_y_persiste_tracking(self):
        sb = self._sb("confirmed")
        _run(self.mw._process_shipment("/shipments/777", "t1", "tok", sb))

        upd = _updates_for(sb, "orders")
        self.assertEqual(upd[0]["status"], "shipped")
        trk = _inserts_for(sb, "order_tracking")
        self.assertEqual(len(trk), 1)
        self.assertEqual(trk[0]["external_id"], "777")
        self.assertEqual(trk[0]["tracking_number"], "TRK-1")
        self.assertEqual(trk[0]["carrier"], "Servientrega")
        self.assertEqual(trk[0]["estimated_delivery"], "2026-08-10")

    def test_shipment_no_retrocede_estado_pero_si_persiste_tracking(self):
        sb = self._sb("delivered")
        _run(self.mw._process_shipment("/shipments/777", "t1", "tok", sb))

        self.assertEqual(_updates_for(sb, "orders"), [], "delivered(4) > shipped(3)")
        self.assertEqual(len(_inserts_for(sb, "order_tracking")), 1,
                         "el tracking se persiste aunque la orden no avance")

    def test_tracking_existente_se_actualiza(self):
        sb = self._sb("confirmed")
        sb._tables["order_tracking"] = [{
            "id": "trk-row", "tenant_id": "t1", "provider": "mercadolibre", "external_id": "777",
        }]
        _run(self.mw._process_shipment("/shipments/777", "t1", "tok", sb))

        self.assertEqual(_inserts_for(sb, "order_tracking"), [])
        upd = _updates_for(sb, "order_tracking")
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0]["status"], "shipped")

    def test_shipment_sin_orden_conocida_no_persiste(self):
        sb = _Sb()
        with self.assertLogs("routers.meli_webhook", level="WARNING"):
            _run(self.mw._process_shipment("/shipments/777", "t1", "tok", sb))
        self.assertEqual(sb.inserts, [])

    def test_shipment_sin_order_id_no_accion(self):
        self.fetch.return_value = {"id": 777, "status": "shipped", "order_id": None}
        sb = self._sb()
        _run(self.mw._process_shipment("/shipments/777", "t1", "tok", sb))
        self.assertEqual(sb.inserts, [])
        self.assertEqual(sb.updates, [])


# ─── _process_notification (routing) ─────────────────────────────────────────


class ProcessNotificationTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})
        p_client = patch.object(self.mw, "_get_service_client")
        self.get_client = p_client.start()
        self.addCleanup(p_client.stop)
        p_token = patch.object(self.mw.meli_client, "get_valid_token", new=AsyncMock(return_value="tok-1"))
        self.token = p_token.start()
        self.addCleanup(p_token.stop)
        p_fetch = patch.object(self.mw, "_fetch_meli_resource", new=AsyncMock(return_value={"id": "x"}))
        self.fetch = p_fetch.start()
        self.addCleanup(p_fetch.stop)

    def _sb_con_tenant(self):
        return _Sb({"tenant_integrations": [
            {"tenant_id": "t1", "provider": "mercadolibre", "status": "connected", "meta": {"user_id": 222}},
        ]})

    def test_sin_tenant_no_procesa(self):
        self.get_client.return_value = _Sb()
        _run(self.mw._process_notification("orders_v2", "/orders/1", "999"))
        self.fetch.assert_not_called()
        self.token.assert_not_called()

    def test_sin_token_no_procesa(self):
        self.get_client.return_value = self._sb_con_tenant()
        self.token.return_value = None
        _run(self.mw._process_notification("orders_v2", "/orders/1", "222"))
        self.fetch.assert_not_called()

    def test_resource_malformado_rechazado_antes_del_fetch(self):
        self.get_client.return_value = self._sb_con_tenant()
        with self.assertLogs("routers.meli_webhook", level="WARNING") as cm:
            _run(self.mw._process_notification("orders_v2", "/users/me", "222"))
        self.assertIn("resource_rejected", "\n".join(cm.output))
        self.fetch.assert_not_called()

    def test_topico_items_actualiza_listing(self):
        sb = self._sb_con_tenant()
        self.get_client.return_value = sb
        self.fetch.return_value = {
            "id": "MCO1", "status": "paused", "price": 30000, "title": "Jabón",
            "thumbnail": "http://img", "condition": "new", "category_id": "C1",
            "attributes": [{"id": "BRAND"}],
        }
        _run(self.mw._process_notification("items", "/items/MCO1", "222"))

        upd = _updates_for(sb, "marketplace_listings")
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0]["status"], "paused")
        self.assertEqual(upd[0]["external_price"], 30000)

    def test_topico_desconocido_no_hace_fetch(self):
        self.get_client.return_value = self._sb_con_tenant()
        _run(self.mw._process_notification("questions", "/questions/1", "222"))
        self.fetch.assert_not_called()

    def test_orders_v2_despacha_a_process_order(self):
        self.get_client.return_value = self._sb_con_tenant()
        with patch.object(self.mw, "_process_order", new=AsyncMock()) as po:
            _run(self.mw._process_notification("orders_v2", "/orders/555", "222"))
        po.assert_called_once()


# ─── _upsert_meli_contact ────────────────────────────────────────────────────


class UpsertContactTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})

    def test_sin_telefono_retorna_none(self):
        sb = _Sb()
        cid = self.mw._upsert_meli_contact({"nickname": "anaru"}, "t1", sb)
        self.assertIsNone(cid)
        self.assertEqual(sb.upserts, [])

    def test_contacto_nuevo_hace_upsert_y_audit(self):
        sb = _Sb()
        cid = self.mw._upsert_meli_contact(
            {"first_name": "Ana", "last_name": "Ruiz",
             "billing_info": {"phone": "+57 300 111 2233"}},
            "t1", sb, meli_order_id="555",
        )
        self.assertEqual(cid, "contacts-u1")
        payload = sb.upserts[0][1]
        self.assertEqual(payload["phone"], "573001112233")
        self.assertEqual(payload["name"], "Ana Ruiz")
        self.assertEqual(payload["consent_channel"], "marketplace_meli")
        self.assertEqual(payload["consent_evidence"]["meli_order_id"], "555")
        audit = _inserts_for(sb, "consent_audit_log")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["source"], "system")

    def test_phone_legacy_con_plus_se_migra(self):
        """Rev. 104: filas legacy con phone E.164 ('+57...') se migran al canon."""
        sb = _Sb({"contacts": [
            {"id": "c-legacy", "tenant_id": "t1", "phone": "+573001112233"},
        ]})
        cid = self.mw._upsert_meli_contact(
            {"billing_info": {"phone": "573001112233"}}, "t1", sb,
        )
        self.assertEqual(cid, "c-legacy")
        upd = _updates_for(sb, "contacts")
        self.assertEqual(len(upd), 1)
        self.assertEqual(upd[0]["phone"], "573001112233")
        self.assertEqual(sb.upserts, [], "fila legacy encontrada → UPDATE, no UPSERT")

    def test_error_db_retorna_none_sin_propagar(self):
        sb = _Sb()
        sb.fail[("contacts", "select")] = RuntimeError("db down")
        cid = self.mw._upsert_meli_contact(
            {"billing_info": {"phone": "573001112233"}}, "t1", sb,
        )
        self.assertIsNone(cid)


# ─── Endpoint ────────────────────────────────────────────────────────────────


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.mw = _reload_module({"MELI_WEBHOOK_ALLOWED_IPS": ""})

    def _request(self, body=None, raises=False):
        req = MagicMock()
        if raises:
            req.json = AsyncMock(side_effect=ValueError("no json"))
        else:
            req.json = AsyncMock(return_value=body)
        return req

    def _bt(self):
        from fastapi import BackgroundTasks
        return BackgroundTasks()

    def test_body_invalido_responde_ok(self):
        resp = _run(self.mw.meli_webhook(self._request(raises=True), self._bt(), supabase=_Sb()))
        self.assertEqual(resp.status_code, 200)

    def test_campos_faltantes_no_procesa(self):
        bt = self._bt()
        resp = _run(self.mw.meli_webhook(
            self._request({"topic": "orders_v2"}), bt, supabase=_Sb(),
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(bt.tasks), 0)

    def test_evento_duplicado_no_agenda(self):
        sb = _Sb(rpc_handler=lambda name, params: True)  # meli_webhook_seen → ya visto
        bt = self._bt()
        body = {
            "topic": "orders_v2", "resource": "/orders/1", "user_id": 222,
            "application_id": "app", "sent": "2026-08-01T00:00:00Z",
        }
        resp = _run(self.mw.meli_webhook(self._request(body), bt, supabase=sb))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'"duplicate":true', resp.body)
        self.assertEqual(len(bt.tasks), 0)

    def test_evento_nuevo_agenda_procesamiento(self):
        sb = _Sb(rpc_handler=lambda name, params: False)
        bt = self._bt()
        body = {
            "topic": "orders_v2", "resource": "/orders/1", "user_id": 222,
            "application_id": "app", "sent": "2026-08-01T00:00:00Z",
        }
        resp = _run(self.mw.meli_webhook(self._request(body), bt, supabase=sb))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(bt.tasks), 1)
        self.assertEqual(bt.tasks[0].func, self.mw._process_notification)


if __name__ == "__main__":
    unittest.main()
