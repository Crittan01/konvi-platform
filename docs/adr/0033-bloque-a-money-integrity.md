# ADR-0033 — BLOQUE A: Integridad de dinero

- **Estado:** En progreso (PR-1 cubre items 1–3; items 4–5 en PRs siguientes) — 2026-07-10
- **Contexto:** Segundo bloque de la remediación production-grade (Prompt Maestro), derivado de
  `docs/audit/production-readiness-2026-07-09.md §BLOQUE A`. Cada item se **re-verificó contra el código
  actual** (workflow read-only, no se asumió el audit) antes de tocar nada. Criterio de hecho del bloque:
  *ningún link Wompi cobra un total distinto al acordado; cupón siempre honrado o link anulado; ningún
  pago aprobado se pierde; borrar en UI no destruye historial.*

## Decisiones (PR-1)

### 1. La señal para invalidar el link al cambiar un cupón es la orden `pending_payment`, no `cart.status`
El guard `cart.status == 'checkout'` en los handlers de cupón (dispatcher agentic **y** orchestrator legacy)
era **código muerto**: ningún path escribe ese status (es vestigial en el CHECK constraint). Resultado:
aplicar/revocar un cupón mutaba el total del cart pero dejaba la orden `pending_payment` con su link Wompi
(`amount_in_cents` congelado) intacto → el cliente podía pagar el link viejo con un total divergente.
**Decisión:** retirar el guard muerto y, tras un apply/revoke exitoso, llamar al helper canónico
`invalidate_pending_order_on_cart_change` (el mismo que `add_item`/`remove_item` ya usan) — que keyea por la
**orden `pending_payment` existente** (CAS `.eq(status,'pending_payment')`), la cancela y hace `payments→voided`.
Si invalidó algo, el bot avisa al cliente que el link anterior ya no es válido. Ambas rutas (live + legacy) fixeadas.

### 2. La conversión moneda→cents redondea, no trunca
`create_payment_link` calculaba `int(total_amount * 100)`. Como `total_amount` es `numeric(10,2)` leído como
float, `total*100` produce `X.9999998` y `int()` **trunca 1 centavo** (subcobro) en totales fraccionarios
(típicos de cupón %). El bot ya cotiza con `round` (`payment_link_tool.py`), así que la API cobraba 1 cent
menos de lo prometido. **Decisión:** `int(round(total_amount * 100))` — recupera los cents exactos acordados
y alinea la API con la convención del orchestrator. Afecta a la vez el monto enviado a Wompi y el snapshot
`payments.amount_in_cents`.

### 3. Heredar el descuento del cart al crear una orden exige una redención VIVA
`create_order` restaba `conversation_carts.discount_cents` del cart más reciente **sin guard**. Como
`consume_redemption` no limpia `discount_cents` al consumir el cupón, un cart ya `converted` conserva el
descuento → un 2º pedido manual del operador para la misma conversación re-aplicaba el mismo descuento
(doble descuento / pedido en $0). **Decisión:** heredar el descuento solo si (a) el cart está en estado
no-terminal (`open`/`checkout`) **y** (b) existe una `coupon_redemptions` con `status='applied'` (señal
autoritativa del cupón vivo) para ese cart. Un cupón consumido (`consumed`) o revocado (`revoked`) ya no
descuenta. Preserva el flujo legítimo (bot / operador-confirma-cart, donde la redención está `applied`).

## Consecuencias
- **Positivas:** cierra 3 defectos de dinero verificados; el cobro Wompi = total acordado; el cupón nunca
  se paga sobre un total obsoleto ni se re-aplica en una orden nueva.
- **Riesgo:** bajo. Item 1 solo invalida cuando hay orden `pending_payment` (flujo normal pre-link no cambia);
  item 2 solo difiere ≤1 cent en la dirección correcta; item 3 preserva el flujo bot (redención `applied`).
  El nuevo query a `coupon_redemptions` es tenant-scoped (pasa `audit_tenant_filter.py`).
- **Residual conocido (pre-existente, declarado):** el "void" del link es local (`payments.voided` +
  `orders.cancelled`); NO llama a un void de Wompi (no existe API pública de refund — dossier §5), así que el
  `checkout_url` viejo sigue técnicamente pagable hasta expirar su TTL — idéntico a `add_item`/`remove_item`.
  La reconciliación del webhook debe tolerar un pago que llega para una orden `cancelled` → se cubre en item 4.
- **Validación E2E:** el wiring cupón→invalidate (inline en el dispatcher, no unit-testeable en aislamiento
  sin fragilidad) se valida con **UAT dinámico** (conversación real turn-a-turn), no scripts estáticos.

## Pendiente en este bloque (PRs siguientes)
- **Item 5 (retención legal):** el purge de contacto hace hard-delete de `orders/payments` → se hará selectivo
  (contacto con pedidos = anonimizar PII + preservar historial; Cód. Comercio Art. 60). Retención **confirmada por founder**.
- **Item 4 (reconciliación Wompi):** cron pull que confirme órdenes `pending_payment` pagadas cuyo webhook se
  perdió, + sweeper Wompi-aware (hoy cancela una orden pagada a los 35 min). **Dossier-first**: verificar en doc
  oficial Wompi la correlación link→transacción (`GET /v1/transactions?reference=`) antes de implementar; se
  presenta el diseño al founder antes de codear.
