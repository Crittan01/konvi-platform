"""Formato de respuestas y secciones de contexto del orquestador (extraído de
orchestrator.py — G12). Builders de texto/secciones para el prompt y el
post-proceso de respuesta WhatsApp. Funciones cerradas internamente (0 llamadas
a otras partes del orchestrator). Extraído verbatim 2026-08-13 — comportamiento
idéntico; orchestrator.py los re-importa a su namespace.
"""
import logging
import re
from typing import Any, Optional

from supabase import Client  # anotaciones runtime (sin __future__ annotations)

from fsm.address import (  # helpers de dirección (usados por _format_address_for_summary)
    normalize_building_type as _normalize_building_type,
    normalize_conjunto_type as _normalize_conjunto_type,
)
from text_utils import format_cents_cop as _format_cop, normalize_text as _normalize_text

_BOLD_KB_PATTERNS: list[str] = [
    # Plazos específicos primero (más largos = más específicos).
    # IMPORTANTE: NO incluir un patrón genérico "\d+\s*días" porque
    # solaparía con "X días calendario / hábiles" causando doble-bold.
    r"\d+\s*d[ií]as\s+calendario",
    r"\d+\s*d[ií]as\s+h[áa]biles",
    r"\d+\s*horas?\s+(?:h[áa]biles|calendario)",
    # Términos contractuales/legales recurrentes.
    r"sin\s+usar",
    r"empaque\s+original",
    r"perfectas?\s+condiciones?",
    r"producto\s+defectuoso",
    r"ofertas?\s+especiales?",
    r"contacto\s+con\s+la\s+piel",
    r"n[úu]mero\s+de\s+pedido",
]

logger = logging.getLogger(__name__)

_PRESENTATION_MARKERS = (
    "lo tenemos en", "tenemos las siguientes", "presentaciones",
    "presentacion", "tamanos disponibles", "tamaños disponibles",
    "estos tamanos", "estos tamaños", "viene en", "disponible en",
    "estas presentaciones", "te puedo ofrecer",
)

_DAY_LABELS_ES_ISO = {1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom"}

_KB_CITE_RE = re.compile(r"_Fuente:\s*([^\n_]+?)_")

_KB_CITE_CTA = (
    "Si quieres que te amplíe algún punto o que te envíe el documento "
    "completo, házmelo saber."
)

_CATEGORY_HEADER_RE = re.compile(r"^\*[^*\n]+:\*\s*$")

_BULLET_LINE_RE = re.compile(r"^\* (?!_Entre otros)\S")

_TRUNCATED_MARKER = "* _Entre otros..._"

_MARKETING_CITE = (
    "> _Tenemos muchas más referencias para ti — pregúntame por la "
    "que te interese._ "
)


def _mask_value(value: Optional[str]) -> str:
    """Mask sensible value, mostrando solo primeros 2 + últimos 4 chars."""
    if not value:
        return "(no registrado)"
    s = str(value)
    if len(s) <= 6:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 6) + s[-4:]


def _build_customer_data_summary(
    supabase: Client, contact_id: str, tenant_id: str
) -> str:
    """Rev. 97 — Resumen de datos del titular para envío vía WhatsApp.

    Output text-only (PDF + Meta document upload diferido a follow-up).
    Incluye campos PII enmascarados parcialmente para que el cliente
    confirme qué datos tenemos sin exponer doc completo en chat.
    """
    try:
        c_res = supabase.table("contacts").select(
            "name, email, phone, document_type, document_number, address, "
            "consent_given, consent_given_at, consent_revoked_at"
        ).eq("id", contact_id).eq("tenant_id", tenant_id).limit(1).execute()
        if not c_res.data:
            return (
                "No tenemos registros tuyos en el sistema. "
                "Si crees que esto es un error, escríbenos al correo "
                "soporte para ayudarte."
            )
        c = c_res.data[0]

        # Conteo de orders.
        orders_count = 0
        try:
            o_res = supabase.table("orders").select(
                "id", count="exact",
            ).eq("contact_id", contact_id).eq("tenant_id", tenant_id).execute()
            orders_count = int(getattr(o_res, "count", 0) or 0)
        except Exception:
            pass

        consent_status = "Activo" if c.get("consent_given") else "Revocado"

        lines = [
            "*Resumen de tus datos personales*",
            "",
            f"• Nombre: {c.get('name') or '(no registrado)'}",
            f"• Email: {c.get('email') or '(no registrado)'}",
            f"• Teléfono: {_mask_value(c.get('phone'))}",
            f"• Documento: {c.get('document_type') or '?'} {_mask_value(c.get('document_number'))}",
            f"• Dirección: {'(registrada)' if c.get('address') else '(no registrada)'}",
            "",
            f"• Consentimiento: {consent_status}",
            f"• Pedidos asociados: {orders_count}",
            "",
            "Si quieres el reporte completo en formato JSON, escríbele al "
            "tenant pidiéndolo formalmente (Habeas Data Art. 14 Ley 1581/2012). "
            "Si quieres eliminar tus datos, responde *elimina mis datos*.",
        ]
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("[SAR] Error generando summary contact=%s: %s", contact_id, exc)
        return (
            "Tu solicitud quedó registrada. En 24-48h te enviaremos el "
            "reporte completo de los datos que guardamos sobre ti "
            "(Habeas Data Ley 1581/2012)."
        )


def _last_outbound_presented_variants_all(
    catalog: list, history: list[dict],
) -> list[dict]:
    """Rev. 104 (Bug-C runtime) — devuelve TODOS los productos cuyas
    variantes fueron presentadas en el último outbound del bot.

    Mejora sobre la versión singular: cuando el bot lista variantes de
    múltiples productos en un solo outbound (ej. "Coco: 60g/100g/150g.
    Sérum: 15ml/30ml"), debemos considerar AMBOS como candidatos para
    resolver el variant que el cliente elija a continuación. El caller
    itera hasta encontrar un match.

    Match plural-tolerante: usa los tokens discriminativos del título
    (no substring exacto). "Jabones Artesanales de Coco" matchea el
    producto "Jabón Artesanal de Coco" porque comparten {coco, jabon,
    artesanal} (los plurales se resuelven por prefijo de 4-5 chars).

    Retorna `[]` si:
      • No hay outbound previo
      • El outbound no muestra signos de listado de variantes (sin marker
        ni bullets numéricos suficientes)
      • Ningún producto del catálogo matchea por discriminativos
    """
    if not catalog or not history:
        return []
    for msg in reversed(history):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        if not content:
            return []
        content_norm = _normalize_text(content)
        has_marker = any(m in content_norm for m in _PRESENTATION_MARKERS)
        bullet_attrs = re.findall(
            r"[\*•\-]\s*(\d+)\s*(?:g|gr|gramos|ml|cc|mililitros|kg|oz)\b",
            content_norm,
            re.IGNORECASE,
        )
        if not (has_marker or len(bullet_attrs) >= 2):
            return []
        content_tokens = set(re.findall(r"[a-z0-9ñ]+", content_norm))
        results: list[dict] = []
        _stop = {"de", "con", "y", "o", "la", "el", "los", "las",
                 "un", "una", "para", "por"}
        for prod in catalog:
            title = str(prod.get("title") or "").strip()
            if not title:
                continue
            title_norm = _normalize_text(title)
            title_tokens = (
                set(re.findall(r"[a-z0-9ñ]+", title_norm)) - _stop
            )
            if not title_tokens:
                continue
            # Match laxo plural-tolerante: cada token discriminativo del
            # título debe aparecer en el contenido EXACTO o como prefijo
            # ≥4 chars de algún token del contenido.
            def _match_token(tw: str) -> bool:
                if tw in content_tokens:
                    return True
                if len(tw) < 4:
                    return False
                # Prefijo: el token del contenido empieza con el del título
                # (cubre "jabones" matchea "jabon").
                return any(
                    ct.startswith(tw[:4]) and len(ct) >= 4
                    for ct in content_tokens
                )

            if all(_match_token(tw) for tw in title_tokens):
                results.append(prod)
        return results
    return []


def _format_phone_for_summary(phone: Optional[str]) -> str:
    """Formatea el celular para mostrar en el resumen.

    El celular se captura automáticamente del WhatsApp (no se pide por chat),
    pero se muestra para que el cliente confirme que es el correcto antes
    de generar el link de pago. Envía y Wompi requieren este dato.
    """
    if not phone:
        return ""
    # Defensivo: rechazar cadenas como "null" / "none" / "undefined" que
    # pueden colarse desde JSON parseado o coerción str(None) en algún path.
    phone_str = str(phone).strip().lower()
    if phone_str in ("null", "none", "undefined", ""):
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if not digits:
        return ""
    if digits.startswith("57") and len(digits) == 12:
        return f"+57 {digits[2:5]} {digits[5:8]} {digits[8:]}"
    if len(digits) == 10:
        return f"+57 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return f"+{digits}" if not str(phone).startswith("+") else str(phone)


def _format_address_for_summary(address: Optional[dict]) -> str:
    """Renderiza la dirección persistida en una sola línea legible para el resumen.

    Sem 7 F2 cierre 2026-05-19 (Opción 1 SIMPLIFY) — render condicional según
    `building_type`:
      • casa → solo street + barrio + city.
      • edificio → + "Piso X" (si floor) + "Apto Y".
      • conjunto torres → + complex + "Torre X" + "Apto Y".
      • conjunto casas → + complex + "Casa #Y" (sin torre).
      • oficina → + "Piso X" (si floor) + "Oficina Y" + "(Empresa: Z)" si company_name.
    """
    if not isinstance(address, dict):
        return ""
    parts: list[str] = []
    street = str(address.get("street") or "").strip()
    if street:
        parts.append(street)
    btype = _normalize_building_type(address.get("building_type"))
    ctype = _normalize_conjunto_type(address.get("conjunto_type"))
    floor = str(address.get("floor") or "").strip()
    company = str(address.get("company_name") or "").strip()

    sub_parts: list[str] = []
    if btype == "conjunto":
        tower = str(address.get("tower") or "").strip()
        apt = str(address.get("apartment") or "").strip()
        complex_name = str(address.get("complex_name") or "").strip()
        if complex_name:
            sub_parts.append(complex_name)
        if ctype == "casas":
            # Sem 7 F2 cierre 2026-05-20 (D4) — manzana opcional en
            # conjunto de casas. Reusa `tower` semánticamente como
            # "Manzana / Bloque". Sin migración de schema.
            if tower:
                _tlow = tower.lower()
                if _tlow.startswith("manzana") or _tlow.startswith("bloque"):
                    sub_parts.append(tower)
                else:
                    sub_parts.append(f"Manzana {tower}")
            if apt:
                sub_parts.append(f"Casa #{apt}")
        else:
            if tower:
                sub_parts.append(f"Torre {tower}" if not tower.lower().startswith("torre") else tower)
            if apt:
                sub_parts.append(f"Apto {apt}")
    elif btype == "edificio":
        apt = str(address.get("apartment") or "").strip()
        complex_name = str(address.get("complex_name") or "").strip()
        if complex_name:
            sub_parts.append(complex_name)
        if floor:
            sub_parts.append(f"Piso {floor}")
        if apt:
            sub_parts.append(f"Apto {apt}")
    elif btype == "oficina":
        apt = str(address.get("apartment") or "").strip()
        if floor:
            sub_parts.append(f"Piso {floor}")
        if apt:
            sub_parts.append(f"Oficina {apt}")
    if sub_parts:
        parts.append(", ".join(sub_parts))
    neighborhood = str(address.get("neighborhood") or "").strip()
    if neighborhood:
        parts.append(neighborhood)
    city = str(address.get("city") or "").strip()
    if city:
        parts.append(city)

    base = " — ".join(parts)
    if btype == "oficina" and company:
        return f"{base} _(Empresa: {company})_"
    return base


def _verified_ctx_from_cart(cart: dict) -> Optional[dict]:
    """Rev. 80: convierte el cart en DB (output de cart_tool.get_cart_with_items)
    al schema de verified_ctx que espera _build_order_summary_text.

    Rev. 103 — `requires_requote=True` (set por add_item/remove_item) NO
    invalida el cart como fuente de verdad de ITEMS. Solo significa que
    `cart.shipping_cents` está stale — el caller debe extraer el shipping
    actual desde history. Antes (rev. 80) retornaba None y el caller
    caía a inferencia desde history truncado → alucinación de productos.
    Razón: cart-as-SoT debe mantenerse independiente del estado
    shipping; los items son verdad incluso si el envío necesita re-quote.

    Devuelve None solo si cart vacío.
    """
    if not cart:
        return None
    items = cart.get("items") or []
    if not items:
        return None
    subtotal = int(cart.get("subtotal_cents") or 0)
    # Rev. 103 — si requires_requote, ignorar shipping del cart (se
    # extrae de history en caller). Items y subtotal SIEMPRE válidos.
    if cart.get("requires_requote"):
        shipping = 0
    else:
        shipping = int(cart.get("shipping_cents") or 0)
    total = int(cart.get("total_cents") or (subtotal + shipping))
    out_items = []
    for it in items:
        v = it.get("variation") or {}
        p = it.get("product") or {}
        title = p.get("title") or p.get("name") or "Producto"
        variant_label = v.get("label") or v.get("presentation") or ""
        out_items.append({
            "variation_id": it.get("variation_id"),
            "product_id": it.get("product_id"),
            "title": title,
            "variant_label": variant_label,
            "quantity": int(it.get("quantity") or 1),
            "unit_price_cents": int(it.get("unit_price_cents") or 0),
        })
    # Sem 6 I.2.7 — propagar cupón aplicado para que el resumen lo muestre.
    coupon_code = cart.get("coupon_code")
    discount_cents = int(cart.get("discount_cents") or 0)
    return {
        "items": out_items,
        "subtotal_cents": subtotal,
        "shipping_cost_cents": shipping,
        "total_cents": total,
        "coupon_code": coupon_code,
        "discount_cents": discount_cents,
        "_source": "cart_db",
    }


def _build_order_summary_text(
    *,
    contact_record: dict,
    verified_ctx: Optional[dict],
    catalog: Optional[list] = None,
    history: Optional[list[dict]] = None,
    cart_from_db: Optional[dict] = None,
    supabase: Any = None,
    tenant_id: Optional[str] = None,
) -> Optional[str]:
    """Resumen estructurado determinístico antes de la confirmación final.

    Rev. 80 — Prioridad de fuentes:
      1. cart_from_db (DB SoT) si tiene items y NO requiere recotización.
      2. verified_ctx provisto por el caller.
      3. Fallback: history-parsing (DEPRECATED rev. 80, queda como red de
         seguridad cuando el cart-en-DB no está disponible).

    Si no hay contexto verificable retorna None y dejamos que el LLM
    componga el mensaje (degradación segura).
    """
    if not verified_ctx and cart_from_db:
        verified_ctx = _verified_ctx_from_cart(cart_from_db)
        # Rev. 103 — si cart tiene items pero shipping=0 (requires_requote),
        # extraer shipping del history para no mostrar "Envío: $0".
        if verified_ctx and not verified_ctx.get("shipping_cost_cents"):
            _ship_hist = _extract_shipping_cost_from_history(history or []) or 0
            if _ship_hist > 0:
                verified_ctx["shipping_cost_cents"] = _ship_hist
                verified_ctx["total_cents"] = (
                    int(verified_ctx.get("subtotal_cents") or 0) + _ship_hist
                )
    if not verified_ctx:
        # Rev. 103 — fallback eliminado. Si no hay cart real, retornar None
        # para que el LLM componga (con LIE_PHRASES guard) en vez de
        # inventar productos del catálogo. El populate-on-demand fue
        # source of hallucinations (caso real conv 32e0397e: cliente pidió
        # Coco 60g → orden con "Aceite Esencial de Árbol de Té").
        return None
    if not verified_ctx.get("total_cents"):
        return None

    items = verified_ctx.get("items")
    lines: list[str] = ["📋 *Resumen de tu pedido:*", ""]
    if isinstance(items, list) and items:
        lines.append("*Productos:*")
        for it in items:
            qty = int(it.get("quantity") or 1)
            title = str(it.get("title") or "Producto").strip()
            variant = str(it.get("variant_label") or "").strip()
            line_total = int(it.get("unit_price_cents") or 0) * qty
            label = f"• {qty}x {title}"
            if variant and variant.lower() not in {"estandar", "estándar"}:
                label += f" ({variant})"
            label += f": {_format_cop(line_total)}"
            lines.append(label)
    else:
        title = str(verified_ctx.get("product_name") or "Producto")
        variant = str(verified_ctx.get("variant_label") or "").strip()
        qty = int(verified_ctx.get("quantity") or 1)
        line_total = int(verified_ctx.get("unit_price_cents") or 0) * qty
        label = f"• {qty}x {title}"
        if variant and variant.lower() not in {"estandar", "estándar"}:
            label += f" ({variant})"
        label += f": {_format_cop(line_total)}"
        lines.append("*Productos:*")
        lines.append(label)

    subtotal = int(verified_ctx.get("subtotal_cents") or 0)
    shipping = int(verified_ctx.get("shipping_cost_cents") or 0)
    total = int(verified_ctx.get("total_cents") or 0)
    # Sem 6 I.2.7 (ADR-0015) — descuento de cupón.
    discount = int(verified_ctx.get("discount_cents") or 0)
    coupon_code = verified_ctx.get("coupon_code")
    lines.append("")
    lines.append(f"Subtotal: {_format_cop(subtotal)}")
    # Rev. 103 — incluir carrier en línea de envío para que el cliente
    # vea qué transportadora cotizó (Económica = default cuando dice
    # "sigamos" sin elegir explícitamente).
    #
    # Sem 7 F2 cierre 2026-05-20 — Bug P9 founder UAT (conv 7053666a):
    # En conversaciones largas (≥25 msgs), el outbound de cotización queda
    # FUERA del window de history → extractor retorna None → resumen
    # muestra "Envío: $X" sin carrier (regresión visual).
    # Fix: usar `cart_from_db.shipping_meta.carrier` como FUENTE PRIMARIA
    # (cart-as-SoT, ADR-0011) y caer a history solo si DB no tiene.
    carrier_name: Optional[str] = None
    if isinstance(cart_from_db, dict):
        _meta = cart_from_db.get("shipping_meta") or {}
        if isinstance(_meta, dict):
            _carrier_db = str(_meta.get("carrier") or "").strip()
            _service_db = str(_meta.get("service_level") or "").strip()
            if _carrier_db:
                # Componer "Coordinadora Ground" o "FedEx Express®" con
                # service_level si está disponible.
                carrier_name = (
                    f"{_carrier_db} {_service_db}".strip()
                    if _service_db else _carrier_db
                )
    if not carrier_name:
        carrier_name = _extract_shipping_carrier_from_history(history or [])
    if carrier_name and shipping > 0:
        lines.append(f"Envío (Económica - {carrier_name}): {_format_cop(shipping)}")
    else:
        lines.append(f"Envío: {_format_cop(shipping)}")
    if discount > 0 and coupon_code:
        lines.append(f"Descuento: -{_format_cop(discount)} ({coupon_code})")
    lines.append(f"*TOTAL: {_format_cop(total)}*")

    contact = contact_record if isinstance(contact_record, dict) else {}
    name = str(contact.get("name") or "").strip()
    email = str(contact.get("email") or "").strip()
    phone = _format_phone_for_summary(contact.get("phone"))
    # Rev. 103 — phone alternativo de envío. Solo se muestra si difiere
    # del WhatsApp (caso "compro para otra persona").
    shipping_phone_raw = contact.get("shipping_phone")
    shipping_phone = _format_phone_for_summary(shipping_phone_raw)
    has_alternate_phone = bool(shipping_phone) and shipping_phone != phone
    doc_t = str(contact.get("document_type") or "").strip().upper()
    doc_n = str(contact.get("document_number") or "").strip()
    address_line = _format_address_for_summary(contact.get("address"))

    if any([name, email, phone, doc_t and doc_n, address_line]):
        lines.append("")
        lines.append("*Datos de envío:*")
        if name:
            lines.append(f"• Nombre: {name}")
        if email:
            lines.append(f"• Correo: {email}")
        if phone:
            if has_alternate_phone:
                # Cliente dio shipping alternativo — diferenciar ambos.
                lines.append(f"• Celular (WhatsApp): {phone}")
                lines.append(f"• Celular (envío): *{shipping_phone}*")
            else:
                lines.append(f"• Celular: {phone}")
        if doc_t and doc_n:
            lines.append(f"• Documento: {doc_t} {doc_n}")
        if address_line:
            lines.append(f"• Dirección: {address_line}")

    # ── Rev. 108 holístico — texto adaptado a payment_method del cart ────
    # Si cart_from_db.payment_method == 'cod':
    #   • Mensaje "Pagas $X al recibir" en lugar de "link de pago"
    #   • Warning condicional si carrier.charges_return_fee=true (dossier
    #     §7.2: ENVIA y COORDINADORA cobran costo devolución).
    is_cod_order = False
    carrier_charges_return = False
    if isinstance(cart_from_db, dict):
        is_cod_order = (
            (cart_from_db.get("payment_method") or "credit").lower() == "cod"
        )
        if is_cod_order and carrier_name and supabase is not None and tenant_id:
            try:
                from lib.carrier_capabilities import (
                    get_effective_carrier_capability,
                )
                # carrier_name puede tener service_level concatenado;
                # extraer primer token (ej. "SERVIENTREGA Mensajería" → "SERVIENTREGA")
                _carrier_pure = (carrier_name.split() or [""])[0]
                _cap = get_effective_carrier_capability(
                    supabase,
                    tenant_id=tenant_id,
                    carrier_name=_carrier_pure,
                )
                carrier_charges_return = _cap.charges_return_fee
            except Exception:
                # Fallback: no warning — log silent.
                carrier_charges_return = False

    lines.append("")
    if is_cod_order:
        lines.append(f"💵 Pagarás *{_format_cop(total)}* en efectivo al recibir tu pedido.")
        if carrier_charges_return:
            lines.append("")
            _carrier_short = (carrier_name or "el courier").split()[0] if carrier_name else "el courier"
            lines.append(
                f"⚠️ *Aviso de devolución*: si rechazas el pedido al recibir, "
                f"{_carrier_short} cobra costo de devolución (a tu cargo, "
                f"~$5.000 estimado)."
            )
        lines.append("")
        lines.append("¿Confirmas tu pedido?")
    else:
        lines.append("¿Confirmas que los datos están correctos para generar tu link de pago?")
    return "\n".join(lines)


def _extract_shipping_cost_from_history(history: list[dict]) -> Optional[int]:
    """
    Extrae el costo de envío en centavos del último outbound de cotización en el historial.
    Busca patrones como '$12.000 COP', '$12,000', '12000'.
    Retorna None si no encuentra o no puede parsear.
    """
    _price_pattern = re.compile(r"\$\s*([\d.,]+)\s*(?:COP)?", re.IGNORECASE)
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        content_norm = _normalize_text(content)
        if "economica" not in content_norm and "rapida" not in content_norm:
            continue
        # Encontrado: extraer primer precio de la línea "Económica"
        for line in content.splitlines():
            if "Económica" in line or "Economica" in line or "economica" in _normalize_text(line):
                matches = _price_pattern.findall(line)
                for raw in matches:
                    cleaned = raw.replace(".", "").replace(",", "")
                    try:
                        value = int(cleaned)
                        if value >= 1000:  # mínimo $10 COP en centavos
                            return value * 100  # convertir pesos → centavos
                    except ValueError:
                        continue
    return None


def _extract_shipping_carrier_from_history(history: list[dict]) -> Optional[str]:
    """Rev. 103 — extrae el carrier de la opción Económica del último
    outbound de cotización. Caso real: el cliente que dice "sigamos" tras
    una cotización multi-opción defaultea a Económica; el resumen y el
    DB necesitan saber QUÉ carrier es para que la transportadora
    reciba la guía correcta.

    Formatos soportados (continúa buscando hacia atrás si el primer
    outbound con "Económica" no matchea — ej. carrier ack post-quote):
      • Cotización: "* *Económica*: Coordinadora Ground | $7.310 | ..."
      • Carrier ack: "voy con la opción *Económica* (Coordinadora Ground) por ..."
    Retorna ej. "Coordinadora Ground" o None.
    """
    _patterns = (
        # Cotización con `|` separators
        re.compile(r"(?:Económica|Economica)\*?:?\s*([^|]+?)\s*\|"),
        # Ack con paréntesis
        re.compile(r"(?:Económica|Economica)\*?\s*\(([^)]+)\)"),
    )
    for msg in reversed(history or []):
        if str(msg.get("direction") or "").lower() != "outbound":
            continue
        content = str(msg.get("content") or "")
        if "Económica" not in content and "Economica" not in content:
            continue
        for line in content.splitlines():
            if "Económica" not in line and "Economica" not in line:
                continue
            for pat in _patterns:
                m = pat.search(line)
                if m:
                    name = m.group(1).strip().strip("*").strip()
                    if name and 2 <= len(name) <= 60:
                        return name
        # No match en este outbound — sigue buscando hacia atrás (NO return None aquí).
    return None


def _format_support_schedule_text(schedule: Optional[dict]) -> str:
    """Deriva 'Lun a Vie de 09:00 a 18:00' desde support_schedule jsonb.
    Reemplaza el legacy `tenants.business_hours` (texto libre, sin estructura).

    Convención de días: ISO weekday 1=Lu..7=Do (alineada con DaysSelector UI
    y con `_is_outside_support_hours`). NO mezclar con 0-6 (Python weekday())."""
    if not schedule or not isinstance(schedule, dict):
        return ""
    raw_days = schedule.get("days") or []
    open_t   = (schedule.get("open") or "").strip()
    close_t  = (schedule.get("close") or "").strip()
    if not raw_days or not open_t or not close_t:
        return ""
    days = sorted({int(d) for d in raw_days if isinstance(d, (int, float)) and 1 <= int(d) <= 7})
    if not days:
        return ""
    # Si es bloque continuo (ej. Lu-Vi = [1,2,3,4,5]) → notación rango.
    is_contiguous = all(days[i] - days[i - 1] == 1 for i in range(1, len(days)))
    if is_contiguous and len(days) >= 2:
        labels = f"{_DAY_LABELS_ES_ISO[days[0]]} a {_DAY_LABELS_ES_ISO[days[-1]]}"
    else:
        labels = ", ".join(_DAY_LABELS_ES_ISO[d] for d in days)
    return f"{labels} de {open_t} a {close_t}"


def _build_store_info_section(
    tenant_name: str,
    store_type: str,
    shipping_origin: dict,
    social_links: dict,
    store_locations: list,
    support_schedule: Optional[dict] = None,
    mision: str = "",
    vision: str = "",
    valores: str = "",
    nit: str = "",
    email_contacto: str = "",
    telefono_contacto: str = "",
) -> str:
    """
    Construye la sección de información comercial del tenant para el system prompt.
    Adaptativa por tipo de tienda: fisica | virtual | fisica_virtual.
    Permite al bot responder sin escalar: ubicación, sedes, redes, horario.

    Rev. 71 — La columna legacy `business_hours` (texto libre) se eliminó del prompt.
    El horario textual ahora se deriva de `support_schedule` (jsonb) — fuente única.
    """
    has_fisica  = store_type in ("fisica", "fisica_virtual")
    has_virtual = store_type in ("virtual", "fisica_virtual")

    lines: list[str] = [f"\nSOBRE LA TIENDA — INFORMACIÓN COMERCIAL DE {tenant_name.upper()}:"]

    # Modo de operación explícito (rev. 71 — antes el bot lo inferia del shape)
    if has_fisica and has_virtual:
        lines.append("- Modo de operación: atención presencial en sedes y venta online.")
    elif has_virtual:
        lines.append("- Modo de operación: solo tienda virtual (sin sedes físicas al público).")
    elif has_fisica:
        lines.append("- Modo de operación: atención presencial en sedes (consulta horario).")

    if has_fisica:
        # Sedes públicas (atención al cliente). Diferentes conceptualmente del
        # origen de despacho (`shipping_origin`) — ver bloque dedicado abajo.
        sedes = [s for s in (store_locations or []) if s.get("city") or s.get("street")]
        if sedes:
            lines.append("- Sedes públicas de atención al cliente:")
            # Rev. 71 — sede con `is_primary=True` se rotula explícita y se ordena primero.
            primary = [s for s in sedes if s.get("is_primary")]
            others  = [s for s in sedes if not s.get("is_primary")]
            ordered = (primary + others) if primary else sedes
            for sede in ordered:
                sede_name = sede.get("name") or "Sede"
                if sede.get("is_primary"):
                    sede_name = f"{sede_name} (principal)"
                city      = sede.get("city", "")
                state     = sede.get("state", "")
                street    = sede.get("street", "")
                phone     = sede.get("phone", "")
                email     = sede.get("email", "")
                loc       = city
                if state and state != city:
                    loc += f", {state}"
                sede_line = f"  · {sede_name}: {street}{', ' + loc if loc else ''}" if street else f"  · {sede_name}: {loc}"
                if phone:
                    sede_line += f" | Tel: {phone}"
                if email:
                    sede_line += f" | Email: {email}"
                lines.append(sede_line)

    # Rev. 71 — Origen de despacho (`shipping_origin`): es la BODEGA operacional
    # desde donde sale Envia. NO es necesariamente pública — solo se entrega al
    # LLM la ciudad/estado para que pueda responder "despachamos desde Bogotá"
    # sin revelar la dirección exacta de la bodega (dato operacional sensible).
    ship_city  = (shipping_origin or {}).get("city", "")
    ship_state = (shipping_origin or {}).get("state", "")
    if ship_city:
        ship_loc = ship_city
        if ship_state and ship_state != ship_city:
            ship_loc += f", {ship_state}"
        lines.append(f"- Origen de despacho (bodega): {ship_loc}")

    active_social = {k: v for k, v in (social_links or {}).items() if v}
    if active_social:
        social_parts = ", ".join(f"{k.capitalize()}: {v}" for k, v in active_social.items())
        lines.append(f"- Redes y canales digitales: {social_parts}")

    horario_texto = _format_support_schedule_text(support_schedule)
    if horario_texto:
        lines.append(f"- Horario de atención: {horario_texto}")

    if mision:
        lines.append(f"- Misión: {mision}")
    if vision:
        lines.append(f"- Visión: {vision}")
    if valores:
        lines.append(f"- Valores: {valores}")

    # Rev. 71 — Identidad legal/contacto del negocio. Solo se entrega al LLM con
    # instrucción explícita de usarse SI EL CLIENTE PREGUNTA. Evita que el bot
    # ofrezca proactivamente NIT/email/teléfono (sería invasivo) pero permite
    # responder con verdad cuando lo piden ("¿cuál es su NIT?", "¿correo?").
    identidad_lines: list[str] = []
    if nit:
        identidad_lines.append(f"  - NIT: {nit}")
    if email_contacto:
        identidad_lines.append(f"  - Email de contacto del negocio: {email_contacto}")
    if telefono_contacto:
        identidad_lines.append(f"  - Teléfono del negocio: {telefono_contacto}")
    if identidad_lines:
        lines.append("- Identidad legal y canales corporativos (úsalos SOLO si el cliente lo pregunta):")
        lines.extend(identidad_lines)

    if len(lines) == 1:
        return ""  # Sin info configurada → no inyectar sección vacía

    lines.append(
        "INSTRUCCIÓN — DISTINGUE estos conceptos al responder (rev. 71):"
    )
    lines.append(
        "  · Si el cliente pregunta '¿dónde están?' / '¿puedo recoger?' / '¿tienen tienda física?' "
        "→ usa SEDES PÚBLICAS DE ATENCIÓN. La sede (principal) es la primera referencia."
    )
    lines.append(
        "  · Si el cliente pregunta '¿desde dónde despachan?' / '¿de qué ciudad sale el envío?' "
        "→ usa ORIGEN DE DESPACHO (solo ciudad/estado, NUNCA la dirección exacta — es bodega operacional)."
    )
    lines.append(
        "  · Si el cliente pregunta '¿cuándo entregan?' / '¿en cuántos días?' "
        "→ NO inventes; consulta KB categoría envíos o pide confirmar la cotización del carrier."
    )
    lines.append(
        "Para preguntas de horario, redes, misión o valores: responde con la info de arriba. NO escales por estas preguntas."
    )
    return "\n".join(lines)


def _format_whatsapp_response_text(text: str) -> str:
    """Normaliza el texto del LLM al formato visual canónico WhatsApp (rev. 77).

    Decisión de canon de bullet (corregida tras consulta FAQ oficial):
      WhatsApp dice textualmente:
        "Listas con viñetas: Escribe un asterisco o guion seguido de espacio"
        — https://faq.whatsapp.com/539178204879377
      Por lo tanto el formato NATIVO es `* item` (asterisco + espacio). El cliente
      WhatsApp lo renderiza como viñeta con indent automático y espaciado correcto.
      El caracter `•` Unicode también se ve como bullet pero es solo texto plano
      sin tratamiento especial del cliente.
      Esta función normaliza `•`, `-`, `·`, `+` al inicio de línea hacia `* `
      para usar el formato nativo de WhatsApp en todos los mensajes salientes.

    Reglas aplicadas:
      1. CRLF → LF + trim.
      2. Markdown `**bold**` → `*bold*` (WhatsApp usa un solo asterisco para negrita).
      3. Bullets `• `, `- `, `· `, `+ ` al inicio de línea → `* ` (formato nativo).
      4. Después de `:` con bullet pegado → newline antes del bullet.
      5. Bullet seguido inmediatamente de pregunta `¿` → línea en blanco entre.
      6. Frase con `.!?` seguida de `¿` → línea en blanco entre.
      7. 3+ saltos consecutivos colapsados a 2 (máximo respiro visual).
      8. Citas `> texto` se preservan intactas.

    No invento separadores: si el LLM ya devuelve estructura limpia, queda igual.
    """
    if not text:
        return text
    formatted = text.replace("\r\n", "\n").replace("\r", "\n").strip()

    # 2. Markdown bold doble → simple (WhatsApp usa `*texto*`).
    formatted = re.sub(r"\*\*([^\n*]+?)\*\*", r"*\1*", formatted)

    # 2.b — Rev. 88: bullet malformado al inicio de línea.
    # El LLM a veces produce `*Texto:` (asterisco pegado a palabra, sin
    # espacio, sin cerrar) intentando dar formato bold pero quedando como
    # bullet roto. Detección: línea inicia con `*` + carácter de palabra Y
    # NO tiene `*` de cierre en la misma línea.
    # Convertimos a bullet canónico `* Texto:` agregando el espacio.
    # Preservamos `*texto*` (bold válido cerrado) intacto.
    formatted = re.sub(
        r"(?m)^\*(?=\w)([^*\n]+?)$",
        r"* \1",
        formatted,
    )

    # 3. Bullets variantes al inicio de línea → `* ` (formato nativo WhatsApp).
    # Detecta `• `, `- `, `· `, `+ ` con espacio al inicio (con o sin sangría).
    # NO incluimos `* ` en el patrón porque ya está en formato canónico.
    # NO confunde con `*texto*` (bold inline) porque exige `\s+` después del marker.
    formatted = re.sub(
        r"(?m)^(\s*)[•\-\·\+]\s+(?=\S)",
        r"\1* ",
        formatted,
    )

    # 4. Asegurar newline antes de bullet pegado a `:` (cuando LLM olvida \n).
    formatted = re.sub(r": +\* +(?=\S)", ":\n* ", formatted)

    # 5. Bullet seguido de pregunta sin separación → párrafo aparte.
    formatted = re.sub(r"(\*\s[^\n]+)\s+(¿)", r"\1\n\n\2", formatted)

    # 6. Punto/exclamación/interrogación seguida de pregunta → párrafo aparte.
    formatted = re.sub(r"([.!?])\s+(¿)", r"\1\n\n\2", formatted)

    # 7. Colapsar 3+ saltos consecutivos a 2 (un párrafo de respiro, no más).
    formatted = re.sub(r"\n{3,}", "\n\n", formatted)

    # 8. Rev. 92 — Truncar listados de catálogo a 2 + "Entre otros" por categoría.
    #    Ver `_truncate_category_listings` para reglas + cita marketing.
    formatted = _truncate_category_listings(formatted)

    # 9. Rev. 92 — Realzar citas KB. Convierte `_Fuente: X_` (etiqueta
    #    colgada en cursiva) en blockquote `> Fuente: X` + agrega CTA
    #    invitacional. Mejora UX cuando no hay URL pública del doc.
    formatted = _enhance_kb_citation(formatted)

    # 10. Rev. 103 — Negrita en términos KB regulatoria (plazos, condiciones,
    #     términos legales). Aplica solo si hay cita Fuente:.
    formatted = _bold_kb_terms(formatted)

    # 11. Rev. 104 — Estilo WhatsApp casual colombiano: NO opening puntuación.
    # Removemos `¡` y `¿` — los closing `!` y `?` se preservan. En español
    # estos signos SOLO aparecen como aperturas, nunca dentro de palabras,
    # así que el strip global es seguro. Es la red de seguridad determinística:
    # aunque el LLM ignore la regla del prompt, el outbound siempre sale natural.
    formatted = formatted.replace("¡", "").replace("¿", "")

    return formatted


def _bold_kb_terms(text: str) -> str:
    """Rev. 103 — post-process determinístico: envuelve en *negrita* los
    términos recurrentes de KB regulatoria (devoluciones, garantías) que
    mejoran la legibilidad del cliente en pantalla WhatsApp.

    Solo aplica si la respuesta tiene cita `Fuente:` (señal de KB).
    Idempotente: si ya está en negrita, no duplica.

    Sigue el patrón de `_truncate_category_listings`,
    `_enhance_kb_citation` e `_inject_known_customer_name`.
    """
    if not text or "Fuente:" not in text:
        return text
    if not isinstance(text, str):
        return text
    out = text
    for pattern in _BOLD_KB_PATTERNS:
        # Lookbehind/lookahead negativo para `*`: evita re-envolver
        # si el LLM ya puso el término en negrita.
        regex = re.compile(rf"(?<!\*)({pattern})(?!\*)", re.IGNORECASE)
        # `count=1` por patrón — destacar 1ra aparición; evita saturar.
        out = regex.sub(r"*\1*", out, count=1)
    return out


def _enhance_kb_citation(text: str) -> str:
    """Rev. 92 — Si la respuesta tiene `_Fuente: TITLE_` (cita KB en
    cursiva del LLM rev. 78), transforma el bloque final a:

        <cuerpo de la respuesta>

        <CTA invitacional>

        > Fuente: TITLE

    Garantiza separadores `\\n\\n` (párrafo) antes del CTA y antes del
    blockquote — el LLM tiende a pegar el cite directo al cuerpo sin
    blank line.

    Razones del cambio:
      • Cita en cursiva sin URL = etiqueta colgada (cliente no puede
        consultar el documento).
      • Blockquote (`>`) separa visualmente y se identifica como
        referencia.
      • CTA invita al cliente a profundizar dentro del mismo chat.

    Idempotente: si ya hay `> Fuente:` o el CTA, no duplica.
    """
    if not text or "_Fuente:" not in text:
        return text
    if "> Fuente:" in text:
        return text
    match = _KB_CITE_RE.search(text)
    if not match:
        return text
    title = match.group(1).strip()
    if not title:
        return text
    cta_present = "házmelo saber" in text or "hazmelo saber" in text

    # Construir el bloque final con separadores explícitos.
    blocks: list[str] = []
    if not cta_present:
        blocks.append(_KB_CITE_CTA)
    blocks.append(f"> Fuente: {title}")
    final_block = "\n\n".join(blocks)

    # Trim whitespace alrededor del cite original para evitar
    # acumulación de saltos (\n\n\n) tras la sustitución.
    before = text[:match.start()].rstrip()
    after = text[match.end():].lstrip()

    result = before + "\n\n" + final_block
    if after:
        result += "\n\n" + after
    return result


def _truncate_category_listings(text: str) -> str:
    """Rev. 92 — Si el outbound es un listado de catálogo, trunca cada
    categoría a MÁXIMO 2 ítems concretos + un 3er bullet `* _Entre otros..._`
    cuando hay ≥3 ítems en la categoría. Si al menos UNA categoría fue
    truncada, agrega cita marketing al final.

    Reglas aplicadas:
      • Categoría = línea `*Header:*` seguida de bullets `* item`.
      • Si la categoría tiene ≥3 bullets → corta a 2 + `* _Entre otros..._`.
      • Si la categoría tiene ≤2 bullets → no toca.
      • Si al menos 1 categoría fue truncada → append cita marketing.

    Skip por seguridad — NUNCA trunca:
      • Resúmenes de pedido (`📋` o `*TOTAL:` o `*Resumen`).
      • Cotizaciones de envío (texto contiene "Económica" o "transportadora").
      • Cualquier texto que no tenga al menos 1 cabecera de categoría.

    El LLM no honra confiablemente la regla del prompt; este post-process
    determinístico garantiza la UX.
    """
    if not text or not isinstance(text, str):
        return text

    # Skip-conditions: nunca tocamos summaries / cotizaciones / carts.
    skip_markers = (
        "📋", "*TOTAL:", "*Resumen", "Económica", "Rápida",
        "transportadora", "*Datos de envío", "¿Confirmas",
        "*Productos:*",  # Cart summary o order ack — items deben verse todos.
    )
    if any(marker in text for marker in skip_markers):
        return text
    # Skip si CUALQUIER bullet tiene prefijo cart-quantity (ej. "* 2x ...").
    if re.search(r"(?m)^\* \d+x ", text):
        return text

    lines = text.split("\n")
    out: list[str] = []
    i = 0
    truncated_any = False
    has_any_category = False

    while i < len(lines):
        line = lines[i]
        if _CATEGORY_HEADER_RE.match(line):
            has_any_category = True
            out.append(line)
            i += 1
            # Recolectar bullets que siguen (saltando líneas en blanco intermedias).
            bullets: list[str] = []
            while i < len(lines):
                ln = lines[i]
                if _BULLET_LINE_RE.match(ln):
                    bullets.append(ln)
                    i += 1
                    continue
                break
            if len(bullets) >= 3:
                out.extend(bullets[:2])
                out.append(_TRUNCATED_MARKER)
                truncated_any = True
            else:
                out.extend(bullets)
        else:
            out.append(line)
            i += 1

    # Si no detectamos categorías, devolver intacto.
    if not has_any_category:
        return text

    result = "\n".join(out)
    if truncated_any and "Tenemos muchas más referencias" not in result:
        # Append con doble salto antes para separar visualmente.
        result = result.rstrip() + "\n\n" + _MARKETING_CITE
    return result
