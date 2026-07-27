"""El detalle completo del comprobante de compra, por correo.  ADR-0040 paso 6.

El acuse que va por WhatsApp es corto a propósito (`messages` alimenta el contexto del
LLM). Este es el documento completo: lo que el comprador necesita para una garantía, un
retracto o un reclamo.

DEUDA DECLARADA, igual que `refund_notifications.py`: las 7 plantillas de correo al
comprador viven en `services/api/routers/wompi_webhook.py`, y `services/api/` NO EXISTE en
el contenedor del orchestrator (rootDir separados en Render), así que un import cruzado
revienta. Los helpers de formato están replicados a conciencia. Si se edita el estilo allá,
hay que actualizarlo acá.

NO ES UNA FACTURA ELECTRÓNICA DIAN y el documento no puede aparentarlo: sería inducir a
error o confusión (Ley 1480 art. 30). Hay un test que falla si aparece "factura de venta",
"CUFE", "DIAN" o una resolución de facturación.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Debe coincidir con snapshot['version']. Si el armado del comprobante cambia de forma,
# esto sube y la clave de idempotencia cambia con él.
RECEIPT_DOC_VERSION = 1


def _esc(v: Any) -> str:
    """Escapa para HTML. Ninguna de las 7 plantillas existentes lo hace, y acá el
    contenido incluye texto que escribió el comerciante (razón social, títulos de
    producto) y el comprador (su nombre)."""
    if v is None:
        return ""
    return (
        str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&#39;")
    )


def _cop(value: Any) -> str:
    """Réplica de `_fmt_cop` (wompi_webhook.py) — pesos colombianos, sin centavos."""
    try:
        return f"${float(value or 0):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "$0"


def _texto_plano(html: str) -> str:
    """Parte text/plain. Sin esto el correo puntúa peor en filtros de spam y es
    ilegible en clientes que no renderizan HTML."""
    sin_tags = re.sub(r"<br\s*/?>", "\n", html)
    sin_tags = re.sub(r"</(p|tr|h1|h2|h3|div)>", "\n", sin_tags)
    sin_tags = re.sub(r"<[^>]+>", "", sin_tags)
    lineas = [ln.strip() for ln in sin_tags.splitlines()]
    return "\n".join(ln for ln in lineas if ln)


def _fila(rotulo: str, valor: Optional[str]) -> str:
    """Una línea del bloque de identificación. Devuelve cadena vacía si no hay valor:
    un rótulo huérfano ("Documento: —") es peor que no tener la línea."""
    if not valor:
        return ""
    return (
        f'<tr><td style="padding:2px 12px 2px 0;color:#7f8c8d;white-space:nowrap">{_esc(rotulo)}</td>'
        f'<td style="padding:2px 0;color:#2c3e50">{_esc(valor)}</td></tr>'
    )


def _marcar_titulo(texto: str) -> str:
    """Pone en negrita la primera palabra hasta el punto ("Retracto.", "Garantía.").
    El texto legal vive en `lib.legal_texts` sin HTML — el formato es de la vista."""
    if "." not in texto:
        return texto
    titulo, resto = texto.split(".", 1)
    return f"<strong>{titulo}.</strong>{resto}"


def compose_receipt_subject(*, numero: str, vendedor: str) -> str:
    return f"Comprobante {numero} — {vendedor}" if vendedor else f"Comprobante {numero}"


def compose_receipt_html(*, snapshot: dict, numero: str, politica: Optional[dict] = None) -> str:
    """Arma el documento a partir del SNAPSHOT CONGELADO, nunca de datos vivos.

    `politica` trae las condiciones de retracto del tenant (tabla
    `tenant_cancellation_policy`). Se leen en vez de hardcodearse porque son configurables
    por comerciante — pero con los mínimos de ley como piso: la Ley 1480 art. 47 da 5 días
    hábiles y ningún tenant puede ofrecer menos.
    """
    vendedor = (snapshot or {}).get("vendedor") or {}
    comprador = (snapshot or {}).get("comprador") or {}
    pedido = (snapshot or {}).get("pedido") or {}
    totales = (snapshot or {}).get("totales") or {}
    items = (snapshot or {}).get("items") or []

    filas_items = "".join(
        f'<tr>'
        f'<td style="padding:8px 0;border-bottom:1px solid #ecf0f1">{_esc(i.get("titulo"))}</td>'
        f'<td style="padding:8px 0;border-bottom:1px solid #ecf0f1;text-align:center">{_esc(i.get("cantidad"))}</td>'
        f'<td style="padding:8px 0;border-bottom:1px solid #ecf0f1;text-align:right">{_cop(i.get("precio_unitario"))}</td>'
        f'<td style="padding:8px 0;border-bottom:1px solid #ecf0f1;text-align:right">{_cop(i.get("total_linea"))}</td>'
        f'</tr>'
        for i in items
    ) or '<tr><td colspan="4" style="padding:8px 0;color:#7f8c8d">Sin ítems registrados</td></tr>'

    # El descuento solo aparece si lo hubo: una línea "Descuento $0" es ruido.
    descuento = float(totales.get("descuento") or 0)
    fila_descuento = (
        f'<tr><td style="padding:4px 0;color:#7f8c8d">Descuento</td>'
        f'<td style="padding:4px 0;text-align:right;color:#27ae60">− {_cop(descuento)}</td></tr>'
        if descuento > 0 else ""
    )

    pago = "Contra entrega" if (pedido.get("forma_pago") or "") == "cod" else "Pago en línea"

    # Todo texto legal sale de `lib.legal_texts`, que es la única fuente. Antes estaba
    # escrito a mano acá y en tres sitios más, y habían divergido — con plazos y
    # excepciones equivocados que, bajo el art. 29, obligaban al vendedor en los términos
    # en que se los anunció.
    from lib.legal_texts import texto_garantia, texto_retracto  # noqa: PLC0415

    _retracto = texto_retracto(politica, items)
    bloque_retracto = (
        f'<p style="margin:4px 0">{_marcar_titulo(_esc(_retracto))}</p>' if _retracto else ""
    )
    bloque_garantia = f'<p style="margin:4px 0">{_marcar_titulo(_esc(texto_garantia(items)))}</p>' 

    aviso_incompleto = (
        '<p style="margin:8px 0 0;color:#b9770e;font-size:12px">'
        'Algunos datos de identificación del vendedor están pendientes de completar.</p>'
        if vendedor.get("completa") is False else ""
    )

    return f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;color:#2c3e50">
  <h2 style="margin:0 0 4px;font-size:20px">Comprobante de compra {_esc(numero)}</h2>
  <p style="margin:0 0 16px;color:#7f8c8d;font-size:13px">
    Documento no fiscal · No es una factura de venta
  </p>

  <table style="width:100%;font-size:13px;margin-bottom:16px">
    {_fila("Vendedor", vendedor.get("nombre"))}
    {_fila("Documento", vendedor.get("documento"))}
    {_fila("Dirección", vendedor.get("direccion"))}
    {_fila("Correo", vendedor.get("email"))}
  </table>
  {aviso_incompleto}

  <table style="width:100%;font-size:13px;margin-bottom:16px">
    {_fila("Comprador", comprador.get("nombre"))}
    {_fila("Teléfono", comprador.get("telefono"))}
    {_fila("Forma de pago", pago)}
  </table>

  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <tr style="color:#7f8c8d;font-size:12px">
      <th style="text-align:left;padding-bottom:6px">Producto</th>
      <th style="text-align:center;padding-bottom:6px">Cant.</th>
      <th style="text-align:right;padding-bottom:6px">Unitario</th>
      <th style="text-align:right;padding-bottom:6px">Total</th>
    </tr>
    {filas_items}
  </table>

  <table style="width:100%;font-size:13px;margin-top:12px">
    <tr><td style="padding:4px 0;color:#7f8c8d">Subtotal</td>
        <td style="padding:4px 0;text-align:right">{_cop(totales.get("subtotal"))}</td></tr>
    {fila_descuento}
    <tr><td style="padding:4px 0;color:#7f8c8d">Envío</td>
        <td style="padding:4px 0;text-align:right">{_cop(totales.get("envio"))}</td></tr>
    <tr><td style="padding:8px 0;border-top:2px solid #2c3e50;font-weight:bold">Total</td>
        <td style="padding:8px 0;border-top:2px solid #2c3e50;text-align:right;font-weight:bold">
          {_cop(totales.get("total"))} COP</td></tr>
  </table>

  <div style="margin-top:20px;padding-top:12px;border-top:1px solid #ecf0f1;font-size:12px;color:#7f8c8d">
    {bloque_retracto}
    {bloque_garantia}
    <p style="margin:12px 0 0">Recibiste este correo porque hiciste una compra.
    Guárdalo como comprobante.</p>
  </div>
</div>"""


async def send_receipt_email(
    *,
    receipt_id: str,
    tenant_id: str,
    numero: str,
    snapshot: dict,
    destinatario: str,
    politica: Optional[dict] = None,
    responder_a: Optional[str] = None,
) -> bool:
    """Envía el documento. True SOLO si Resend lo aceptó.

    NO marca nada en la base: marcar es responsabilidad del worker, que es quien sabe
    distinguir "salió" de "no había a quién mandarlo".

    LA GUARDA DE ABAJO ES EL RIESGO NÚMERO UNO DE ESTA FUNCIÓN. Sin `RESEND_API_KEY`,
    `_send_email_via_resend` loguea "Email simulated" y devuelve **True sin enviar nada**
    (notifications.py). Un caller ingenuo marcaría como remitido un documento con plazo
    legal que nunca salió — y el comprador se quedaría sin él creyendo que lo tiene.
    Se lee el atributo del módulo, no os.environ, porque el env se resuelve en import-time.
    """
    import notifications  # noqa: PLC0415 — import plano: mismo rootDir del servicio

    if not getattr(notifications, "RESEND_API_KEY", ""):
        logger.error(
            "[COMPROBANTE][EMAIL] sin RESEND_API_KEY — %s NO se envía y NO se marca",
            numero,
        )
        return False

    if not destinatario:
        return False

    html = compose_receipt_html(snapshot=snapshot, numero=numero, politica=politica)
    vendedor = ((snapshot or {}).get("vendedor") or {}).get("nombre") or ""
    try:
        return await notifications._send_email_via_resend(
            to=destinatario,
            subject=compose_receipt_subject(numero=numero, vendedor=vendedor),
            html=html,
            text=_texto_plano(html),
            # Determinística: incluye la versión del documento, así que si el armado
            # cambia de forma el correo puede reenviarse sin chocar con el dedupe.
            idempotency_key=f"receipt:{tenant_id}:{receipt_id}:v{RECEIPT_DOC_VERSION}"[:256],
            # Quien vende es el tenant, aunque el correo salga de la plataforma. Ley 1480
            # art. 50 lit. a): el comprador tiene que poder llegar al vendedor.
            reply_to=responder_a,
        )
    except Exception as exc:
        logger.error("[COMPROBANTE][EMAIL] fallo enviando %s: %s", numero, exc)
        return False
