"""Pago APPROVED sobre una orden en estado terminal — el cliente pagó y no hay pedido.

Antes, TODOS estos casos se descartaban con un `logger.info` idéntico:
  (a) replay del mismo webhook sobre una orden confirmada → idempotente de verdad
  (b) pago huérfano sobre orden CANCELADA → el cliente pagó un link viejo y no tiene pedido
  (c) pago distinto sobre orden confirmada → posible doble cobro

Solo (a) es realmente idempotente. (b) y (c) son DINERO QUE ENTRÓ y que nadie atendía: sin
alerta, sin intento de anulación, y sin forma de listarlos después.

Escenario de (b), que es frecuente y no un borde: el cliente recibe el link, aplica un cupón o
cambia el carrito, el bot invalida la orden y crea otra — pero Wompi NO permite invalidar un
payment_link, así que el viejo sigue pagable ~30 min.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

API = Path(__file__).resolve().parents[1] / "services" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))


@pytest.fixture
def mod():
    from routers import wompi_webhook
    return wompi_webhook


def _payload(method="CARD"):
    return {"data": {"transaction": {
        "payment_method_type": method,
        "finalized_at": "2026-07-25T10:00:00.000Z",
    }}}


def _order(status="cancelled"):
    return {"id": "ord-1", "tenant_id": "ten-1", "status": status}


def test_huerfano_no_voideable_queda_marcado_para_reembolso(mod, caplog):
    """NEQUI/PSE/Bancolombia no se pueden voidear (fondos ya transferidos) → debe quedar
    explícitamente pendiente de reembolso manual, no perderse en un log INFO."""
    sb = MagicMock()
    with caplog.at_level("ERROR"):
        mod._handle_orphan_payment(
            supabase=sb, order=_order("cancelled"), txn_id="txn-1",
            amount_in_cents=150000, payload=_payload("NEQUI"), current_status="cancelled",
        )
    upd = sb.table.return_value.update.call_args[0][0]
    assert upd == {"status": "orphan_refund_pending"}
    assert any("REEMBOLSO MANUAL" in r.message or "REEMBOLSO MANUAL" in str(r.args) or
               "orphan" in r.message.lower() for r in caplog.records)


def test_huerfano_con_tarjeta_intenta_void(mod):
    """CARD dentro de la ventana → se intenta anular el cobro automáticamente."""
    sb = MagicMock()
    with patch.object(mod, "is_void_eligible", return_value=True), \
         patch.object(mod, "get_tenant_wompi_creds", return_value=("prv_x", None, "production")), \
         patch.object(mod, "void_transaction_sync", return_value={"status": "VOIDED"}) as void:
        mod._handle_orphan_payment(
            supabase=sb, order=_order("cancelled"), txn_id="txn-2",
            amount_in_cents=200000, payload=_payload("CARD"), current_status="cancelled",
        )
    assert void.called, "debe intentar el void para un pago con tarjeta elegible"
    assert sb.table.return_value.update.call_args[0][0] == {"status": "orphan_voided"}


def test_void_rechazado_deja_reembolso_pendiente(mod):
    """Si Wompi rechaza el void (captura ya cerrada), NO debe quedar como anulado."""
    sb = MagicMock()
    with patch.object(mod, "is_void_eligible", return_value=True), \
         patch.object(mod, "get_tenant_wompi_creds", return_value=("prv_x", None, "production")), \
         patch.object(mod, "void_transaction_sync", return_value={"status": "APPROVED"}):
        mod._handle_orphan_payment(
            supabase=sb, order=_order("cancelled"), txn_id="txn-3",
            amount_in_cents=100000, payload=_payload("CARD"), current_status="cancelled",
        )
    assert sb.table.return_value.update.call_args[0][0] == {"status": "orphan_refund_pending"}


def test_void_que_revienta_no_propaga(mod):
    """El webhook debe cerrar igual: Wompi bloquea la API ante 5xx. El pago queda marcado."""
    sb = MagicMock()
    with patch.object(mod, "is_void_eligible", return_value=True), \
         patch.object(mod, "get_tenant_wompi_creds", return_value=("prv_x", None, "production")), \
         patch.object(mod, "void_transaction_sync", side_effect=Exception("wompi caído")):
        mod._handle_orphan_payment(  # no debe lanzar
            supabase=sb, order=_order("cancelled"), txn_id="txn-4",
            amount_in_cents=100000, payload=_payload("CARD"), current_status="cancelled",
        )
    assert sb.table.return_value.update.call_args[0][0] == {"status": "orphan_refund_pending"}


def test_el_pago_queda_consultable(mod):
    """La razón de marcar payments.status: poder LISTAR los pagos que necesitan devolución en
    vez de tener que cruzar logs."""
    sb = MagicMock()
    mod._handle_orphan_payment(
        supabase=sb, order=_order("cancelled"), txn_id="txn-5",
        amount_in_cents=50000, payload=_payload("PSE"), current_status="cancelled",
    )
    # se filtra por txn y por tenant (aislamiento)
    eq_calls = [c[0] for c in sb.table.return_value.update.return_value.eq.call_args_list]
    assert ("wompi_txn_id", "txn-5") in eq_calls or any("txn-5" in str(c) for c in eq_calls)
