# ADR-0015 — Coupon Engine (Sem 6 I.2)

**Status**: Accepted · 2026-05-07
**Sesión**: rev. 105 Sem 6
**Plan refs**: I.2.1-I.2.9 + decisión arquitectónica plan I.2 P1 ESENCIAL MVP (sube de Fase 4 futuro a P1).
**Predecessor refs**: ADR-0011 §6 (cart-as-SoT lifecycle), `cart/events.py` extiende CANONICAL_EVENTS.

---

## Context

El plan original colocaba cupones en Fase 4 (futuro post-producción).
En la sesión 2026-05-05 founder marcó cupones como **P1 esencial para
MVP**: tenants colombianos esperan ofrecer códigos promo desde día 1
(BIENVENIDO, PROMO10, ENVIOGRATIS) y sin el feature el SaaS pierde
competitividad inmediata.

El reto arquitectónico es integrar cupones al **cart-as-SoT** sin
violar los invariantes ADR-0011:
- §A.0.1: cart es la fuente de verdad transaccional, NO el LLM.
- §6.4.1: recotización shipping lazy — si shipping cambia, cupón
  `free_shipping` debe re-aplicar con nuevo `shipping_cents`.
- §6.4.4: status materializado en `conversation_carts` (subtotal, shipping,
  total) — agregamos `discount_cents` sin tocar el flujo existente.

Además, cupones tocan **Habeas Data Ley 1581** (audit log de descuentos
aplicados por contact_id) y **race conditions** (varios clientes
simultáneos consumiendo el último cupón disponible).

---

## Decision

### D1. Modelo de datos en 3 entidades

```
coupons (catálogo per tenant)
  ↓ 1:N
coupon_redemptions (audit append-only)
  ↑ N:1
conversation_carts (estado materializado: coupon_id + discount_cents)
```

- **`coupons`**: catálogo. Tenant define códigos, tipos, limits, fechas.
- **`coupon_redemptions`**: append-only. Cada aplicación/revocación/
  consumo deja huella forensics. Status FSM: `applied → consumed | revoked`.
- **`conversation_carts.coupon_id` + `coupon_code` + `discount_cents`**:
  estado derivado fast-read del cart vivo (cosmético — el origen real es
  `coupon_redemptions` activo del cart).

Justificación: igual patrón que `cart_events` vs `conversation_carts`
materializado (ADR-0011 §A.3) — audit log + row materializada.
Permite reconstruir auditoría completa + lookups rápidos sin JOIN.

### D2. Tipos de descuento (3 mutuamente excluyentes)

| Tipo | `discount_value` | Cálculo en cart |
|---|---|---|
| `percent` | 0-100 (entero) | `discount = floor(subtotal_cents * value / 100)` |
| `fixed_amount` | cents (BIGINT >=0) | `discount = min(value, subtotal_cents)` |
| `free_shipping` | ignorado | `discount = shipping_cents` (al momento de aplicar) |

**`free_shipping` dinámico**: si shipping cambia (recotización ADR-0011
§6.4.1), el `discount_cents` del cart se actualiza al nuevo
`shipping_cents`. La fila `coupon_redemptions` mantiene el monto
original como `discount_applied_cents` (snapshot al apply); el monto
efectivo final se persiste en `consumed_at` cuando orden APPROVED.

**Decisión**: `discount` aplica solo sobre `subtotal_cents` para
`percent`/`fixed_amount`. NO sobre shipping. `free_shipping` es la
ruta explícita para subsidiar envío.

### D3. NO combinables (P1) — combinables P3

Solo 1 cupón aplicado por cart a la vez. Si cliente intenta aplicar
un segundo, el sistema responde "ya tienes el cupón X aplicado, ¿lo
reemplazas por Y?" (decisión cliente).

Justificación P1: combinables introducen reglas (orden de aplicación,
exclusiones percent×percent, etc.) que requieren UI compleja
(matrix de compatibilidad). Para MVP, single-coupon es suficiente.
Combinables = ADR futuro post-producción.

### D4. Limits validados en runtime al apply

Validators determinísticos (función pura `validate_coupon_applicable`):
1. `is_active = true`.
2. `valid_from IS NULL OR valid_from <= NOW()`.
3. `valid_until IS NULL OR valid_until >= NOW()`.
4. `subtotal_cents >= min_subtotal_cents`.
5. `max_redemptions IS NULL OR redemptions_count < max_redemptions`.
6. (Solo en apply) cart no tiene cupón aplicado activo (D3).

Si cualquier check falla, retorna `(ok=False, reason)` con razón
específica para mostrar al cliente.

### D5. Race conditions en `redemptions_count`

Decisión: incrementar `redemptions_count` ATÓMICAMENTE solo cuando
orden pasa a APPROVED (Wompi webhook). NO al apply al cart (sería
prematuro: cliente puede abandonar checkout).

Mecánica:
1. Apply al cart → `coupon_redemptions.status='applied'`,
   `redemptions_count` SIN tocar.
2. Cart `cancelled`/`abandoned` → status='revoked', sigue sin tocar.
3. Cart `converted` (orden creada) → status sigue 'applied' hasta APPROVED.
4. Wompi APPROVED → `coupon_redemptions.status='consumed'` +
   `UPDATE coupons SET redemptions_count = redemptions_count + 1
    WHERE id = :id AND (max_redemptions IS NULL
    OR redemptions_count < max_redemptions)`. Si filas afectadas = 0,
   significa que el cupón se llenó entre apply y APPROVED — emitir
   warning (cliente disfrutó el descuento; consideramos overhang
   aceptable para max_redemptions raros).

Atomic UPDATE con WHERE clause es PostgreSQL-safe (no necesita advisory
lock para single-row increment con CHECK).

### D6. Habeas Data + Audit

- `coupon_redemptions.contact_id` puede ser NULL (cliente sin consent).
  ON DELETE SET NULL si contact eliminado vía SAR (Ley 1581 ART. 14).
- `coupon_redemptions` es append-only — NUNCA se elimina; status FSM
  permite trazar histórico completo.
- En el future SAR endpoint (ya existe `routers/data_subject_request.py`),
  exponer redemptions del contact al exportar dataset.

### D7. Cart events extension

Extender `services/ai-orchestrator/cart/events.py` CANONICAL_EVENTS:
- `coupon_applied`: payload `{coupon_id, code, type, discount_cents}`.
- `coupon_revoked`: payload `{coupon_id, code, reason}`.
- `coupon_consumed`: payload `{coupon_id, code, discount_cents, order_id}`.

### D8. Cupón se libera si orden cancelada (I.2.9)

Si orden creada pero NO APPROVED (cliente cancela manual, Wompi DECLINED,
TTL expira), `coupon_redemptions.status` queda en `applied` o se mueve
a `revoked` por el cron de TTL (`status='abandoned'` cart sweeper).
NUNCA se cuenta en `redemptions_count` porque solo se incrementa en
APPROVED (D5). Por construcción, no hay leak.

### D9. NO storefront web aún (J.0.0.4)

Cupón engine nace channel-agnóstico. Hooks expuestos como funciones
puras (sin asumir WhatsApp). Cuando storefront web exista (futuro
post-producción), reusará `apply_coupon(cart_id, code)` sin
modificación.

### D10. UI Settings → Promociones (I.2.8)

CRUD admin. Owner/manager pueden crear/editar/desactivar cupones del
tenant. Validators frontend espejan los backend (sin confiar). UI
muestra `redemptions_count / max_redemptions` actual + botón
"Desactivar" (soft delete vía `is_active=false`, NUNCA hard delete
para preservar auditoría).

---

## Consequences

### Positivas
- Cart-as-SoT extendido sin violar invariantes ADR-0011.
- Auditoría Habeas Data completa per redemption.
- Race conditions resueltas con atomic UPDATE (no advisory lock).
- Channel-agnóstico (storefront web reusa).
- Tipos `percent`/`fixed_amount`/`free_shipping` cubren 95% casos
  reales tenants colombianos.

### Negativas / Trade-offs
- **No combinables** = caso de uso "BIENVENIDO + ENVIOGRATIS" requiere
  P3 ADR futuro.
- **`free_shipping` dinámico** complica re-cotización (descuento muta
  con shipping). Manejado vía recompute al `set_shipping_meta` (cart_tool).
- **`discount_cents` en `conversation_carts` columna** = duplicación
  controlada (vs JOIN cada request). Tradeoff aceptado por performance
  Inbox (lecturas masivas).
- **redemptions_count overhang** posible si max_redemptions=1 y 2
  clientes simultáneos pasan a APPROVED en window <1ms. Overhead
  aceptable: log warning + cliente conserva descuento. Para cupones
  exclusivos críticos (1 sola redención global), tenant debe usar
  comunicación 1:1 manual.

### Riesgos
- **Si tenant cambia `discount_value` mientras cupones aplicados
  pendientes**: el cart tiene `discount_cents` snapshotted al apply,
  no se re-calcula automáticamente. Decisión: aceptado por
  determinismo. Cliente que aplicó antes del cambio mantiene su valor.
- **Cupones con `valid_until` en el pasado al consumir**: validamos
  AL APPLY (D4). Si cliente apply ahora pero APPROVED después de
  expiración, el cupón se cuenta como consumido. Aceptado: simplifica
  flujo y respeta la promesa al cliente que aplicó a tiempo.

---

## Implementation plan

| Item | Esfuerzo | Estado |
|---|---|---|
| I.2.1 Migration `coupons` + `coupon_redemptions` + columns + RLS | 1d | en sesión 2026-05-07 |
| I.2.5 Helper Python `apply_coupon` / `revoke_coupon` / `consume_redemption` | 1d | en sesión 2026-05-07 |
| I.2.6 Validators puros `validate_coupon_applicable` | 0.5d | en sesión 2026-05-07 |
| I.2.3 Hook `cart_events` (`coupon_applied/revoked/consumed`) | 1d | session next |
| I.2.4 Recompute total al apply/revoke + shipping recotization | 0.5d | session next |
| I.2.7 `_build_order_summary_text` muestra "Descuento: -$X (CÓDIGO)" | 0.5d | session next |
| I.2.2 Detector pre-LLM "cupón XYZ" en orchestrator | 1d | session next |
| I.2.8 UI Settings → Promociones CRUD | 2d | session next |
| I.2.9 Cupón liberado si orden cancelada | 0.5d | session next |
| Tests + UAT S43/S44/S45 | distribuido | distribuido |

---

## References

- Plan I.2: `/home/ansible/.claude/plans/declarative-wondering-patterson.md` sección I.2.
- ADR-0011 §6 (cart-as-SoT lifecycle, recotización lazy).
- `services/ai-orchestrator/cart/events.py` (CANONICAL_EVENTS extension).
- `supabase/migrations/20260501000000_conversation_carts.sql` (cart base schema).
