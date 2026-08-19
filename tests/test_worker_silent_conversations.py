"""El barrido que atiende al cliente que escribió y no recibió respuesta.

La detección vive en SQL (tests/dbharness/test_silent_conversations.py fija dónde está
la línea entre silencio y demora). Acá se prueba lo que el worker HACE con cada caso, que
es donde está el riesgo real: si falla el paso equivocado, el cliente queda igual de
abandonado pero ahora con la sensación de que el sistema lo atendió.

Orden de importancia de las cuatro acciones:
  1. escalar a human_takeover  → lo único que garantiza que un humano se entere
  2. auditar                   → idempotencia + el tracker de SLA la toma desde acá
  3. avisar al equipo
  4. escribirle al cliente     → best-effort: si lo roto es justo el envío, falla
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

if "vault_helper" not in sys.modules:  # worker → whatsapp_sender → vault_helper
    _stub = type(sys)("vault_helper")
    _stub.VaultHelper = type("_V", (), {"__init__": lambda self, sb: None})
    _stub.resolve_secret = lambda v, c, f: c.get(f, "")
    sys.modules["vault_helper"] = _stub


CONV = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"


class _Q:
    """Query encadenable que sólo registra: acá interesa QUÉ se escribió, no filtrarlo."""

    def __init__(self, log, table):
        self._log, self._table = log, table

    def update(self, payload):
        self._log.append(("update", self._table, payload))
        return self

    def insert(self, payload):
        self._log.append(("insert", self._table, payload))
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": []})()


class _FakeSB:
    def __init__(self, silent_rows, rpc_raises=False):
        self.log: list = []
        self._rows = silent_rows
        self._rpc_raises = rpc_raises

    def table(self, name):
        return _Q(self.log, name)

    def rpc(self, name, params=None):
        if self._rpc_raises:
            raise RuntimeError("function public.rpc_find_silent_conversations does not exist")
        self.log.append(("rpc", name, params))
        return type("R", (), {"execute": lambda _s: type("D", (), {"data": self._rows})()})()

    # atajos de lectura
    def writes(self, op, table):
        return [p for o, t, p in self.log if o == op and t == table]


def _row(**over):
    base = {
        "conversation_id": CONV, "tenant_id": TENANT,
        "customer_phone": "+573001112233", "last_inbound_at": "2026-07-25T10:00:00Z",
        "silence_minutes": 27,
    }
    base.update(over)
    return base


def _build_worker(fake_sb):
    """Instancia el worker con Supabase falso, restaurando sys.modules después
    (un `del sys.modules['worker']` sin restaurar contamina otros tests)."""
    os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://stub.test")
    os.environ.setdefault("SUPABASE_SECRET_KEY", "stub_key")
    import supabase as _sp
    saved = sys.modules.get("worker")
    try:
        with patch.object(_sp, "create_client", return_value=fake_sb):
            sys.modules.pop("worker", None)
            import worker as _w
            inst = _w.OrchestratorWorker()
            inst.supabase = fake_sb
            inst._silent_conv_enabled = True
            inst._last_silent_conv_check_at = 0.0
            return _w, inst
    finally:
        if saved is not None:
            sys.modules["worker"] = saved


def _sweep(worker_mod, inst, *, send_returns="wamid.OK"):
    with patch.object(worker_mod, "send_whatsapp_message",
                      new=AsyncMock(return_value=send_returns)) as send, \
         patch("telegram_notifications.notify_escalation_async",
               new=AsyncMock(return_value=True)) as notify:
        asyncio.run(inst._detect_silent_conversations_if_due())
    return send, notify


# ─── Lo que hace cuando encuentra un cliente sin respuesta ───────────────────

def test_escala_a_un_humano():
    """Es la única acción que garantiza que alguien se entere."""
    sb = _FakeSB([_row()])
    mod, inst = _build_worker(sb)
    _sweep(mod, inst)
    assert {"status": "human_takeover"} in sb.writes("update", "conversations")


def test_le_escribe_al_cliente_que_esta_esperando():
    sb = _FakeSB([_row()])
    mod, inst = _build_worker(sb)
    send, _ = _sweep(mod, inst)
    assert send.await_count == 1, "el cliente lleva media hora esperando y no le escribimos"
    assert send.await_args.kwargs["to_phone"] == "+573001112233"
    from agentic.degraded_messages import DEGRADED_GENERIC
    assert send.await_args.kwargs["text"] == DEGRADED_GENERIC, \
        "el copy debe salir del catálogo canónico, no ser ad-hoc"


def test_avisa_al_equipo():
    sb = _FakeSB([_row()])
    mod, inst = _build_worker(sb)
    _, notify = _sweep(mod, inst)
    assert notify.await_count == 1


def test_deja_la_escalada_visible_para_el_tracker_de_sla():
    """El tracker de SLA calcula desde el último `escalation_audit`. Sin esa fila la
    conversación queda en human_takeover pero fuera de su radar — escalada y olvidada."""
    sb = _FakeSB([_row()])
    mod, inst = _build_worker(sb)
    _sweep(mod, inst)
    tipos = {p.get("content_type") for p in sb.writes("insert", "messages")}
    assert "escalation_audit" in tipos
    assert "silent_conversation_audit" in tipos, "sin esta fila re-alerta cada 5 min"


def test_persiste_el_mensaje_enviado_para_que_aparezca_en_el_inbox():
    sb = _FakeSB([_row()])
    mod, inst = _build_worker(sb)
    _sweep(mod, inst)
    textos = [p for p in sb.writes("insert", "messages") if p.get("content_type") == "text"]
    assert len(textos) == 1
    assert textos[0]["meta_message_id"] == "wamid.OK"


# ─── Cuando lo que está roto es justo el envío ──────────────────────────────

def test_si_el_envio_falla_la_escalada_igual_ocurre():
    """El caso frecuente: el cliente quedó mudo PORQUE el envío está roto. Reintentarlo
    también falla — pero un humano ya fue avisado, que es lo que salva al cliente."""
    sb = _FakeSB([_row()])
    mod, inst = _build_worker(sb)
    send, notify = _sweep(mod, inst, send_returns=None)
    assert {"status": "human_takeover"} in sb.writes("update", "conversations")
    assert notify.await_count == 1
    assert inst._metrics["silent_conversations_detected"] == 1
    assert inst._metrics["silent_conversations_recovered"] == 0, \
        "no se le respondió al cliente: contarlo como recuperado mentiría en las métricas"
    assert not [p for p in sb.writes("insert", "messages") if p.get("content_type") == "text"], \
        "no debe quedar un outbound 'entregado' que nunca salió"


def test_si_el_envio_revienta_no_tumba_el_barrido():
    sb = _FakeSB([_row(conversation_id=CONV), _row(conversation_id=CONV.replace("1", "3"))])
    mod, inst = _build_worker(sb)
    with patch.object(mod, "send_whatsapp_message",
                      new=AsyncMock(side_effect=Exception("Meta caído"))), \
         patch("telegram_notifications.notify_escalation_async", new=AsyncMock()):
        asyncio.run(inst._detect_silent_conversations_if_due())  # no debe propagar
    assert len(sb.writes("update", "conversations")) == 2, "la 2ª conv quedó sin atender"


def test_si_no_puede_escalar_no_finge_haber_atendido():
    """Si el UPDATE falla, escribirle al cliente 'ya te contactan' sería una promesa que
    nadie va a cumplir: no hay humano avisado ni conv en el Inbox."""
    sb = _FakeSB([_row()])
    mod, inst = _build_worker(sb)

    def _boom(name):
        q = _Q(sb.log, name)
        if name == "conversations":
            q.execute = lambda: (_ for _ in ()).throw(RuntimeError("db caída"))
        return q

    sb.table = _boom
    send, notify = _sweep(mod, inst)
    assert send.await_count == 0
    assert notify.await_count == 0


# ─── Interruptores y degradación ────────────────────────────────────────────

def test_apagado_por_flag_no_hace_nada():
    sb = _FakeSB([_row()])
    mod, inst = _build_worker(sb)
    inst._silent_conv_enabled = False
    send, _ = _sweep(mod, inst)
    assert send.await_count == 0
    assert sb.log == []


def test_sin_la_migracion_aplicada_avisa_pero_no_rompe():
    """El worker puede desplegarse antes que la migración; el ciclo entero no puede caerse
    por eso."""
    sb = _FakeSB([], rpc_raises=True)
    mod, inst = _build_worker(sb)
    send, _ = _sweep(mod, inst)
    assert send.await_count == 0


def test_no_barre_dos_veces_seguidas():
    sb = _FakeSB([_row()])
    mod, inst = _build_worker(sb)
    _sweep(mod, inst)
    send2, _ = _sweep(mod, inst)   # inmediatamente después
    assert send2.await_count == 0, "el intervalo mínimo no se respetó"


def test_sin_conversaciones_silenciosas_no_toca_nada():
    sb = _FakeSB([])
    mod, inst = _build_worker(sb)
    send, notify = _sweep(mod, inst)
    assert send.await_count == 0
    assert notify.await_count == 0
    assert sb.writes("update", "conversations") == []


def test_fila_incompleta_se_saltea_sin_romper():
    sb = _FakeSB([_row(tenant_id=None), _row()])
    mod, inst = _build_worker(sb)
    send, _ = _sweep(mod, inst)
    assert send.await_count == 1, "la fila buena debe atenderse igual"


def test_la_ventana_consultada_respeta_las_24h_de_meta():
    """Fuera de la ventana de servicio no podríamos responder free-form: alertar ahí no
    habilitaría ninguna acción."""
    sb = _FakeSB([])
    mod, inst = _build_worker(sb)
    _sweep(mod, inst)
    params = [p for o, n, p in sb.log if o == "rpc"][0]
    assert params["p_window_hours"] == mod.META_CSW_HOURS
    assert params["p_silence_minutes"] >= 5, "umbral demasiado corto: alertaría demoras normales"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
