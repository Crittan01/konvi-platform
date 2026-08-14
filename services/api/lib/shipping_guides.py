"""Generación de guías de envío post-pago (extraído de routers/wompi_webhook.py — G12 corte 3).

Cluster cohesivo: tras pago APPROVED (webhook Wompi), genera la guía Aveonline
con claim-before-bill idempotente (ADR-0034), peso/dimensiones reales del pedido
y credenciales per-tenant. Extraído verbatim 2026-08-13 — comportamiento
idéntico; el router las importa (los nombres quedan en su namespace).

Los imports de `integrations.aveonline_client` y `lib.dane_resolver` son LAZY
dentro de `_generate_shipping_guide_async` (se movieron verbatim con ella).
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def _generate_shipping_guide(
    supabase, *, order_id: str, tenant_id: str,
) -> bool:
    """Wrapper SYNC para callers sync (wompi BackgroundTask).

    Usa asyncio.run() — funciona porque BackgroundTask sync NO tiene
    event loop activo. Para callers async (endpoint FastAPI), usar
    `_generate_shipping_guide_async` directamente con await.
    """
    import asyncio as _aio
    # UAT founder 2026-07-10: pausa configurable ANTES de generar la guía en el path
    # automático post-pago (ventana de cancelación/edición + evita guía "instantánea").
    try:
        _delay = float(os.getenv("GUIDE_GENERATION_DELAY_SECONDS", "60"))
    except ValueError:
        _delay = 60.0
    return _aio.run(
        _generate_shipping_guide_async(
            supabase, order_id=order_id, tenant_id=tenant_id,
            delay_seconds=max(0.0, _delay),
        )
    )


async def _generate_shipping_guide_async(
    supabase, *, order_id: str, tenant_id: str, delay_seconds: float = 0.0,
) -> bool:
    """Genera guía Aveonline tras pago APPROVED (best-effort).

    Solo aplica si el tenant tiene `tenant_shipping_provider_config.
    active_provider='aveonline'`. Si está en 'envia' o cualquier otro,
    skip (los demás providers tienen su propia mecánica).

    simulate=True por default → NO factura. Tenant setea
    AVEONLINE_GENERATE_REAL_GUIDES=true (env) cuando esté listo.

    Best-effort: si falla, log warning + persiste row pending en
    shipments para que operador genere manual desde Inbox.

    delay_seconds (UAT founder 2026-07-10): pausa previa SOLO en el path automático
    post-pago (webhook la pasa desde GUIDE_GENERATION_DELAY_SECONDS, default 60s) —
    (a) da ventana de cancelación/edición antes de generar (con guías reales = antes
    de facturar), (b) evita la sensación "robótica" de guía instantánea. El path
    manual del operador (orders.py) NO pasa delay (respuesta inmediata).

    Returns:
        True si guía generó OK + shipment persistido con tracking_number
        (caller dispara etapa 2: email "envío en camino" + WA tracking).
        False si skip (provider != aveonline / contact incompleto /
        Aveonline rechazó). Caller no dispara etapa 2.
    """
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    # 1. Provider check.
    tenant_real_guides = False  # BLOQUE B (item 3): default fail-safe (simulado)
    try:
        cfg = (
            supabase.table("tenant_shipping_provider_config")
            .select("active_provider, real_guides_enabled")
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        provider = ((cfg.data or {}).get("active_provider") or "").lower()
        tenant_real_guides = bool((cfg.data or {}).get("real_guides_enabled"))
    except Exception:
        provider = ""

    if provider != "aveonline":
        logger.info(
            "[WOMPI][AVEONLINE] tenant=%s provider=%s — skip guía (no aveonline)",
            tenant_id, provider or "none",
        )
        return False

    # 2. Cargar order + contact + tenant shipping_origin + shipping_meta.
    try:
        order_res = (
            supabase.table("orders")
            .select(
                "id, total_amount, shipping_cost, contact_id, payment_method, "
                "contacts(name, email, phone, shipping_phone, "
                "document_type, document_number, address)"
            )
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        order = order_res.data or {}
    except Exception as exc:
        logger.warning("[WOMPI][AVEONLINE] no pude leer order: %s", exc)
        return False

    contact = order.get("contacts") or {}
    if not contact.get("name") or not contact.get("phone"):
        logger.info(
            "[WOMPI][AVEONLINE] order=%s contact incompleto — skip guía",
            order_id[:8],
        )
        return False

    addr = contact.get("address") or {}
    # A2 finiquito 2026-06-23: schema canónico `street` (rev. 110).
    # Audit live 2026-06-23: 5/5 contactos productivos KAIU usan `street`.
    # Fallback `line1` preservado 30 días defensivo por retries de webhooks
    # legacy con snapshot serializado pre-deploy (adversarial #12).
    addr_street = addr.get("street") or addr.get("line1") or ""
    if not addr.get("city") or not addr_street:
        logger.info(
            "[WOMPI][AVEONLINE] order=%s sin dirección — skip guía "
            "(addr keys=%s)",
            order_id[:8], list(addr.keys()),
        )
        return False

    # 3. Tenant shipping_origin (sender).
    try:
        ten = (
            supabase.table("tenants")
            .select("name, shipping_origin, telefono_contacto, email_contacto, nit")
            .eq("id", tenant_id).single().execute()
        )
        tenant = ten.data or {}
    except Exception:
        tenant = {}

    origin = tenant.get("shipping_origin") or {}
    if not origin.get("city") or not origin.get("street"):
        logger.warning(
            "[WOMPI][AVEONLINE] tenant=%s sin shipping_origin completo — skip",
            tenant_id[:8],
        )
        return False

    # 4. Cart shipping_meta → idtransportador (rate_id). BUG F5 (guía cruzada): filtrar por el cart QUE
    # CONVIRTIÓ A ESTA ORDEN (converted_order_id), no el último del tenant → evita usar el carrier de otra
    # orden bajo concurrencia. Sin cart vinculado → sm vacío → carrier_rate_id vacío (path degradado seguro).
    try:
        cart = (
            supabase.table("conversation_carts")
            .select("shipping_meta")
            .eq("tenant_id", tenant_id)
            .eq("converted_order_id", order_id)
            .order("updated_at", desc=True).limit(1).execute()
        )
        sm = ((cart.data or [{}])[0]).get("shipping_meta") or {}
    except Exception:
        sm = {}

    carrier_rate_id = sm.get("rate_id") or ""
    # Rev. 107 — persistir carrier_name real (SERVIENTREGA/ENVIA/etc.)
    # en lugar del provider name ("aveonline"). El cliente espera ver
    # "Envío SERVIENTREGA $7.530" en resumen post-pago, no "aveonline".
    selected_carrier_name = (sm.get("carrier") or "").strip()
    if not carrier_rate_id:
        logger.warning(
            "[WOMPI][AVEONLINE] order=%s sin carrier rate_id — skip",
            order_id[:8],
        )
        return False

    # 5. Construir payload + invocar generate_guide.
    _claim_id = None  # BLOQUE B item 5: def antes del try — el except grande lo referencia
    try:
        from integrations.aveonline_client import AveonlineClient

        cli = AveonlineClient(tenant_id, supabase)

        addr_full = " ".join(filter(None, [
            addr_street,
            f"apto {addr['apartment']}" if addr.get("apartment") else None,
            addr.get("building_type") or None,
            f"torre {addr['tower']}" if addr.get("tower") else None,
        ]))

        sender = {
            "nit": tenant.get("nit") or "",
            "nombre": (origin.get("name") or tenant.get("name") or "")[:80],
            "direccion": origin.get("street") or "",
            "barrio": "",
            "telefono": tenant.get("telefono_contacto") or origin.get("phone") or "",
            "celular": tenant.get("telefono_contacto") or origin.get("phone") or "",
            "email": tenant.get("email_contacto") or "",
        }
        recipient = {
            "doc": contact.get("document_number") or "",
            "nombre": contact.get("name") or "",
            "direccion": addr_full or addr.get("street") or "",
            "barrio": addr.get("neighborhood") or "",
            "telefono": (contact.get("shipping_phone") or contact.get("phone") or "").lstrip("+"),
            "celular": (contact.get("shipping_phone") or contact.get("phone") or "").lstrip("+"),
            "email": contact.get("email") or "",
        }
        # Rev. 108 Fase B — COD: si orden tiene payment_method='cod',
        # pasar `cod_enabled=True` + `valorrecaudo=total_amount` al cliente
        # Aveonline. El courier recauda al entregar (campo `contraentrega=1`).
        order_total = int(float(order.get("total_amount") or 0))
        # valorDeclarado del seguro = valor de la MERCANCÍA (subtotal de productos), NO el total con envío
        # (auditoría coherencia 2026-07-01, LOW #1): se asegura el producto, no el flete. Fallback al total
        # si no hay shipping_cost. valorrecaudo (COD) SÍ es el total (el courier recauda productos + envío).
        shipping_cost = int(float(order.get("shipping_cost") or 0))
        merchandise_cop = max(order_total - shipping_cost, 0) or order_total
        is_cod = (order.get("payment_method") or "credit").lower() == "cod"
        # F5: reusar peso/dims COTIZADOS (shipping_meta.weight_inputs, persistidos por el quote) → la guía
        # sale con el peso real y no sobre-declara ni dispara reajuste retroactivo. Fallback a default solo si
        # el cart no cotizó (guía sin quote previo). `sm` = shipping_meta del cart de ESTA orden (arriba).
        _wi = (sm or {}).get("weight_inputs") or {}
        # UAT founder 2026-07-10: dscontenido de la guía era un hardcode ("Productos
        # cosmética artesanal") inválido multi-tenant y para reclamos ante el carrier.
        # Derivar del contenido REAL del pedido (títulos de order_items, ≤90 chars).
        guide_content = "Pedido"
        try:
            _items_res = (
                supabase.table("order_items")
                .select("title, quantity")
                .eq("order_id", order_id)
                .eq("tenant_id", tenant_id)  # ADR-0025: filtro explícito por tenant (lint)
                .limit(5)
                .execute()
            )
            _titles = [
                f"{int(r.get('quantity') or 1)}x {str(r.get('title') or '').strip()}"
                for r in (_items_res.data or []) if r.get("title")
            ]
            if _titles:
                guide_content = ("; ".join(_titles))[:90]
        except Exception as _it_exc:
            logger.debug("[WOMPI][AVEONLINE] items para dscontenido falló: %s", _it_exc)
        package = {
            "weight_kg": float(_wi.get("weight_kg") or 0.5),  # default conservador si no hay cotización
            "length_cm": float(_wi.get("length_cm") or 15),
            "width_cm": float(_wi.get("width_cm") or 10),
            "height_cm": float(_wi.get("height_cm") or 5),
            "declared_value_cop": merchandise_cop,
            "units": 1,
            "content": guide_content,
            "cod_enabled": is_cod,
            "valorrecaudo": order_total if is_cod else 0,
        }
        # BLOQUE B (item 3): guía real solo si AMBOS — master global de plataforma
        # (kill-switch) Y activación per-tenant (real_guides_enabled). Default false en
        # ambos → simulado (fail-safe). Activar guías reales es acción founder por-tenant.
        _master_real = os.getenv("AVEONLINE_GENERATE_REAL_GUIDES", "false").lower() == "true"
        simulate = not (_master_real and tenant_real_guides)

        # Bug runtime KAIU 2026-05-24: Aveonline rechaza city raw
        # ("Bogotá D.C." → "No se pudo generar la guia."). Requiere
        # formato canónico "BOGOTA(CUNDINAMARCA)". Aplicamos el mismo
        # normalizador del cotizador para coherencia origin/destination.
        from integrations.aveonline_client import to_aveonline_city_format
        from lib.dane_resolver import resolve_dane_from_city

        origin_city_norm = to_aveonline_city_format(
            origin.get("city") or "", origin.get("state") or "",
        )
        dest_city_norm = to_aveonline_city_format(
            addr.get("city") or "", addr.get("state") or "",
        )

        # Bug fix rev. 109 (2026-05-31): Aveonline `generarGuia2` rechaza
        # destino sin DANE numérico ("No se puede generar la guia").
        # Precedencia destino:
        #   1. cart.shipping_meta.dane_code — el bot lo resolvió al cotizar
        #      (shipping_quote_tool._persist_destination_city_to_cart). Fuente
        #      más reciente: el cliente acaba de declarar la ciudad este turn.
        #   2. contact.address.dane_code — si el save_address tool lo persistió
        #      (post-rev.109 lo hará; backwards-compat para addresses viejas).
        #   3. DIVIPOLA via lib.dane_resolver — defensa final.
        # Origin solo usa (1)+(3) porque tenants.shipping_origin_dane SÍ está
        # garantizado al configurar Settings.
        origin_dane = (
            origin.get("dane_code")
            or resolve_dane_from_city(origin.get("city") or "", origin.get("state"))
        )
        dest_dane = (
            sm.get("dane_code")
            or addr.get("dane_code")
            or resolve_dane_from_city(addr.get("city") or "", addr.get("state"))
        )

        # BLOQUE B (item 5) — claim-before-bill (idempotencia anti guía DUPLICADA facturable).
        # Se computan los jsonb (NOT NULL de shipments) y se INSERTA una fila 'generating'
        # ANTES de facturar. El índice único parcial (tenant_id, order_id) WHERE status IN
        # ('generating','labeled','simulated') hace fallar un 2º INSERT concurrente/retry →
        # esa invocación NO factura (evita cobro duplicado real por webhook doble / cron).
        origin_addr_jsonb = {
            "city": origin.get("city"),
            "street": origin.get("street"),
            "dane_code": origin.get("dane_code"),
            "phone": tenant.get("telefono_contacto") or origin.get("phone"),
            "name": origin.get("name") or tenant.get("name"),
        }
        destination_addr_jsonb = {
            "city": addr.get("city"),
            "street": addr.get("street"),
            "apartment": addr.get("apartment"),
            "tower": addr.get("tower"),
            "building_type": addr.get("building_type"),
            "neighborhood": addr.get("neighborhood"),
        }
        # Schema shipments requiere `parcels` NOT NULL. F5: peso/dims cotizados de la guía.
        # UAT founder 2026-07-10: declared_value alineado a lo REALMENTE declarado a
        # Aveonline (merchandise_cop = mercancía sin flete), no al total con envío.
        parcels_jsonb = [{
            "weight_kg": float(_wi.get("weight_kg") or 0.5),
            "length_cm": float(_wi.get("length_cm") or 15),
            "width_cm": float(_wi.get("width_cm") or 10),
            "height_cm": float(_wi.get("height_cm") or 5),
            "declared_value_cop": merchandise_cop,
            "units": 1,
            "content": guide_content,
        }]
        try:
            _claim = supabase.table("shipments").insert({
                "tenant_id": tenant_id,
                "order_id": order_id,
                "carrier": selected_carrier_name or "aveonline",
                "status": "generating",
                "origin_address": origin_addr_jsonb,
                "destination_address": destination_addr_jsonb,
                "parcels": parcels_jsonb,
            }).execute()
            _claim_id = (_claim.data or [{}])[0].get("id")
        except Exception as _claim_exc:
            # unique_violation (o error DB): ya hay guía en progreso/generada para esta orden
            # → NO facturar (idempotente). El 2º webhook/retry/cron de reconciliación cae aquí.
            logger.info(
                "[WOMPI][AVEONLINE] guía ya reclamada/generada order=%s — skip idempotente: %s",
                order_id[:8], _claim_exc,
            )
            return False
        if not _claim_id:
            logger.warning(
                "[WOMPI][AVEONLINE] claim shipment sin id order=%s — abort", order_id[:8],
            )
            return False

        # Rev. 108 fix arquitectónico — ahora función async. Antes
        # usaba asyncio.new_event_loop() + run_until_complete, lo cual
        # fallaba ("Cannot run the event loop while another loop is
        # running") cuando se invoca desde context async (endpoint
        # FastAPI). Solución: función async, callers la awaitean directo.
        result = await cli.generate_guide(
            origin={
                "dane": origin_dane,
                "city": origin_city_norm or origin.get("city") or "",
            },
            destination={
                "dane": dest_dane,
                "city": dest_city_norm or addr.get("city") or "",
            },
            package=package,
            carrier={"idtransportador": carrier_rate_id},
            sender=sender,
            recipient=recipient,
            simulate=simulate,
        )
    except Exception as exc:
        # Excepción al facturar. Distinguir por si HUBO dinero en juego:
        #  - simulate=True → NO hubo cobro (guía simulada) → mover a 'pending_generation'
        #    (fuera del índice único) para permitir reintento seguro. Evita que el caso común
        #    (real guides OFF por default) quede varado silenciosamente.
        #  - simulate=False (guía REAL) → un TIMEOUT pudo facturar (AMBIGUO). Money-safe: dejar
        #    'generating' (en el índice → bloquea auto-retry) para resolución manual del operador
        #    (verificar en Aveonline) en vez de arriesgar doble cobro. Se persiste el error para
        #    que NO sea silencioso (el shipment queda con quote_response.error visible).
        _ambiguous_real = not simulate
        if _claim_id:  # None si la excepción ocurrió antes del claim (nada que actualizar)
            try:
                supabase.table("shipments").update({
                    "status": "generating" if _ambiguous_real else "pending_generation",
                    "quote_response": {
                        "error": str(exc)[:500],
                        "simulated": simulate,
                        "ambiguous_bill": _ambiguous_real,
                    },
                }).eq("id", _claim_id).eq("tenant_id", tenant_id).execute()
            except Exception as _upd_exc:
                logger.warning("[WOMPI][AVEONLINE] update claim tras excepción falló: %s", _upd_exc)
        logger.warning(
            "[WOMPI][AVEONLINE] generate_guide error order=%s simulate=%s (%s): %s",
            order_id[:8], simulate,
            "REAL ambiguo → claim 'generating', resolución manual" if _ambiguous_real
            else "simulado → 'pending_generation', reintentable",
            exc,
        )
        return False

    if not result.get("ok"):
        logger.warning(
            "[WOMPI][AVEONLINE] guía no generada order=%s code=%s err=%s",
            order_id[:8], result.get("code"), result.get("error"),
        )
        # Aveonline respondió NOT-OK → definitivamente NO facturó → mover el claim a
        # 'pending_generation' (fuera del índice único) para permitir un reintento seguro.
        # 2 intentos: si el UPDATE falla, el claim quedaría 'generating' bloqueando el retry.
        for _attempt in (1, 2):
            try:
                supabase.table("shipments").update({
                    "status": "pending_generation",
                    "quote_response": {
                        "error": result.get("error"),
                        "code": result.get("code"),
                        "simulated": simulate,
                    },
                }).eq("id", _claim_id).eq("tenant_id", tenant_id).execute()
                break
            except Exception as exc:
                logger.warning(
                    "[WOMPI][AVEONLINE] update pending shipment falló (intento %d): %s",
                    _attempt, exc,
                )
        return False

    # 6. Actualizar el claim con el tracking real (labeled/simulated). La guía YA se generó/
    #    facturó → guardar el tracking es crítico. 2 intentos; si falla una guía REAL, log a
    #    nivel error con el tracking (recuperable) — la guía existe en Aveonline aunque la DB falle.
    _upd_fields = {
        # Prioridad: carrier name del response Aveonline (más canónico) >
        # carrier del cart > provider name fallback.
        "carrier": (
            result.get("carrier_name") or selected_carrier_name or "aveonline"
        ),
        "status": "labeled" if not simulate else "simulated",
        "tracking_number": result.get("tracking_number"),
        "tracking_url": result.get("tracking_url"),
        "label_url": result.get("label_url"),
    }
    _persisted = False
    for _attempt in (1, 2):
        try:
            supabase.table("shipments").update(_upd_fields).eq(
                "id", _claim_id).eq("tenant_id", tenant_id).execute()
            _persisted = True
            break
        except Exception as exc:
            logger.warning(
                "[WOMPI][AVEONLINE] persist shipment err (intento %d): %s", _attempt, exc,
            )
    if not _persisted and not simulate:
        # Guía REAL facturada cuyo tracking NO se persistió → recuperación manual desde este log.
        logger.error(
            "[WOMPI][AVEONLINE] GUÍA REAL FACTURADA sin persistir order=%s tracking=%s "
            "label=%s (claim %s queda 'generating') — recuperar manualmente",
            order_id[:8], result.get("tracking_number"), result.get("label_url"),
            str(_claim_id)[:8],
        )
        return False
    logger.info(
        "[WOMPI][AVEONLINE] guía %s order=%s tracking=%s (simulate=%s)",
        "SIMULADA" if simulate else "REAL",
        order_id[:8], result.get("tracking_number"), simulate,
    )
    return True
