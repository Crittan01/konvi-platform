"""El acuse que le llega al comprador.

Ley 1480 art. 50 lit. d) habla de REMITIR el acuse de recibo, no de tenerlo disponible:
emitir el comprobante y dejarlo en una tabla no cumple nada.

Lo que estas pruebas protegen, además de que salga:
  • que el acuse sea CORTO — va a `messages`, que alimenta el contexto del LLM, y meter
    ahí un documento lleno de cifras cuesta tokens en cada turno posterior y le da al
    modelo números para parafrasear (choca con "el LLM no decide verdad transaccional");
  • que nadie reciba DOS acuses;
  • que un acuse que no pudo salir quede distinguible de uno pendiente — el plazo legal
    corre igual.
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
CONV = "cccccccc-cccc-cccc-cccc-cccccccccccc"


class _Q:
    def __init__(self, sb, tabla):
        self._sb, self._t = sb, tabla
        self._op = "select"

    def select(self, *a, **k):
        return self

    def insert(self, payload):
        self._op = "insert"
        self._sb.inserts.append((self._t, payload))
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._op == "insert":
            return type("R", (), {"data": [{}]})()
        if self._t == "conversations":
            return type("R", (), {"data": self._sb.conv})()
        return type("R", (), {"data": []})()


class _FakeSB:
    def __init__(self, *, pendientes=None, telefono="+573001112233", marca=True):
        self.pendientes = pendientes if pendientes is not None else []
        self.conv = [{"customer_phone": telefono}] if telefono else [{}]
        self.marca = marca
        self.inserts: list = []
        self.rpcs: list = []

    def table(self, n):
        return _Q(self, n)

    def rpc(self, nombre, params=None):
        self.rpcs.append((nombre, params))
        datos = {
            "rpc_find_receipts_pending_ack": self.pendientes,
            "rpc_mark_receipt_ack": [True] if self.marca else [],
        }.get(nombre, [])
        return type("R", (), {"execute": lambda _s: type("D", (), {"data": datos})()})()

    def marcas(self):
        return [p for n, p in self.rpcs if n == "rpc_mark_receipt_ack"]


def _pend(**over):
    base = {"receipt_id": RID, "tenant_id": TENANT, "order_id": "o-1",
            "conversation_id": CONV, "numero": "CP-000042",
            "total": 68000, "forma_pago": "credit", "dentro_de_csw": True}
    base.update(over)
    return base


def _worker(sb):
    os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://stub.test")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "stub_key")
    import supabase as _sp
    saved = sys.modules.get("worker")
    try:
        with patch.object(_sp, "create_client", return_value=sb):
            sys.modules.pop("worker", None)
            import worker as _w
            inst = _w.OrchestratorWorker()
            inst.supabase = sb
            inst._receipt_ack_enabled = True
            return _w, inst
    finally:
        if saved is not None:
            sys.modules["worker"] = saved


def _correr(mod, inst, *, envio="wamid.OK"):
    with patch.object(mod, "send_whatsapp_message", new=AsyncMock(return_value=envio)) as send:
        asyncio.run(inst._send_receipt_acks())
    return send


# ─── Que salga ──────────────────────────────────────────────────────────────

def test_le_remite_el_acuse_al_comprador():
    sb = _FakeSB(pendientes=[_pend()])
    mod, inst = _worker(sb)
    send = _correr(mod, inst)
    assert send.await_count == 1
    assert send.await_args.kwargs["to_phone"] == "+573001112233"
    assert inst._metrics["receipt_acks_sent"] == 1


def test_el_acuse_lleva_numero_y_total():
    """Es lo mínimo para que el comprador pueda referirse a su compra."""
    sb = _FakeSB(pendientes=[_pend()])
    mod, inst = _worker(sb)
    texto = _correr(mod, inst).await_args.kwargs["text"]
    assert "CP-000042" in texto and "68.000" in texto


def test_el_acuse_es_corto():
    """Va a `messages`, que alimenta el contexto del LLM en cada turno posterior."""
    sb = _FakeSB(pendientes=[_pend()])
    mod, inst = _worker(sb)
    texto = _correr(mod, inst).await_args.kwargs["text"]
    assert len(texto) < 300, f"{len(texto)} caracteres es un documento, no un acuse"
    assert texto.count("\n") <= 6


def test_no_dice_que_es_una_factura():
    """Aparentar un documento fiscal sería inducir a error (art. 30)."""
    sb = _FakeSB(pendientes=[_pend()])
    mod, inst = _worker(sb)
    texto = _correr(mod, inst).await_args.kwargs["text"].lower()
    for prohibido in ("factura", "cufe", "dian"):
        assert prohibido not in texto


def test_distingue_contra_entrega():
    """El comprador que paga en la puerta necesita ver eso reflejado."""
    sb = _FakeSB(pendientes=[_pend(forma_pago="cod")])
    mod, inst = _worker(sb)
    assert "contra entrega" in _correr(mod, inst).await_args.kwargs["text"]


def test_queda_en_el_inbox_del_operador():
    sb = _FakeSB(pendientes=[_pend()])
    mod, inst = _worker(sb)
    _correr(mod, inst)
    msgs = [p for t, p in sb.inserts if t == "messages"]
    assert len(msgs) == 1 and msgs[0]["meta_message_id"] == "wamid.OK"


# ─── Que nadie reciba dos ───────────────────────────────────────────────────

def test_se_marca_como_remitido():
    sb = _FakeSB(pendientes=[_pend()])
    mod, inst = _worker(sb)
    _correr(mod, inst)
    marca = sb.marcas()[0]
    assert marca["p_channel"] == "whatsapp" and marca["p_skipped"] is None


def test_si_otro_tick_gano_la_carrera_no_se_re_persiste():
    """La marca es el candado. Si no la ganó esta corrida, el mensaje ya lo persistió otra."""
    sb = _FakeSB(pendientes=[_pend()], marca=False)
    mod, inst = _worker(sb)
    _correr(mod, inst)
    assert [p for t, p in sb.inserts if t == "messages"] == []
    assert inst._metrics["receipt_acks_sent"] == 0


# ─── Cuando no se puede ─────────────────────────────────────────────────────

def test_fuera_de_la_ventana_de_meta_se_marca_el_motivo():
    """No se puede escribir free-form y las plantillas están diferidas. Marcarlo es lo que
    evita que un acuse que nunca sale sea indistinguible de uno pendiente."""
    sb = _FakeSB(pendientes=[_pend(dentro_de_csw=False)])
    mod, inst = _worker(sb)
    send = _correr(mod, inst)
    assert send.await_count == 0
    assert inst._metrics["receipt_acks_out_of_window"] == 1
    assert sb.marcas()[0]["p_skipped"] == "fuera_de_ventana_csw"


def test_sin_telefono_se_marca_en_vez_de_intentar():
    sb = _FakeSB(pendientes=[_pend()], telefono=None)
    mod, inst = _worker(sb)
    send = _correr(mod, inst)
    assert send.await_count == 0
    assert sb.marcas()[0]["p_skipped"] == "sin_telefono"


def test_si_el_envio_falla_NO_se_marca_y_se_reintenta():
    """Un acuse tiene plazo legal: darlo por perdido en el primer fallo sería peor."""
    sb = _FakeSB(pendientes=[_pend()])
    mod, inst = _worker(sb)
    _correr(mod, inst, envio=None)
    assert sb.marcas() == [], "no debe marcarse: el próximo barrido reintenta"
    assert inst._metrics["receipt_acks_sent"] == 0


def test_un_fallo_no_frena_a_los_demas():
    sb = _FakeSB(pendientes=[_pend(), _pend(receipt_id=RID.replace("a", "d"))])
    mod, inst = _worker(sb)
    with patch.object(mod, "send_whatsapp_message",
                      new=AsyncMock(side_effect=[Exception("Meta caído"), "wamid.OK"])):
        asyncio.run(inst._send_receipt_acks())
    assert inst._metrics["receipt_acks_sent"] == 1


# ─── Interruptores ──────────────────────────────────────────────────────────

def test_apagado_por_flag_no_hace_nada():
    sb = _FakeSB(pendientes=[_pend()])
    mod, inst = _worker(sb)
    inst._receipt_ack_enabled = False
    send = _correr(mod, inst)
    assert send.await_count == 0 and sb.rpcs == []


def test_sin_la_migracion_avisa_pero_no_rompe():
    sb = _FakeSB()

    def _boom(nombre, params=None):
        raise RuntimeError("no existe")

    sb.rpc = _boom
    mod, inst = _worker(sb)
    _correr(mod, inst)   # no debe lanzar
    assert inst._metrics["receipt_acks_sent"] == 0


def test_la_ventana_consultada_es_la_de_meta():
    sb = _FakeSB()
    mod, inst = _worker(sb)
    _correr(mod, inst)
    params = [p for n, p in sb.rpcs if n == "rpc_find_receipts_pending_ack"][0]
    assert params["p_csw_hours"] == mod.META_CSW_HOURS


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
