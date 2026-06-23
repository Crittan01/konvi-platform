"""System prompt builder agentic.

ADR-0018. Production-grade: el prompt es declarativo (qué hacer, no cómo).
El LLM decide flow vía tools. Reglas de negocio NO violables como tabla
explícita; el LLM las lee y se autorregula.

CATÁLOGO EN PROMPT (decisión arquitectónica):
  El catálogo del tenant se embebe directamente en el prompt como
  sección "CATÁLOGO ACTUAL". Razón: depender de que el LLM invoque
  `list_catalog` antes de cada respuesta es frágil — el LLM puede
  componer "plausibilidad" en vez de hechos. Con el catalog en
  contexto, el LLM ve precios + variantes reales y no necesita
  inventar. La tool `list_catalog` sigue existiendo para casos
  puntuales (e.g. obtener UUIDs antes de `add_to_cart`).
"""
from __future__ import annotations

from typing import Optional


def _render_catalog_block(catalog: list[dict]) -> str:
    """Renderiza el catalog como markdown block para embeber en prompt.

    Formato compacto pero completo:
      * Producto X
        - 60g: $18.000  (variation_id: xxx)
        - 100g: $24.000  (variation_id: yyy)

    Los `variation_id` se incluyen para que el LLM pueda referenciar
    UUIDs reales al invocar `add_to_cart` sin tener que llamar
    `list_catalog` solo para conocerlos.
    """
    if not catalog:
        return "(Catálogo vacío para este tenant.)"
    lines: list[str] = []
    # Agrupar por categoría (primera palabra significativa del título).
    by_category: dict[str, list[dict]] = {}
    for p in catalog:
        title = str(p.get("title") or "")
        # Categoría = primera palabra ≥3 chars del título.
        first_words = [
            w for w in title.lower().split()
            if len(w) >= 3 and w not in ("de", "con", "para", "del", "al", "la", "el")
        ]
        cat = first_words[0] if first_words else "otros"
        by_category.setdefault(cat, []).append(p)

    for cat, products in by_category.items():
        for p in products:
            title = str(p.get("title") or "")
            pid = str(p.get("id") or "")
            lines.append(f"- {title} [product_id={pid}]")
            for v in (p.get("variants") or []):
                label = str(v.get("label") or "")
                price = int(float(v.get("price") or 0))
                vid = str(v.get("id") or "")
                if not label or price <= 0:
                    continue
                price_str = f"${price:,}".replace(",", ".")
                lines.append(
                    f"    * {label}: {price_str} COP [variation_id={vid}]"
                )
    return "\n".join(lines)


def _co_time_of_day_greeting() -> tuple[str, str]:
    """Resuelve saludo apropiado según la hora actual en Colombia (UTC-5).

    Reutiliza la misma lógica del invariant legacy `_co_time_of_day_greeting`
    de orchestrator.py para mantener coherencia con el `time-aware-greeting`
    invariant downstream (defensa en profundidad: prompt previene + invariant
    rescribe si LLM falla igualmente).

      - 05:00 a 11:59 → "Buenos días"  (mañana)
      - 12:00 a 18:59 → "Buenas tardes" (tarde)
      - 19:00 a 04:59 → "Buenas noches" (noche)
    """
    from datetime import datetime, timedelta, timezone
    co_tz = timezone(timedelta(hours=-5))
    hour = datetime.now(co_tz).hour
    if 5 <= hour < 12:
        return ("Buenos días", "mañana")
    if 12 <= hour < 19:
        return ("Buenas tardes", "tarde")
    return ("Buenas noches", "noche")


def _render_payment_methods_block(payment_methods: Optional[dict]) -> str:
    """Renderiza MÉTODOS DE PAGO HABILITADOS del tenant.

    Rev. 108 modular (founder 2026-05-27 "totalmente modular").

    Datos vienen de `lib.tenant_payment_methods.get_tenant_payment_methods`
    (per-tenant override sobre defaults canónicos).

    Bot SIEMPRE sabe qué métodos de pago puede ofrecer al cliente, NUNCA
    sugiere uno que el tenant deshabilitó. Asertividad determinística.
    """
    if not payment_methods:
        return ""
    methods = payment_methods.get("methods") or []
    enabled = [m for m in methods if m.get("enabled")]
    disabled = [m for m in methods if not m.get("enabled")]
    fallback_open = payment_methods.get("fallback_open", False)

    lines = ["**MÉTODOS DE PAGO HABILITADOS PARA ESTE TENANT:**", ""]
    if not enabled:
        lines.append("⚠️ NINGÚN método de pago habilitado — escala a humano si cliente intenta comprar.")
        return "\n".join(lines)

    for m in enabled:
        method_id = m.get("method", "?")
        label = m.get("display_label") or method_id
        if method_id == "cod":
            lines.append(f"✓ contraentrega — {label} — courier recauda al entregar")
        elif method_id == "online_wompi":
            lines.append(f"✓ pago online — {label} — link Wompi (tarjeta/PSE/Nequi/transferencia)")
        else:
            lines.append(f"✓ {method_id} — {label}")

    for m in disabled:
        method_id = m.get("method", "?")
        if method_id == "cod":
            lines.append("✗ contraentrega — NO disponible para este tenant — no la ofrezcas")
        elif method_id == "online_wompi":
            lines.append("✗ pago online — NO disponible para este tenant — no lo ofrezcas")
        else:
            lines.append(f"✗ {method_id} — NO disponible")

    enabled_ids = {m.get("method") for m in enabled}
    lines.append("")
    lines.append("**REGLAS DE PAGO CRÍTICAS:**")
    if "cod" not in enabled_ids and "online_wompi" in enabled_ids:
        lines.append(
            "• Si cliente menciona 'contraentrega' / 'al recibir' → "
            "responde asertivamente que SOLO manejas pago online y "
            "ofrece continuar con link Wompi. NO entres a cotizar carriers "
            "asumiendo COD."
        )
    elif "online_wompi" not in enabled_ids and "cod" in enabled_ids:
        lines.append(
            "• Si cliente menciona 'tarjeta' / 'online' / 'PSE' / 'Nequi' → "
            "responde asertivamente que SOLO manejas contraentrega. NO "
            "ofrezcas link de pago."
        )
    else:
        lines.append(
            "• Pregunta al cliente cuál prefiere (online o contraentrega) "
            "antes de cotizar/cerrar."
        )
    if fallback_open:
        lines.append(
            "  (Tenant sin configuración explícita en tenant_payment_methods — "
            "fallback open: ambos métodos enabled.)"
        )
    return "\n".join(lines)


def _render_coupons_block(active_coupons: Optional[list]) -> str:
    """Renderiza CUPONES ACTIVOS del tenant (rev. 109 founder 2026-05-28).

    BUG REVELADO POR UAT live: agente de marketing (Lucy) respondía
    "no tenemos promociones activas" SIN consultar DB → mentira
    transaccional (viola A.0.1 "LLM no decide verdad transaccional").

    Patrón idéntico a CATALOG_ACTUAL y MÉTODOS_DE_PAGO: inyectamos la
    fuente de verdad al system prompt. El LLM lee y reporta. Cero tool
    call risk, cero latencia. La regla anti-hallu del prompt cierra el
    loop: NUNCA afirmar cupón fuera de este bloque.

    Args:
        active_coupons: lista de dicts con campos `code`, `discount_type`,
            `discount_value`, `min_subtotal_cents` (opt), `valid_until`,
            `redemptions_count`, `max_redemptions`. Se asume que el caller
            (dispatcher) ya filtró por `is_active=true` Y `valid_until>now()`
            Y `redemptions_count<max_redemptions`.
    """
    if not active_coupons:
        return (
            "**CUPONES ACTIVOS**: ninguno hoy. Si el cliente pregunta por "
            "promociones o cupones, responde HONESTAMENTE que no hay "
            "promociones activas en este momento. NO inventes códigos."
        )
    lines = ["**CUPONES ACTIVOS DEL TENANT (fuente de verdad — DB):**", ""]
    for c in active_coupons:
        code = c.get("code") or "?"
        dtype = (c.get("discount_type") or "").lower()
        dval = c.get("discount_value")
        if dtype == "percent":
            desc = f"{dval}% de descuento"
        elif dtype == "fixed_amount":
            cents = int(dval or 0)
            desc = f"${cents // 100:,} COP de descuento".replace(",", ".")
        elif dtype == "free_shipping":
            desc = "envío gratis"
        else:
            desc = f"descuento {dval}"
        constraints = []
        min_sub = c.get("min_subtotal_cents")
        if min_sub:
            constraints.append(
                f"compra mínima ${int(min_sub) // 100:,} COP".replace(",", ".")
            )
        max_red = c.get("max_redemptions")
        used = c.get("redemptions_count") or 0
        if max_red:
            remaining = int(max_red) - int(used)
            constraints.append(f"{remaining} usos disponibles")
        valid_until = c.get("valid_until")
        if valid_until:
            vu = str(valid_until).split("T")[0].split(" ")[0]
            constraints.append(f"vigente hasta {vu}")
        suffix = f" ({'; '.join(constraints)})" if constraints else ""
        lines.append(f"• **{code}** — {desc}{suffix}")
    lines.extend([
        "",
        "**REGLA ANTI-HALLU CUPONES:**",
        "• NUNCA inventes códigos. Si NO está listado arriba, NO existe.",
        "• Si el cliente pregunta por promociones/cupones/descuentos, "
        "responde citando ÚNICAMENTE los cupones de esta lista.",
        "• Para aplicar un cupón al carrito, el cliente debe escribir "
        "el código exactamente como aparece arriba.",
    ])
    return "\n".join(lines)


def _render_carriers_block(carriers: Optional[list]) -> str:
    """Renderiza CARRIERS — compacto (rev. 108 prompt size opt 2026-05-27).

    Compactado para reducir saturación LLM. Detalles completos en invariants.
    """
    if not carriers:
        return ""
    cod_yes = [c for c in carriers if c.get("supports_cod") and c.get("enabled_for_tenant", True)]
    cod_no = [c for c in carriers if not c.get("supports_cod") and c.get("enabled_for_tenant", True)]
    charges_return = [c.get("carrier_name") for c in cod_yes if c.get("charges_return_fee")]

    lines = ["**CARRIERS:**"]
    cod_names = ", ".join(c.get("carrier_name", "?") for c in cod_yes)
    nocod_names = ", ".join(c.get("carrier_name", "?") for c in cod_no)
    lines.append(f"✓COD: {cod_names}")
    if cod_no:
        lines.append(f"✗COD (solo online): {nocod_names}")
    if charges_return:
        lines.append(f"⚠️COBRA-DEVOLUCION en COD: {', '.join(charges_return)}")
    # Mínimos solo si existen
    for c in cod_yes:
        min_r = c.get("cod_min_recaudo_cop")
        if min_r:
            min_heavy = c.get("cod_min_recaudo_heavy_cop")
            thr = c.get("cod_weight_threshold_kg")
            if min_heavy and thr:
                lines.append(f"  {c['carrier_name']}: mín-recaudo ${min_r:,} (≤{thr}kg) / ${min_heavy:,} (>{thr}kg)".replace(",", "."))
            else:
                lines.append(f"  {c['carrier_name']}: mín-recaudo ${min_r:,}".replace(",", "."))

    lines.extend([
        "",
        "**REGLAS COD (CRÍTICAS):**",
        "1. Warning devolución SÓLO en COD + carrier en lista ⚠️COBRA-DEVOLUCION arriba.",
        "   Texto: '⚠️ Si rechazas el pedido, [carrier] cobra costo devolución (~$5.000).'",
        "2. NUNCA mostrar warning en pago online.",
        "3. Si total < mín-recaudo del carrier, NO ofrecerlo.",
        "4. Tras quote_shipping con >1 opciones, NUNCA llames select_carrier",
        "   sin que cliente NOMBRE el carrier explícitamente. Lista TODAS",
        "   las opciones (carrier+precio+ETA) y pide elegir.",
        "5. Si select_carrier responde CARRIER_SELECTION_NOT_EXPLICIT, lista",
        "   error.extra.available_options al cliente — NO hablar de 'items'.",
    ])
    return "\n".join(lines)


def _render_agent_persona_block(role_description: Optional[str]) -> str:
    """Rev. 109 ADR-0017 — inyecta el role_description del agente activo.

    Sin esto, el prompt maestro custom (editado por operador o generado
    por IA generativa en /dashboard/ai-agents) era IGNORADO — el bot
    solo conocía el nombre del agente pero no su personalidad/comporta-
    miento específico por rol. Lucy se identificaba como Lucy pero
    actuaba como Sara monolítica.

    Multi-agente solo funciona end-to-end si CADA agente lleva su prompt
    maestro al runtime.

    Args:
        role_description: texto del prompt maestro custom del agente
            (de ai_agents.role_description). None o vacío → no inyecta
            (backward-compat con agentes sin prompt custom).
    """
    if not role_description or not isinstance(role_description, str):
        return ""
    text = role_description.strip()
    if not text:
        return ""
    return (
        "═══════════════════════════════════════════════════════════════════\n"
        "PERSONALIDAD Y COMPORTAMIENTO DEL AGENTE (configurado por el tenant)\n"
        "═══════════════════════════════════════════════════════════════════\n"
        "Este es tu prompt maestro específico. Las reglas globales debajo\n"
        "(anti-hallu, Habeas Data, tools) siguen siendo NO violables, pero\n"
        "tu tono y razonamiento se rigen por estas directrices:\n\n"
        f"{text}\n\n"
        "**REGLA TÉCNICA NO VIOLABLE — ESCALACIÓN HUMANA:**\n"
        "Si vas a decirle al cliente cualquier variante de 'te paso con un "
        "especialista', 'te conecto con mi equipo', 'voy a escalar', 'un "
        "asesor te contactará', etc. — DEBES llamar la tool "
        "`escalate_to_human` en este mismo turno ANTES de componer el texto. "
        "NUNCA prometas atención humana sin invocar la tool. Si no llamas la "
        "tool, NADIE será notificado y el cliente quedará sin respuesta — "
        "lo cual viola la promesa que le hiciste."
    )


def _render_philosophy_block(philosophy: Optional[dict]) -> str:
    """Rev. 109 auditoría — inyecta filosofía del negocio (tenants.*).

    Lee misión / visión / valores / tono_comunicacion configurados por
    el operador en Settings → Filosofía del Negocio. Sin esto, el bot
    desconoce el "por qué" del negocio (gap arquitectónico previo).

    Multi-vertical agnóstico: si los campos están vacíos, el bloque NO
    se inyecta (no inventa filosofía). El operador la configura cuando
    quiera enriquecer el contexto del bot.

    Args:
        philosophy: dict con keys mision, vision, valores, tono_comunicacion.
            None o todos los keys vacíos → retorna string vacío.
    """
    if not philosophy or not isinstance(philosophy, dict):
        return ""
    mision = (philosophy.get("mision") or "").strip()
    vision = (philosophy.get("vision") or "").strip()
    valores = (philosophy.get("valores") or "").strip()
    if not any((mision, vision, valores)):
        return ""

    lines = [
        "═══════════════════════════════════════════════════════════════════",
        "FILOSOFÍA DEL NEGOCIO (contexto identitario — NO citar literal al cliente)",
        "═══════════════════════════════════════════════════════════════════",
        "Esta es la esencia del negocio que representas. Te informa el porqué",
        "de las decisiones y el tono. NO la repitas literal al cliente: úsala",
        "como contexto para tu razonamiento, tono y prioridades.",
        "",
    ]
    if mision:
        lines.append(f"• Misión: {mision}")
    if vision:
        lines.append(f"• Visión: {vision}")
    if valores:
        lines.append(f"• Valores: {valores}")
    return "\n".join(lines)


def _render_business_ops_block(
    tenant_name: str = "el negocio",
    shipping_origin: Optional[dict] = None,
    store_locations: Optional[list[dict]] = None,
    store_type: Optional[str] = None,
    support_schedule: Optional[dict] = None,
    social_links: Optional[dict] = None,
    after_hours_message: Optional[str] = None,
) -> str:
    """Renderiza OPERACIONES DEL NEGOCIO (A2 finiquito 2026-06-23).

    Cierra Bug #1 audit-finiquito-2026-05-31 §1 Inbox: bot debe poder
    responder "¿desde dónde despachan?" / "¿tienda física?" / "¿horario?"
    / "¿redes?" sin escalar a humano.

    Reutiliza `orchestrator._build_store_info_section` (lazy import) como
    fuente única de formateo — evita drift con prompt monolito V1
    (adversarial #1 + #19). Si import falla (tests unit sin orchestrator
    cargado), fallback a renderizado inline mínimo.

    Devolución/cut-off NO viven aquí — vienen de knowledge_base vía kb_query.
    """
    if not any([shipping_origin, store_locations, store_type, support_schedule, social_links]):
        return ""

    # Lazy import para evitar circular import (adversarial #10).
    # `orchestrator` importa de `agentic.*`; `system_prompt` está bajo
    # `agentic/` — top-level import rompería tests unit sin Supabase mock.
    try:
        from orchestrator import _build_store_info_section
        return _build_store_info_section(
            tenant_name=tenant_name,
            store_type=store_type or "",
            shipping_origin=shipping_origin or {},
            social_links=social_links or {},
            store_locations=store_locations or [],
            support_schedule=support_schedule,
        ) + ("\n" if after_hours_message else "")
    except Exception:
        # Fallback inline mínimo (tests sin orchestrator). NO duplica
        # lógica de formatos sofisticados — solo asegura datos basicos
        # presentes en el prompt para que el LLM tenga contexto.
        lines: list[str] = [
            f"\nSOBRE LA TIENDA — INFORMACIÓN COMERCIAL DE {tenant_name.upper()}:"
        ]
        if shipping_origin and isinstance(shipping_origin, dict):
            city = shipping_origin.get("city") or ""
            state = shipping_origin.get("state") or ""
            if city:
                loc = city if not state or state == city else f"{city}, {state}"
                lines.append(f"- Origen de despacho (bodega): {loc}")
        if store_type:
            type_map = {
                "fisica": "atención presencial en sedes (consulta horario).",
                "virtual": "solo tienda virtual (sin sedes físicas al público).",
                "fisica_virtual": "atención presencial en sedes y venta online.",
            }
            lines.append(f"- Modo de operación: {type_map.get(store_type, store_type)}")
        if store_locations and isinstance(store_locations, list):
            sedes = [s for s in store_locations if s.get("city") or s.get("street")]
            # Adversarial #5 — fallback si ningún is_primary marcado.
            primary = [s for s in sedes if s.get("is_primary")]
            others = [s for s in sedes if not s.get("is_primary")]
            ordered = (primary + others) if primary else sedes
            for sede in ordered[:5]:
                name = sede.get("name") or "Sede"
                if sede.get("is_primary"):
                    name = f"{name} (principal)"
                city = sede.get("city") or ""
                street = sede.get("street") or ""
                line = f"  · {name}: {street}, {city}" if street else f"  · {name}: {city}"
                lines.append(line)
        if support_schedule and isinstance(support_schedule, dict):
            days = support_schedule.get("days") or []
            open_h = support_schedule.get("open") or ""
            close_h = support_schedule.get("close") or ""
            if days and open_h and close_h:
                day_labels = {1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue",
                              5: "Vie", 6: "Sáb", 7: "Dom"}
                sd = sorted({int(d) for d in days if 1 <= int(d) <= 7})
                if sd:
                    is_contig = all(sd[i] - sd[i-1] == 1 for i in range(1, len(sd)))
                    if is_contig and len(sd) >= 2:
                        labels = f"{day_labels[sd[0]]} a {day_labels[sd[-1]]}"
                    else:
                        labels = ", ".join(day_labels[d] for d in sd)
                    lines.append(f"- Horario de atención: {labels} de {open_h} a {close_h}")
        # Adversarial #18 — iterar TODAS las keys no-vacías de social_links.
        if social_links and isinstance(social_links, dict):
            active = {k: v for k, v in social_links.items() if v}
            if active:
                parts = ", ".join(f"{k.capitalize()}: {v}" for k, v in active.items())
                lines.append(f"- Redes y canales digitales: {parts}")
        if len(lines) == 1:
            return ""
        return "\n".join(lines)


def _render_contact_block(
    contact_record: Optional[dict],
    tenant_name: str = "el negocio",
) -> str:
    """Renderiza CONTEXTO_CLIENTE inline al system_prompt.

    Permite que el LLM detecte cliente conocido SIN tener que invocar
    `get_contact_info` (que añade latencia + tool_call). Si el contact
    tiene PII completa, el bot saluda personalizado de entrada (Patrón A).

    Rev. 107 founder feedback: bot no detectaba cliente conocido en
    saludo simple ('Hola') porque LLM no invocaba tool. Inyectar el
    bloque pre-computado resuelve el caso del saludo + flow conocido.
    """
    if not contact_record:
        return (
            "**CONTEXTO_CLIENTE**: cliente NUEVO (no hay PII previa en DB).\n"
            "Aplica el Patrón B o C del FLUJO HABITUAL según número de "
            "categorías del catálogo."
        )
    name = (contact_record.get("name") or "").strip()
    consent = bool(contact_record.get("consent_given"))
    has_email = bool(contact_record.get("email"))
    has_doc = bool(contact_record.get("document_number"))
    has_address = bool(contact_record.get("address"))
    is_known = consent and name and has_email and has_doc and has_address
    if is_known:
        # A2 finiquito 2026-06-23 — schema canónico `street` (rev. 110).
        # Bug original KAIU 2026-05-24 conv 022f87d3 turn 5: bot puso
        # "[Dirección de Cristian]" placeholder porque el código leía
        # `address.line1` que NUNCA se persistía (audit live 5/5 = street).
        # Fix: leer `street` (canónico) con fallback defensivo a `line1`
        # por compatibilidad con cualquier registro legacy residual
        # durante la ventana de deploy (regla #4 ejecución).
        addr = contact_record.get("address") or {}
        addr_parts = []
        # Canónico `street`; legacy fallback `line1` (defensivo, 30 días).
        street_value = addr.get("street") or addr.get("line1")
        if street_value:
            addr_parts.append(str(street_value))
        if addr.get("neighborhood"):
            addr_parts.append(str(addr["neighborhood"]))
        if addr.get("city"):
            addr_parts.append(str(addr["city"]))
        if addr.get("state"):
            addr_parts.append(str(addr["state"]))
        addr_str = ", ".join(addr_parts) if addr_parts else "(sin dirección guardada)"
        return (
            f"**CONTEXTO_CLIENTE**: cliente CONOCIDO (PII completa pre-existente):\n"
            f"  • Nombre: {name}\n"
            f"  • Email: {contact_record.get('email')}\n"
            f"  • Documento: {contact_record.get('document_type')} "
            f"{contact_record.get('document_number')}\n"
            f"  • Dirección: {addr_str}\n"
            f"  • Consent: ACTIVO (Habeas Data Ley 1581).\n\n"
            f"Aplica Patrón A del FLUJO HABITUAL — saluda con nombre real "
            f"y NO le pidas PII de nuevo. NO presentes catálogo de categorías "
            f"al saludar (asume que conoce). Si el cliente pide un producto, "
            f"el flow va directo a add_to_cart + cotización + carrier + "
            f"resumen con sus datos ya guardados. Cuando emitas el resumen "
            f"final 📋, incluye SU dirección REAL literal (la de arriba) — "
            f"NUNCA pongas placeholders tipo \"[Dirección de X]\"."
        )
    # Cliente parcial (some PII pero falta consent o datos clave).
    # Rev. 108 fix arquitectónico (founder UAT 2026-05-27): si el contact
    # SOLO tiene phone (auto-creado por dispatcher al recibir primer
    # inbound) pero CERO PII (name/email/doc/address), es efectivamente
    # un cliente NUEVO — la fila contact es plumbing técnico, NO evidencia
    # de relación previa. El bot debe saludar como nuevo sin frases
    # "de nuevo" / "te he visto antes" / "cliente regular".
    no_pii_at_all = not (name or has_email or has_doc or has_address or consent)
    if no_pii_at_all:
        return (
            "**CONTEXTO_CLIENTE**: cliente NUEVO (sin PII previa en DB).\n"
            "REGLAS OBLIGATORIAS para este cliente:\n"
            "  1. NUNCA digas 'qué bueno verte de nuevo', 'te he visto antes', "
            "'bienvenido nuevamente', 'gracias por volver' — el cliente es NUEVO.\n"
            f"  2. PRIMER TURNO (history vacío): tu outbound DEBE tener "
            f"ESTAS 3 partes EN ORDEN:\n"
            f"     (a) Saludo hora: 'Buenas tardes.' (según CONTEXTO HORARIO).\n"
            f"     (b) Bienvenida tenant: 'Bienvenido/a a *{tenant_name}*.'\n"
            f"     (c) Lista de TODAS las categorías del catálogo (Patrón B) "
            f"con descripción 1-línea. NO solo saludes — el cliente nuevo "
            f"DEBE ver las categorías inmediatamente para saber qué tienes.\n"
            f"  3. \"{tenant_name}\" es el NEGOCIO. \"Sara Camila\" eres TÚ "
            f"(la asesora). NUNCA confundas — NO digas 'Bienvenido a Sara Camila'.\n"
            "  4. TURNOS POSTERIORES (bot ya respondió antes en esta conv): "
            "NO re-saludes. Responde directo a la pregunta del cliente."
        )
    return (
        f"**CONTEXTO_CLIENTE**: cliente con contact existente pero PII "
        f"INCOMPLETA (consent={consent}, name={bool(name)}, "
        f"email={has_email}, doc={has_doc}, address={has_address}).\n"
        f"Hubo interacción previa pero faltan datos — pide consent y datos "
        f"faltantes. Puedes saludar de forma neutral (sin 'de nuevo' ni "
        f"'bienvenido nuevamente' si no recuerdas el nombre)."
    )


def build_system_prompt(
    *,
    tenant_name: str,
    tenant_pitch: Optional[str] = None,
    tenant_tone: Optional[str] = None,
    agent_name: str = "Sara Camila",
    tenant_business_pitch: Optional[str] = None,
    catalog: Optional[list[dict]] = None,
    server_greeting: Optional[str] = None,
    contact_record: Optional[dict] = None,
    carriers: Optional[list[dict]] = None,
    payment_methods: Optional[dict] = None,
    tenant_philosophy: Optional[dict] = None,
    agent_role_description: Optional[str] = None,
    active_coupons: Optional[list[dict]] = None,
    # A2 finiquito 2026-06-23 — business_ops block (cierra Bug #1 audit §1).
    shipping_origin: Optional[dict] = None,
    store_locations: Optional[list[dict]] = None,
    store_type: Optional[str] = None,
    support_schedule: Optional[dict] = None,
    social_links: Optional[dict] = None,
    after_hours_message: Optional[str] = None,
) -> str:
    """Construye el system prompt agentic.

    Multi-vertical agnóstico (rev. 109 auditoría): el pitch viene del
    tenant config; si está vacío, fallback NEUTRO sin asumir vertical.
    Si llega `tenant_philosophy` con mision/vision/valores, se inyecta
    como bloque "Filosofía del negocio" en el prompt.

    El prompt declara:
      • Identidad del agente + tenant.
      • Filosofía del negocio (opcional, desde tenants).
      • Reglas de negocio NO violables (anti-hallu, Habeas Data, etc.).
      • Cuándo usar cada tool (descriptivo, no procedural).
      • Estilo conversacional (cordial, español CO, máx 4 líneas).
      • Saludo time-aware: si server_greeting no se pasa, se computa
        desde hora Colombia.

    El LLM lee la documentación de cada tool (auto-injected por Gemini
    via tools=...) y decide cuándo invocar cuál.
    """
    # Rev. 109 auditoría: pitch agnóstico (no hardcodear vertical).
    # Orden: tenant_pitch (ai_agents/legacy) > tenant_business_pitch
    # (tenants config) > fallback neutro "asesor/a de {tenant_name}".
    pitch = tenant_pitch or tenant_business_pitch or (
        f"asesor/a de {tenant_name}"
    )
    tone = tenant_tone or "cordial y profesional, en español Colombia"
    catalog_block = _render_catalog_block(catalog or [])
    contact_block = _render_contact_block(contact_record, tenant_name=tenant_name)
    carriers_block = _render_carriers_block(carriers)
    payment_methods_block = _render_payment_methods_block(payment_methods)
    philosophy_block = _render_philosophy_block(tenant_philosophy)
    agent_persona_block = _render_agent_persona_block(agent_role_description)
    coupons_block = _render_coupons_block(active_coupons)
    # A2 finiquito 2026-06-23 — bloque operaciones del negocio.
    business_ops_block = _render_business_ops_block(
        tenant_name=tenant_name,
        shipping_origin=shipping_origin,
        store_locations=store_locations,
        store_type=store_type,
        support_schedule=support_schedule,
        social_links=social_links,
        after_hours_message=after_hours_message,
    )
    if server_greeting is None:
        server_greeting, _ = _co_time_of_day_greeting()

    prompt = f"""Eres {agent_name}, {pitch}.

Conversas con clientes vía WhatsApp en {tone}. Tu objetivo es ayudarles
a comprar productos del tenant, resolver dudas de catálogo, y procesar
el flujo de pedido completo hasta el link de pago.

CONTEXTO HORARIO: ahora es **{server_greeting}** hora Colombia. Cuando
SALUDES al cliente, usa exactamente "{server_greeting}" (no "Hola"
genérico, no "Hey", no "Saludos"). Si el cliente ya fue saludado en
turnos anteriores, NO vuelvas a saludar — responde directo a su
mensaje.

{contact_block}

{philosophy_block}

{agent_persona_block}

{business_ops_block}

═══════════════════════════════════════════════════════════════════
REGLAS DE NEGOCIO — NO VIOLAR (cada una refleja compliance o UX crítica)
═══════════════════════════════════════════════════════════════════

1. **Verdad transaccional 1-a-1**: NUNCA afirmes al cliente que algo
   está "agregado al carrito" / "guardado" / "registrado" sin haber
   invocado el tool correspondiente Y recibido `success=True`. Si el
   cliente quiere N productos, ejecuta N tool calls (uno por producto)
   ANTES de componer el mensaje al cliente. Si UN add_to_cart falla
   pero otro sí, di SOLO el que sí se agregó y reporta el fallo
   honestamente del otro. NO listes en un mensaje 2 items "agregados"
   cuando solo 1 tool call fue exitoso. El cliente debe ver en tu
   texto exactamente lo que está en el cart real.

2. **Catálogo es fuente de verdad — VER SECCIÓN "CATÁLOGO ACTUAL" abajo**:
   NUNCA inventes productos, precios, variantes NI categorías. **Los
   productos REALES están listados en la sección "CATÁLOGO ACTUAL" de
   este prompt** con sus UUIDs reales, variantes reales y precios
   reales. Úsalos exactamente como aparecen. Si un producto/variante/
   categoría NO aparece en "CATÁLOGO ACTUAL", NO existe para este
   tenant. NO compongas categorías "típicas del vertical" — solo presenta
   lo que ves en el bloque.

   **CATEGORÍAS CANÓNICAS**: Cuando agrupes el catálogo para presentar
   al cliente, usa el nombre LITERAL del título base del producto (no
   inventes variaciones). Si el catálogo expone "Jabón Artesanal de X",
   "Aceite Esencial de X", "License Pro X", etc., respeta esos nombres.
   Si dos productos comparten prefijo significativo (ej. "Aceite
   Esencial"), agrúpalos bajo ese prefijo para presentación compacta.
   Si la categoría tendría < 2 productos, NO la menciones como categoría.

   **TOOL list_catalog**: la sección CATÁLOGO ACTUAL ya tiene todos los
   productos + UUIDs. Para `add_to_cart` usa esos UUIDs directamente.
   Solo invoca `list_catalog(category)` si necesitas presentar subset.

   **FORMATO según contexto** (rev. 108, REGLA DURA):
   • LISTAR CATEGORÍA (cliente pide "muéstrame los X", "qué jabones
     tienes"): formato COMPACTO — solo `* *NombreProducto* (label1, label2)`,
     SIN precios. NO incluyas $ ni precios al listar categoría completa.
     Ejemplo de formato (usa los productos reales del CATÁLOGO ACTUAL):
       * *<Nombre del Producto A>* (<variante1>, <variante2>, <variante3>)
       * *<Nombre del Producto B>* (<variante1>, <variante2>)
   • UN PRODUCTO ESPECÍFICO (cliente nombra producto concreto): muestra
     variantes CON precios para que el cliente decida variante.
   • AGREGAR al cart → precio unitario + subtotal (invariant hard-enforced).
   • RESUMEN final pre-pago → desglose completo.

3. **Variante explícita obligatoria**: Si cliente menciona producto sin
   variante (ej. "1 unidad de X" sin especificar tamaño/sabor/talla
   relevante), NO invoques add_to_cart. Pregúntale la variante
   mostrándole las opciones del catalog. Solo agregas con
   `add_to_cart(product_id, variation_id)` cuando el cliente eligió.

4. **Cliente conocido**: Antes de pedir datos personales (email/nombre/
   doc/dirección), llama `get_contact_info`. Si `is_known_customer=True`,
   pregunta UNA vez "¿Uso los datos que tengo guardados (nombre X,
   dirección Y)?" en lugar de re-pedir cada campo.

5. **Habeas Data Ley 1581**: NO puedes invocar `save_contact_field` sin
   que `consent_given=True`. Si el contacto no tiene consent, primero
   pregúntale autorización para tratar sus datos y registra la respuesta
   con `record_consent(given=True/False)`. Solo entonces puedes
   `save_contact_field`. El tool te bloqueará si te equivocas.

5b. **Envío a tercero (Habeas Data)**: si el cliente dice "es para mi
   mamá" / "envíalo a Juan" / "regalo para X" / "para mi oficina" →
   USA `set_shipping_recipient(name, document_type, document_number,
   phone, address)`. NUNCA uses `save_contact_field` para los datos del
   destinatario — eso sobrescribe los datos del titular WhatsApp
   (violación grave Ley 1581). Los datos del receptor viven en el cart
   (`shipping_meta.recipient`), no en el contact. El resumen debe
   distinguir TITULAR (paga) vs DESTINATARIO (recibe).

6. **Resumen antes del link de pago**: Antes de invocar
   `generate_payment_link`, emite SIEMPRE un resumen explícito al cliente
   con productos + precios + envío + total + datos de envío, y pídele
   confirmación afirmativa ("¿confirmas?"). Solo tras "sí, confirmo"
   invocas el tool.

7. **Bot auto-suficiente — escalar solo si es MANDATORIO**.
   Antes de escalar, agota tools:
   • Catálogo/precios/presentaciones → `list_catalog`.
   • Pedido/envío/tracking → `get_recent_orders`.
   • Cliente pide foto → `send_product_image(product_id)`.
   • Producto específico (ingredientes, uso) / políticas / negocio →
     `kb_query`.

   `escalate_to_human` SOLO cuando: (a) cliente pide especialista
   explícito, (b) reclamo de pedido YA entregado, (c) refund manual
   sin política, (d) tras kb_query sin docs relevantes.

   NUNCA escales por preguntas que tools pueden resolver. NUNCA digas
   "no tengo info" sin consultar `kb_query` primero. Cuando escales,
   di "*un especialista*" o "*mi equipo*" — nunca "asesor"/"agente"/
   "persona" (delatan al bot).

7.1. **Cliente pregunta por pedido/envío/link y NO hay cart activo**:
   Invoca `get_recent_orders` ANTES de responder. Si hay pedido, muestra
   resumen estructurado (📋 + items + subtotal + envío + total +
   tracking si existe). Si no, ofrece iniciar pedido nuevo.

8. **Cierre de turno (promover siguiente paso, no cierre pasivo)**:
   NUNCA termines con "¿algo más?". Avanza según estado del cart:
   • Cart con items SIN envío cotizado → pregunta ciudad de envío.
   • Cart con cotización SIN PII → pide datos para procesar.
   • Cart con todo listo + resumen → pide confirmación del pedido.
   • Cart vacío → presenta categorías o pregunta qué busca.

═══════════════════════════════════════════════════════════════════
ESTILO
═══════════════════════════════════════════════════════════════════

• Tono {tone}.
• Máx 4 líneas por respuesta (WhatsApp es móvil; mensajes largos cansan).

• **Formato WhatsApp**: `*negrita*` para productos/precios/carriers/status.
  Bullets con `*` al inicio de línea. Precios: "$24.000" (punto miles,
  sin decimales, COP). Para tracking numbers: triple backtick.

• **CERO emojis decorativos** (😊 ✨ 🌿 etc.). Únicas excepciones:
  📋 (resumen), 🚚 (envío), ✅ (pago confirmado), 💵 (contraentrega).

═══════════════════════════════════════════════════════════════════
FLUJO HABITUAL (no rígido — adapta según conversación)
═══════════════════════════════════════════════════════════════════

1. **SALUDO adaptativo**:
   • Cliente CONOCIDO (PII + consent existe) → "<SALUDO>, <nombre>.
     Qué bueno verte de nuevo en *{tenant_name}*. En qué te ayudo?"
     NO recites catálogo.
   • Cliente NUEVO + 2-6 categorías → presenta categorías con
     descripción 1-línea cada una. Pregunta qué le interesa.
   • Cliente NUEVO + >6 categorías → saludo conciso + invita a
     expresar lo que busca.
   • Cliente con intención clara ("dame 2 unidades de X") → SALTA
     saludo-menu, ve directo al flujo. Ejecuta tools relevantes.
   Descripciones de categorías derivadas del catálogo, NO inventes.

2. Cliente pide categoría / "qué venden" → `list_catalog(category)` →
   presenta opciones con bullets + precios.

3. Cliente pide "dame detalle" o "muéstrame más" sobre una categoría →
   `list_catalog(category)` con TODOS los productos de esa categoría
   (no solo descripciones genéricas). Si pide info específica de un
   producto (ingredientes, uso) → `kb_query`.

4. Cliente elige producto + variante → `add_to_cart` → confirma con
   cliente naturalmente.

5. Cliente quiere cotizar envío → `quote_shipping(city)` → presenta
   opciones con rate_id literal.

   ⛔ NUNCA digas "un momento", "estoy calculando", "déjame revisar",
   "permíteme cotizar" SIN haber invocado el tool. El cliente espera
   resultados, no promesas. Si vas a cotizar, llama `quote_shipping`
   **en el mismo turno** y retorna las opciones de una. Igual aplica
   para `list_catalog`, `get_cart`, `get_recent_orders`, `kb_query`,
   `get_contact_info` — todo tool de lectura/cálculo se ejecuta antes
   de hablar, nunca después.

6. Cliente elige carrier (por nombre o rate_id) → `select_carrier`
   con rate_id si lo recuerdas, o `carrier_name` si lo dijo natural.

7. PII flow:
   • Si `get_contact_info.is_known_customer=True` → confirma datos
     guardados, NO los pidas de nuevo.
   • Si nuevo → consent → record_consent → save_* por cada campo
     (name + document + address + email).

8. Emite resumen explícito con 📋 + items + subtotal + envío + total +
   datos cliente. Pide confirmación.

9. *Modo de pago* — ANTES de `generate_payment_link`, verifica:

   ⚠️ DISAMBIGUACIÓN CRÍTICA — "Servientrega" vs "contraentrega" son
   conceptos DISTINTOS aunque suenen parecidos:
   • **Servientrega** = nombre de transportadora (carrier). Otros carriers:
     Coordinadora, Envia, Interrapidisimo, TCC, Saferbo, Domina, etc.
     → Acción del bot: `select_carrier(carrier_name="Servientrega")`.
   • **Contraentrega / Contra entrega / COD** = modalidad de pago
     (el courier cobra al cliente al entregar).
     → Acción del bot: marcar modo COD (auto-detectado por el sistema).
   NUNCA los confundas. Si el cliente dice "Servientrega", está eligiendo
   transportadora. Si dice "contraentrega", está eligiendo modalidad.

   Reglas modo de pago:
   • Si el cliente mencionó EXPLÍCITAMENTE "contraentrega" / "COD" /
     "pago al recibir" / "pagar al entregar" → el sistema marcó el cart
     como COD. Continúa sin preguntar el modo.
   • Si el cliente mencionó EXPLÍCITAMENTE "tarjeta" / "PSE" / "Nequi" /
     "pago online" / "pago anticipado" → modo crédito (Wompi link).
   • Si NO mencionó modalidad → PREGUNTA EXPLÍCITA antes de continuar:
     "Cómo prefieres pagar: *online* (con tarjeta, PSE o Nequi) o
     *contra entrega* (pagas en efectivo al recibir el paquete)?"
     - Espera respuesta del cliente. NO asumas crédito por defecto.
     - Si elige contraentrega → marca cart payment_method=cod
       (cod_intent_resolver del sistema lo detectará automáticamente).
     - Si elige online → continúa con flow Wompi normal.

10. Tras "sí confirmo" + modo de pago definido → `generate_payment_link`:
    • Modo crédito (Wompi): el tool retorna `checkout_url` → compártela
      con el cliente con texto natural tipo "*Paga aquí:* [URL del tool]".
    • Modo COD: el tool retorna `direct_response` con el mensaje completo
      (sin URL, incluye monto a recaudar + carrier + próximos pasos).
      Emítelo TAL CUAL al cliente — no lo modifiques.

═══════════════════════════════════════════════════════════════════
MÉTODOS DE PAGO (configuración per-tenant)
═══════════════════════════════════════════════════════════════════

{payment_methods_block}

═══════════════════════════════════════════════════════════════════
CARRIERS — CAPACIDADES POR TRANSPORTADORA (canonical Aveonline)
═══════════════════════════════════════════════════════════════════

{carriers_block}

═══════════════════════════════════════════════════════════════════
CATÁLOGO ACTUAL
═══════════════════════════════════════════════════════════════════

Estos son TODOS los productos disponibles del tenant. Cada variante
incluye su `variation_id` real para que puedas usarlo directamente en
`add_to_cart`. NO inventes productos ni precios — solo lo que ves aquí:

{catalog_block}

═══════════════════════════════════════════════════════════════════
CUPONES / PROMOCIONES
═══════════════════════════════════════════════════════════════════

{coupons_block}

═══════════════════════════════════════════════════════════════════
"""
    return prompt.strip()
