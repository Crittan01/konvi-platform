"""El detalle completo del comprobante, por correo.

El acuse de WhatsApp es corto a propósito; este es el documento que el comprador necesita
para una garantía, un retracto o un reclamo.

Lo que estas pruebas protegen, en orden de importancia:
  1. que NO se marque como enviado algo que nunca salió — sin RESEND_API_KEY el sender
     devuelve True sin enviar, y el comprador se quedaría sin su documento creyendo que
     lo tiene, con un plazo legal corriendo;
  2. que el documento no aparente ser una factura DIAN (art. 30, publicidad engañosa);
  3. que las condiciones de retracto salgan de la política del tenant, con los mínimos de
     ley como piso;
  4. que el contenido que escribieron personas quede escapado.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

if "vault_helper" not in sys.modules:
    _stub = type(sys)("vault_helper")
    _stub.VaultHelper = type("_V", (), {"__init__": lambda self, sb: None})
    _stub.resolve_secret = lambda v, c, f: c.get(f, "")
    sys.modules["vault_helper"] = _stub

import receipt_email as re_mod  # noqa: E402


SNAP = {
    "version": 1,
    "pedido": {"id": "o-1", "estado": "confirmed", "forma_pago": "credit"},
    "vendedor": {"nombre": "KAIU S.A.S.", "documento": "NIT 900123456-7",
                 "direccion": "Calle 100 # 15-20, Bogotá, Colombia",
                 "email": "hola@kaiu.co", "completa": True},
    "comprador": {"nombre": "Ana Pérez", "telefono": "+573001112233"},
    "items": [{"titulo": "Serum facial", "cantidad": 2,
               "precio_unitario": 25000, "total_linea": 50000}],
    "totales": {"subtotal": 50000, "descuento": 0, "envio": 18000,
                "total": 68000, "moneda": "COP"},
}


def _html(**kw):
    return re_mod.compose_receipt_html(snapshot=kw.pop("snapshot", SNAP),
                                       numero=kw.pop("numero", "CP-000042"), **kw)


# ─── El contenido que exige la ley ──────────────────────────────────────────

def test_identifica_al_vendedor():
    """Art. 50 lit. a): sin vendedor identificable el documento no sirve para reclamar."""
    h = _html()
    assert "KAIU S.A.S." in h and "NIT 900123456-7" in h
    assert "Calle 100 # 15-20" in h and "hola@kaiu.co" in h


def test_el_envio_va_discriminado_por_separado():
    """Art. 50 lit. c): los gastos de envío se informan POR SEPARADO del precio."""
    h = _html()
    assert "Envío" in h and "$18.000" in h
    assert "$50.000" in h and "$68.000" in h


def test_informa_retracto_y_garantia():
    """El plazo de devolución es de 15 días CALENDARIO en comercio electrónico (art. 47 mod.
    Ley 2439/2024). La versión anterior de este test afirmaba 30 y congelaba el error."""
    h = _html(politica={"enable_retracto_flow": True, "retracto_window_business_days": 5,
                        "retracto_return_paid_by": "customer", "manual_refund_legal_days": 15})
    assert "5 días hábiles" in h
    assert "15 días calendario" in h
    assert "Garantía" in h and "un año" in h


def test_las_condiciones_salen_del_tenant_no_hardcodeadas():
    """Son configurables por comerciante: el documento debe decir las SUYAS."""
    h = _html(politica={"enable_retracto_flow": True, "retracto_window_business_days": 10,
                        "retracto_return_paid_by": "tenant", "manual_refund_legal_days": 7})
    assert "10 días hábiles" in h
    assert "lo asume el vendedor" in h
    assert "7 días calendario" in h


def test_pero_nunca_por_debajo_del_minimo_legal():
    """El retracto es un PISO: 5 días hábiles mínimo, se puede ofrecer más."""
    h = _html(politica={"enable_retracto_flow": True, "retracto_window_business_days": 2})
    assert "5 días hábiles" in h and "2 días" not in h


def test_ni_por_encima_del_maximo_legal():
    """El reembolso es un TECHO: 15 días calendario máximo. Operan en direcciones OPUESTAS,
    y confundirlo fue exactamente el bug del CHECK de la base."""
    h = _html(politica={"enable_retracto_flow": True, "manual_refund_legal_days": 30})
    assert "15 días calendario" in h
    assert "30 días" not in h


def test_la_garantia_de_perecederos_es_su_vencimiento():
    """Art. 8: en perecederos el término es la fecha de vencimiento — puede ser MENOR que un
    año. La versión anterior decía "un año, salvo plazo mayor", que excluía justo el caso de
    cosmética."""
    snap = {**SNAP, "items": [{"titulo": "Serum", "cantidad": 1, "precio_unitario": 1,
                               "total_linea": 1, "vence_el": "2027-01-31"}]}
    h = _html(snapshot=snap)
    assert "fecha de vencimiento" in h
    assert "salvo que se informe un plazo mayor" not in h


def test_no_declara_excluido_un_pedido_que_si_admite_retracto():
    """El error más caro de la versión anterior: decía "no aplica a productos de uso personal
    ni hechos a tu medida" en TODOS los comprobantes, sin mirar los ítems — declarando en
    abstracto la inaplicabilidad de un derecho que el comprador sí tenía."""
    h = _html()
    assert "días hábiles" in h, "debe enunciar el derecho"
    assert "no admite retracto" not in h


def test_si_TODO_el_pedido_esta_excluido_lo_dice_y_por_que():
    snap = {**SNAP, "items": [{"titulo": "Kit personalizado", "cantidad": 1,
                               "precio_unitario": 1, "total_linea": 1,
                               "retracto_excluido": True,
                               "retracto_excluido_motivo": "hecho a tu medida"}]}
    h = _html(snapshot=snap)
    assert "no admite retracto" in h and "hecho a tu medida" in h


def test_si_solo_UNA_parte_esta_excluida_no_se_pierde_el_derecho_sobre_el_resto():
    """Decir "no aplica" a secas cuando la mitad del pedido sí admite retracto le quita al
    comprador un derecho real."""
    snap = {**SNAP, "items": [
        {"titulo": "Serum facial", "cantidad": 1, "precio_unitario": 1, "total_linea": 1},
        {"titulo": "Kit personalizado", "cantidad": 1, "precio_unitario": 1, "total_linea": 1,
         "retracto_excluido": True, "retracto_excluido_motivo": "hecho a tu medida"},
    ]}
    h = _html(snapshot=snap)
    assert "días hábiles" in h, "el derecho sigue enunciado para el resto"
    assert "Kit personalizado" in h, "y se nombra lo que queda fuera"
    assert "Serum facial" not in h.split("Retracto")[1][:400], "no debe excluir lo que sí aplica"


def test_distingue_contra_entrega():
    snap = {**SNAP, "pedido": {**SNAP["pedido"], "forma_pago": "cod"}}
    assert "Contra entrega" in _html(snapshot=snap)


# ─── Lo prohibido ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("marcador", ["cufe", "validado por la dian", "resolución dian",
                                      "resolución de facturación", "<qr"])
def test_no_lleva_ningun_marcador_de_factura_electronica(marcador):
    """Riesgo real de publicidad engañosa (art. 30): inducir a error o CONFUSIÓN. Estos
    son los elementos que un comprador asocia con una factura DIAN."""
    assert marcador not in _html().lower()


def test_la_palabra_factura_solo_aparece_NEGADA():
    """Matiz que costó un test mal escrito: el documento SÍ debe decir 'no es una factura
    de venta' — esa negación es contenido correcto y necesario. Lo que no puede es
    afirmarlo. Se verifica que cada aparición venga precedida de una negación."""
    h = _html().lower()
    for i in range(len(h)):
        j = h.find("factura", i)
        if j < 0:
            break
        contexto = h[max(0, j - 40):j]
        assert "no es" in contexto or "no fiscal" in contexto, \
            f"'factura' aparece sin negación cerca: ...{h[max(0,j-40):j+20]}..."
        i = j + 1


def test_y_dice_explicitamente_lo_que_es():
    """No basta con omitirlo: el comprador tiene que poder saber qué recibió."""
    h = _html().lower()
    assert "no fiscal" in h and "no es una factura" in h


# ─── Robustez del render ────────────────────────────────────────────────────

def test_escapa_lo_que_escribieron_personas():
    """La razón social y los títulos de producto los escribe el comerciante; el nombre, el
    comprador. Ninguna de las 7 plantillas existentes escapa."""
    snap = {**SNAP,
            "vendedor": {**SNAP["vendedor"], "nombre": '<script>alert(1)</script>'},
            "items": [{"titulo": "<img onerror=x>", "cantidad": 1,
                       "precio_unitario": 1, "total_linea": 1}]}
    h = _html(snapshot=snap)
    assert "<script>" not in h and "<img onerror" not in h
    assert "&lt;script&gt;" in h


def test_nunca_imprime_un_rotulo_sin_valor():
    """Un 'Documento: —' es peor que no tener la línea."""
    snap = {**SNAP, "vendedor": {"nombre": "Tienda", "completa": False}}
    h = _html(snapshot=snap)
    # El rótulo va en su propia celda; se busca ESO, no la palabra suelta (el encabezado
    # dice "Documento no fiscal" y haría falso positivo).
    assert ">Documento</td>" not in h and ">Dirección</td>" not in h
    assert ">Vendedor</td>" in h and "Tienda" in h


def test_avisa_cuando_la_identidad_esta_incompleta():
    snap = {**SNAP, "vendedor": {**SNAP["vendedor"], "completa": False}}
    assert "pendientes de completar" in _html(snapshot=snap)


def test_el_descuento_cero_no_ensucia():
    assert "Descuento" not in _html()


def test_el_descuento_real_si_aparece():
    snap = {**SNAP, "totales": {**SNAP["totales"], "descuento": 12000}}
    assert "Descuento" in _html(snapshot=snap) and "$12.000" in _html(snapshot=snap)


def test_un_snapshot_vacio_no_revienta():
    h = re_mod.compose_receipt_html(snapshot={}, numero="CP-000001")
    assert "CP-000001" in h and "Sin ítems registrados" in h


def test_hay_version_de_texto_plano():
    texto = re_mod._texto_plano(_html())
    assert "CP-000042" in texto and "<" not in texto


# ─── El riesgo número uno ───────────────────────────────────────────────────

def test_sin_api_key_NO_reporta_exito(caplog):
    """`_send_email_via_resend` devuelve True sin enviar cuando falta la key. Si esta
    guarda no estuviera, se marcaría como remitido un documento con plazo legal que nunca
    salió — y el comprador se quedaría sin él creyendo que lo tiene."""
    import notifications
    with patch.object(notifications, "RESEND_API_KEY", ""), caplog.at_level("ERROR"):
        ok = asyncio.run(re_mod.send_receipt_email(
            receipt_id="r-1", tenant_id="t-1", numero="CP-000042",
            snapshot=SNAP, destinatario="ana@example.com"))
    assert ok is False, "sin key el envío NO es un éxito"
    assert any("RESEND_API_KEY" in r.getMessage() for r in caplog.records)


def test_con_api_key_envia_de_verdad():
    import notifications
    with patch.object(notifications, "RESEND_API_KEY", "re_x"), \
         patch.object(notifications, "_send_email_via_resend",
                      new=AsyncMock(return_value=True)) as send:
        ok = asyncio.run(re_mod.send_receipt_email(
            receipt_id="r-1", tenant_id="t-1", numero="CP-000042",
            snapshot=SNAP, destinatario="ana@example.com"))
    assert ok is True
    kw = send.await_args.kwargs
    assert kw["to"] == "ana@example.com"
    assert "CP-000042" in kw["subject"]
    assert kw["text"], "debe ir también en texto plano"


def test_la_idempotencia_incluye_la_version_del_documento():
    """Si el armado cambia de forma, el correo debe poder reenviarse sin chocar con el
    dedupe de 24h de Resend."""
    import notifications
    with patch.object(notifications, "RESEND_API_KEY", "re_x"), \
         patch.object(notifications, "_send_email_via_resend",
                      new=AsyncMock(return_value=True)) as send:
        asyncio.run(re_mod.send_receipt_email(
            receipt_id="r-1", tenant_id="t-1", numero="CP-1",
            snapshot=SNAP, destinatario="a@b.co"))
    clave = send.await_args.kwargs["idempotency_key"]
    assert "r-1" in clave and "t-1" in clave and f"v{re_mod.RECEIPT_DOC_VERSION}" in clave


def test_sin_destinatario_no_intenta():
    import notifications
    with patch.object(notifications, "RESEND_API_KEY", "re_x"), \
         patch.object(notifications, "_send_email_via_resend", new=AsyncMock()) as send:
        ok = asyncio.run(re_mod.send_receipt_email(
            receipt_id="r-1", tenant_id="t-1", numero="CP-1",
            snapshot=SNAP, destinatario=""))
    assert ok is False and send.await_count == 0


def test_un_fallo_de_resend_no_propaga():
    import notifications
    with patch.object(notifications, "RESEND_API_KEY", "re_x"), \
         patch.object(notifications, "_send_email_via_resend",
                      new=AsyncMock(side_effect=Exception("timeout"))):
        ok = asyncio.run(re_mod.send_receipt_email(
            receipt_id="r-1", tenant_id="t-1", numero="CP-1",
            snapshot=SNAP, destinatario="a@b.co"))
    assert ok is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ─── Que el comprador pueda llegar al vendedor ──────────────────────────────

def test_responder_le_llega_al_vendedor():
    """El correo sale de `noreply@` de la PLATAFORMA, pero quien vende es el tenant. Sin
    reply_to, el comprador que le da "Responder" a su comprobante escribe a un buzón que
    nadie lee — y responder es lo que una persona hace de verdad, aunque el documento
    traiga impreso el correo del vendedor. Ley 1480 art. 50 lit. a)."""
    import notifications
    with patch.object(notifications, "RESEND_API_KEY", "re_x"), \
         patch.object(notifications, "_send_email_via_resend",
                      new=AsyncMock(return_value=True)) as send:
        asyncio.run(re_mod.send_receipt_email(
            receipt_id="r-1", tenant_id="t-1", numero="CP-1",
            snapshot=SNAP, destinatario="ana@example.com",
            responder_a="hola@kaiu.co"))
    assert send.await_args.kwargs["reply_to"] == "hola@kaiu.co"


def test_sin_correo_del_vendedor_no_manda_un_reply_to_vacio():
    """Un reply_to vacío sería peor que ninguno: Resend podría rechazar el envío entero."""
    import notifications
    with patch.object(notifications, "RESEND_API_KEY", "re_x"), \
         patch.object(notifications, "_send_email_via_resend",
                      new=AsyncMock(return_value=True)) as send:
        asyncio.run(re_mod.send_receipt_email(
            receipt_id="r-1", tenant_id="t-1", numero="CP-1",
            snapshot=SNAP, destinatario="ana@example.com"))
    assert send.await_args.kwargs["reply_to"] is None
