"""El barrido que manda el detalle completo por correo.

Es HERMANO del acuse por WhatsApp, no un paso dentro de él, y ese es el punto: el barrido
de acuses excluye las filas con `ack_skipped_reason` y las que no tienen conversación — que
son exactamente la población que el correo viene a rescatar. Hasta ahora el worker prometía
"queda disponible por correo" sobre filas que habían quedado fuera para siempre.
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

if "vault_helper" not in sys.modules:
    _stub = type(sys)("vault_helper")
    _stub.VaultHelper = type("_V", (), {"__init__": lambda self, sb: None})
    _stub.resolve_secret = lambda v, c, f: c.get(f, "")
    sys.modules["vault_helper"] = _stub

RID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class _Q:
    def __init__(self, sb, t):
        self._sb, self._t = sb, t

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._t == "tenant_cancellation_policy":
            return type("R", (), {"data": self._sb.politica})()
        return type("R", (), {"data": []})()


class _FakeSB:
    def __init__(self, *, pendientes=None, marca=True, politica=None):
        self.pendientes = pendientes if pendientes is not None else []
        self.marca = marca
        self.politica = politica if politica is not None else [{"retracto_window_business_days": 5}]
        self.rpcs: list = []

    def table(self, t):
        return _Q(self, t)

    def rpc(self, nombre, params=None):
        self.rpcs.append((nombre, params))
        datos = {
            "rpc_find_receipts_pending_email": self.pendientes,
            "rpc_mark_receipt_email": [True] if self.marca else [],
        }.get(nombre, [])
        return type("R", (), {"execute": lambda _s: type("D", (), {"data": datos})()})()

    def marcas(self):
        return [p for n, p in self.rpcs if n == "rpc_mark_receipt_email"]


def _pend(**over):
    base = {"receipt_id": RID, "tenant_id": TENANT, "numero": "CP-000042",
            "snapshot": {"totales": {"total": 68000}}, "email": "ana@example.com"}
    base.update(over)
    return base


def _worker(sb):
    os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://stub.test")
    os.environ.setdefault("SUPABASE_SECRET_KEY", "stub_key")
    import supabase as _sp
    saved = sys.modules.get("worker")
    try:
        with patch.object(_sp, "create_client", return_value=sb):
            sys.modules.pop("worker", None)
            import worker as _w
            inst = _w.OrchestratorWorker()
            inst.supabase = sb
            inst._receipt_email_enabled = True
            return _w, inst
    finally:
        if saved is not None:
            sys.modules["worker"] = saved


def _correr(inst, *, envio=True):
    import receipt_email
    with patch.object(receipt_email, "send_receipt_email",
                      new=AsyncMock(return_value=envio)) as send:
        asyncio.run(inst._send_receipt_emails())
    return send


# ─── Que salga ──────────────────────────────────────────────────────────────

def test_manda_el_detalle_completo():
    sb = _FakeSB(pendientes=[_pend()])
    _, inst = _worker(sb)
    send = _correr(inst)
    assert send.await_count == 1
    assert send.await_args.kwargs["destinatario"] == "ana@example.com"
    assert inst._metrics["receipt_emails_sent"] == 1


def test_el_reply_to_sale_del_snapshot_no_del_tenant_vivo():
    """Si el vendedor cambia su correo, el comprobante viejo debe seguir apuntando al que
    tenía cuando se emitió — es parte de lo que hace al documento un comprobante."""
    snap = {"vendedor": {"email": "viejo@kaiu.co"}, "totales": {"total": 1000}}
    sb = _FakeSB(pendientes=[_pend(snapshot=snap)])
    _, inst = _worker(sb)
    send = _correr(inst)
    assert send.await_args.kwargs["responder_a"] == "viejo@kaiu.co"


def test_le_pasa_el_snapshot_congelado_no_datos_vivos():
    sb = _FakeSB(pendientes=[_pend()])
    _, inst = _worker(sb)
    send = _correr(inst)
    assert send.await_args.kwargs["snapshot"] == {"totales": {"total": 68000}}


def test_le_pasa_la_politica_de_retracto_del_tenant():
    """Las condiciones son configurables por comerciante: el documento debe decir las suyas."""
    sb = _FakeSB(pendientes=[_pend()], politica=[{"retracto_window_business_days": 10}])
    _, inst = _worker(sb)
    send = _correr(inst)
    assert send.await_args.kwargs["politica"]["retracto_window_business_days"] == 10


def test_se_marca_para_no_reenviar():
    sb = _FakeSB(pendientes=[_pend()])
    _, inst = _worker(sb)
    _correr(inst)
    m = sb.marcas()[0]
    assert m["p_email"] == "ana@example.com" and m["p_skipped"] is None


# ─── Cuando no se puede ─────────────────────────────────────────────────────

def test_comprador_sin_correo_se_marca_con_motivo():
    """No es un fallo, es un hecho del comprador. Marcarlo evita que quede pendiente para
    siempre; el acuse por WhatsApp ya lo cubrió."""
    sb = _FakeSB(pendientes=[_pend(email=None)])
    _, inst = _worker(sb)
    send = _correr(inst)
    assert send.await_count == 0
    assert sb.marcas()[0]["p_skipped"] == "comprador_sin_correo"


def test_si_el_envio_falla_NO_se_marca_y_se_reintenta():
    """Un comprobante tiene plazo legal: darlo por perdido en el primer fallo sería peor."""
    sb = _FakeSB(pendientes=[_pend()])
    _, inst = _worker(sb)
    _correr(inst, envio=False)
    assert sb.marcas() == []
    assert inst._metrics["receipt_emails_failed"] == 1
    assert inst._metrics["receipt_emails_sent"] == 0


def test_una_excepcion_no_frena_a_los_demas():
    sb = _FakeSB(pendientes=[_pend(), _pend(receipt_id=RID.replace("a", "d"))])
    _, inst = _worker(sb)
    import receipt_email
    with patch.object(receipt_email, "send_receipt_email",
                      new=AsyncMock(side_effect=[Exception("resend caído"), True])):
        asyncio.run(inst._send_receipt_emails())
    assert inst._metrics["receipt_emails_sent"] == 1
    assert inst._metrics["receipt_emails_failed"] == 1


def test_sin_politica_del_tenant_igual_envia():
    """La política es enriquecimiento, no requisito: el renderizador tiene los mínimos
    de ley como piso."""
    sb = _FakeSB(pendientes=[_pend()], politica=[])
    _, inst = _worker(sb)
    assert _correr(inst).await_count == 1


# ─── Independencia de los dos canales ───────────────────────────────────────

def test_no_consulta_el_estado_del_acuse_de_whatsapp():
    """Si dependiera de él, heredaría sus exclusiones — y esas filas son justo las que el
    correo viene a rescatar."""
    sb = _FakeSB(pendientes=[_pend()])
    _, inst = _worker(sb)
    _correr(inst)
    assert "rpc_find_receipts_pending_ack" not in [n for n, _ in sb.rpcs]
    assert "rpc_mark_receipt_ack" not in [n for n, _ in sb.rpcs]


# ─── Interruptores ──────────────────────────────────────────────────────────

def test_apagado_por_flag_no_hace_nada():
    sb = _FakeSB(pendientes=[_pend()])
    _, inst = _worker(sb)
    inst._receipt_email_enabled = False
    send = _correr(inst)
    assert send.await_count == 0 and sb.rpcs == []


def test_sin_la_migracion_avisa_pero_no_rompe():
    sb = _FakeSB()

    def _boom(n, p=None):
        raise RuntimeError("no existe")

    sb.rpc = _boom
    _, inst = _worker(sb)
    _correr(inst)   # no debe lanzar
    assert inst._metrics["receipt_emails_sent"] == 0


def test_sin_pendientes_no_hace_nada():
    sb = _FakeSB(pendientes=[])
    _, inst = _worker(sb)
    send = _correr(inst)
    assert send.await_count == 0 and sb.marcas() == []
