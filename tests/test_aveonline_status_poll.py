"""A10 (auditoría 2026-08-02) — Polling backup de tracking Aveonline.

El tracking dependía 100% del webhook `webhookEstadosGuias`: si el tenant no lo
registra o un evento se pierde, el envío queda congelado en un no-terminal.
`get_estado` (obtenerEstadoAuth) existía en el cliente espejo con CERO callers.

Cubre el job del worker (`_poll_aveonline_shipment_status_if_due`) y el módulo
local `shipment_status_notifications` (réplica documentada — el API NO es
importable desde el proceso del orchestrator):
  · Selección: solo guías reales stale no-terminales (cap + filtros SQL).
  · Avance monotónico: entrega detectada por poll avanza shipment + orden y
    notifica; un historico viejo NO retrocede ni notifica un salto atrás.
  · Sin cambio → dedup cross-ciclo → no re-notifica.
  · Error del proveedor / tenant sin credenciales → el loop sigue.
"""
import asyncio
import os
import sys
import time
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("GEMINI_API_KEY", "test")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator")

import shipment_status_notifications as ssn  # noqa: E402

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
ORDER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SHIP = "bbbbbbbb-1111-2222-3333-444444444444"
CONV = "33333333-3333-3333-3333-333333333333"


def _auth_error(msg="sin Aveonline configurado"):
    """AveonlineAuthError resuelta EN TIEMPO DE TEST desde el módulo worker.

    NO importar la clase a nivel de este archivo: otros tests de la suite
    recargan `worker` / `integrations.aveonline_client` (sys.modules.pop +
    reload), y la clase importada al coleccionar quedaría con identidad
    distinta de la que el `except AveonlineAuthError` del worker referencia en
    runtime → el except no la atraparía (polución cross-test).
    """
    import worker as _w
    return _w.AveonlineAuthError(msg)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Fakes DB ────────────────────────────────────────────────────────────────

class _Not:
    def __init__(self, q):
        self._q = q

    def is_(self, k, v):
        self._q.calls.append(("not_is", k, v))
        return self._q

    def in_(self, k, v):
        self._q.calls.append(("not_in", k, v))
        return self._q


class _FakeQuery:
    """Query-builder mock: registra la cadena de filtros y resuelve un resultado
    fijo (o callable(query) para lanzar/variar)."""

    def __init__(self, table, result, rec=None):
        self.table = table
        self._result = result
        self._rec = rec if rec is not None else []
        self.calls = []
        self._op = "select"
        self._payload = None
        self.not_ = _Not(self)

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def eq(self, k, v):
        self.calls.append(("eq", k, v))
        return self

    def in_(self, k, v):
        self.calls.append(("in", k, v))
        return self

    def lt(self, k, v):
        self.calls.append(("lt", k, v))
        return self

    def order(self, k, *a, **kw):
        self.calls.append(("order", k))
        return self

    def limit(self, n):
        self.calls.append(("limit", n))
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._op in ("insert", "update"):
            self._rec.append({
                "table": self.table, "op": self._op,
                "payload": self._payload, "calls": list(self.calls),
            })
        result = self._result
        if callable(result):
            result = result(self)
        return MagicMock(data=result)


class _FakeSupabase:
    def __init__(self, results, rec=None, rpc_results=None):
        self._results = results
        self._rec = rec if rec is not None else []
        self._rpc_results = rpc_results if rpc_results is not None else {}
        self.rpc_calls = []
        self._queries = {}

    def table(self, name):
        # Cache por tabla: permite inspeccionar la cadena de filtros después
        # (supabase-py crea un builder nuevo por llamada; aquí uno basta).
        q = self._queries.get(name)
        if q is None:
            q = _FakeQuery(name, self._results.get(name), self._rec)
            self._queries[name] = q
        return q

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        result = self._rpc_results.get(name, True)
        if callable(result):
            result = result(params)
        return MagicMock(execute=MagicMock(return_value=MagicMock(data=result)))


def _shipment(*, tenant=TENANT_A, status="in_transit", tracking="G-9001",
              ship_id=SHIP, order_id=ORDER):
    return {
        "id": ship_id, "tenant_id": tenant, "order_id": order_id,
        "status": status, "carrier": "SERVIENTREGA",
        "tracking_number": tracking, "tracking_url": "https://track.example/G-9001",
    }


def _estado_result(estado, historicos=None, ok=True):
    return {
        "ok": ok,
        "guias": [{
            "estado": estado,
            "rutadigitalizada": "",
            "historicos": historicos or [],
        }],
        "raw": {},
        "message": "",
    }


class _FakeAveonlineClient:
    """Sustituto del cliente espejo: respuestas por tracking o excepción."""

    def __init__(self, behavior):
        self._behavior = behavior  # {tracking: dict | Exception}
        self.calls = []

    async def get_estado(self, *, tracking_number):
        self.calls.append(tracking_number)
        b = self._behavior.get(tracking_number)
        if isinstance(b, Exception):
            raise b
        return b or {"ok": False, "guias": [], "raw": {}, "message": "?"}


def _worker_stub(*, enabled=True, last_at=0.0):
    """Stub spec'd del worker con los métodos reales bajo test bindeados."""
    from worker import OrchestratorWorker
    stub = MagicMock(spec=OrchestratorWorker)
    stub._aveonline_status_poll_enabled = enabled
    stub._last_aveonline_status_poll_at = last_at
    stub._metrics = {
        "aveonline_status_poll_checked": 0,
        "aveonline_status_poll_updated": 0,
        "aveonline_status_poll_notified": 0,
        "aveonline_status_poll_errors": 0,
    }
    stub.last_heartbeat_ts = 0.0
    stub._apply_aveonline_poll_result = types.MethodType(
        OrchestratorWorker._apply_aveonline_poll_result, stub,
    )
    stub._lookup_shipment_by_id = types.MethodType(
        OrchestratorWorker._lookup_shipment_by_id, stub,
    )
    return stub


def _run_job(stub, sb, clients, *, batch=25, stale_hours=6):
    """Ejecuta el job con AveonlineClient + helpers del módulo parcheados."""
    from worker import OrchestratorWorker
    stub.supabase = sb
    made_clients = {}

    def _factory(tenant_id, supabase):
        c = clients[tenant_id]
        made_clients[tenant_id] = c
        return c

    with patch("worker.AveonlineClient", side_effect=_factory), \
         patch("worker.AVEONLINE_STATUS_POLL_BATCH", batch), \
         patch("worker.AVEONLINE_STATUS_POLL_STALE_HOURS", stale_hours), \
         patch("worker._AVEONLINE_STATUS_POLL_DELAY_SECONDS", 0), \
         patch("worker._record_shipment_tracking_event",
               MagicMock(return_value=True)) as rec, \
         patch("worker._advance_order_to_delivered",
               MagicMock(return_value=True)) as adv, \
         patch("worker._notify_client_shipment_status",
               new=AsyncMock()) as notify:
        _run(OrchestratorWorker._poll_aveonline_shipment_status_if_due(stub))
    return rec, adv, notify, made_clients


# ─── Selección de candidatos (query) ─────────────────────────────────────────

class CandidateSelectionTest(unittest.TestCase):
    def test_disabled_no_query(self):
        stub = _worker_stub(enabled=False)
        sb = MagicMock()
        from worker import OrchestratorWorker
        stub.supabase = sb
        _run(OrchestratorWorker._poll_aveonline_shipment_status_if_due(stub))
        sb.table.assert_not_called()

    def test_throttled_by_interval(self):
        stub = _worker_stub(last_at=time.time())  # recién corrió
        sb = MagicMock()
        from worker import OrchestratorWorker
        stub.supabase = sb
        _run(OrchestratorWorker._poll_aveonline_shipment_status_if_due(stub))
        sb.table.assert_not_called()

    def test_query_solo_stale_no_terminales_con_guia_y_cap(self):
        stub = _worker_stub()
        sb = _FakeSupabase({"shipments": []})
        rec, adv, notify, _ = _run_job(stub, sb, {}, batch=7, stale_hours=6)
        # La query de candidatos es la primera llamada a table("shipments").
        q = sb.table("shipments")
        self.assertIn(("not_is", "tracking_number", "null"), q.calls)
        not_in = next(c for c in q.calls if c[0] == "not_in")
        self.assertEqual(not_in[1], "status")
        self.assertEqual(
            set(not_in[2]),
            {"delivered", "returned", "cancelled", "simulated"},
        )
        self.assertTrue(any(c[0] == "lt" and c[1] == "updated_at" for c in q.calls))
        self.assertIn(("order", "updated_at"), q.calls)  # la más stale primero
        self.assertIn(("limit", 7), q.calls)             # cap por ciclo
        rec.assert_not_called()
        notify.assert_not_awaited()


# ─── Flujo principal: avance monotónico + notificación ───────────────────────

class PollFlowTest(unittest.TestCase):
    def test_entrega_detectada_avanza_orden_y_notifica(self):
        sh = _shipment(status="in_transit")
        refreshed = {**sh, "status": "delivered"}
        # La re-lectura post-RPC (autoridad del guard monotónico) devuelve delivered.
        sb = _FakeSupabase({
            "shipments": lambda q: [refreshed] if ("eq", "id", SHIP) in q.calls else [sh],
        })
        client = _FakeAveonlineClient({
            "G-9001": _estado_result("ENTREGADA", historicos=[
                {"estado": "EN REPARTO", "fechamostrar": "2026-08-01 08:00:00"},
                {"estado": "ENTREGADA", "fechamostrar": "2026-08-02 09:00:00"},
            ]),
        })
        stub = _worker_stub()
        rec, adv, notify, _ = _run_job(stub, sb, {TENANT_A: client})
        # 2 eventos registrados (historico EN REPARTO + ENTREGADA).
        self.assertEqual(rec.call_count, 2)
        kw = rec.call_args_list[-1].kwargs
        self.assertEqual(kw["nombre_estado"], "ENTREGADA")
        self.assertEqual(kw["tenant_id"], TENANT_A)
        self.assertEqual(kw["shipment_id"], SHIP)
        # Orden avanzada a delivered (rank monotónico F-6).
        adv.assert_called_once()
        self.assertEqual(adv.call_args.args[1], TENANT_A)
        self.assertEqual(adv.call_args.args[2], ORDER)
        # Notificación con el estado interno mapeado.
        notify.assert_awaited_once()
        nkw = notify.call_args.kwargs
        self.assertEqual(nkw["internal_status"], "delivered")
        self.assertEqual(nkw["raw_status"], "ENTREGADA")
        self.assertEqual(stub._metrics["aveonline_status_poll_updated"], 1)
        self.assertEqual(stub._metrics["aveonline_status_poll_notified"], 1)
        self.assertEqual(stub._metrics["aveonline_status_poll_checked"], 1)

    def test_sin_cambio_no_notifica(self):
        # El proveedor reporta el MISMO estado que ya tiene el shipment y el
        # evento dedupa (inserted=False) → ni status ni notificación.
        sh = _shipment(status="in_transit")
        sb = _FakeSupabase({"shipments": [sh]})
        client = _FakeAveonlineClient({
            "G-9001": _estado_result("EN REPARTO", historicos=[
                {"estado": "EN REPARTO", "fechamostrar": "2026-08-01 08:00:00"},
            ]),
        })
        stub = _worker_stub()
        with patch("worker.AveonlineClient", side_effect=lambda **k: client), \
             patch("worker._AVEONLINE_STATUS_POLL_DELAY_SECONDS", 0), \
             patch("worker._record_shipment_tracking_event",
                   MagicMock(return_value=False)), \
             patch("worker._advance_order_to_delivered") as adv, \
             patch("worker._notify_client_shipment_status", new=AsyncMock()) as notify:
            from worker import OrchestratorWorker
            stub.supabase = sb
            _run(OrchestratorWorker._poll_aveonline_shipment_status_if_due(stub))
        notify.assert_not_awaited()
        adv.assert_not_called()
        self.assertEqual(stub._metrics["aveonline_status_poll_updated"], 0)

    def test_historico_viejo_no_retrocede_ni_notifica(self):
        # Poll trae un estado NUEVO pero VIEJO en el ciclo (RECOGIDA=pending)
        # cuando el shipment ya va in_transit → gate anti-retroceso: se registra
        # el evento (audit) pero NO se notifica un salto hacia atrás.
        sh = _shipment(status="in_transit")
        sb = _FakeSupabase({"shipments": [sh]})
        client = _FakeAveonlineClient({
            "G-9001": _estado_result("RECOGIDA", historicos=[
                {"estado": "RECOGIDA", "fechamostrar": "2026-08-02 10:00:00"},
            ]),
        })
        stub = _worker_stub()
        rec, adv, notify, _ = _run_job(stub, sb, {TENANT_A: client})
        rec.assert_called_once()          # audit del evento sí
        notify.assert_not_awaited()       # pero jamás "tu envío volvió a recogida"
        adv.assert_not_called()
        self.assertEqual(stub._metrics["aveonline_status_poll_notified"], 0)

    def test_error_proveedor_no_rompe_el_loop(self):
        sh_a = _shipment(tenant=TENANT_A, tracking="G-A", ship_id="ship-a")
        sh_b = _shipment(tenant=TENANT_B, tracking="G-B", ship_id="ship-b",
                         status="pending")
        refreshed_b = {**sh_b, "status": "in_transit"}
        sb = _FakeSupabase({
            "shipments": lambda q: (
                [refreshed_b] if ("eq", "id", "ship-b") in q.calls else [sh_a, sh_b]
            ),
        })
        client_a = _FakeAveonlineClient({"G-A": RuntimeError("aveonline 5xx")})
        client_b = _FakeAveonlineClient({
            "G-B": _estado_result("EN TRANSITO", historicos=[
                {"estado": "EN TRANSITO", "fechamostrar": "2026-08-02 07:00:00"},
            ]),
        })
        stub = _worker_stub()
        rec, adv, notify, _ = _run_job(
            stub, sb, {TENANT_A: client_a, TENANT_B: client_b},
        )
        # El candidato A falló (métrica) pero B se procesó completo.
        self.assertEqual(stub._metrics["aveonline_status_poll_errors"], 1)
        self.assertEqual(client_b.calls, ["G-B"])
        rec.assert_called_once()
        notify.assert_awaited_once()

    def test_tenant_sin_credenciales_degrada_en_silencio(self):
        # AveonlineAuthError → log debug + skip de TODOS los shipments de ese
        # tenant (una sola llamada al proveedor), el resto sigue.
        sh_a1 = _shipment(tenant=TENANT_A, tracking="G-A1", ship_id="ship-a1")
        sh_a2 = _shipment(tenant=TENANT_A, tracking="G-A2", ship_id="ship-a2")
        sh_b = _shipment(tenant=TENANT_B, tracking="G-B", ship_id="ship-b",
                         status="pending")
        refreshed_b = {**sh_b, "status": "in_transit"}
        sb = _FakeSupabase({
            "shipments": lambda q: (
                [refreshed_b] if ("eq", "id", "ship-b") in q.calls
                else [sh_a1, sh_a2, sh_b]
            ),
        })
        client_a = _FakeAveonlineClient({
            "G-A1": _auth_error(),
            "G-A2": _auth_error(),
        })
        client_b = _FakeAveonlineClient({
            "G-B": _estado_result("EN REPARTO", historicos=[
                {"estado": "EN REPARTO", "fechamostrar": "2026-08-02 07:00:00"},
            ]),
        })
        stub = _worker_stub()
        with self.assertLogs("orchestrator.worker", level="DEBUG") as cm:
            rec, adv, notify, _ = _run_job(
                stub, sb, {TENANT_A: client_a, TENANT_B: client_b},
            )
        # Solo UNA consulta para el tenant sin credenciales (skip del resto).
        self.assertEqual(client_a.calls, ["G-A1"])
        self.assertTrue(any("sin credenciales" in m for m in cm.output))
        # B procesado con normalidad.
        rec.assert_called_once()
        notify.assert_awaited_once()
        self.assertEqual(stub._metrics["aveonline_status_poll_errors"], 0)


# ─── Módulo shipment_status_notifications ────────────────────────────────────

class MappingUnitTest(unittest.TestCase):
    def test_map_raw_status_espejo_webhook(self):
        self.assertEqual(ssn.map_raw_status("EN REPARTO"), "in_transit")
        self.assertEqual(ssn.map_raw_status("ENTREGADA"), "delivered")
        self.assertEqual(ssn.map_raw_status("CLIENTE AUSENTE"), "exception")
        self.assertEqual(ssn.map_raw_status("DEVOLUCIÓN"), "returned")
        self.assertEqual(ssn.map_raw_status("ESTADO RARO"), "pending")
        self.assertEqual(ssn.map_raw_status(""), "pending")

    def test_parse_occurred_at_formatos(self):
        self.assertEqual(
            ssn.parse_occurred_at("2026-08-01 10:20:30"),
            "2026-08-01T10:20:30+00:00",
        )
        self.assertEqual(
            ssn.parse_occurred_at("2026/08/01 10:20:30 pm"),
            "2026-08-01T22:20:30+00:00",
        )
        self.assertIsNone(ssn.parse_occurred_at(""))
        self.assertIsNone(ssn.parse_occurred_at("no-es-fecha"))

    def test_is_status_regression(self):
        self.assertTrue(ssn.is_status_regression("in_transit", "pending"))
        self.assertFalse(ssn.is_status_regression("in_transit", "exception"))
        self.assertFalse(ssn.is_status_regression("exception", "in_transit"))
        self.assertFalse(ssn.is_status_regression("pending", "in_transit"))


class RecordEventUnitTest(unittest.TestCase):
    def test_dedup_id_estable_y_mapping(self):
        sb = _FakeSupabase({}, rpc_results={"fn_record_shipment_tracking_event": True})
        ok = ssn.record_shipment_tracking_event(
            sb, tenant_id=TENANT_A, shipment_id=SHIP, order_id=ORDER,
            guia="G-1", nombre_estado="EN REPARTO", fecha="2026-08-01 08:00:00",
            raw_payload={"source": "status_poll"},
        )
        self.assertTrue(ok)
        name, params = sb.rpc_calls[0]
        self.assertEqual(name, "fn_record_shipment_tracking_event")
        self.assertEqual(
            params["p_external_event_id"],
            "G-1|poll:EN REPARTO|2026-08-01 08:00:00",
        )
        self.assertEqual(params["p_provider"], "aveonline")
        self.assertEqual(params["p_internal_status"], "in_transit")
        self.assertEqual(params["p_occurred_at"], "2026-08-01T08:00:00+00:00")
        self.assertIsNone(params["p_raw_estado_id"])

    def test_rpc_error_retorna_false(self):
        sb = _FakeSupabase({}, rpc_results={
            "fn_record_shipment_tracking_event": lambda p: (_ for _ in ()).throw(RuntimeError("db")),
        })
        ok = ssn.record_shipment_tracking_event(
            sb, tenant_id=TENANT_A, shipment_id=SHIP, order_id=ORDER,
            guia="G-1", nombre_estado="ENTREGADA", fecha="", raw_payload={},
        )
        self.assertFalse(ok)


class AdvanceOrderUnitTest(unittest.TestCase):
    def test_desde_shipped_avanza_con_guard_rank(self):
        rec = []
        sb = _FakeSupabase({"orders": [{"id": ORDER}]}, rec)
        ok = ssn.advance_order_to_delivered(sb, TENANT_A, ORDER, "shipped")
        self.assertTrue(ok)
        upd = next(r for r in rec if r["table"] == "orders")
        self.assertEqual(upd["payload"], {"status": "delivered"})
        in_call = next(c for c in upd["calls"] if c[0] == "in")
        # El guard rank EXCLUYE pending/pending_payment (prepago impago).
        self.assertNotIn("pending", in_call[2])
        self.assertNotIn("pending_payment", in_call[2])
        self.assertIn("shipped", in_call[2])

    def test_desde_delivered_es_noop(self):
        rec = []
        sb = _FakeSupabase({"orders": [{"id": ORDER}]}, rec)
        self.assertFalse(ssn.advance_order_to_delivered(sb, TENANT_A, ORDER, "delivered"))
        self.assertFalse(rec)

    def test_desde_cancelled_es_noop(self):
        rec = []
        sb = _FakeSupabase({"orders": [{"id": ORDER}]}, rec)
        self.assertFalse(ssn.advance_order_to_delivered(sb, TENANT_A, ORDER, "cancelled"))
        self.assertFalse(rec)


class NotifyUnitTest(unittest.TestCase):
    def _sb(self):
        return _FakeSupabase({
            "orders": [{
                "conversation_id": CONV,
                "contacts": {"name": "Ana", "email": "ana@x.com"},
            }],
            "tenants": {"name": "KAIU"},
        })

    def _call(self, internal_status, *, shipment=None):
        sb = self._sb()
        shipment = shipment or _shipment()
        with patch.object(ssn, "_enqueue_whatsapp_outbound",
                          MagicMock(return_value=True)) as wa, \
             patch.object(ssn, "_send_email_via_resend",
                          new=AsyncMock(return_value=True)) as email, \
             patch.object(ssn, "notify_escalation_async",
                          new=AsyncMock(return_value=True)) as tg:
            _run(ssn.notify_client_shipment_status(
                sb, tenant_id=TENANT_A, shipment=shipment,
                internal_status=internal_status, raw_status="RAW",
            ))
        return wa, email, tg

    def test_delivered_wa_y_email_sin_alerta_operador(self):
        wa, email, tg = self._call("delivered")
        wa.assert_called_once()
        self.assertIn("entregado", wa.call_args.kwargs["text"])
        email.assert_awaited_once()
        self.assertEqual(
            email.call_args.kwargs["idempotency_key"],
            f"{TENANT_A}:{ORDER}:shipment_status:delivered",
        )
        tg.assert_not_awaited()

    def test_exception_wa_email_y_alerta_operador(self):
        wa, email, tg = self._call("exception")
        wa.assert_called_once()
        email.assert_awaited_once()
        tg.assert_awaited_once()
        self.assertIn("Novedad", tg.call_args.kwargs["reason"])

    def test_returned_solo_alerta_operador(self):
        # Devolución: el operador contacta primero (política del webhook F-7) —
        # NO se avisa al cliente todavía.
        wa, email, tg = self._call("returned")
        wa.assert_not_called()
        email.assert_not_awaited()
        tg.assert_awaited_once()
        self.assertIn("Devolución", tg.call_args.kwargs["reason"])

    def test_shipment_sin_order_no_notifica(self):
        wa, email, tg = self._call("delivered", shipment=_shipment(order_id=None))
        wa.assert_not_called()
        email.assert_not_awaited()
        tg.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
