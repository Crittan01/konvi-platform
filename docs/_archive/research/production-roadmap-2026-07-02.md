> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Roadmap a Producción — Konvi (2026-07-02)

**Fuente:** consolida el plan maestro de 7 fases + la matriz de completitud 100% del dashboard (27 módulos) +
las decisiones de categorías/productos. Es la **única fuente de verdad** del trabajo. Reemplaza el trabajo a pedazos.

**Estado base:** ~30% de módulos production-ready. UI/reads maduros (~95%); la brecha es WRITE end-to-end con las
4 garantías: **RBAC server-side + aislamiento tenant + `@audit_log` + integridad transaccional.**

**Decisión cerrada (categorías/productos):** categorías en **2 niveles — Categoría › Subcategoría**; el producto
cuelga de una **subcategoría** (hoja) y hereda su **contrato de atributos**. Un eje operativo (la de marketplace se
deriva). Es el estándar e-commerce y lo que el founder pidió.

**Regla de migraciones:** cada migración a prod requiere autorización explícita del founder. Se **agrupan por fase**
para autorizar en bloque (lista al final).

---

## FASE 0 — Endurecimiento sistémico (transversal, primero: arregla muchos módulos de un golpe)
**Objetivo:** cerrar los 3 patrones que se repiten en todo el dashboard.
- **RLS `WITH CHECK`**: añadir `WITH CHECK (tenant_id = app_current_tenant())` a las ~15 policies `FOR ALL` que solo
  tienen `USING` (empezar por tenant_integrations, notification_settings, tenant_users…). → evita escribir fila de otro tenant.
- **Guards de rol server-side**: redirect server-side por rol en las páginas sensibles sin gate (Métricas, Auditoría,
  Finanzas) — hoy solo el sidebar oculta el link; se abren por URL directa.
- **`@audit_log`**: añadir el decorador a las ~13 mutaciones sin rastro (inbox status/send, marketplace 5 acciones,
  whatsapp-templates, etc.).
- **Migraciones:** WITH CHECK (drop+create idempotente por policy). **Fortalecimiento:** test de enforcement RLS real.

## FASE 1 — Coherencia de DINERO (crítico activo)
**Objetivo:** total que ve el cliente == cobro Wompi == orden, con descuento incluido.
- Migración `orders.discount_cents` + `orders.total_amount` a DECIMAL (hoy FLOAT, anti-pattern dinero).
- El RPC `cart_add_item` (o capa cart) es dueño del cálculo: `total = max(0, subtotal + shipping − discount)`;
  recomputar tras add/update/remove.
- `payment_link_tool` y `orders.py:187` pasan/usan el descuento (hoy `orders.py:187` lo ignora).
- Exponer `discount_cop` en GetCartTool para que el bot narre el total con descuento.
- **Test end-to-end** cart+cupón → orden → `payment.amount_in_cents` que falle si el descuento no llega al cobro.

## FASE 2 — Categorías + Productos (lo hablado)
**Objetivo:** jerarquía + contrato de atributos vivo y validado end-to-end.
- **Jerarquía:** migración `product_categories.parent_id` (2 niveles) + datos KAIU (padre "Salud y Belleza" con sus 5
  categorías como subcategorías; productos intactos). Selector de categoría **agrupado por vertical** (`<optgroup>`) en
  alta + edición.
- **Contrato de atributos — autoría:** endpoint + UI CRUD para `product_attribute_definitions` (RBAC + `@audit_log`,
  patrón `product_categories.py`) + **seed versionado del contrato KAIU**. Hoy solo se lee → el alta guiada está inerte.
- **Validación HARD server-side:** `products.py` create/patch carga el contrato de la categoría y **rechaza (422)**
  atributos fuera de contrato y valores fuera de `allowed_values`. Hoy el JSONB es libre vía API.
- **Editor de `products.attributes`** (product-level) en el edit-drawer (hoy write-once en el alta).
- **`mass-importer` → API** `POST /products` (hereda `@audit_log` + RBAC + validación; hoy escribe directo a Supabase).
- **Limpieza:** decidir `category_attributes`/`attribute_values` (poblar el núcleo curado global, o eliminar tablas
  fantasma); retirar `platform_category_id` por-producto de ProductCreate/Patch.
- **Migraciones:** parent_id + índice; seed contrato KAIU.

## FASE 3 — Activación de tenant (crítico para producción multi-tenant)
**Objetivo:** un negocio nuevo puede arrancar el bot sin intervención manual.
- **Credenciales WhatsApp en UI:** capturar `app_id`, `app_secret` (→Vault `pgsec_upsert_secret`), `verify_token`;
  `integration_type='direct_provider'`. Hoy el connector los REQUIERE pero se siembran por script.
- **Bucket `tenant-media` + RLS** en `storage.objects` (migración) — desbloquea send-image y cierra IDOR cross-tenant.
- **URL de webhook con `/{tenant_id}`** + `verify_token` mostrados en la UI (hoy la URL no tiene tenant → 404 en Meta).
- **Onboarding self-service:** RPC `provision_tenant` (SECURITY DEFINER) crea tenant + primer owner transaccional +
  verificación de email; checklist de readiness en el dashboard.
- **Migraciones:** bucket+policies storage, provision_tenant.

## FASE 4 — Integridad de INVENTARIO
**Objetivo:** no vender de más ni bloquear stock fantasma; el operador ve lo real.
- **Vista de stock DISPONIBLE** (bruto − reservas activas, `fn_variation_available_stock`) en UI y en lo que cita el bot.
- **Bug reserva:** `payment_link_tool:477` lee `reservation_id` pero el RPC devuelve `out_reservation_id` → rollback no
  libera. Enrutar por `lib/stock_reservation.py`. Eliminar doble reserva (SOFT+HARD sin release).
- **Oversell cross-canal:** disparar `sync_meli_stock` tras consumir stock por WhatsApp (hoy MeLi muestra stock viejo).
- **Migraciones:** `CHECK (stock_quantity >= 0)`, UNIQUE parcial `stock_movements(order_id, variation_id)`.
- **Faltantes:** UI de reservas activas + timeline de `stock_movements`; cancel de pedido restaura stock.

## FASE 5 — Pago→Envío + Cotizador + Retención
**Objetivo:** la guía sale con datos reales del cart correcto; cerrar gaps de despacho/legal.
- **Guía:** persistir peso/dims cotizados en `shipping_meta.weight_inputs` y **reusar** en la guía (hoy hardcode 0.5kg);
  filtrar `shipping_meta` por **conversación/orden** (hoy toma el último cart del tenant → guía cruzada en concurrencia).
- **Cotizador:** quitar/recablear los 4 botones post-cotización (label/tracking/pickup/cancel → endpoints 404).
- **Pagos:** UNIQUE(`wompi_txn_id`) + reconciliación Wompi **antes** del cron de expiry (que hoy cancela órdenes pagadas).
- **Retención (Ley 1581):** `CREATE EXTENSION pg_cron` (hoy el `cron.schedule` se traga el fallo → borrado no corre).
- **Health:** WhatsApp `phone_id` desde `credentials` (hoy siempre None → health falso "crítico").
- **Migraciones:** UNIQUE payments, extensión pg_cron.

## FASE 6 — Compliance + robustez del path agentic + módulos parciales
- **SLA escalación** (`worker.py:904`): derivar antigüedad del evento de escalación, no de `last_interaction_at` (el
  cliente lo renueva escribiendo).
- **Habeas Data en path agentic** (producción): export Art.14 + rectificación Art.16 + detección de menores +
  `consent_audit_log` de toda solicitud (hoy completo solo en el path legacy muerto).
- **Reclamos:** `resolution_notes` editable (hoy readOnly) + transiciones a estados terminales.
- **Legal:** servir `/docs/legal/*.md` (hoy 404) + UI de SIC report (endpoint existe, sin botón).
- **Cerrar cuenta:** hard-delete hoy gated OFF → cumplir la promesa legal de eliminación.

## FASE 7 — Limpieza de SOBRANTES (baja superficie/riesgo)
- Router `settings.py` completo (0 callers) · endpoints de lectura muertos (GET /orders, /contacts, /shipping/history) ·
  `category_attributes`/`attribute_values` (0 lectores) · `order_tracking`/`bot_source_log` write-only · bloque
  post-cotización + `route.ts` muertos · columnas Envia legacy en `shipments` · redirect stubs (inventory, account) ·
  `ai_agents.persona_block`/templates sin consumidor · `health_metrics` collect_meli (provider mismatch).

---

## Migraciones por fase (para autorizar en bloque)
- **F0:** WITH CHECK en ~15 policies.
- **F1:** `orders.discount_cents` + `total_amount`→DECIMAL.
- **F2:** `product_categories.parent_id` + índice; seed contrato de atributos KAIU.
- **F3:** bucket `tenant-media` + policies storage; `provision_tenant` RPC.
- **F4:** `CHECK stock>=0`; UNIQUE parcial `stock_movements`.
- **F5:** UNIQUE `payments(wompi_txn_id)`; `CREATE EXTENSION pg_cron`.

## Orden de ejecución recomendado
**F0 (sistémico) → F1 (dinero) → F2 (categorías/productos) → F3 (activación) → F4 (inventario) → F5 (pago/envío/legal)
→ F6 (compliance/parciales) → F7 (limpieza).** F0 y F1 primero por apalancamiento e impacto financiero activo.