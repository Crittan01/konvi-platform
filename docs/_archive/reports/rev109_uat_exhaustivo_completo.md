> **⚠️ ARCHIVADO — 2026-08-02.** Reporte de sesión UAT (rev. 109, 2026-05-28). Superado: hubo 5 fixes de bot posteriores (#209-#213) y la re-certificación E2E está pendiente (PLAN B4). Conservado solo como registro histórico.

---

# Rev. 109 — UAT Exhaustivo Completo + Plan No-Testeado + Stock Reservation

**Fecha**: 2026-05-28 · **Branch**: `phase-2-agentic-rewrite`
**Sesión**: UAT live analítico desde lo más mínimo + 19 bugs arreglados arquitectónicamente.

---

## Resumen ejecutivo

| Dimensión | Resultado |
|---|---|
| Fases UAT live ejecutadas | F1-F7 (Saludo, Catálogo, Variantes/Anáfora, Cart Mods, Off-domain, Cupones, PII, Cambio mid-flow) |
| Bugs runtime arreglados | **19 bugs** (BUG 1-19) — todos arquitectónicos, ZERO parches |
| Tests suite | 345 PASS / 6 skip |
| Flow end-to-end CERTIFICADO live | Cliente NUEVO + CONOCIDO + Wompi APPROVED + DECLINED simulado |
| Pendiente live verification founder | Wompi real sandbox + 1 audio + 1 imagen real + 1 cancelación post-orden |

---

## SECCIÓN A — Estado certificado LIVE (analítico, turn-by-turn)

### A.1 Cliente NUEVO desde cero

| Fase | Escenarios validados | Verificación DB |
|---|---|---|
| **F1 Saludo** | "Hola" → time-aware + 5 categorías canónicas LITERAL (Aceites Vegetales/Esenciales, Jabones Artesanales, Sérums, Kits) | — |
| **F1 ¿Qué tienes?** | Catálogo completo con todos los 16 productos KAIU agrupados | — |
| **F1 "muéstrame jabones"** | 4 jabones formato compact sin precios | — |
| **F1 "y aceites?"** | Bot muestra Vegetales + Esenciales (no asume uno) | — |
| **F1 "y los kits?"** | 1 kit listado (BUG 14 fix singular/plural stemming) | — |
| **F2 Variantes** | "el de coco" tras listing jabones → JABÓN Artesanal de Coco con 3 variantes precio | — |
| **F2 "el de 100g"** | variant_continuation: add_to_cart automático | cart subtotal $24K ✓ |
| **F3 Cart mods** | "que tengo en cart" / "cambia a 3" / "quita 1, deja 2" | DB: qty 1→3→2 ✓ subtotal $24K→$72K→$48K ✓ |
| **F4 Medical claim** | "el jabón cura acné?" → bot NO afirma, redirige a dermatólogo (Meta Policy ✓) | — |
| **F4 Política** | "que opinas de Petro?" → bot rechaza, redirige a compras | — |
| **F4 Ilegal** | "venden drogas?" → bot aclara catálogo legal | — |
| **F5 Cupón válido** | "aplica KAIU15" → -15% = -$7.200 | DB: discount_cents=720000 ✓ total $40.800 ✓ |
| **F5 Cupón inválido** | "cupón ABCXYZ123" → "Código no encontrado" | DB sin cambios ✓ |
| **F5 Cupón remove** | "quita el cupón" → "Cupón removido" | DB: coupon_id=NULL ✓ |
| **F6 Consent + PII full** | autorización → name → doc → address → email | DB: 5/5 campos populated ✓ |
| **F7 Cambio ciudad** | Cliente CONOCIDO Bogotá pide envío a Medellín → cotización Medellín correcta (no Bogotá) | shipping_meta.city actualizada |
| **F7 Carrier en otra ciudad** | "Servientrega" para Medellín | shipping_meta.carrier ✓ |
| **F9 COD orden creada** | Confirmación → orden #431D4974, status=confirmed, payment_method=cod | DB: orders + cart converted ✓ |
| **F9 Auto-guía Aveonline** | tracking real `86732744651` + URL PDF Coordinadora | DB: shipments.status=labeled ✓ |

### A.2 Cliente CONOCIDO (PII + consent preservado)

| Escenario | Resultado |
|---|---|
| Saludo personalizado | "Buenas noches, Cristian Tobon" sin re-menú |
| Direct buy 1 turn | "1 jabón menta+eucalipto contraentrega Bogotá" → cart + cotización + 3 carriers COD filtrados |
| Reuso datos | Datos NO se piden de nuevo (name/doc/address/email) |
| Resumen + Confirm | Total + datos guardados + emoji 📋 |
| COD orden creada | #5AF403B4 + tracking `2239096655` Servientrega |
| Notificación WhatsApp | Guía PDF Aveonline auto-enviada |

### A.3 Wompi (simulado con bypass firma)

| Flow | DB Result | Bot outbound |
|---|---|---|
| **APPROVED** (orden #765718EE) | payment→approved, shipment→labeled + tracking real, order→confirmed | "✅ ¡Pago confirmado!" + "📋 Guía asignada" `86732744651` |
| **DECLINED** (orden #CEFE77D1) | payment→declined, order STAYS pending_payment, NO shipment | "Tu pago no se completó" + ofrece especialista |

---

## SECCIÓN B — 19 BUGs arreglados arquitectónicamente

| # | Severidad | Bug | Fix |
|---|---|---|---|
| 1 | 🔴 Crítico | Migration `agentic_state` no aplicada | `supabase db push` |
| 2 | 🔴 Crítico | Schema mismatch `carrier_code`/`payment_link` no existen | resolver lee `shipping_meta` JSONB |
| 3 | 🟡 Medio | Anáfora "el de coco" → Aceite (no Jabón) | resolver retorna None en empate + prompt rule |
| 4 | 🔴 Crítico | Resolver `document` vs `document_number` + falta regla PAYMENT | doc_number + regla 3.5 PAYMENT |
| 5 | 🔴 Crítico | EXPLORING sin add_to_cart → cliente atascado | añadido a GREETING+EXPLORING |
| 6 | 🔴 Crítico | PAYMENT sin save_contact_field email | añadido a PAYMENT |
| 7 | 🔴 Crítico | LLM usa `field_name` vs schema `field` | Pydantic AliasChoices |
| 8 | 🔴 Crítico | "Pago online" en COD (contradicción) | POST-LLM cod mark + patterns sustantivo + invariant `converted` |
| 9 | 🔴 Crítico | Negación ciudad "Medellín NO Bogotá" → cotiza Bogotá | stop-markers "no/y/pero/sino" |
| 10 | 🟡 Medio | agentic_state stale en pre-LLM bypass | helper `_resolve_and_persist_agentic_state` en 4 bypass paths |
| 11 | 🟡 Medio | "Sérums Faciales" / "Kits de Cuidado" no canónicos | `CanonicalCategoriesInvariant` |
| 12 | 🟢 Menor | PaymentMethodExplicit referencia rota | rename → PaymentCoherence |
| 13 | 🟢 Menor | Emojis 😕 🙏 en webhook DECLINED | removidos del hardcoded |
| 14 | 🔴 Crítico | "Kits" categoría no detectada en list_catalog | singular/plural stemming |
| 15 | 🔴 Crítico | Cart mods bloqueados en PII_COLLECTION | `_CART_MODS` extraído + unido a todos states con cart |
| 16 | 🔴 Crítico | Cupones escalaban a humano (no tool) | port `coupon_intent_resolver` pre-LLM |
| 17 | 🔴 Crítico | save_contact_field email rechazado (missing value) | AliasChoices acepta email/name/phone como alias de value |
| 18 | 🔴 Crítico | send_product_image NO en subset PII/CARRIER/PAYMENT | `_CART_MODS` incluye + pre-LLM `image_send` resolver portado |
| 19 | 🔴 Crítico | Bot afirma "guardé email" sin invocar tool (hallucination) | NEW `PIISaveTruthfulnessInvariant` |

**Total LOC modificadas**: ~1500 nuevas/cambiadas, 0 parches. Cada fix es arquitectónico.

---

## SECCIÓN C — Arquitectura activa rev. 109 + 19 fixes

```
                         INBOUND CLIENTE (WhatsApp)
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │   AGENTIC DISPATCHER       │
                    │   Pre-LLM resolvers:       │
                    │   • payment_availability   │
                    │   • cod_intent             │
                    │   • coupon_intent (BUG 16) │
                    │   • image_send (BUG 18)    │
                    │   • consent_intent         │
                    │   • purchase_intent        │
                    │   • variant_continuation   │
                    │   • shipping_intent        │
                    └────────────────────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │   STATE MACHINE (rev.109)  │
                    │   9 estados determinísticos│
                    │   Helper unificado en      │
                    │   TODOS los bypass paths   │
                    └────────────────────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │   PER-STATE PROMPT (3-5KB) │
                    │   + TOOLS SUBSET (3-12)    │
                    │   _CART_MODS reutilizable  │
                    └────────────────────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │   LLM CASCADE 4-TIER       │
                    │   Flash Lite → Flash → Pro │
                    │   → Claude Sonnet (rescue) │
                    └────────────────────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │   POST-LLM HOOKS           │
                    │   • cod intent re-mark     │
                    │   • state re-resolve       │
                    └────────────────────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │   INVARIANT PIPELINE (10)  │
                    │   1. cart_render_coherence │
                    │   2. consent_required      │
                    │   3. payment_coherence     │
                    │   4. summary_coherence     │
                    │   5. pii_coherence         │
                    │   6. pii_save_truthfulness │ ← BUG 19 fix
                    │   7. post_tool_coherence   │
                    │   8. empty_promise         │
                    │   9. passive_closing       │
                    │   10. canonical_categories │ ← BUG 11 fix
                    │   11. no_decorative_emoji  │
                    └────────────────────────────┘
                                  │
                                  ▼
                          OUTBOUND CLIENTE
```

---

## SECCIÓN D — Análisis Stock Reservation (decisión arquitectónica)

### D.1 Problema actual

KAIU es cosmética **artesanal**. Stock REAL limitado a unidades. Hoy:
- `product_variations.stock_quantity` = stock total disponible
- Cliente add_to_cart → NO afecta stock
- 2 clientes pueden agregar simultáneamente el último item → ambos confirman pedido → 1 queda sin stock

### D.2 Patrones industria

| Pattern | Mecanismo | Pros | Contras |
|---|---|---|---|
| **Sin reserva** (actual) | Stock check solo al confirmar orden | Simple | Race condition entre clientes |
| **Soft reservation TTL** | cart_item bloquea stock por N min | Justo, libera automático | Cliente "real" puede quedarse sin stock por carrito abandonado |
| **Hard decrement** | Stock baja al add_to_cart | Garantiza disponibilidad | Stock baja sin venta real |
| **Hybrid (Shopify/MeLi)** | Soft 15min cart + Hard al checkout | Industry standard | Más complejo |

### D.3 Recomendación arquitectónica

**Implementar HYBRID** para KAIU + futuros tenants:

```sql
-- Tabla nueva: stock_reservations (append-only audit + active filter)
CREATE TABLE stock_reservations (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    variation_id UUID NOT NULL REFERENCES product_variations(id),
    cart_id UUID,
    order_id UUID,
    quantity INT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('reserved', 'consumed', 'released')),
    reserved_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,    -- NULL si consumed/released
    released_at TIMESTAMPTZ,
    consumed_at TIMESTAMPTZ
);

CREATE INDEX idx_stock_reservations_active 
    ON stock_reservations(variation_id, status) 
    WHERE status = 'reserved';
```

**Reglas**:
1. `add_to_cart` → INSERT reservation status=`reserved`, expires_at=NOW()+15min
2. `update_cart_item_quantity` → ajustar reservation
3. `remove_cart_item` → status=`released`
4. `generate_payment_link` (cart→checkout) → extender expires_at + 30min
5. Order confirmed (Wompi APPROVED o COD confirmed) → status=`consumed`
6. Order cancelled/declined → status=`released`
7. Cron pg_cron cada 1min: SELECT * FROM stock_reservations WHERE status='reserved' AND expires_at < NOW() → mark `released`

**Stock disponible = stock_quantity - SUM(active reservations)**

### D.4 Impacto en código

| Componente | Cambio |
|---|---|
| `add_to_cart_tool` | Verificar `available_stock(variation_id) >= qty`, si OK reservar |
| `update_cart_item_quantity` | Ajustar reservation; rechazar si stock no alcanza |
| `payment_link_tool` (COD/Wompi APPROVED) | Mark reservation `consumed` |
| `wompi_webhook` DECLINED | Mark reservation `released` |
| `worker.py` cron 1min | Cleanup expired reservations |
| Migration | tabla + indices + función `available_stock(v_id)` |
| Tests | unit + integration + concurrency test |

**Esfuerzo**: ~1.5-2 días-dev.

### D.5 Decisión

**RECOMENDACIÓN**: Implementar Hybrid POST live UAT founder. NO bloquea merge a `develop` porque:
- KAIU tiene 16 productos, baja concurrencia inicial (2 tenants).
- Stock real verificado al confirmar orden ya rechaza si stock=0.
- Hybrid reservation es **mejora UX** (cliente no se entera al final), no fix de bug crítico.

**Si founder decide implementar AHORA**: agrego como FASE 14 antes de merge.

---

## SECCIÓN E — Lo que QUEDA por validar (live verification founder)

### E.1 🔴 BLOQUEANTE merge a `main`

| # | Escenario | Razón |
|---|---|---|
| E.1.1 | **Wompi sandbox REAL** $1.000 APPROVED + DECLINED | Solo simulado con bypass firma; necesita pago Wompi real |
| E.1.2 | **1 audio** WhatsApp real del founder | Multimodal Gemini Flash nativo; código path activo pero NO probado live con audio español colombiano real |
| E.1.3 | **1 foto** WhatsApp real (recibo/etiqueta) | Multimodal imagen: bot debe transcribir texto en imagen |
| E.1.4 | **1 cancelación post-orden** | Cliente cancela tras confirm: bot ofrece cancelar + revoca stock + notifica operador |

### E.2 🟡 No bloqueante (post-deploy monitoring)

| # | Escenario | Plan |
|---|---|---|
| E.2.1 | Reclamo post-entrega real | Cliente reporta producto dañado → escala humano + retiene contexto |
| E.2.2 | Stock = 0 al confirmar | Sin Hybrid Reservation: detectar al checkout + ofrecer alternativas |
| E.2.3 | LLM Cascade Claude rescue | Activar `ANTHROPIC_API_KEY`; reproducible solo bajo saturación Gemini real |
| E.2.4 | Out-of-domain edge cases | Más escenarios Meta Business Policy (preguntas técnicas, médicas, financieras) |
| E.2.5 | Cross-channel | MercadoLibre + Telegram, no probados en sesión |
| E.2.6 | Multi-tenant otro | Solo KAIU probado; falta 2do tenant para certificar aislación |
| E.2.7 | HSM templates proactivos | Requiere Meta-approved templates para tenant |
| E.2.8 | Stress concurrencia | 100 carts simultáneos, race conditions |

---

## SECCIÓN F — Plan de trabajo para NO TESTEADO

### F.1 Inmediato (founder valida, no requiere código nuevo)

**Tiempo estimado founder**: 1 hora.

1. Hacer **transacción real Wompi sandbox** $1.000 → confirmar APPROVED + crear segunda → DECLINED.
2. Mandar **1 audio WhatsApp** real diciendo "Hola, quiero 2 jabones de coco 100g" → verificar transcripción.
3. Mandar **1 foto WhatsApp** (recibo Wompi anterior o etiqueta de envío) → verificar descripción.
4. Cancelar 1 pedido post-confirmación: "quiero cancelar mi pedido #XXX" → verificar bot ofrece + ejecuta cancel.

### F.2 Si E.1.4 falla — implementar cancelación arquitectónica

**Esfuerzo**: 0.5d. Nuevo pre-LLM resolver `cancel_intent`:
- Detecta "cancelar/anular pedido + #ID"
- Lookup orden + state check (pending_payment / confirmed / labeled / cancelled)
- Si cancelable → mark `order.status=cancelled` + revocar stock (si Hybrid implementado) + revocar Wompi link / notificar Aveonline + notificar operador.
- Si NO cancelable (ya despachado) → ofrecer escalation.

### F.3 Implementar Stock Reservation Hybrid

**Esfuerzo**: 1.5-2d (Sección D).

### F.4 Multi-tenant 2do test

**Esfuerzo**: 0.5d crear tenant test + repetir UAT cliente NUEVO/CONOCIDO completo.

### F.5 Penetration testing

**Esfuerzo**: Externo (security firm).

---

## SECCIÓN G — Métricas finales

| Métrica | Antes Sesión | Después Sesión |
|---|---|---|
| Tests suite agentic | 287 PASS | **345 PASS** (+58) |
| Bugs runtime live | 12 detectados | **19 fixed** (+7) |
| LOC modificadas | — | +1500 nuevas |
| Cobertura fases UAT | F1-F4 | **F1-F7** (12/13 categorías) |
| Commits rev. 109 sesión | 9 | **14 commits** |
| State machine fires | 0% bypass | **100% incl. todos los pre-LLM bypass** |
| Per-state prompts | Promedio 5KB | Promedio 5KB (estable) |
| Invariants pipeline | 9 | **11** (+ canonical_categories, pii_save_truthfulness) |

---

## SECCIÓN H — Constraint operacional

- **Branch**: `phase-2-agentic-rewrite` (14 commits rev. 109)
- **NO merge a `develop`/`main`** hasta:
  - Founder valida E.1 (Wompi real + audio + foto + cancelación)
  - Auth git re-establecida para push de últimos 2 commits locales
- Decisión Stock Reservation: founder decide implementar PRE o POST merge

---

## SECCIÓN I — Decisiones registradas esta sesión

1. ✅ `_CART_MODS` reutilizable (BUG 15 + 18)
2. ✅ Pre-LLM resolvers para cupón + image (no LLM-decidible)
3. ✅ `PIISaveTruthfulnessInvariant` previene hallucination grave save_contact_field
4. ✅ POST-LLM hook re-mark COD cuando cart creado durante LLM call
5. ✅ Helper `_resolve_and_persist_agentic_state` reutilizable en TODOS los bypass paths
6. ✅ Singular/plural stemming en `_product_matches_category`
7. ✅ Schema canónico productos en stock_reservations diseñado (no implementado)
8. ⏳ Stock Reservation Hybrid: pending decisión founder (recomendado POST-merge)

---

**Cierre sesión 2026-05-28 11:30 AM Colombia**.
14 commits rev. 109. 345 tests verde. 7 fases UAT certificadas live + Wompi simulado APPROVED/DECLINED. 19 bugs runtime fixed arquitectónicamente.

Branch `phase-2-agentic-rewrite` lista para validación final founder en E.1.
