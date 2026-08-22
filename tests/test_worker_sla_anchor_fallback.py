"""Escaladas que el SLA no vigilaba: las rutas legales y de dinero.

El tracker de SLA anclaba en la fila `escalation_audit` y hacía `continue` si no existía.
Pero de las ~12 rutas que ponen una conversación en `human_takeover`, solo 5 escriben esa
fila — y entre las que NO están justo el retracto de la Ley 1480, las solicitudes de
Habeas Data y la detección de menor de edad.

O sea: las rutas que menos pueden quedarse sin respuesta eran precisamente las invisibles.
El cliente quedaba escalado y esperando, y el SLA no disparaba nunca.

El ancla correcta es `human_takeover_at`, que estampa un trigger en la TRANSICIÓN de
estado — existe para las ~12 rutas por igual y para las que se agreguen después, que es lo
que evita que el agujero se reabra.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

if "vault_helper" not in sys.modules:
    _stub = type(sys)("vault_helper")
    _stub.VaultHelper = type("_V", (), {"__init__": lambda self, sb: None})
    _stub.resolve_secret = lambda v, c, f: c.get(f, "")
    sys.modules["vault_helper"] = _stub

CONV = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _hace(horas):
    return (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()


class _Q:
    """Encadenable. Devuelve filas según qué content_type se esté pidiendo."""

    def __init__(self, sb, table):
        self._sb, self._table = sb, table
        self._eq: dict = {}
        self._op = "select"

    def select(self, *a, **k):
        return self

    def insert(self, payload):
        self._op = "insert"
        self._sb.inserts.append(payload)
        return self

    def update(self, payload):
        self._op = "update"
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def or_(self, *a, **k):
        return self

    def gt(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._op != "select":
            return type("R", (), {"data": []})()
        if self._table == "conversations":
            return type("R", (), {"data": self._sb.convs})()
        ctype = self._eq.get("content_type")
        if ctype:
            return type("R", (), {"data": self._sb.msgs.get(ctype, [])})()
        if self._eq.get("payload->>sent_by") == "operator":
            return type("R", (), {"data": self._sb.respuesta_operador})()
        return type("R", (), {"data": []})()


class _FakeSB:
    def __init__(self, convs, msgs=None, respuesta_operador=None):
        self.convs = convs
        self.msgs = msgs or {}
        self.respuesta_operador = respuesta_operador or []
        self.inserts: list = []

    def table(self, name):
        return _Q(self, name)


def _conv(**over):
    base = {
        "id": CONV, "tenant_id": TENANT, "customer_phone": "+573001112233",
        "human_takeover_at": _hace(5), "last_interaction_at": _hace(1),
    }
    base.update(over)
    return base


def _build_worker(fake_sb):
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
            inst._last_sla_check_at = 0.0
            return _w, inst
    finally:
        if saved is not None:
            sys.modules["worker"] = saved


def _correr_sla(inst):
    with patch("telegram_notifications.notify_escalation_async",
               new=AsyncMock(return_value=True)) as notify:
        asyncio.run(inst._check_human_takeover_sla_if_due())
    return notify


def _alerto(sb, notify):
    return notify.await_count == 1 and any(
        p.get("content_type") == "sla_breach_audit" for p in sb.inserts
    )


# ─── El agujero que se cierra ───────────────────────────────────────────────

def test_escalada_sin_audit_row_ahora_si_dispara_el_sla():
    """El caso de las 7 rutas huérfanas — retracto Ley 1480, Habeas Data, menor de edad.
    Antes: `continue` silencioso y el cliente esperaba para siempre."""
    sb = _FakeSB([_conv(human_takeover_at=_hace(5))], msgs={})  # sin escalation_audit
    _, inst = _build_worker(sb)
    notify = _correr_sla(inst)
    assert _alerto(sb, notify), "escalada sin audit row: el SLA sigue sin verla"


def test_el_ancla_usada_es_human_takeover_at():
    """Y debe ser el instante de la escalación, no un valor cualquiera: el mensaje de
    alerta le dice al operador desde cuándo espera el cliente."""
    hace_5h = _hace(5)
    sb = _FakeSB([_conv(human_takeover_at=hace_5h)])
    _, inst = _build_worker(sb)
    _correr_sla(inst)
    breach = [p for p in sb.inserts if p.get("content_type") == "sla_breach_audit"][0]
    assert breach["payload"]["escalated_at"] == hace_5h


def test_sin_ninguna_ancla_avisa_en_vez_de_desaparecer(caplog):
    """Registro anterior al trigger o insertado directo. No se puede medir el SLA, pero
    tampoco puede seguir siendo invisible."""
    sb = _FakeSB([_conv(human_takeover_at=None)])
    _, inst = _build_worker(sb)
    with caplog.at_level("WARNING"):
        notify = _correr_sla(inst)
    assert notify.await_count == 0
    assert any("sin ancla" in r.getMessage() for r in caplog.records), \
        "una conv sin ancla debe quedar registrada, no descartarse"


# ─── Lo que NO debe cambiar ─────────────────────────────────────────────────

def test_el_audit_row_sigue_teniendo_prioridad():
    """Cuando existe es el instante REAL de la escalación y trae el motivo — mejor ancla
    que la transición de estado."""
    hace_9h, hace_5h = _hace(9), _hace(5)
    sb = _FakeSB([_conv(human_takeover_at=hace_5h)],
                 msgs={"escalation_audit": [{"created_at": hace_9h}]})
    _, inst = _build_worker(sb)
    _correr_sla(inst)
    breach = [p for p in sb.inserts if p.get("content_type") == "sla_breach_audit"][0]
    assert breach["payload"]["escalated_at"] == hace_9h, "el audit row debe primar"


def test_no_realerta_una_breach_ya_notificada():
    """Idempotencia vigente: si la alerta es RECIENTE (< SLA_REALERT_HOURS),
    no se re-notifica. (B-1 F8: pasadas SLA_REALERT_HOURS sí vuelve a sonar —
    ver tests/agentic/test_b1_human_takeover.py)."""
    sb = _FakeSB([_conv()], msgs={"sla_breach_audit": [{"id": "ya", "created_at": _hace(1)}]})
    _, inst = _build_worker(sb)
    notify = _correr_sla(inst)
    assert notify.await_count == 0


def test_si_el_operador_respondio_no_hay_breach():
    sb = _FakeSB([_conv()], respuesta_operador=[{"id": "msg-operador"}])
    _, inst = _build_worker(sb)
    notify = _correr_sla(inst)
    assert notify.await_count == 0


def test_si_telegram_falla_no_marca_la_breach_como_avisada():
    """Si se estampara igual, un fallo transitorio descartaría la alerta para siempre."""
    sb = _FakeSB([_conv()])
    _, inst = _build_worker(sb)
    with patch("telegram_notifications.notify_escalation_async",
               new=AsyncMock(side_effect=Exception("telegram caído"))):
        asyncio.run(inst._check_human_takeover_sla_if_due())
    assert not [p for p in sb.inserts if p.get("content_type") == "sla_breach_audit"], \
        "sin aviso entregado no se puede marcar como notificada"


def test_sin_conversaciones_escaladas_no_hace_nada():
    sb = _FakeSB([])
    _, inst = _build_worker(sb)
    notify = _correr_sla(inst)
    assert notify.await_count == 0
    assert sb.inserts == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
