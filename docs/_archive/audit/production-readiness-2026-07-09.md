> **⚠️ ARCHIVADO — 2026-08-03.** Contenido histórico superado, conservado solo como registro. Estado vigente: docs/PLAN.md y .context/01-state.md.

---

# Auditoría de Production-Readiness — Tenant Console de Konvi
**FASE 0 del Prompt Maestro · 2026-07-09 · gate previo al Platform Console**

> **Metodología.** 28 auditores read-only en paralelo (18 módulos + 5 integraciones vs doc oficial + 5 flujos E2E), luego **verificación adversarial de los 49 hallazgos P0/P1** contra el código en HEAD (`develop`=`640ff565`=producción). Resultado de la verificación: **47 CONFIRMED · 1 PLAUSIBLE · 1 ALREADY_FIXED · 0 REFUTED** — los auditores casi no produjeron falsos positivos, y se recalibró la severidad de 14 hallazgos a la baja. **Este informe reporta solo lo verificado en HEAD.** Evidencia `file:line` en cada punto; las divergencias de integración citan la doc oficial vigente. Los `.context/*.md` están desactualizados (~rev.111) — la verdad es el código + git.

> ⚠️ **NO se implementó nada** (auditoría pura). Este documento termina con un **plan por bloques** que requiere tu aprobación antes de tocar código (§9).

---

## Resumen ejecutivo

- **266 hallazgos** en 9 ejes: **1 P0 · 48 P1 · 115 P2 · 102 P3**. Tras verificación adversarial: **1 P0 + 33 P1 confirmados** (34 críticos reales), 14 bajados a P2/P3, 1 ya resuelto.
- **Veredicto global:** el producto **NO está production-grade como un todo cableado**, aunque el *core* (bot/orchestrator, connector, API-gateway) sí lo está (85-88%). El problema no es el motor conversacional — es que **los flujos de negocio E2E tienen eslabones rotos** que tocan **dinero, envío, stock cross-canal, PII y RBAC**.
- **Patrón dominante (eje 2 + eje 9 — cableado/coherencia):** módulos que funcionan aislados pero **no conversan** con el resto del pipeline. Ej.: la cotización de Aveonline no está cableada al form de creación de pedidos; `orders.status` nunca se reconcilia con el estado real de la guía; un pedido de MeLi que pasa a pagado no decrementa stock; aplicar un cupón no invalida el link de pago vivo.
- **1 P0 de seguridad:** el bot (`get_claim_status`) puede exponer reclamos de **otros clientes del mismo tenant** por WhatsApp (PII enumerable). Prioridad absoluta.

### Madurez por módulo (estimación production-grade)

| Módulo | % | P0 | P1 | P2 | P3 |
|---|---|---|---|---|---|
| Ventas · Reclamos | **58%** | 1 | 2 | 7 | 3 |
| Canales · Mercado Libre | **58%** | 0 | 3 | 5 | 5 |
| Cotizador/Despachos Aveonline | **62%** | 0 | 5 | 7 | 2 |
| Ventas · Pedidos | **62%** | 0 | 5 | 9 | 2 |
| Productos · Catálogo + importación masiva | **68%** | 0 | 3 | 4 | 4 |
| Analítica: Métricas + Auditoría | **68%** | 0 | 2 | 1 | 7 |
| Ventas · Contactos | **70%** | 0 | 2 | 5 | 2 |
| Compras + Finanzas | **70%** | 0 | 2 | 5 | 4 |
| Configuración · Integraciones | **70%** | 0 | 2 | 4 | 4 |
| Dashboard home operativo | **72%** | 0 | 1 | 3 | 5 |
| Inbox conversacional | **72%** | 0 | 3 | 6 | 2 |
| IA: Knowledge Base + Agentes | **72%** | 0 | 1 | 6 | 3 |
| Ventas · Promociones/Cupones | **78%** | 0 | 1 | 3 | 3 |
| Productos · Categorías | **80%** | 0 | 0 | 3 | 7 |
| Configuración | **82%** | 0 | 2 | 3 | 3 |
| Connector WhatsApp | **85%** | 0 | 0 | 2 | 7 |
| Bot/Orchestrator | **85%** | 0 | 0 | 5 | 3 |
| API Gateway + transversales | **88%** | 0 | 0 | 3 | 5 |

---

## §1 · P0 — Crítico de seguridad (inmediato)

### 🔴 get_claim_status filtra reclamos de otros clientes del mismo tenant (PII enumerable por WhatsApp)
- **Módulo:**  · eje None · esfuerzo ?
- **Evidencia:** 
- **Verificación:** El query de GetClaimStatusTool.execute (services/ai-orchestrator/agentic/tools/claims.py:257-267) selecciona `reason, requested_amount, resolution_notes` de la tabla claims filtrando SOLO por `.eq("tenant_id", ctx.tenant_id)` y `.eq("ticket_number", args.ticket_number)`. No hay filtro por el cliente
- **Fix:** Añadir el filtro por cliente en el query: `.eq("customer_id", ctx.contact_id)` junto a tenant_id/ticket_number. Requiere guard: si `ctx.contact_id` es None (Optional en base.py:48), devolver tool_failure en vez de query sin filtro (fail-closed), para no reintroducir la fuga. Alternativamente resolver contact_id vía conversation_id si no viene poblado. Verificar que el flujo del orquestador siempre popula ctx.contact_id antes de habilitar el filtro estricto para no romper consultas legítimas.

---

## §2 · P1 verificados (33) — bloquean la operación real

Agrupados por bloque de trabajo (ver plan §9). Cada uno confirmado contra HEAD.

### B · Dinero (pagos / cupones)
**UI 'Eliminar' ejecuta el hard-purge cascade (testing/admin) y destruye orders/payments; el soft-delete legal (DELETE) es ruta muerta** _(eje None, esf ?)_
- Evidencia: 
- Fix: Desacoplar el botón 'Eliminar' de producción del purge cascade: (1) cablear la UI al DELETE /{id} (soft-delete/anonimización) que preserva orders/payments/audit por 10 años; (2) para resolver la contaminación cart-recovery que motivó el switch (comment page.tsx:588-596), hacer que delete_contact además expire/borre carts activos + conversations huérfanas SIN tocar orders/paymen

**Guard 'cupón antes del link' muerto (cart.status='checkout' nunca se escribe) + apply_coupon no invalida orden pending → link Wompi stale cobrable a precio pleno** _(eje None, esf ?)_
- Evidencia: 
- Fix: Dos partes: (a) En la rama de éxito de apply_coupon del dispatcher (~dispatcher.py:1653) y su espejo en orchestrator.py, tras _result.ok llamar invalidate_pending_order_on_cart_change(supabase, cart_id=_coupon_cart_id, tenant_id=tenant_id, reason='coupon_applied') — igual que add/remove item — para cancelar la orden pending + void del payment pending, e informar al cliente que 

**Wompi link amount truncated (int(total*100)) vs webhook rounds (int(round(total*100))) — percentage-coupon orders charged but never confirmed** _(eje None, esf ?)_
- Evidencia: 
- Fix: Alinear la creación del link a la misma cuantización que la validación: en orders.py:481 y wompi_webhook.py:450 usar int(round(total_amount*100)) en lugar de int(total_amount*100). Fix mínimo y suficiente. Mejor aún (defensivo): trabajar en centavos enteros desde el cart (total_cents = subtotal_cents + shipping_cents - discount_cents, todos int) y evitar el viaje float↔peso; o 

**Webhook Wompi fire-and-forget sin reconciliación wired: un APPROVED puede perderse permanentemente** _(eje None, esf ?)_
- Evidencia: 
- Fix: Cablear un job de reconciliación (worker periódico o pg_cron→endpoint interno) que seleccione orders pending_payment antiguas por tenant, consulte GET /transactions vía get_transaction_sync con creds del tenant, y si es APPROVED ejecute la ruta de confirmación idempotente (_confirm_order + notif + guía; los guards TERMINAL_STATES/dedup ya protegen). Persistir huérfanos en tabla

**Cart coupon discount silently re-applied to operator's manual Inbox order (no status/item guard)** _(eje None, esf ?)_
- Evidencia: 
- Fix: In create_order, do not inherit the cart discount for operator-initiated manual orders. Minimal, layered fix: (1) restrict the cart lookup to non-terminal carts — add .neq("status","converted") (or .in_ ['open','applied']) so a converted cart can never re-apply; (2) defense-in-depth: zero discount_cents on conversion (orders.py:618-622) so residual discount can't leak; (3) only

### C · Aveonline / envío
**Despacho Aveonline gobernado por flag GLOBAL de plataforma (AVEONLINE_GENERATE_REAL_GUIDES), no per-tenant; hoy toda guía es dummy** _(eje None, esf ?)_
- Evidencia: 
- Fix: 1) Reemplazar el env global por un ajuste per-tenant: columna booleana generate_real_guides en tenant_shipping_provider_config (default false); leerla dentro de _generate_shipping_guide_async keyed por tenant_id, y computar simulate = not tenant_cfg.generate_real_guides. Mantener el env AVEONLINE_GENERATE_REAL_GUIDES como kill-switch global (si false, forzar simulate en todos a

**Agentic Aveonline path drops weight_inputs → guide declares 0.5kg hardcode instead of cotized weight** _(eje None, esf ?)_
- Evidencia: 
- Fix: En legacy_adapters/aveonline.py, en la llamada set_quoted_options (lines 434-439), agregar weight_inputs derivado de `package` espejando shipping_quote_tool.py:1991-1996: weight_inputs={"weight_kg": round(float(getattr(package,"weight_kg",0.5)),3), "length_cm": float(getattr(package,"length_cm",15)), "width_cm": float(getattr(package,"width_cm",10)), "height_cm": float(getattr(

**Guía facturable duplicada en retry: shipments sin UNIQUE(order_id) + pre-check idempotencia con .limit(1) sin .order()** _(eje None, esf ?)_
- Evidencia: 
- Fix: 1) DB: añadir dedup real — o UNIQUE partial index `CREATE UNIQUE INDEX ON shipments(order_id) WHERE order_id IS NOT NULL AND status <> 'pending_generation'` (permite reintentar sobre pending pero bloquea 2 guías con tracking), o mejor UPSERT: en fallo insertar/updatear la fila pending por (tenant_id, order_id); en éxito UPDATE de esa misma fila a labeled+tracking en vez de INSE

**TTL de JWT Aveonline incoherente: web persiste 27.8h, cliente Python capa a 1h, y quote no hace refresh+retry en auth error (-2)** _(eje None, esf ?)_
- Evidencia: 
- Fix: Doble fix, aplicado a AMBAS copias (services/api/integrations/aveonline_client.py y services/ai-orchestrator/integrations/aveonline_client.py, mas apps/web): (A) Coherencia de TTL: en connectAveonline (aveonline-actions.ts:167) capar el jwt_expires_at persistido a <=3600s (o no persistir jwt_expires_at desde la web y dejar el refresh lazy del cliente Python), para que ambos pat

**Console PATCH status=cancelled bypasses the cancellation pipeline — no restock/void/guide-cancel/audit-row; console and bot diverge on cancellation** _(eje None, esf ?)_
- Evidencia: 
- Fix: Route the API cancellation through the shared pipeline instead of a bare status UPDATE. Options: (a) extract order_cancellation.cancel_order into a shared lib both api and ai-orchestrator import, or (b) have the API PATCH handler, when new_status=='cancelled' and current_status is beyond 'pending' (stock decremented / payment / guide), call an internal endpoint on ai-orchestrat

**Cotización Aveonline no cableada al form de creación de pedidos: shipping_cost es input manual que entra al total cobrado, y solo se puede cotizar después de confirmar** _(eje None, esf ?)_
- Evidencia: 
- Fix: Cablear el cotizador al form de creación: añadir botón 'Cotizar envío' en orders-new-form.tsx (y order-mini-form.tsx) que llame POST /api/v1/shipping/quote con destino/peso/items y prefille shippingCost con la tarifa Aveonline devuelta (quote_response). Hacer el campo read-only o al menos marcar override discrecional con warning + registro. Idealmente exigir cotización previa a

**orders.status never reconciles with Aveonline shipment state — order stays 'Confirmado' while shipment is delivered** _(eje None, esf ?)_
- Evidencia: 
- Fix: Add an auto-advance of orders.status when a terminal/relevant shipment event lands, keeping the operator override. Minimal: map internal_status→order_status (in_transit→shipped, delivered→delivered) and apply inside fn_record_shipment_tracking_event when v_inserted=1 and p_order_id IS NOT NULL, guarded by the same monotonic rank used in orders.py (_ORDER_STATUS_RANK) so it neve

**Guías Aveonline reales gated por env global AVEONLINE_GENERATE_REAL_GUIDES (default simulate), flag no per-tenant** _(eje None, esf ?)_
- Evidencia: 
- Fix: Reemplazar el env global por un flag per-tenant: añadir columna booleana en `tenants` (p.ej. `aveonline_real_guides`) y derivar `simulate = not bool(tenant.get("aveonline_real_guides"))` desde el dict `tenant` ya cargado en el webhook, con fallback seguro a simulate=True. Opcional: mantener el env como kill-switch global (AND con el flag por tenant). Actualizar docstring 703-70

### D · Mercado Libre
**Orden MeLi pending→paid nunca decrementa stock (oversell cross-canal)** _(eje None, esf ?)_
- Evidencia: 
- Fix: En la rama `if existing:` (línea 585-591), tras el UPDATE de status, detectar la transición a 'confirmed' y disparar el decremento: cuando `existing["status"] != "confirmed" and internal_status == "confirmed"`, llamar `_decrement_stock_for_meli_order(existing["id"], tenant_id, supabase)`. La guarda de idempotencia existente (stock_movements por order_id) evita doble decremento 

**MeLi stock sync zeroes unmapped native variations (import + legacy links; auto-triggered post-WhatsApp sale)** _(eje None, esf ?)_
- Evidencia: 
- Fix: In the no-mapping fallback (marketplace.py:141 and :580), when the MeLi item has variations and meli_variation_id is None, carry each variation's current available_quantity from the GET (`v.get("available_quantity")`) into the PUT payload so untracked variations are preserved rather than zeroed. Additionally harden meli_client.py:632-634 to not zero non-first variations (e.g. s

**Webhook MeLi: allowlist IP basada en X-Forwarded-For[0] (hop controlado por cliente) como única autenticación** _(eje None, esf ?)_
- Evidencia: 
- Fix: Defensa en profundidad, no depender de un solo control: (1) No confiar en XFF[0]. Derivar la IP real desde la contribución del proxy de confianza: tomar el hop rightmost tras descartar N hops de proxies confiables (número fijo/conocido de Render), o usar request.client.host si Render ya normaliza. (2) Validar `resource` contra un allowlist estricto antes del GET, p.ej. `re.full

**Pedido MeLi que transiciona pending→paid nunca decrementa stock (oversell cross-canal)** _(eje None, esf ?)_
- Evidencia: 
- Fix: En el branch `if existing:` (meli_webhook.py:585-591): tras el UPDATE de status, si `internal_status == "confirmed"` y el estado previo no era ya confirmed/processing/shipped/delivered, llamar `_decrement_stock_for_meli_order(existing["id"], tenant_id, supabase)`. El helper ya es idempotente (chequea stock_movements por order_id, líneas 390-400) y ya hace el push a MeLi vía syn

**Cancelación no repone stock en paths MeLi y consola; refund prometido no se ejecuta** _(eje None, esf ?)_
- Evidencia: 
- Fix: Extraer la orquestación de cancelación (restore stock + refund + re-sync canal) a un servicio compartido invocable desde los 3 entrypoints. Mínimo: (1) que orders.py patch_order en transición a 'cancelled' cree fila order_cancellations y ejecute restore+refund (o llame al pipeline vía API interna al orchestrator); (2) que _restore_stock reverse también movements con reason='sal

### E · Catálogo / stock / import
**Importación masiva rota E2E: el importador lee la hoja 'Instrucciones' (SheetNames[0]) en vez de la hoja de datos** _(eje None, esf ?)_
- Evidencia: 
- Fix: En mass-importer.tsx:135 seleccionar explícitamente la hoja de datos en vez de SheetNames[0]. Opción robusta: `const dataName = wb.SheetNames.find(n => n !== 'Instrucciones') ?? wb.SheetNames[0]; const ws = wb.Sheets[dataName]`. Alternativa mínima: invertir el orden de append (líneas 117-118) para que la hoja de datos quede primera — pero es frágil si Excel reordena; preferir l

**Importador colapsa precios inválidos/vacíos a $1 COP en silencio — producto vendible por el bot a 1 peso** _(eje None, esf ?)_
- Evidencia: 
- Fix: En import-template.ts, dejar de defaultear precios inválidos a 1: si `num(row[L.precioNormal])` es null o <=0, empujar la fila (SKU/nombre) a una lista de errores que groupRowsToProducts devuelva junto a los productos, y que la UI del importador muestre esas filas como rechazadas en lugar de importarlas. Añadir validación `pPromo < pNormal` análoga a catalog-form.tsx:469 (desca

**Cache transaccional trunca variantes a 6 (silencioso) → variantes 7+ invendibles, bot responde "no existe" pese a stock** _(eje None, esf ?)_
- Evidencia: 
- Fix: El cache transaccional (parsed_variants que consume el cart) NO debe truncarse — mismo principio ya aplicado a productos (comentario :10-14). Opciones: (1) eliminar el slice :MAX_VARIANTS_PER_PRODUCT para parsed_variants y truncar SOLO en la inyección al prompt (prompt/builder.py, system_prompt.py) igual que la Pieza 3 hace con productos; (2) mínimo interino: convertir MAX_VARI

**RLS FOR ALL en suppliers/purchase_orders/purchase_order_items permite escritura directa PostgREST que bypasea RBAC owner-only, audit_log y la lógica WAC/stock** _(eje None, esf ?)_
- Evidencia: 
- Fix: Espejar el fix de expenses en una migración nueva: para suppliers, purchase_orders y purchase_order_items → DROP POLICY "Tenants can manage their ..."; CREATE POLICY ... FOR SELECT USING (tenant_id = app_current_tenant()). Sin policy INSERT/UPDATE/DELETE para `authenticated`: las escrituras quedan solo para service_role vía services/api (donde ya viven RBAC owner-only, audit_lo

### F · Seguridad / RBAC / auditoría
**audit_log no es tamper-evident: cualquier miembro autenticado del tenant puede UPDATE/DELETE/forjar entradas vía PostgREST** _(eje None, esf ?)_
- Evidencia: 
- Fix: Aplicar a audit_log el mismo patrón append-only ya canónico en consent_audit_log: (1) REVOKE UPDATE, DELETE ON public.audit_log FROM authenticated, anon (conservar SELECT/INSERT para lectura vía RLS); (2) función SECURITY DEFINER que hace RAISE EXCEPTION + triggers BEFORE UPDATE y BEFORE DELETE (defensa en profundidad si alguien re-otorga el privilegio). Endurecimiento adiciona

**Pestaña 'Accesos a datos personales' rota: pii_access_log sin GRANT SELECT para authenticated** _(eje None, esf ?)_
- Evidencia: 
- Fix: Nueva migración con `GRANT SELECT ON public.pii_access_log TO authenticated;` (solo SELECT — mantener INSERT/UPDATE/DELETE restringidos a service_role; los triggers append-only + RLS tenant_isolation siguen protegiendo filas). Así la policy RLS existente (scoping por membresía tenant_users) por fin se aplica y la vista 'access' funciona. Alternativa: cambiar audit/page.tsx a us

**MFA bypasseable llamando el gateway público konvi-api (FastAPI) con access token AAL1** _(eje None, esf ?)_
- Evidencia: 
- Fix: Enforce AAL2 en el gateway FastAPI, no sólo en Next. Opción mínima: en _extract_jwt_payload (o una nueva dependency global aplicada a routers de negocio) leer el claim `aal` del JWT y, si el user tiene factor TOTP verified (consulta Supabase Auth admin / GoTrue factors por sub, o confiar en el claim `aal`+`amr`), rechazar 401 cuando aal=='aal1' pero el user requiere aal2. Como 

### G · Inbox / WhatsApp onboarding
**Enviar fuera de ventana 24h crashea el Inbox: backend devuelve detail dict, frontend lo renderiza como React child** _(eje None, esf ?)_
- Evidencia: 
- Fix: Normalizar detail a string en el punto de consumo. En inbox-manager.tsx:267-268: `const d = err?.detail; setSendError(typeof d === 'string' ? d : (d?.message ?? 'No se pudo enviar'))`. Idealmente aprovechar `d?.code` (WINDOW_EXPIRED/WINDOW_NO_INBOUND) para UI accionable (CTA plantilla). Mismo saneo en attachment-uploader.tsx:134 (`typeof data.detail === 'string' ? data.detail :

**Inbound customer media not viewable in Inbox: only media_id persisted, no proxy/URL for operator** _(eje None, esf ?)_
- Evidencia: 
- Fix: Add a tenant-scoped media proxy: web route GET /api/conversations/[conversationId]/media/[messageId] (verify session tenant owns the conversation+message via RLS/service_role eq tenant_id) that resolves media_id -> bytes using the per-tenant Meta token (reuse fetch_media_bytes logic) and streams with correct content-type; or download-once-to-Supabase-Storage at ingest (connecto

**WhatsApp webhook URL shown to tenant points to NXDOMAIN host and the wrong service — self-service Model B onboarding broken E2E** _(eje None, esf ?)_
- Evidencia: 
- Fix: Both layers must agree on the CONNECTOR host, not the API host. (1) Backend integrations.py:142 fallback → https://konvi-connector.onrender.com; add WHATSAPP_CONNECTOR_URL env to the konvi-api service in render.yaml (value konvi-connector.onrender.com until a connector.konvi.co / api.konvi.co→connector DNS decision is made per ADR-0023 OQ-4). (2) Frontend: stop hardcoding; exte

**Panel WhatsApp muestra/copia URL de webhook en dominio muerto (api.konvi.co NXDOMAIN) — rompe el handshake Meta día-1** _(eje None, esf ?)_
- Evidencia: 
- Fix: 1) Fuente única: añadir a webhook-urls.ts un host de CONNECTOR separado (el whatsapp webhook NO vive en el host de la API): p.ej. WEBHOOK_CONNECTOR_HOST = process.env.NEXT_PUBLIC_CONNECTOR_WEBHOOK_HOST || 'https://konvi-connector.onrender.com', más path '/api/v1/whatsapp/webhook' y builder que concatene /{tenantId}. 2) Reemplazar el string hardcodeado en whatsapp-setup.tsx:95-9

### H · Contactos
**Console persists phone in E.164 with '+' while ecosystem canon is digits-only → duplicate contacts, broken consent reactivation** _(eje None, esf ?)_
- Evidencia: 
- Fix: In services/api/routers/contacts.py, import lib.phone.to_db_format and normalize before persistence: in create_contact set payload['phone']=to_db_format(contact.phone) and payload['shipping_phone']=to_db_format(contact.shipping_phone); apply the same in patch_contact for any phone/shipping_phone writes — mirroring meli_webhook.py. This makes console writes collide correctly on 

### I · KB / Finanzas / Dashboard
**Anulación de gastos muerta E2E: falta POST /api/v1/expenses/{id}/reverse en el API** _(eje None, esf ?)_
- Evidencia: 
- Fix: Implementar en services/api/routers/expenses.py: `@router.post('/{expense_id}/reverse')` con `_role: str = Depends(require_write_role)` (o guard owner-only si la matriz lo exige), `@audit_log(entity_type='expense', action='reversed')`. Lógica: SELECT del gasto con `.eq('id', expense_id).eq('tenant_id', tenant_id)` (ADR-0025) → 404 si no existe; 409 si reversed_at ya no es null;

**RAG de KB sin detección de drift de versión de embedding + re-embed founder-gated tras migración a gemini-embedding-2** _(eje None, esf ?)_
- Evidencia: 
- Fix: 1) Acción founder inmediata: correr reembed_kb_documents.py --yes en prod (INTERVENCION HUMANA REQUERIDA, ya marcada por el auditor). 2) Bug adicional detectado en el propio script de fix: reembed_kb_documents.py solo hace update {"embedding": ...} y NO setea embedding_model_version → tras re-embeber, la columna de versión queda inconsistente, dejando cualquier futura detección

### J · Otros
**[Eje 2] Reclamos: resolución/reembolso/rechazo no notifica al cliente; la UI afirma al operador que sí** _(eje None, esf ?)_
- Evidencia: 
- Fix: 

---

## §3 · Recalibrados a la baja (14 → P2/P3) y 1 ya resuelto

- ✅ **YA RESUELTO en HEAD:**  — Code en HEAD ya está en gemini-embedding-2 en las 3 capas: services/ai-orchestrator/llm_embed.py:52-57 y services/api/lib/llm_embed.py:52-57 (default gemini-emb
- ↓ **P3** (auditor puso P1): Realtime de orders no publicado: cards de pedidos no reciben eventos propios (pero se refr — Hechos de código exactos: dashboard-client.tsx:130 suscribe a table:'orders'; ninguna migración ejecuta ALTER PUBLICATION supabase_realtime 
- ↓ **P2** (auditor puso P1): Guías fallidas de órdenes credit/Wompi no tienen botón de reintento en UI (badge misdirige — Real y vigente en HEAD. orders-manager.tsx:597-602 renderiza GenerateGuideButton solo con payment_method==='cod' && status==='confirmed'. Un
- ↓ **P2** (auditor puso P1): Inbox: la ventana 24h expirada es un callejón sin salida — la UI/API prometen "usa una pla — Verificado en HEAD. conversations.py:687-690 declara templates "fuera de scope hoy" y bloquea el envío; _check_24h_window_or_raise (694-741)
- ↓ **P2** (auditor puso P1): Form de creación de pedidos: selects nativos planos con cap silencioso de 1000, sin búsque — Todo lo alegado existe en HEAD. page.tsx:29 define FORM_SELECT_LIMIT=1000; page.tsx:115-127 carga products (select 'id, title, product_varia
- ↓ **P2** (auditor puso P1): Rol operator ve boton 'Nuevo Reclamo' pero POST /api/v1/claims lo rechaza con 403 (contrad — La contradiccion de 3 fuentes es real y vigente en HEAD. (1) UI: apps/web/app/dashboard/(sales)/claims/page.tsx:18 `canWrite = ['owner','man
- ↓ **P2** (auditor puso P1): DPA §5.bis placeholder (Model B app_secret custody) — real pre-onboarding legal gap + unco — Factual claims all verified. (1) apps/web/public/docs/legal/dpa.md is modified uncommitted (git status: not staged; diff = +38 lines). (2) H
- ↓ **P2** (auditor puso P1): "Enviar a revisión" dialog is a no-op: no submit record, no notification to Konvi team — Verified in HEAD. whatsapp-templates.tsx:784 — the submit dialog's only control is a "Entendido" button that calls setSubmitFor(null); no fe
- ↓ **P2** (auditor puso P1): Cotización COD envía valorrecaudo=0 / idasumecosto=0, divergiendo de la guía real (valorre — Divergencia código↔código confirmada y vigente en HEAD. aveonline_client.py:447-451 (quote): siempre idasumecosto=0, valorrecaudo=0, valorMi
- ↓ **P2** (auditor puso P1): El cliente no recibe notificación push al resolverse/reembolsarse su reclamo (diseño pull- — Verificado en HEAD. services/api/routers/claims.py — los tres paths de mutación (patch_claim, resolve_claim, create_claim) solo hacen supaba
- ↓ **P2** (auditor puso P1): Claims 'refunded' es solo un estado: sin monto reembolsado real, sin refund_txn, sin track — El gap central es real y vigente en HEAD. La tabla `claims` (supabase/migrations/20260413150000_claims.sql) solo tiene columnas monetarias `
- ↓ **P2** (auditor puso P1): Inbox operator flow has no "cobrar-primero" path: mini-form hardcodes auto_confirm, consol — All cited evidence is accurate in HEAD. order-mini-form.tsx:106 hardcodes auto_confirm:true → backend (orders.py:281-291) forces status=conf
- ↓ **P2** (auditor puso P1): Onboarding WhatsApp de tenants externos: gate DPA §5.bis solo en docs, sin enforcement en  — Las tres afirmaciones del auditor se verifican en HEAD. (1) docs/legal/dpa.md:57-93 §5.bis es placeholder explícito ("PLACEHOLDER — CLÁUSULA
- ↓ **P2** (auditor puso P1): WhatsApp notifica guía dummy sin tag SIMULADA en modo dry-run (email sí lo tagea) — Cadena verificada en HEAD. render.yaml fija AVEONLINE_GENERATE_REAL_GUIDES="false" en api (línea 207) y worker (~312). wompi_webhook.py:1586
- ↓ **P2** (auditor puso P1): MeLi webhook IP allowlist hardcodes 4 IPs; alleged 8-IP official list unverifiable — see above

---

## §4 · Integraciones vs documentación oficial

### Integración Aveonline — 78%
Integración madura y bien defendida: auth JWT con refresh y TTL capado a 1h (coincide con doc oficial), cotización multi-carrier, generación de guía, receiver de webhook con secret+dedup+rate-limit cuyo payload calza EXACTO con la doc oficial (guia/pedido_id/estado[].estado_id/nombre_estado/fecha), registro de webhook cableado a endpoint owner, cancelación con escalación a operador, y parity test que guarda la duplicación api↔orchestrator. Gaps production-grade: (1) la cotización COD envía valorrecaudo=0/idasumecosto=0 mientras la guía envía valorrecaudo=total/idasumecosto=1 — contradice los e

**Citas verificadas:**
- Endpoint cotización nacional = POST https://app.aveonline.co/api/nal/v1.0/generarGuiaTransporteNacional.php con tipo='cotizar2' (cotizarDoble NO docum — <https://integraciones.aveonline.co/docs/nacional/cotizacion/>
- Modos de pago documentados en cotización: Credit contraentrega=0/idasumecosto=0/valorrecaudo=0; COD contraentrega=1 con valorrecaudo=[amount] e idasum — <https://integraciones.aveonline.co/docs/nacional/cotizacion/>
- Tabla numbererror oficial de cotización: -0 sin errores, -1 origen inválido, -2 destino inválido, -3 peso ≤0, -4 unidades ≤0, -5 valor declarado <10.0 — <https://integraciones.aveonline.co/docs/nacional/cotizacion/>
- Generación de guía: tipo='generarGuia2' al mismo endpoint; campos dsdirre/dsnitre/dstelre/dscelularre/dscorreopre/dsnombre (remitente), dsdir/dsnit/ds — <https://integraciones.aveonline.co/docs/nacional/generacionGuia/>
- Response de guía: resultado.guia con numguia, rutaguia (printable guide URL), rotulo, rutasticker (sticker térmico 110x120), archivorotulo/archivostic — <https://integraciones.aveonline.co/docs/nacional/generacionGuia/>
- Auth oficial: POST https://app.aveonline.co/api/comunes/v1.0/autenticarusuario.php con tipo='auth', usuario, clave; token JWT 'con vigencia de una hor — <https://integraciones.aveonline.co/docs/nacional/autenticacion>

### Integración Wompi — 82%
Integración madura y en su mayoría FIEL a la doc oficial: POST /v1/payment_links con campos correctos (name/description/single_use/collect_shipping/amount_in_cents/currency=COP/expires_at ISO8601 UTC/sku=order_id 36 chars/redirect_url), checkout URL https://checkout.wompi.co/l/{id} correcto, decisión documentada de NO enviar customer_data (doc confirma que solo acepta customer_references) correcta. Firma de eventos implementada exactamente como la doc: SHA256 simple (no HMAC) de concat(valores de signature.properties resueltos data-relative + timestamp + events_key), uppercase, comparación con

**Citas verificadas:**
- Eventos webhook: tipos transaction.updated / nequi_token.updated / bancolombia_transfer_token.updated; el código procesa solo transaction.updated (cor — <https://docs.wompi.co/en/docs/colombia/eventos/>
- Algoritmo de firma de eventos: SHA256 simple (no HMAC) de concat(valores de signature.properties + timestamp UNIX + events secret), resultado en hex u — <https://docs.wompi.co/en/docs/colombia/eventos/>
- Doc exige NO asumir signature.properties como array fijo — el código itera properties dinámicamente (wompi_client.py:127-134), COINCIDE — <https://docs.wompi.co/en/docs/colombia/eventos/>
- Política de reintentos: máx 3 en 24h (30 min, 3 h, 24 h) hasta obtener 200 — el comment de wompi_webhook.py:9-10 COINCIDE; pero como el handler siempr — <https://docs.wompi.co/en/docs/colombia/eventos/>
- No existe event.id oficial en el payload de eventos — el dedup por signature.checksum (wompi_webhook.py:65-70, 131-163) es una alternativa razonable,  — <https://docs.wompi.co/en/docs/colombia/eventos/>
- El payload del evento incluye data.transaction.payment_link_id (correlación usada por el webhook, wompi_webhook.py:73) y environment: 'test'|'prod' (N — <https://docs.wompi.co/docs/colombia/eventos/>

### Integración Meta WhatsApp Cloud API — 85%
Integración madura y mayormente alineada con la doc oficial vigente: v22.0 sigue soportado (newest v25.0, sin fecha de expiración anunciada para v22.0); HMAC SHA-256 per-tenant con raw body + compare_digest + invariant cross-tenant (dependencies/meta.py:357-447) es correcto per doc; handshake GET hub.challenge correcto (routers/webhook.py:34-67); ventana CSW 24h enforced en API Inbox (conversations.py:687-736, 422 accionable) y en worker (free-form solo dentro de CSW, HSM UTILITY/MARKETING fuera); categorías de plantilla MARKETING/UTILITY/AUTHENTICATION correctas (whatsapp_templates.py:43); ci

**Citas verificadas:**
- v22.0 sigue disponible/soportado (lanzado 2025-01-21, expiración 'por determinar'); versión más nueva v25.0 (2026-02-18); v19.0 expira 2026-05-21, v20 — <https://developers.facebook.com/docs/graph-api/changelog>
- Mensajes type=image soportan SOLO JPEG y PNG (8-bit RGB/RGBA), máx 5MB; caption máx 1024 chars (el código respeta 1024 en conversations.py:1268 e imag — <https://developers.facebook.com/docs/whatsapp/cloud-api/messages/image-messages>
- Media: imagen 5MB, audio/video 16MB, documentos 100MB; WebP solo para stickers (100KB/500KB); URLs de media expiran en 5 minutos (código: cache TTL 24 — <https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media>
- Pricing per-message (PMP) vigente desde 2025-07-01; solo se cobra al entregar template messages; mensajes no-template dentro de CSW abierta son gratis — <https://developers.facebook.com/docs/whatsapp/pricing>
- Límites de mensajería: tiers de 250 / 2.000 / 10.000 / 100.000 / ilimitado destinatarios únicos business-initiated (fuera de CSW) por ventana móvil de — <https://developers.facebook.com/docs/whatsapp/messaging-limits>
- Webhooks: firma SHA-256 en header X-Hub-Signature-256 formato 'sha256={sig}' con App Secret (código CORRECTO: dependencies/meta.py:357-364 HMAC sobre  — <https://developers.facebook.com/docs/graph-api/webhooks/getting-started>

### stack-versions — 88%
Higiene de versiones muy buena en HEAD (640ff565): Next 15.5.20 es el último backport 15.x con todos los CVEs de mayo-2026 parchados; modelos Gemini de texto todos GA (3.1-flash-lite / 3.5-flash, preview retirado de tiers); embeddings ya migrados a gemini-embedding-2 (3072-dim, coincide con schema vector(3072)) en código + render.yaml + web routes; @supabase/ssr con getAll/setAll en server.ts y getUser() (nunca getSession) para protección. Riesgos restantes: (1) NO verificable desde el repo si el re-embed de kb_documents en prod se ejecutó — gemini-embedding-001 se apaga 2026-07-14 (5 días) y 

**Citas verificadas:**
- gemini-embedding-001 (estable) se retira el 2026-07-14 con reemplazo gemini-embedding-2; gemini-2.5-flash/-lite/-pro se retiran el 2026-10-16; text-em — <https://ai.google.dev/gemini-api/docs/deprecations>
- gemini-3.5-flash y gemini-3.1-flash-lite son modelos ESTABLES (GA) — los tiers default del bot (llm_cascade.py) usan solo modelos GA; gemini-3.1-pro s — <https://ai.google.dev/gemini-api/docs/models>
- gemini-embedding-2: default 3072 dims (coincide con vector(3072) del schema), MRL 128-3072, auto-normaliza truncados, NO usa task_type, espacios incom — <https://ai.google.dev/gemini-api/docs/embeddings>
- Patrón vigente @supabase/ssr: adapter cookies getAll/setAll (único documentado); 'Always use supabase.auth.getClaims() to protect pages'; 'Never trust — <https://supabase.com/docs/guides/auth/server-side/nextjs>
- Next.js 15 en Maintenance LTS con fin de soporte 2026-10-21; Next 16 (Active LTS) released 2025-10-22, latest 16.2.10 — <https://nextjs.org/support-policy>
- Los 12 CVEs de mayo-2026 (middleware bypass, XSS, SSRF, cache poisoning, DoS) están parchados en Next 15.5.18+ — el repo instala 15.5.20 (dist-tag 'ba — <https://vercel.com/changelog/next-js-may-2026-security-release>

### Integración Mercado Libre — 70%
Integración madura en su núcleo: OAuth con state HMAC firmado + nonce one-time + Vault (meli_client.py:97-175, integrations.py:217-319), refresh automático con rotación (meli_client.py:296-387), webhook IPN con defensa por IP + rate-limit + dedup distribuida RPC (meli_webhook.py:80-234, worker.py:977 cron cleanup), ingesta orders_v2/items/shipments con aislamiento tenant correcto, import unitario/bulk con rollback, sync de stock bidireccional cableado a ventas WhatsApp (orders.py:745,833 — fix F4) y UI completa (marketplace-manager + actions.ts + meli-setup). Tests dedicados existen (oauth sta

**Citas verificadas:**
- MeLi envía notificaciones desde 8 IPs: 54.88.218.97, 18.215.140.160, 18.213.114.129, 18.206.34.84, 35.236.253.169, 35.245.91.34, 35.245.20.104, 35.186 — <https://developers.mercadolibre.com.co/es_ar/productos-recibe-notificaciones>
- Requisito webhook: responder HTTP 200 en 500ms; reintentos durante 1h; fallos sostenidos desactivan tópicos por fallback sin guardar en my feeds — el  — <https://developers.mercadolibre.com.co/es_ar/productos-recibe-notificaciones>
- missed_feeds: GET https://api.mercadolibre.com/missed_feeds?app_id=$APP_ID guarda notificaciones perdidas hasta 2 días — no usado en el repo — <https://developers.mercadolibre.com.co/es_ar/productos-recibe-notificaciones>
- Tópicos disponibles: orders_v2 (recomendado), orders feedback, messages, price_suggestion, items, questions, stock-location, shipments, fbm_stock_oper — <https://developers.mercadolibre.com.co/es_ar/productos-recibe-notificaciones>
- Novedad oficial: reintentos de notificaciones reducidos de 8 a 5 en el intervalo de 1 hora (comentarios del código aún dicen 8) — <https://developers.mercadolibre.com.co/es_ar/notificaciones>
- OAuth: access_token expira a las 6 horas (código correcto: expires_in + refresh preventivo a <1h); PKCE opcional salvo que la app lo habilite (entonce — <https://developers.mercadolibre.com.co/es_ar/autenticacion-y-autorizacion>

---

## §5 · Flujos E2E (coherencia como un todo — eje 9)

### Flujo E2E: pedido manual del operador — 68%
- **Veredicto:** La plomería base es sólida y convergente: takeover silencia al bot (orchestrator.py:6822), mensajes del operador van por cola durable al canal Meta per-tenant con ventana 24h enforced, y tanto bot como operador crean pedidos por el MISMO Core API (create_order → payment-link → wompi_webhook → stock/notify/guía). Sin embargo, el flujo del operador NO cierra como un solo producto: el mini-form del I
- **Cadena:** Takeover Inbox → WIRED (chat-panel → PATCH status → bot skip + send 24h→pgmq→Meta) || Crear pedido desde conversación → PARTIAL (mini-form→Core API OK con idempotencia+ownership, pero auto_confirm hardcoded: sin COD ni cobrar-con-link; descuento de cart ajeno se cuela) || Mismo pipeline que el bot → PARTIAL (converge en Core API + webhook + _decrement_stock_on_confirm; diverge en cart/reservas/descuento con contaminación cruzada) || Link de pago desde consola → PARTIAL (existe solo para pending/

### E2E: post-venta y dinero de vuelta — 55%
- **Veredicto:** La mitad frontal del flujo es production-grade: entrega (webhook Aveonline → shipment_events → shipments.status + notificación WA/email al cliente), registro de reclamo por bot (create_claim en todos los estados FSM, ticket # secuencial per-tenant, Telegram al operador) y por consola (server action → API con RBAC, vocabulario de estados alineado UI↔API↔CHECK DB, guards de reapertura, audit_log). L
- **Cadena:** 1) Pedido delivered (courier→shipments+notif cliente): wired / (courier→orders.status): partial — nada actualiza orders.status a 'delivered', queda 'shipped' salvo avance manual en consola → 2) Reclamo vía bot: wired (create_claim + ticket# + Telegram op) → 3) Reclamo vía consola: wired (actions.ts → API claims + RBAC + audit) → 4) Resolución consola: wired (PATCH + guards reopen; POST /resolve sin guard de transición: partial) / consulta de estado por bot: partial (mapa status_human obsoleto re

### E2E: tenant día-1 — 80%
- **Veredicto:** El flujo día-1 está mayormente cableado y production-grade: provision_tenant (script + RPC transaccional con agentic default, 26/26 migraciones aplicadas), primer login (recovery link + /auth/confirm con WEB_APP_URL fix), dashboard con onboarding first-run (steps whatsapp/catálogo/threshold), settings con defaults ante fila ausente, catálogo alta + import masivo vía POST /api/v1/products/bulk, cat
- **Cadena:** provision_tenant(script+RPC+agentic default)→WIRED · primer login owner(recovery→/auth/confirm→set-password→/dashboard)→WIRED · settings mínimos(PATCH /api/v1/settings/tenant, defaults fila ausente, origen despacho)→WIRED · catálogo alta/import(mass-importer→POST /products/bulk)→WIRED · categorías(product_categories)→WIRED · WhatsApp captura 6 credenciales(Vault+tenant_integrations)→WIRED · URL webhook mostrada al tenant→BROKEN (api.konvi.co NXDOMAIN hardcoded front + default API; env ausente en

### E2E: venta conversacional completa — 78%
- **Veredicto:** La cadena está cableada de punta a punta hasta el pago con ingeniería defensiva real (HMAC per-tenant Vault, dedup, validación monto/moneda fail-closed, idempotencia, colas pgmq, notificaciones WA+email por etapas). El quiebre está en la cola de fulfillment: (1) en prod las guías Aveonline son SIMULADAS por config (render.yaml AVEONLINE_GENERATE_REAL_GUIDES="false") — el cliente pagante recibe por
- **Cadena:** inbound Meta HMAC per-tenant (connector webhook.py:135 + dependencies/meta.py)→WIRED · persistencia messages/conversations/contacts (db_persistence.py:102-293)→WIRED · worker poll+claim+coalesce (worker.py:334-577)→WIRED · agentic/FSM/tools cart (agentic/*, cart_tool)→WIRED · cotización envío (shipping_quote_tool.py:1462 → api /shipping/quote → AveonlineClient per-tenant)→WIRED · orden via Core API con X-Internal-Service-Secret (payment_link_tool.py:206-214, orders.py:126)→WIRED · link Wompi per

### E2E: catálogo multi-canal — 70%
- **Veredicto:** El flujo existe de punta a punta y está mucho más cableado de lo que sugieren los docs históricos: alta/import de producto vía API con contrato de atributos ADR-0029, catálogo inyectado al bot en vivo (query fresca por turno, stock disponible = bruto − reservas, sin cache stale), OAuth MeLi per-tenant con tokens en Vault + refresh automático, webhook IPN con allowlist de IPs + dedup distribuido, y
- **Cadena:** 1) Producto creado (web→API products.py con validación) / importado de MeLi (marketplace.py _import_meli_item con rollback atómico) → WIRED · 2) Atributos por contrato de categoría (products.py:240-271 valida vs product_attribute_definitions en create/patch) → WIRED (import MeLi lo omite: partial menor) · 3) Visible al bot → WIRED (catalog_tool.get_tenant_catalog: query viva por turno, stock disponible descuenta reservas activas, atributos product-level citables; no hay cache = no hay staleness)
---

## §6 · Backlog P2 (115) — incompletitud funcional / UX que degrada el día a día

Resumen por módulo (uno por línea; detalle completo en el journal de auditoría). Entran en los bloques del plan como 'pulido del módulo'.

**API Gateway + transversales** (3):
- [EJE 9/4] PATCH/DELETE /api/v1/settings/team vivos sin consumidor y divergentes (más débiles) que las server actions del Team page
- [EJE 8] Sin handler global de excepciones: los 500 rompen el contrato de error es-CO y pierden el request_id de correlación
- [EJE 9/2] Cutover GEMINI_API_KEY incompleto: /api/insights (web) no tiene espejo en FastAPI, bloqueando el retiro de la key del se

**Analítica: Métricas + Auditoría** (1):
- Cero cobertura de auditoría para mutaciones del bot: ai-orchestrator no escribe ni un evento en audit_log

**Bot/Orchestrator** (5):
- Extracción de inbounds recientes muerta: filtra por 'role' pero el history usa 'direction' — guard anti-asunción de variantes degr
- Opt-out/re-opt-in: lookup de contacto por phone exacto sin normalizar '+' — STOP puede no revocar consent silenciosamente
- Telemetría de costo LLM write-only: total_tokens se persiste pero ningún consumidor la lee (decisión F5 'insumo de pricing/límites
- Peor caso de cascada saturada (~5 min/llamada) excede heartbeat 120s y reclaim 3 min; fallo terminal deja al cliente en silencio t
- Recordatorio de pago free-form no verifica conversación opted_out (asimetría con el path HSM que sí respeta consent_revoked_at)

**Canales · Mercado Libre** (5):
- Cancelación de orden MeLi no restaura stock
- Preguntas y mensajería post-venta MeLi inexistentes (paridad núcleo del canal)
- No se pueden publicar productos del catálogo hacia MeLi (flujo unidireccional import-only)
- Sin reconciliación de notificaciones perdidas ni backfill de órdenes al conectar
- Race de refresh token (single-use en MeLi) sin lock cross-réplica puede matar la integración

**Compras + Finanzas** (5):
- Recepción/creación/edición de OC no atómicas: multi-write sin transacción deja estados corruptos a mitad de fallo
- Lost update de stock_quantity: receive de OC y decremento por venta hacen read-modify-write concurrente sin operación atómica
- RBAC drift: /dashboard/purchases sin guard server-side de rol y GETs del router sin restricción — manager/operator ven costos/márg
- RBAC drift server-side en gastos: el API acepta manager (require_write_role) donde la matriz y la UI exigen owner
- Cero tests backend para purchases.py y expenses.py: WAC, idempotencia de receive y RBAC sin red de seguridad

**Configuración** (3):
- 'Lectura-solo' del grace period solo se aplica en CORE_API — las server actions que escriben directo a Supabase lo ignoran
- RLS permite a manager UPDATE de TODAS las columnas de tenants mientras la API y la UI son owner-only
- Cancelar la eliminación no restaura los métodos de pago y el copy no lo advierte — el bot queda sin formas de pago en silencio

**Configuración · Integraciones** (4):
- Wompi queda 'connected' sin validar las llaves contra la API — estado de conexión no veraz para el flujo de dinero
- Rotar credenciales WhatsApp destruye tier/quality_signal del número: el upsert reemplaza credentials completo pese a documentarse 
- Cambiar el chat_id de Telegram no revoca la identidad del grupo anterior — el grupo viejo conserva autoridad /resolver y /estado
- Telegram setWebhook es intervención manual del founder por cada tenant — los comandos de operador no son self-service

**Connector WhatsApp** (2):
- Reacciones y tipos de mensaje no gobernados caen al LLM como texto placeholder — el bot improvisa respuesta a un 👍
- ACK 200 antes de persistir, sin retry ni dead-letter: fallo transitorio de Supabase o restart de Render pierde mensajes de cliente

**Cotizador/Despachos Aveonline** (7):
- Cotización consola ≠ cotización bot: mismo cliente HTTP pero reglas de negocio divergentes (semilla founder)
- order_id aceptado pero nunca persistido en la cotización → sync de orders.shipping_cost es código muerto
- La UI promete 'polling backup cada 6h' que no existe; sin webhook configurado el tracking muere en silencio
- Estado del shipment puede RETROCEDER con eventos históricos: update sin comparar occurred_at
- Contenido de la guía hardcoded 'Productos cosmética artesanal' — KAIU-specific en código multi-tenant
- Novedades (exception) y devoluciones (returned) no llegan a ningún operador
- Historial mezcla cotizaciones-estimador con despachos reales; KPI 'Total envíos' cuenta ruido (semilla founder)

**Dashboard home operativo** (3):
- [eje 9] Counts de conversaciones ignoran archived_at: cifras del home (y badge del sidebar) infladas e incoherentes con lo que el 
- [eje 6] Deep-links de las OpsCards aterrizan sin el filtro que la alerta promete: el operador debe re-buscar lo que la card ya ide
- [eje 6] Pestaña 'Negocio' es acumulado all-time sin un solo KPI de dinero — no es control de negocio real para el operador diario 

**E2E: catálogo multi-canal** (4):
- Ítems MeLi multi-variación: solo 1 variación vinculable y el sync fuerza a 0 las demás variaciones en MeLi
- Decremento de stock directo es read-then-write no atómico — carrera cross-canal puede perder unidades
- Detección de drift precio/stock es pasiva: solo existe como badge al abrir la página Marketplace
- Cero cobertura de tests sobre el money-path de ingesta MeLi (_process_order / decremento / transiciones)

**E2E: post-venta y dinero de vuelta** (5):
- orders.status nunca se sincroniza a 'delivered' desde el courier: la orden queda 'shipped' aunque el cliente ya recibió y fue noti
- Finanzas y Métricas incoherentes entre sí y con la realidad del reembolso: P&L no descuenta reembolsos; Métricas suma requested_am
- Devolución física ('returned' del courier) muere en un log: sin alerta al operador, sin restock, sin cambio en la orden
- No existe cola/vista de reembolsos manuales pendientes: el índice DB pending_manual no tiene consumidor y el único aviso es un Tel
- Consola no puede cancelar/reembolsar pedidos post-confirmación: el pipeline completo (void+restock+guía+audit) solo es alcanzable 

**E2E: tenant día-1** (1):
- Submit de plantillas HSM a Meta: el tenant 'solicita' pero no existe cola, transición de estado ni notificación al equipo Konvi — 

**E2E: venta conversacional completa** (4):
- [eje 4/9] Flag de guías reales es env global por servicio, no per-tenant — contradice su propio contrato y bloquea multi-tenant
- [eje 9] orders.status nunca avanza a shipped/delivered — bot y lista de Pedidos reportan 'confirmado' después de la entrega
- [eje 8/5] Tracking depende 100% del webhook Aveonline: sin polling fallback y sin retry documentado del provider
- [eje 9/3] Contenido del paquete hardcodeado 'Productos cosmética artesanal' en guía y parcels — inválido para otros tenants/vertic

**Flujo E2E: pedido manual del operador** (4):
- El decremento de stock del pedido manual puede consumir las reservas del cart del bot (ítems distintos) y marcar ese cart como con
- Despacho sin path UI para pedidos manuales credit-confirmados: botón de guía gated a COD aunque el backend acepta cualquier confir
- Reenvío del link de pago vía wa.me: sale por el WhatsApp personal del operador, fuera del canal oficial del tenant y sin quedar en
- confirm_rate actualiza orders.shipping_cost sin recomputar total_amount: total del pedido queda desalineado de ítems+envío

**IA: Knowledge Base + Agentes** (6):
- Toggle strict_guardrails ("Zero-Hallucinations Activo") muerto en el runtime agentic de producción
- kb_query filtra markers con prefijo stale "[NO_DATA" — los markers sintéticos reales pasan como documentos encontrados con instruc
- Triple implementación de preview/index con drift real y GEMINI_API_KEY todavía expuesta al servicio web (drift D3 abierto)
- Preview del bot no es fiel al runtime real (prompt, RAG y tools distintos)
- RBAC/plan-capability drift en /dashboard/ai-agents: sidebar owner-only + capability, página permite manager y no valida capability
- Sin superficie de trace/diagnóstico del bot para el operador — agentic_shadow_log se escribe pero ninguna UI lo lee

**Inbox conversacional** (6):
- BUG FOUNDER emojis tofu: regresión F1 — body .font-sans pisa el stack de fuentes emoji del fix A7 (CSS muerto desde 2026-07-04)
- Crear Pedido desde Inbox: envío a discreción manual sin cotización Aveonline, pese a que POST /shipping/quote ya existe y está pro
- Pedido desde Inbox se crea 'confirmed' descontando stock sin ruta de pago: ignora payment_link/Wompi que la API de orders ya sopor
- Catálogo del panel/picker de pedidos capado a 100 productos y product_count miente (cuenta la página capada, no el total)
- Botón 'Rerun IA' visible para rol operator pero el endpoint exige write role (owner/manager) → 403 con mensaje genérico
- Búsqueda, filtros y contador SLA operan solo sobre la ventana cargada (50 convs iniciales) — sin búsqueda server-side

**Integración Aveonline** (3):
- Mapeo numbererror contradice la tabla oficial: 'Destino no existe' (-2) se reporta como credenciales inválidas y 'Peso ≤ 0' (-3) c
- Sin reconciliación ante webhooks de estado perdidos: get_estado (obtenerEstadoAuth) implementado pero con CERO callers, y Aveonlin
- cancel_guide usa tipo='cancelarGuia' que NO existe en la doc oficial — la cancelación de órdenes con guía depende de un endpoint n

**Integración Mercado Libre** (9):
- Campos leídos de GET /shipments/{id} no existen en la estructura documentada (order_id, shipping_option, estimated_delivery_final)
- Defensa de origen del webhook bypasseable: se confía en X-Forwarded-For[0] (spoofeable)
- Revocación de token usa endpoint no documentado (DELETE /oauth/token) — el disconnect no revoca el grant real
- Rama muerta: la integración nunca se marca status='error' cuando el refresh falla — degradación silenciosa sin 'Reconectar' en UI
- Refresh token single-use sin single-flight: carreras concurrentes y fallo parcial pueden invalidar la integración
- Máquina de estados de órdenes incompleta: faltan partially_refunded/pending_cancel, regresión de estado sin rank guard, y cancelac
- Sin manejo de 429/backoff en el cliente MeLi pese a guía oficial; cuota por client_id compartida entre todos los tenants
- Sin recuperación de notificaciones perdidas (missed_feeds) ni reconciliación periódica de órdenes
- Items MeLi multi-variación: el sync pone en 0 el stock de las variaciones no mapeadas

**Integración Meta WhatsApp Cloud API** (2):
- MIME de imagen divergente de doc oficial: webp/gif aceptados en toda la cadena pero Meta solo soporta JPEG/PNG en type=image
- Pérdida potencial de inbound: ACK 200 inmediato + persistencia en BackgroundTasks in-process sin cola durable ni dead-letter

**Integración Wompi** (1):
- Conversión a centavos inconsistente (truncación vs round) puede rechazar como monto_mismatch un pago APPROVED legítimo

**Productos · Categorías** (3):
- Bug founder: el 'tipo metric/boolean/number/text' NO está en el form de crear categoría — es el editor de atributos mostrando toke
- is_required existe en DB y API pero está muerto: ni la consola lo expone ni products.py lo hace cumplir
- Los atributos variant-axis NO se validan server-side contra el contrato — promesa anti-alucinación parcial

**Productos · Catálogo + importación masiva** (4):
- Bulk import no valida atributos contra el contrato ADR-0029 (ni permite atributos product-level/safety_note) — bypass del anti-alu
- Reporte del importador no es granular: filas descartadas en silencio, errores sin número de fila, aborte total si una categoría es
- Ajuste manual de stock escribe directo a Supabase: sin sync MeLi, no atómico y con race read-modify-write contra la venta del bot
- Upsert bulk por (tenant_id, sku) puede re-parentar variantes a otro producto en silencio

**Ventas · Contactos** (5):
- [EJE 9] Consent otorgado vía bot (variante dominante) no estampa consent_source, consent_channel ni consent_notice_version
- [EJE 3] Export SAR omite conversaciones/mensajes (su docstring dice incluirlas) y el erase no toca PII embebida en messages
- [EJE 6] Ficha de contacto sin historial navegable a pedidos/conversaciones pese a que el consumo ya existe
- [EJE 6] Listado cap 500 con búsqueda solo en memoria: contactos creados por el bot se vuelven inalcanzables al crecer el tenant
- [EJE 3] No existe importación masiva de contactos aunque la UI ofrece 'Importación' como canal de consent

**Ventas · Pedidos** (9):
- APPROVED tardío sobre orden avanzada más allá de 'confirmed' regresa el estado y descuenta stock DOS veces
- Saltos de estado vía API se saltan el decremento de stock: pending → processing/shipped/delivered nunca descuenta inventario
- COD sin validación de contacto/dirección en creación, y el fallo de guía muestra un diagnóstico engañoso
- La guía COD se vuelve inaccesible si el pedido avanza: botón solo en 'confirmed' y endpoint rechaza processing/shipped con 422
- Pedidos credit confirmados sin Wompi (auto_confirm / transferencia) no tienen camino a guía Aveonline en la consola
- Link de pago: cada clic crea un link Wompi nuevo sin reuso, ambos quedan vivos (posible doble cobro) y el link no es visible/recup
- confirm_rate actualiza orders.shipping_cost sin recomputar total_amount: desglose y total divergen (y el cobro ya hecho no coincid
- Flag de guías reales Aveonline es un env GLOBAL de plataforma, no config per-tenant (contradice su propio comentario)
- Anomalías de dinero mueren en logs de Render: monto_mismatch, webhooks huérfanos, pago sobre orden cancelada y fallo de decremento

**Ventas · Promociones/Cupones** (3):
- RPC coupon_increment_redemption no existe en migraciones — consume siempre usa fallback read-then-update no atómico
- create_order lee discount_cents del cart más reciente sin filtrar status ni cupón activo — descuento stale puede filtrarse a una o
- Detector de cupones solo reconoce códigos en MAYÚSCULAS y el LLM no tiene tool de cupones — 'tengo el cupón promo10' es un dead-en

**Ventas · Reclamos** (7):
- [Eje 9] El bot responde el estado del reclamo con vocabulario OBSOLETO: 'in_progress'/'closed' ya no existen y los estados reales 
- [Eje 9] Vocabulario 'reason' incoherente: el bot escribe texto libre, el mapeo a keys canónicas que el router dice que existe NO e
- [Eje 3] 'Reembolsar' solo marca estado: sin registro de reconciliación, sin reuso del pipeline void existente, sin validar monto v
- [Eje 1] Transiciones terminal→terminal sin guard: un manager puede reescribir 'refunded'→'rejected'/'resolved' (historial financie
- [Eje 3] Resolución por reposición no toca inventario ni genera pedido de reemplazo
- [Eje 6] Sin SLA de reclamos: el bot promete revisión 'en las próximas horas' y Ley 1480 impone plazos, pero nada mide ni alerta el
- [Eje 7] Cobertura de tests del router claims casi nula: reopen guard (403/409), /resolve, VALID_REASONS y RBAC sin un solo test de

**stack-versions** (1):
- Next.js 15 en Maintenance LTS — EOL 2026-10-21 (~3.4 meses), migración a Next 16 no iniciada

---

## §7 · Matriz de dependencias entre módulos

Qué toca a qué (para no arreglar un extremo y dejar el otro roto — regla del 'todo cableado'):

| Cambio en… | Impacta / requiere coordinar con… |
|---|---|
| Pedidos (creación + estados) | Inbox (takeover crea pedido), Aveonline (cotización+guía), Wompi (link), Cupones (descuento), Contactos, Métricas, Finanzas, Auditoría |
| Aveonline (cliente + cotización) | Pedidos (form), Bot/agentic (quote tool), Despachos (guía+tracking), Reclamos (cancelar guía), Compras (costo envío) |
| Cupones (apply/revoke) | Cart, Pedidos (invalidar orden pending), Wompi (void link), Bot (announce), Métricas (ingreso descontado) |
| Wompi (link + webhook) | Pedidos (estado pago), Cupones (monto), Reclamos (refund/void), Finanzas (ingreso), Auditoría |
| Stock / variantes | Catálogo, Bot (cache catálogo + quote), MercadoLibre (sync bidireccional), Reclamos (reposición), Pedidos (reserva) |
| Mercado Libre (órdenes/stock) | Catálogo (inventario compartido), Pedidos (pipeline), Stock (oversell), Connector-meli |
| Contactos (teléfono canónico) | Inbox (matching conversación), Pedidos, Bot (identidad cliente), Habeas Data |
| RBAC / RLS / auditoría | TODOS los módulos (matriz de permisos UI↔API), Configuración, gateway API |
| WhatsApp Model B (webhook/DNS) | Connector, Onboarding tenant, Integraciones hub, Bot (routing) |
| Reclamos (resolución) | Wompi (refund), Stock (reposición), Bot (notificar cliente), Pedidos (estado), Auditoría |

---

## §8 · Plan por bloques (propuesto — requiere tu aprobación)

Orden por **riesgo × dependencia**: seguridad/dinero primero; luego los flujos E2E de mayor valor operativo; cada bloque cierra su cableado cross-módulo y su UAT dinámico antes de pasar al siguiente. Cada bloque = rama desde `develop` → implementación → tests (unit + UAT dinámico) → `validate.sh --ci` verde → verificación E2E real → migraciones seguras → docs/ADR → PR → **checkpoint de aprobación**.

### BLOQUE 0 — Seguridad P0/P1 (INMEDIATO)
- **Alcance:** get_claim_status filtra reclamos cross-cliente (P0); audit_log tamper-evident (RLS INSERT-only + hash chain o trigger); RLS FOR ALL en suppliers/purchase_orders/PO_items (bypass PostgREST); MFA AAL1 bypass en gateway público; pii_access_log sin GRANT (pestaña rota).
- **Volumen:** 1 P0 + 5 P1 · **Esfuerzo:** S–M
- **Criterio de hecho:** Ningún endpoint/tool expone datos de otro cliente/tenant; audit_log no forjable por miembro; MFA obligatorio también vía API directa; lint tenant 0.

### BLOQUE A — Integridad de dinero
- **Alcance:** Cupón: invalidar orden pending + void link al aplicar/revocar cupón (guard 'checkout' muerto); Wompi amount truncation int(total*100) vs round; cupón re-aplicado en pedido manual del operador; reconciliación Wompi (APPROVED perdido); UI 'Eliminar' pedido = hard-purge cascade (usar soft-delete legal).
- **Volumen:** 5 P1 · **Esfuerzo:** M
- **Criterio de hecho:** Ningún link Wompi cobra un total distinto al acordado; cupón siempre honrado o link anulado; ningún pago aprobado se pierde; borrar en UI no destruye historial.

### BLOQUE B — Envío Aveonline E2E
- **Alcance:** Cotización cableada al form de Pedidos (hoy shipping_cost es input manual); weight_inputs dropeado (guía a 0.5kg hardcode); flag real-guide per-tenant (hoy global); JWT TTL incoherente (refresh+retry); guía duplicada en retry (UNIQUE(order_id) + idempotencia); orders.status ↔ estado real de la guía (ADR-0020).
- **Volumen:** 8 P1 · **Esfuerzo:** M–L
- **Criterio de hecho:** El operador y el bot cotizan por el MISMO camino con peso real; guías reales gated per-tenant; sin guías duplicadas facturables; el estado del pedido refleja el de Aveonline.

### BLOQUE C — Catálogo / stock / importación
- **Alcance:** Importador lee la hoja 'Instrucciones' en vez de datos (roto E2E); precios inválidos→$1 COP silencioso; cache transaccional trunca variantes a 6 (7+ invendibles); decremento de stock consistente.
- **Volumen:** 4 P1 + P2 · **Esfuerzo:** M
- **Criterio de hecho:** Import masivo funcional con validación por fila; ningún producto vendible a $1; todas las variantes visibles al bot; un solo inventario veraz.

### BLOQUE D — Mercado Libre
- **Alcance:** Orden pending→paid nunca decrementa stock (oversell cross-canal); stock sync pone en 0 variaciones nativas no mapeadas; webhook autenticado solo por X-Forwarded-For[0] (spoofable); cancelación no repone stock; refund prometido no se ejecuta.
- **Volumen:** 5 P1 + P2 · **Esfuerzo:** M–L
- **Criterio de hecho:** Venta en MeLi decrementa el inventario compartido; sin ceros accidentales; webhook con auth real; cancelación repone y reembolsa.

### BLOQUE E — Inbox + WhatsApp onboarding
- **Alcance:** Enviar fuera de ventana 24h crashea el Inbox (backend devuelve dict, React lo renderiza como hijo); media inbound del cliente no visible (solo media_id, sin proxy/URL); **bug del picker de emojis (tofu/cuadros)** del screenshot; panel WhatsApp muestra URL de webhook en dominio muerto (api.konvi.co NXDOMAIN) → rompe el handshake Model B [DNS = intervención humana].
- **Volumen:** 4 P1 + P2 + bug emojis · **Esfuerzo:** M
- **Criterio de hecho:** El operador ve media entrante, envía plantilla fuera de 24h sin crash, y el onboarding Model B muestra una URL de webhook servible.

### BLOQUE F — Post-venta + Contactos + Finanzas
- **Alcance:** Reclamos: resolución/reembolso/rechazo NO notifica al cliente (la UI afirma que sí); cancelación desde consola bypassea el pipeline (sin restock/void/guide-cancel/audit); teléfono canónico E.164 vs digits-only (contactos duplicados, matching roto); anulación de gastos muerta (falta POST /expenses/{id}/reverse).
- **Volumen:** P0 ya en B0 + 4 P1 · **Esfuerzo:** M
- **Criterio de hecho:** Todo cambio de estado post-venta notifica al cliente y ejecuta su pipeline (dinero+stock+auditoría); un solo formato de teléfono; gastos anulables.

### BLOQUE G — Cableado vivo + Dashboard + IA/KB + barrido P2
- **Alcance:** Realtime orders (o polling fallback); deep-links con filtro aplicado; KPIs de dinero en el home; RAG drift de embedding; barrido de los P2 por módulo (UX operativa, estados de error, RBAC UI↔API).
- **Volumen:** P1 residual + P2 · **Esfuerzo:** S–M
- **Criterio de hecho:** Home operativo con dinero real + alertas accionables; sin regresión multi-tenant; P2 cerrados.

> **Nota de secuencia:** B0 (seguridad) y A (dinero) son no-negociables primero. B/C/D/F comparten dependencias (stock ↔ envío ↔ pagos ↔ reclamos): se recomienda hacerlos en ese orden para no re-tocar. G recoge el residual + P2. Los P3 (102) van a backlog etiquetado, no bloquean el gate.

---

## §9 · INTERVENCIÓN HUMANA REQUERIDA

Lo que no puedo ejecutar yo (responsable · pasos · insumos · criterio de éxito):

### DNS `api.konvi.co` (webhook Model B)
- **Responsable:** Founder + DNS Cloudflare
- **Qué/por qué:** El panel de WhatsApp muestra/copía una URL de webhook en `api.konvi.co`, que es **NXDOMAIN** → rompe el handshake de Meta en el onboarding self-service. Provisionar el registro DNS y apuntar al host/servicio correcto; setear `NEXT_PUBLIC_WEBHOOK_HOST`/`WHATSAPP_CONNECTOR_URL`.
- **Insumos:** DNS del dominio · **Criterio de éxito:** Meta valida el webhook y un tenant nuevo completa la conexión Model B.

### Flag de guías reales Aveonline per-tenant
- **Responsable:** Founder
- **Qué/por qué:** Hoy `AVEONLINE_GENERATE_REAL_GUIDES` es GLOBAL de plataforma. Tras el fix per-tenant (BLOQUE B), decidir/activar por-tenant cuándo cada uno pasa a **facturar guías reales** (deja dinero real en juego).
- **Insumos:** Confirmación por tenant · **Criterio de éxito:** Cada tenant genera guías reales solo cuando el founder lo habilita.

### Meta Phase 7 (Model B per-tenant) + HSM
- **Responsable:** Founder + Meta
- **Qué/por qué:** Tokens System User + webhooks per-tenant (ADR-0023) y aprobación de plantillas HSM por Meta no son automatizables desde el código.
- **Insumos:** Credenciales Meta per-tenant · **Criterio de éxito:** Plantillas aprobadas + webhooks per-tenant vivos.

### Aplicación de migraciones nuevas a prod
- **Responsable:** Founder + yo guío
- **Qué/por qué:** Cada bloque que toque esquema (RLS, UNIQUE, realtime publication, etc.) genera migraciones — se aplican con el protocolo seguro (pre-check→apply→repair) por el drift del ledger.
- **Insumos:** Autorización por bloque · **Criterio de éxito:** Ledger sincronizado, post-check verde.

### Rotación de secrets / entidad legal (ADR-0022)
- **Responsable:** Founder
- **Qué/por qué:** Fuera del alcance de código: rotación H7, entidad fiscal/legal.
- **Insumos:** — · **Criterio de éxito:** —

---

## §10 · Reconciliación de `.context/*` (al cerrar cada bloque)

Los `.context/00..06` se detienen ~rev.111 y no reflejan el cierre F1–F7 + 114 decisiones + Resend + fix bot. Al cerrar cada bloque se actualizará el estado real y se creará un ADR por decisión arquitectónica nueva (regla del prompt maestro §2.8). No se tocan en esta FASE 0 (solo auditoría).

---

_Generado por auditoría multi-agente (28 auditores + 49 verificadores adversariales) sobre HEAD `640ff565`, 2026-07-09. Read-only: no se modificó código._