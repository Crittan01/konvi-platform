# Plan estratégico — MeLi "todo el jugo" + Stock centralizado multicanal

_Konvi Platform · 2026-07-18 · síntesis founder-facing (workflow 5 agentes: verify adversarial + 2 lentes + síntesis) · construye sobre ADR-0036 (stock coherence) + ADR-0037 (roadmap)_

## 1. Estado actual — madurez ~40-45%

| Capa | Estado | Evidencia |
|---|---|---|
| Inbound-commerce (ventas MeLi) | ✅ Sólido | orders_v2/items/shipments ingestan; decremento idempotente por webhook |
| Stock coherence cross-canal (ADR-0036) | ✅ Implementado | Guard `ON CONFLICT (order_id, variation_id, reason)` en 3 orígenes |
| Reliability spine crown-jewel | ✅ Merged (#37) | Token refresh lease + fencing + double-check; migración `20260711100000`; XFF hop-aware |
| Console truth-fixes | 🟡 Parcial (#38) | Seller ID/token label/link OK. Falta: `meli_condition`+`synced_at` en GET /listings, health strip, botón "sync todo" |
| Reliability resto | ⬜ Pendiente | Sin retry/backoff (Retry-After), sin single-flight `sync_meli_stock`, sin missed_feeds cron |
| Q&A pre-venta (B3) | ⬜ Pendiente | Sin tabla `meli_questions`, sin handler |
| Mensajería post-venta (B4) | ⬜ Pendiente | Sin ingesta; TRAMPA verificada (worker.py:648-656) |
| Claims/contracargos (B5) | ⬜ Pendiente | Sin `marketplace_claims`, sin handler |
| Publish outbound (B6) | ⬜ Pendiente | Sin `create_item`/`validate_item`, sin cache/predictor |
| Guardrails outbound (B7) | ⬜ Pendiente | Sin shadow, sin invariantes MeLi |

Núcleo "recibir ventas + no sobrevender" sólido. Customer-facing (responder) y outbound (publicar) por construir. La visión del founder (stock centralizado + jugo con permisos actuales) cae en lo desbloqueado (publish + stock + métricas), NO en "el bot responde en MeLi" (fuera de scope por config).

## 2. Stock centralizado multicanal — mecanismo + tienda virtual

3 canales descuentan del MISMO contador `product_variations.stock_quantity` vía `rpc_stock_decrement(order_id, variation_id, qty, reason='sale')` con guard idempotente `ON CONFLICT (order_id, variation_id, reason)`, SECURITY DEFINER + tenant-scoped + FOR UPDATE por fila + clamp `GREATEST(0,…)`. Cada orden trae su propio `order_id` → nunca colisionan entre canales → coherencia cross-canal SE SOSTIENE. Reposición (cancelación → `rpc_stock_restore`, `reason='cancellation_refund'`) mismo guard en los 3 orígenes.

**Tienda virtual = 4º canal SIN cambios de esquema.** `orders.source` es TEXT libre (migración `20260704153000`) → basta `source='storefront'`. **Regla de oro:** el checkout DEBE reusar `orders.py:_decrement_stock_on_confirm` → hereda gratis el guard idempotente Y el push `sync_meli_stock`. Path paralelo que NO dispare sync = MeLi sobrevende.

Riesgos a cerrar: (1) doble decremento intra-canal `'sale'` vs `'reservation_consumed'` (hueco W3-F3) → storefront arranca **decrement-only** sin soft-reserve; (2) oversell por latencia de sync → **single-flight `sync_meli_stock` (A2) es prerequisito duro del 4º canal**; (3) ajuste manual de inventario no propaga a MeLi → quick-win; (4) `orders.source` sin constraint → centralizar constante de canal.

## 3. Config de app MeLi — alineación

CORRECTA para la fase actual. NINGÚN ajuste ahora. Publicación R/W + Venta y envíos R/W + Métricas R + topics orders_v2/items/shipments habilitan el track code-only completo. Comunicaciones SIN ACCESO + topics questions/messages/claims OFF → customer-facing diferido (founder-gated). Efecto tranquilizador: la TRAMPA del Bloque 4 es imposible de disparar hoy (messages OFF).

## 4. Plan de ejecución — track code-only startable YA (cero acción founder, ~12-20d)

| # | Bloque | Entrega | Esfuerzo | Riesgo que mitiga |
|---|---|---|---|---|
| A1 | Worker channel-filter | Filtro de canal en poll inbound; apaga la trampa B4 | 0.5-1d | Misrouting MeLi→WhatsApp |
| A2 | Single-flight `sync_meli_stock` | Lease/dedup del push (patrón crown-jewel) | 1.5-2.5d | Oversell/desync. **Prereq 4º canal** |
| A3 | Retry/backoff reactivo | Honrar Retry-After/429 en clientes httpx | 1-2d | Pérdida de writes transitorios |
| A4 | Bloque 2 restante | `meli_condition`+`synced_at`, health strip, sync-todo | 1-2d | Consola miente sobre salud |
| QW | Quick-win centralización | Edición manual inventario → `sync_meli_stock` | 0.5-1d | "Mantener" incumplido |
| B1 | Bloque 5 claims BUILD | `marketplace_claims` + handler + alerta Telegram (dormido) | 2-3d | Chargebacks sin visibilidad |
| TV | Tienda virtual stock-wiring | Checkout reusa `_decrement_stock_on_confirm` (decrement-only) | 3-5d | 4º canal sin sync. Tras A2 |

Diferidos tras VERIFY-DOC (portal MeLi, sin founder): A5 missed_feeds cron, A6 panel Métricas/CBT, C1/C2 publish plumbing validate-only, D1 guardrails. Dormidos hasta abrir permisos: B2 Q&A, B3 mensajería (no mergear sin A1).

## 5. Bloqueadores VERIFY-OFFICIAL-DOC (NO adivinar — portal dio 403 al dossier)

c1 schema POST /items MCO; c2 category_predictor vs domain_discovery; c3 listing_prices + comisión; c4 missed_feeds vs myfeeds; c5 rate-limits + Retry-After headers; c6 endpoints Métricas R + umbrales CBT 2026 MCO; c7 REST claims vs post_purchase; **c8 mapeo scope-granular↔endpoint del modelo NUEVO (raíz — el dossier documentó el modelo viejo read/write)**; c9 order acknowledgment / shipment status write.

## 6. Founder-gated (lote único cuando decidas)

1. Abrir permiso "Comunicaciones pre/post venta" + re-consent OAuth → desbloquea DATOS B3/B4.
2. Suscribir topics: questions/messages (requieren #1); **claims/post_purchase (solo flip, sin re-consent — el más ligero + mayor ROI dinero/chargebacks → priorízalo)**.
3. Curar mapping ADR-0029 → categoría/atributos MeLi (habilita publish C1).
4. GO-LIVE publish (flip validate-only → POST real; irreversible por listing; NO sin D1 verde).
5. Habilitar respuesta operador / outbound real — solo tras D1.

## 7. Recomendación neta

**Arrancar YA el track code-only en orden: A1 (mata trampa) → A2 (single-flight, prereq 4º canal) → A4 (consola honesta) → QW (sync manual) → B1 claims BUILD → Tienda Virtual.** Product-first: entrega stock centralizado real + salud de conexión sin depender del founder ni de doc bloqueada. Riesgo neto si NO se hace A2 antes del 4º canal: oversell en MeLi por ventana de desync — el fallo más caro y más fácil de prevenir.

Referencias: [ADR-0036], [ADR-0037], [ADR-0023] Model B, [ADR-0024] invariantes, [ADR-0029] atributos, dossier `mercadolibre-dossier-2026-05-05.md`.
