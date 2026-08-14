"""Plantillas de email transaccional (extraído de routers/wompi_webhook.py — G12).

Funciones PURAS de composición (string in/out, sin I/O ni estado). Las consume
`routers/wompi_webhook.py` (confirmaciones de pago, guías, estados de envío,
reembolsos). Extraídas verbatim 2026-08-13 — comportamiento idéntico.
"""
import re


def _mask_email(email: str) -> str:
    """Enmascara el local-part para logs (Habeas Data — coherente con el
    hasheo de teléfonos del resto de la plataforma). Conserva el dominio,
    útil para diagnosticar deliverability por proveedor."""
    e = (email or "").strip()
    local, sep, domain = e.partition("@")
    if not sep:
        return "***"
    head = local[:2]
    return f"{head}{'*' * max(1, len(local) - len(head))}@{domain}"


def _html_to_text(html: str) -> str:
    """Deriva un cuerpo text/plain mínimo del HTML (mejor scoring anti-spam;
    Resend recomienda multipart). Best-effort: strip de tags + colapso de
    espacios. No pretende fidelidad tipográfica."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|tr|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _fmt_cop(value: int) -> str:
    """Formato COP estilo WhatsApp del bot: $18.000 (punto miles)."""
    return f"${value:,.0f}".replace(",", ".")


def _compose_payment_email_html(
    *,
    customer_name: str,
    order_short: str,
    items: list,
    subtotal: int,
    shipping: int,
    total: int,
    carrier: str,
    tenant_name: str,
    tracking_number: str = "",
    tracking_url: str = "",
    label_url: str = "",
    shipment_status: str = "",
) -> str:
    """HTML inline-styled (compatibilidad clientes email).

    Si la guía Aveonline se generó OK (paso 7.5 wompi_webhook), incluye
    sección tracking con número, carrier, link PDF guía + sticker label.
    Si guía aún no generada → sección omitida (mensaje "te avisaremos").
    """
    rows = []
    for it in items:
        qty = int(it.get("quantity") or 1)
        title = str(it.get("title") or "Producto")
        unit_price = int(float(it.get("unit_price") or 0))
        line_total = unit_price * qty
        rows.append(
            f'<tr>'
            f'<td style="padding:8px 0;border-bottom:1px solid #f0f0f0">'
            f'{qty}× {title}</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid #f0f0f0;'
            f'text-align:right">{_fmt_cop(line_total)} COP</td>'
            f'</tr>'
        )
    items_html = "".join(rows) or '<tr><td colspan="2">(sin detalle de items)</td></tr>'
    ship_label = f"Envío ({carrier})" if carrier else "Envío"

    # Sección tracking — solo si hay número de guía válido.
    tracking_html = ""
    if tracking_number:
        is_simulated = (shipment_status or "").lower() == "simulated"
        sim_tag = (
            ' <span style="background:#fff3cd;color:#856404;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:600">SIMULADA</span>'
            if is_simulated else ""
        )
        track_btn = (
            f'<a href="{tracking_url}" style="display:inline-block;background:#2c3e50;'
            f'color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;'
            f'font-weight:600;margin-right:8px">🚚 Rastrear envío</a>'
            if tracking_url else ""
        )
        label_btn = (
            f'<a href="{label_url}" style="display:inline-block;background:#fff;'
            f'color:#2c3e50;padding:10px 18px;border-radius:6px;text-decoration:none;'
            f'font-weight:600;border:1px solid #2c3e50">📄 Descargar guía PDF</a>'
            if label_url else ""
        )
        tracking_html = f"""
  <div style="background:#f8f9fa;border-radius:8px;padding:16px 20px;margin:20px 0">
    <h3 style="margin:0 0 12px;font-size:16px;color:#2c3e50">📦 Información de envío{sim_tag}</h3>
    <p style="margin:0 0 8px;font-size:14px"><strong>Transportadora:</strong> {carrier or '—'}</p>
    <p style="margin:0 0 12px;font-size:14px"><strong>Número de guía:</strong>
      <span style="font-family:monospace;background:#fff;padding:2px 6px;
            border-radius:4px;border:1px solid #e8eef2">{tracking_number}</span>
    </p>
    {track_btn}{label_btn}
  </div>"""

    next_step_html = (
        '<p style="margin:24px 0 8px;color:#5a6772">'
        'Tu pedido ya tiene guía generada. Hacemos seguimiento y te '
        'avisaremos en cada cambio de estado del envío.</p>'
        if tracking_number else
        '<p style="margin:24px 0 8px;color:#5a6772">'
        'Tu pedido ya está en preparación. Te avisaremos cuando '
        'despache con tu número de guía.</p>'
    )

    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">Pago confirmado, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Gracias por tu compra en <strong>{tenant_name or 'nuestra tienda'}</strong>.
    Aquí tienes el detalle de tu pedido <strong>#{order_short}</strong>.
  </p>

  <table style="width:100%;border-collapse:collapse;margin:16px 0">
    <thead>
      <tr><th style="text-align:left;padding:8px 0;border-bottom:2px solid #2c3e50">Producto</th>
          <th style="text-align:right;padding:8px 0;border-bottom:2px solid #2c3e50">Total</th></tr>
    </thead>
    <tbody>{items_html}</tbody>
    <tfoot>
      <tr><td style="padding:8px 0">Subtotal</td>
          <td style="text-align:right">{_fmt_cop(subtotal)} COP</td></tr>
      <tr><td style="padding:4px 0">{ship_label}</td>
          <td style="text-align:right">{_fmt_cop(shipping)} COP</td></tr>
      <tr><td style="padding:12px 0;font-weight:bold;border-top:2px solid #2c3e50">Total</td>
          <td style="text-align:right;padding:12px 0;font-weight:bold;border-top:2px solid #2c3e50">
            {_fmt_cop(total)} COP</td></tr>
    </tfoot>
  </table>
{tracking_html}
  {next_step_html}

  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Recibiste este email porque pagaste un pedido. Si no fuiste tú,
    contacta al vendedor inmediatamente.
  </p>
</div>
</body></html>"""


def _compose_payment_failed_email_html(
    *,
    customer_name: str,
    order_short: str,
    items: list,
    subtotal: int,
    shipping: int,
    total: int,
    carrier: str,
    tenant_name: str,
) -> str:
    """Rev. 109 BRECHA — email cuando Wompi rechaza pago.

    Copy empático sin culpar al cliente. Invita a reintentar y aclara
    que el pedido SIGUE reservado (stock liberado pero podrá reintentarse
    si genera nuevo link). Diseño consistente con _compose_payment_email_html
    (colores tenants + tipografía).
    """
    # Rev. 109 fix bug founder UAT: usar _fmt_cop (NO divide /100) + 'unit_price'
    # (no 'unit_price_cents'). order_items.unit_price y orders.total_amount /
    # shipping_cost están en PESOS, no cents. Consistencia con
    # _compose_payment_email_html existente.
    items_rows = "".join(
        f"""<tr>
          <td style="padding:8px 4px;color:#1f2937;border-bottom:1px solid #e5e7eb;">
            {int(it.get('quantity') or 1)}× {it.get('title', 'Producto')}
          </td>
          <td style="padding:8px 4px;color:#6b7280;text-align:right;
                     border-bottom:1px solid #e5e7eb;">
            {_fmt_cop(int(float(it.get('unit_price') or 0)) * int(it.get('quantity') or 1))} COP
          </td>
        </tr>"""
        for it in (items or [])
    )

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>Pago no procesado</title></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,
             BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:560px;margin:0 auto;padding:32px 24px;background:#fff;">
  <h1 style="color:#b45309;font-size:22px;margin:0 0 16px;">
    Hola {customer_name},
  </h1>
  <p style="color:#374151;font-size:15px;line-height:1.6;margin:0 0 16px;">
    Tu pago del <strong>Pedido #{order_short}</strong> de
    <strong>{tenant_name}</strong> no se procesó esta vez.
  </p>
  <p style="color:#6b7280;font-size:14px;line-height:1.6;margin:0 0 20px;">
    Puede ser por validación bancaria, saldo insuficiente o un error
    momentáneo. No te preocupes — tu pedido queda registrado para que
    puedas reintentarlo sin perder los datos.
  </p>

  <div style="background:#fef3c7;padding:14px 16px;border-radius:6px;
              border-left:3px solid #f59e0b;margin:20px 0;">
    <strong style="color:#92400e;">¿Qué hacer ahora?</strong><br/>
    <span style="color:#78350f;font-size:14px;">
      Revisa tu WhatsApp: allí seguimos el proceso para completar tu pago.
      Si necesitas ayuda o no recibes un nuevo mensaje, responde a ese chat
      y un especialista de nuestro equipo te asiste.
    </span>
  </div>

  <h3 style="color:#1f2937;font-size:16px;margin:24px 0 8px;">
    Resumen del pedido
  </h3>
  <table width="100%" cellspacing="0" cellpadding="0"
         style="border-collapse:collapse;">
    {items_rows}
    <tr>
      <td style="padding:8px 4px;color:#6b7280;">Subtotal</td>
      <td style="padding:8px 4px;color:#6b7280;text-align:right;">
        {_fmt_cop(subtotal)} COP</td>
    </tr>
    <tr>
      <td style="padding:8px 4px;color:#6b7280;">Envío ({carrier or '-'})</td>
      <td style="padding:8px 4px;color:#6b7280;text-align:right;">
        {_fmt_cop(shipping)} COP</td>
    </tr>
    <tr>
      <td style="padding:12px 4px;color:#1f2937;font-weight:600;
                 border-top:2px solid #e5e7eb;">Total a pagar</td>
      <td style="padding:12px 4px;color:#1f2937;font-weight:600;
                 text-align:right;border-top:2px solid #e5e7eb;">
        {_fmt_cop(total)} COP</td>
    </tr>
  </table>

  <p style="color:#9ca3af;font-size:12px;margin:32px 0 0;text-align:center;">
    Este es un correo automático de <strong>{tenant_name}</strong>.<br/>
    Para soporte, responde por WhatsApp.
  </p>
</div>
</body></html>"""


def _compose_shipment_label_ready_email_html(
    *,
    customer_name: str,
    order_short: str,
    items: list,
    subtotal: int,
    shipping: int,
    total: int,
    carrier: str,
    tenant_name: str,
    tracking_number: str,
    tracking_url: str,
    label_url: str,
    shipment_status: str,
) -> str:
    """Email etapa 2 (post-guía generada): "Guía generada — saldrá pronto".

    Rev. 108 — el copy ya NO promete "envío en camino". La guía generada
    solo significa que el courier asignó tracking; el despacho físico
    ocurre cuando el courier recoja el paquete (estado EN RUTA reportado
    vía webhook). Hasta entonces, mensaje preciso: "lista para despacho".
    """
    is_simulated = (shipment_status or "").lower() == "simulated"
    sim_tag = (
        ' <span style="background:#fff3cd;color:#856404;padding:2px 8px;'
        'border-radius:4px;font-size:11px;font-weight:600">SIMULADA</span>'
        if is_simulated else ""
    )
    carrier_str = (carrier or "tu transportadora").strip()
    track_btn = (
        f'<a href="{tracking_url}" style="display:inline-block;background:#2c3e50;'
        f'color:#fff;padding:12px 22px;border-radius:6px;text-decoration:none;'
        f'font-weight:600;margin-right:8px;margin-bottom:8px">🔍 Rastrear envío</a>'
        if tracking_url else ""
    )
    label_btn = (
        f'<a href="{label_url}" style="display:inline-block;background:#fff;'
        f'color:#2c3e50;padding:12px 22px;border-radius:6px;text-decoration:none;'
        f'font-weight:600;border:1px solid #2c3e50;margin-bottom:8px">📄 Descargar guía PDF</a>'
        if label_url else ""
    )
    rows = []
    for it in items:
        qty = int(it.get("quantity") or 1)
        title = str(it.get("title") or "Producto")
        rows.append(
            f'<li style="margin:4px 0;color:#5a6772">{qty}× {title}</li>'
        )
    items_html = "".join(rows) or "<li>(sin detalle)</li>"

    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">📋 Guía asignada, {customer_name}{sim_tag}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu pedido <strong>#{order_short}</strong> en <strong>{tenant_name or 'nuestra tienda'}</strong>
    ya tiene número de guía. El courier lo recogerá pronto y te avisaré
    aquí cuando salga en ruta.
  </p>

  <div style="background:#f8f9fa;border-radius:8px;padding:20px;margin:24px 0">
    <p style="margin:0 0 8px;font-size:14px"><strong>Transportadora:</strong> {carrier_str}</p>
    <p style="margin:0 0 16px;font-size:14px"><strong>Número de guía:</strong>
      <span style="font-family:monospace;background:#fff;padding:3px 8px;
            border-radius:4px;border:1px solid #e8eef2;font-size:15px">{tracking_number}</span>
    </p>
    {track_btn}{label_btn}
  </div>

  <p style="margin:24px 0 8px;color:#5a6772;font-size:13px">
    <strong>Resumen del pedido:</strong>
  </p>
  <ul style="margin:0;padding-left:20px;font-size:13px">{items_html}</ul>
  <p style="margin:8px 0 0;color:#9aa4ad;font-size:12px">
    Total pagado: <strong>{_fmt_cop(total)} COP</strong> (envío {_fmt_cop(shipping)} COP incluido)
  </p>

  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Cualquier inquietud, responde a este email o escríbenos por WhatsApp.
    ¡Gracias por tu compra!
  </p>
</div>
</body></html>"""


def _compose_shipment_in_transit_email_html(
    *,
    customer_name: str,
    order_short: str,
    carrier: str,
    tenant_name: str,
    tracking_number: str,
    tracking_url: str,
    raw_status: str = "",
) -> str:
    """Email etapa 3 (post-webhook EN RUTA): envío físicamente despachado."""
    carrier_str = (carrier or "el courier").strip()
    track_btn = (
        f'<a href="{tracking_url}" style="display:inline-block;background:#2c3e50;'
        f'color:#fff;padding:12px 22px;border-radius:6px;text-decoration:none;'
        f'font-weight:600">🔍 Rastrear envío</a>'
        if tracking_url else ""
    )
    status_line = (
        f'<p style="margin:0 0 8px;color:#5a6772;font-size:13px">'
        f'Estado actual: <strong>{raw_status}</strong></p>'
        if raw_status else ""
    )
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">🚚 Tu envío salió en ruta, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu pedido <strong>#{order_short}</strong> de <strong>{tenant_name or 'nuestra tienda'}</strong>
    ya está en camino con <strong>{carrier_str}</strong>.
  </p>
  <div style="background:#f8f9fa;border-radius:8px;padding:20px;margin:24px 0">
    {status_line}
    <p style="margin:0 0 16px;font-size:14px"><strong>Guía:</strong>
      <span style="font-family:monospace;background:#fff;padding:3px 8px;
            border-radius:4px;border:1px solid #e8eef2;font-size:15px">{tracking_number}</span>
    </p>
    {track_btn}
  </div>
  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Te avisaré aquí mismo cuando el courier confirme la entrega.
  </p>
</div>
</body></html>"""


def _compose_shipment_delivered_email_html(
    *,
    customer_name: str,
    order_short: str,
    carrier: str,
    tenant_name: str,
    tracking_number: str,
) -> str:
    """Email etapa 4 (post-webhook ENTREGADA): pedido entregado."""
    carrier_str = (carrier or "el courier").strip()
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">📬 Pedido entregado, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu pedido <strong>#{order_short}</strong> de <strong>{tenant_name or 'nuestra tienda'}</strong>
    fue entregado vía <strong>{carrier_str}</strong> (guía <code>{tracking_number}</code>).
  </p>
  <p style="margin:16px 0;color:#2c3e50;font-size:15px">
    ¿Todo llegó perfecto? Cuéntanos respondiendo a este email — tu opinión
    nos ayuda a mejorar.
  </p>
  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    ¡Gracias por confiar en nosotros! 💛
  </p>
</div>
</body></html>"""


def _compose_shipment_exception_email_html(
    *,
    customer_name: str,
    order_short: str,
    carrier: str,
    tenant_name: str,
    tracking_number: str,
    raw_status: str = "",
) -> str:
    """Email etapa novedad: alerta + invitación a contactar."""
    carrier_str = (carrier or "el courier").strip()
    reason_line = (
        f'<p style="margin:0 0 8px;font-size:14px">'
        f'<strong>Motivo reportado:</strong> {raw_status}</p>'
        if raw_status else ""
    )
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px">⚠️ Novedad con tu envío, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu pedido <strong>#{order_short}</strong> tuvo un inconveniente con
    <strong>{carrier_str}</strong>.
  </p>
  <div style="background:#fff8e1;border-radius:8px;padding:20px;margin:24px 0;border:1px solid #ffe082">
    {reason_line}
    <p style="margin:0;font-size:14px"><strong>Guía:</strong>
      <span style="font-family:monospace;background:#fff;padding:3px 8px;
            border-radius:4px;border:1px solid #e8eef2;font-size:15px">{tracking_number}</span>
    </p>
  </div>
  <p style="margin:16px 0;color:#2c3e50;font-size:14px">
    Ya estamos revisando con la transportadora. Si tienes información
    relevante (dirección alterna, horario disponible) responde a este
    email o por WhatsApp para acelerar la solución.
  </p>
</div>
</body></html>"""


def _compose_refund_completed_email_html(
    *,
    customer_name: str,
    order_short: str,
    total: int,
    tenant_name: str,
) -> str:
    """Rev. 112 GAP — confirmación de reembolso (VOIDED en Wompi).

    Extraído del dispatcher a composer para paridad estructural con los
    demás templates. Usa `_fmt_cop` (pesos, no cents) y la misma tipografía
    Arial/#2c3e50 del resto del ciclo de vida.
    """
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#2c3e50">
<div style="max-width:600px;margin:0 auto;background:#fff;padding:32px 24px">
  <h2 style="margin:0 0 8px;font-size:22px;color:#059669">✅ Reembolso confirmado, {customer_name}</h2>
  <p style="margin:0 0 16px;color:#5a6772">
    Tu reembolso de <strong>{_fmt_cop(total)} COP</strong> del pedido
    <strong>#{order_short}</strong> ya fue procesado por Wompi y enviado
    al sistema bancario.
  </p>
  <p style="margin:0 0 16px;color:#5a6772">
    El dinero aparecerá en tu tarjeta en <strong>1-2 días hábiles</strong>
    típicos. Puede tardar más según tu banco emisor.
  </p>
  <p style="margin:24px 0 0;color:#9aa4ad;font-size:12px;border-top:1px solid #e8eef2;padding-top:16px">
    Si en 7 días no lo ves reflejado, escríbenos y te ayudamos a rastrearlo
    con Wompi.<br/>— {tenant_name or 'nuestra tienda'}
  </p>
</div>
</body></html>"""
