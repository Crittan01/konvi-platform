# Dossier Ecart Pay — 2026-05-07

**Fecha**: 2026-05-07 · **Sesión**: investigación profunda sección H.2.4 (COD / Contraentrega) · **Sin pruebas en vivo**.
**Fuente primaria**: `https://docs.ecartpay.com/docs/*` (público) + `https://help.envia.com/en/{shipments-cod,withdraw-cod,cod}/` (Cloudflare bloquea WebFetch directo; cifras extraídas de SERP snippets oficiales 2026-05-07).
**Cobertura**: Auth + Orders + Payouts + Withdrawals + Webhooks + Billing + integración con Envia COD.
**Alcance**: foco Colombia (CO). Modelo: per-tenant cuenta separada (heredado de Envia, idéntica filosofía).

> **Aviso metodológico**: las páginas `help.envia.com/*` retornan **HTTP 403 (Cloudflare bot challenge)** ante WebFetch/curl con UAs estándar. Las cifras citadas con [help.envia.com/...] vienen de **snippets indexados públicamente por motores de búsqueda** (no es invención). Citas directas se marcan con comillas; valores derivados se etiquetan "derivado".

---

## 1. TL;DR ejecutivo

Ecart Pay es la **fintech del Grupo Tendencys** (México, desde 2016) y opera como la pieza monetaria de los flujos de Envia. Para H.2.4 (Cash on Delivery en Colombia), Ecart Pay actúa como **cuenta de tránsito**: el transportador deposita lo recolectado, Ecart Pay lo retiene unas horas, y el merchant lo retira a su cuenta bancaria. Cobertura confirmada: **10 países incluyendo Colombia, México, Chile, Argentina, India, USA, Canadá, España, Brasil, Guatemala**.

**Cifras críticas para Colombia (snapshot 2026-05-07)**:
- **0% comisión Ecart Pay sobre el COD** ("there are no commissions" — help.envia.com/en/withdraw-cod/).
- **5,000 COP fee fijo por retiro interbancario** ("there is a charge per transaction of $5,000 COP which corresponds to the cost per interbank transfer").
- **72 horas post-shipment** para que el dinero llegue a Ecart Pay ("receive your payments 72 hours after shipment in your Ecart Pay account").
- **Retiros se procesan martes y viernes 9:30 AM hora México**, solicitud el día anterior.
- **24-48h post-retiro** para que el dinero llegue al banco merchant.
- **Timeline E2E (entrega → cuenta merchant): 5-7 días calendario worst case.**

**Decisión arquitectónica clave**: Ecart Pay NO es contractualmente independiente de Envia para flujos COD. La cuenta Ecart Pay se vincula automáticamente cuando se activa COD en Envia (hipótesis a validar V.6). El merchant no necesita SDK Ecart Pay para H.2.4 MVP — solo necesita escuchar los webhooks `transfer.created` y `withdrawals.paid` para reconciliar. Implementación cliente Ecart Pay se difiere a fase posterior (cuando KAIU quiera ofrecer pagos online standalone, fuera del scope COD).

---

## 2. Hallazgos clave

### 2.1 Endpoints API (catálogo)

Verbo + path documentados en `docs.ecartpay.com/docs/*`:

| Endpoint | Producción | Descripción |
|---|---|---|
| `POST /api/customers` | `https://ecartpay.com/api/customers` | Crear customer (email/phone variants) |
| `GET/PUT/DELETE /api/customers/{id}` | idem | CRUD customer |
| `POST /api/orders` | `https://ecartpay.com/api/orders` | Crear orden con `shipping_items[].carrier="envia"` |
| `GET /api/orders/{id}` | idem | Detalle orden |
| `POST /api/payouts` | `https://ecartpay.com/api/payouts` | Pagar a otro user dentro de Ecart Pay (B2B intra-network) |
| `GET /api/payouts/{id}` | idem | Detalle payout |
| `PUT /api/payouts/{id}/confirmation` | idem | Confirmar payout pendiente con `available_at` (futuro) |
| `GET /api/withdrawals` | `https://ecartpay.com/api/withdrawals` | Historial de retiros (filtros: ID/fecha/currency/status) |
| `POST /api/withdrawals` | (no documentado explícito en SERP, inferido) | Crear retiro (en realidad se hace por dashboard según help.envia.com/en/withdraw-cod) |
| `GET /api/accounts/payments/method` | idem | Listar métodos de retiro activos (CLABE / debit card) |
| `POST /api/webhooks` | idem | Registrar URL webhook con `events[]` |
| `POST /api/tokens` | idem | Tokenizar tarjeta para backend integration |
| `GET /api/transactions` | idem | Historial transacciones (paginación page 1-10 + token-based) |
| `GET /api/transactions/summary` | idem | Balance agregado por moneda. **Soporta COP** (entre las currencies listadas: ARS, BRL, CLP, COP, EUR, GTQ, INR, MXN, USD) |
| `GET /api/transactions/{id}` | idem | Detalle transacción individual |
| `GET /api/billings/providers` | idem | Listar billing providers (Colombia=Siigo IVA 16%, México=Factura.com, AR=iFactura) |

**Sandbox base URL**: `https://sandbox.ecartpay.com/api/*` (paralelo simétrico al productivo).

### 2.2 Autenticación (modelo Basic + Token corto)

**No es Bearer ni OAuth**. Flujo:

1. Combinar `Public Key:Private Key` con colon → Base64 encode → request inicial con `Authorization: Basic {encoded}`.
2. La respuesta incluye un **token efímero válido 1 hora**.
3. Subsiguientes requests usan `Authorization: <token>` (sin prefijo "Bearer").
4. Después de expirar, **regenerar desde scratch**. NO hay refresh token.

**Implicación arquitectónica**:
- Cliente HTTP debe cachear el token con TTL ~50 min y refresh proactivo.
- Per-tenant: cada tenant tiene su propio (Public, Private) en Vault. La caché del token es per-tenant-instance.
- Patrón típico: middleware que inyecta token vigente o lo refresca antes del request.

### 2.3 Sandbox vs Producción

- Sandbox: `https://sandbox.ecartpay.com/*` — credenciales separadas (no interchangeables con prod).
- Producción: `https://ecartpay.com/api/*`.
- Webhooks deben registrarse separadamente (heredado patrón Envia).

### 2.4 Webhooks — Schema y autenticación

**Endpoint registro**: `POST /api/webhooks` body `{url, events[], ...}`.

**Eventos catalogados** (de docs.ecartpay.com/docs/webhook-events):

| Módulo | Evento | Significado para H.2.4 |
|---|---|---|
| Billing | `billing_information.updated` | NOOP (no relevante COD) |
| Billing | `billing_information.deleted` | NOOP |
| Billing | `billings.create` | Cuando se genera factura CFDI/Siigo |
| Subscriptions | `subscription.created/.payment_success/.payment_failed/.paused/.cancelled` | NOOP (KAIU no usa) |
| Transactions | `transactions.paid` | Confirmación de transacción exitosa |
| Transfer | `transfer.created` | **CRÍTICO**: "Emitted when a payment transfer to a merchant is complete". Este es el evento "el dinero del COD llegó a tu cuenta Ecart Pay" |
| Orders | `orders.confirmation` | "Emitted when an order is paid for" |
| Orders | `orders.create` | Orden creada |
| Orders | `orders.update` | Cambio de status |
| Withdrawals | `withdrawals.processing` | Retiro creado |
| Withdrawals | `withdrawals.paid` | **CRÍTICO**: retiro completado al banco merchant |
| Withdrawals | `withdrawals.cancelled` | Retiro cancelado |

**Autenticación webhooks (HMAC-SHA256 nativo — DIFERENCIADOR vs Envia)**:

Headers entregados:
- `x-pay-timestamp` — millis epoch
- `x-pay-signature` — HMAC-SHA256
- `x-pay-webhook-id` — identificador único del webhook

Algoritmo verificación:
1. Construir base string = `{timestamp}.{webhook_id}.{JSON.stringify(data)}`
2. Computar `HMAC_SHA256(secret, base_string)`
3. Comparar (constant-time) con `x-pay-signature`. Si no match → 401.

**Secret**: provisto en panel Ecart Pay como "Global Secret key". **Rotación NO documentada programáticamente** — revalidar manualmente.

**Ausentes en docs**:
- Política de retries (existe sección "Notification Retries" pero no tabla de intervalos).
- IP allowlist.
- Defensa contra replay (timestamp validation strategy no detallada).

### 2.5 Orders endpoint — integración con Envia

**Hallazgo crítico**: el body de `POST /api/orders` acepta nativamente:

```json
"shipping_items": [
  {
    "name": "Express Shipping",
    "amount": 160,
    "carrier": "envia"
  }
]
```

Esto confirma que **Ecart Pay reconoce Envia como carrier de primera clase** en el modelo de datos. No es un campo libre de texto; es un valor enum esperado.

**Implicación H.2.4**: si KAIU crea orden Ecart Pay (en algún flujo distinto al COD), puede asociar shipment Envia directamente. Pero para COD puro, este endpoint NO se usa — el flujo es: Envia genera label → carrier cobra → Envia deposita en Ecart Pay → merchant retira. El merchant NO crea orden Ecart Pay manualmente.

### 2.6 Currencies soportadas

Confirmado por `GET /api/transactions/summary` response: **ARS, BRL, CLP, COP, EUR, GTQ, INR, MXN, USD**.

COP (Colombia) está entre las currencies first-class.

### 2.7 Pricing (cuando Ecart Pay se usa standalone como PSP)

Tarifas para charge processing (irrelevantes para flujo COD-Envia, que tiene "no commission" según help.envia.com/en/withdraw-cod):

| Método | Comisión | Fijo por transacción |
|---|---|---|
| Tarjeta crédito/débito | 2.9% | $0.20 USD |
| Cash (cash networks como OXXO/ClubPago en MX) | 2.9% | $0.40 USD |
| American Express | 3.5% | $0.20 USD |

**NO hay tabla pública de pricing Ecart Pay para COP/Colombia transactions standalone**. Asumir que el flujo COD-Envia es separado con "0 comisión" como política comercial Envia (no una capacidad técnica Ecart Pay).

### 2.8 Billing providers (facturación electrónica)

| País | Provider | Currency | Tax |
|---|---|---|---|
| Colombia | **Siigo** | COP | IVA 16% |
| México | Factura.com | MXN | RFC + payment method codes |
| Argentina | iFactura | ARS | Debit/credit classifications |

**Implicación**: si KAIU activa facturación Ecart Pay para Colombia, va vía Siigo (NO documentado fluye automáticamente para shipments COD; probablemente activación opt-in). Para MVP H.2.4, **NOT REQUIRED** — facturación KAIU sigue el flow B2C estándar Colombia (DIAN/factura electrónica directa, fuera de Ecart Pay).

---

## 3. Multi-tenant compatibility

**Modelo**: idéntico a Envia — **una cuenta Ecart Pay por tenant**, sin sub-accounts ni partner program documentado.

- `docs.ecartpay.com/docs/api-keys` referencia "Production API Keys" y "Sandbox API Keys" pero **no detalla scopes, sub-cuentas, multi-tenant ni rotation programática**.
- `docs.ecartpay.com/docs/customers-1` se enfoca en customers individuales (Mexico-centric con CLABE), no en cuentas merchant.

**Vinculación con Envia**:
- Hipótesis fuerte (V.6 a validar): cuando un tenant activa COD en su cuenta Envia, **Envia provisiona automáticamente una cuenta Ecart Pay vinculada** (heredada del onboarding Envia, sin paso adicional).
- Alternativa: el tenant onboarda manualmente Ecart Pay en `accounts-sandbox.envia.com/signup` (igual que Envia).

**Almacenamiento credenciales**:
- `tenant_integrations.credentials.ecartpay_public_key` (cifrado).
- `tenant_integrations.credentials.ecartpay_private_key` (cifrado).
- `tenant_integrations.credentials.ecartpay_webhook_secret` (cifrado).
- Token de 1 hora se cachea en memoria (Redis) per-tenant.

---

## 4. Limitaciones documentadas

| # | Limitación | Cita / fuente |
|---|---|---|
| EP.L.1 | **Token de auth válido solo 1 hora** sin refresh — exige regeneración constante | docs.ecartpay.com/docs/authorization-token: "The generated token is valid for 1 hour" |
| EP.L.2 | **NO refresh token** — debe regenerarse desde Public+Private keys cada hora | mismo |
| EP.L.3 | **Documentación country-skewed a México**: customers endpoint usa CLABE como ejemplo, phone format mexicano "4775619358", billing principal CFDI. Colombia es ciudadano de segunda clase en la doc | docs.ecartpay.com/docs/customers-1 + docs/billings |
| EP.L.4 | **Sin documentación de KYC para Colombia**: la doc no formaliza qué documentos requiere para activar cuenta Ecart Pay CO. Sumsub aparece como provider de identity verification general (sumsub.com/customers/ecartpay), pero el detalle exacto está fuera de docs.ecartpay.com | gap docs |
| EP.L.5 | **Sin sub-accounts ni multi-tenant nativo**: ningún endpoint público para gestión jerárquica merchant→sellers | docs.ecartpay.com/docs/api-keys (omisión) |
| EP.L.6 | **Cliente Withdraw NO programático**: la creación de retiros NO está bien documentada como POST /api/withdrawals — el flujo confirmado es **dashboard Ecart Pay manual** ("log in to your account, go to the Withdrawals button and select Create retreat" — help.envia.com/en/withdraw-cod) | doc gap |
| EP.L.7 | **Webhook events catálogo limitado**: NO hay evento explícito `cash_on_delivery.collected`, `cod.paid` o similar. Solo `transfer.created` indirecto cuando el dinero llega a Ecart Pay | docs.ecartpay.com/docs/webhook-events |
| EP.L.8 | **Pagos COD-Envia tienen política comercial separada**: "0% comisión" en Colombia es política Envia, NO una capacidad técnica documentada de Ecart Pay para currency=COP. Cualquier cambio comercial Envia podría cambiar esto sin notice doc | help.envia.com/en/withdraw-cod (snippet) |
| EP.L.9 | **Sin SLA documentado**: latencia, uptime, retry policy webhooks no formalizados | docs.ecartpay.com (omisión) |
| EP.L.10 | **Pricing standalone NO incluye COP/CO row**: la tabla de pricing solo cubre USD reference; no hay pricing CO documentado para charges standalone (no impacta COD pero impacta uso futuro) | docs.ecartpay.com/docs/all-about-ecart-pay |
| EP.L.11 | **HMAC base string usa JSON.stringify del data**: si el body tiene whitespace/key-order diferente al original, la firma NO valida. Receiver debe almacenar el body raw bytes y NO el JSON parseado para verificar | docs.ecartpay.com/docs/webhook-authentication |
| EP.L.12 | **Sin idempotency-key documentada**: ningún endpoint expone header `Idempotency-Key`. POST duplicados podrían crear duplicados. Implementar idempotencia local (igual que Envia) | docs.ecartpay.com (omisión) |
| EP.L.13 | **NO hay endpoint público "saldo COD pendiente"** — para saber cuánto está pendiente de cobrar (paquetes en tránsito), hay que llamar `GET /api/transactions` filtrado por status/type. NO hay endpoint `/api/balance` separado | inferido de docs.ecartpay.com/docs/summaries |
| EP.L.14 | **MCP server existe** (docs.ecartpay.com/docs/mcp) pero rechazado por la misma política A.0.1 que rechazó Envia MCP — el LLM no decide verdad transaccional | doc + decisión interna |
| EP.L.15 | **Changelog Ecart Pay público es escueto**: solo 1 entry visible (Oct 2025 "Smarter Subscriptions & Webhooks"). NO hay changelog detallado de COD/Envia integration changes | docs.ecartpay.com/changelog |

---

## 5. Lo que tenemos vs lo que ofrece (auditoría)

**Estado actual del repo (rev. 105 Sem 4)**: **NO existe cliente Ecart Pay**. La integración con Ecart Pay es 100% indirecta vía Envia.

Inventario actual (referenciado contra `services/api/integrations/`):
- `envia_client.py` — sí.
- `wompi_client.py` — sí (PSP separado para flujos online).
- **`ecartpay_client.py` — NO existe**.
- `services/api/routers/envia_webhook.py` — sí.
- **`services/api/routers/ecartpay_webhook.py` — NO existe**.

### 5.1 Capacidades Ecart Pay que NO usamos hoy

| Capacidad | Usar en H.2.4? | Prioridad |
|---|---|---|
| `POST /api/webhooks` registro | **SÍ** — registrar webhook /webhooks/ecartpay/{tenant_id} para `transfer.created` + `withdrawals.paid` | P0 |
| Verificación HMAC-SHA256 webhook | **SÍ** — defensa primaria criptográfica | P0 |
| `GET /api/transactions/summary` | **SÍ** — para mostrar al merchant en dashboard "saldo Ecart Pay COP pendiente de retiro" | P1 |
| `GET /api/withdrawals` historial | SÍ — para mostrar histórico retiros en dashboard merchant | P1 |
| `GET /api/billings/providers` (Siigo CO) | NO en MVP — facturación KAIU es flow separado | P2 |
| `POST /api/orders` con `shipping_items.carrier=envia` | NO en MVP — flujo COD no requiere crear orden Ecart Pay manual | P3 |
| `POST /api/customers` | NO — los customers Ecart Pay no se crean por nuestro lado en COD | P3 |
| `POST /api/payouts` (intra-network) | NO — no aplica a B2C COD | P3 |
| `POST /api/tokens` (tokenización tarjeta) | NO — usamos Wompi para tarjeta | P3 |
| MCP Ecart Pay | **NO** — rechazado por A.0.1 | rechazado |

### 5.2 Endpoints requeridos para H.2.4 MVP

Cliente HTTP mínimo `services/api/integrations/ecartpay_client.py` debe exponer:

1. `auth_token()` — refresh Basic→token con cache 50 min per-tenant.
2. `register_webhook(url, events, secret)` — onboarding inicial del tenant (one-time setup).
3. `verify_webhook_signature(timestamp, webhook_id, body, signature, secret)` — defensa receiver.
4. `get_balance_summary()` — opcional UI dashboard.
5. `list_withdrawals(limit, status)` — opcional UI dashboard.

**Estimado**: 1.5-2 días-dev considerando que es un cliente delgado sin lógica de orders/payouts/customers.

---

## 6. Gaps críticos

### EP.G.P0 — Bloqueantes producción COD

- **EP.G.P0.1**: Cliente HTTP Ecart Pay con auth Basic+token cache. Sin esto NO se pueden registrar webhooks programáticamente (queda manual por dashboard). **Mitigación temporal**: registrar webhook manualmente en panel Ecart Pay durante onboarding tenant.
- **EP.G.P0.2**: Webhook receiver `/webhooks/ecartpay/{tenant_id}` con HMAC-SHA256 verification. Sin esto, dependeríamos solo de webhooks Envia para cerrar el lazo COD (pierde reconciliación con dinero real recibido).
- **EP.G.P0.3**: Tabla `ecartpay_webhook_events` (similar a `envia_webhook_events`) con dedup por `webhook_id` para idempotencia.

### EP.G.P1 — Hardening

- **EP.G.P1.1**: Reconciliación COD: cuando llega `transfer.created`, matchear contra `shipment` por `reference_id` para confirmar que ese dinero corresponde a este pedido. Si no matchea → alerta.
- **EP.G.P1.2**: UI dashboard merchant: mostrar saldo Ecart Pay pendiente + historial retiros + próxima fecha de retiro disponible (martes/viernes).

### EP.G.P2 — Defer

- **EP.G.P2.1**: Integración facturación Siigo (provider Colombia). NO en MVP.
- **EP.G.P2.2**: Cliente Ecart Pay como PSP standalone (charges con tarjeta) — NO en scope (Wompi cubre eso).

---

## 7. Análisis crítico

**¿Sobre-ingeniamos al construir cliente Ecart Pay propio?**
- **NO**. Sin cliente:
  1. No hay manera programática de registrar webhooks → onboarding tenant manual y propenso a error.
  2. La verificación HMAC-SHA256 debe estar en código nuestro (no en Ecart Pay) → necesita el cliente para acceder al secret almacenado en Vault.
  3. UI dashboard merchant requiere balance/withdrawals reads → requiere cliente con auth resuelto.

**¿Sub-aprovechamos al ignorar Orders / Customers / Payouts?**
- **NO** para H.2.4. Esos flujos son de Ecart Pay como PSP; el flow COD-Envia es independiente y self-contained.
- Sí para futuro: si KAIU expande a "ofrecer Ecart Pay como PSP a cliente final" (alternativa a Wompi), entonces Orders + Customers + Tokens entran en scope. Pero NO ahora.

**Riesgo dependencia comercial**: Ecart Pay y Envia son del **mismo grupo (Tendencys)**. La política "0% comisión COD Colombia" es comercial, NO técnica. Si Tendencys cambia política sin notice, el merchant ve cargos sorpresa. Mitigación: monitoring `transfer.created` payload para detectar `fee` o `commission` no esperado y alertar al merchant.

---

## 8. Recomendaciones priorizadas para H.2.4

### Sem 7-8 (siguiendo el plan H.2 actual)

**Día 1-2 — Cliente Ecart Pay base**:
1. Crear `services/api/integrations/ecartpay_client.py` con auth Basic+token cache.
2. Métodos: `register_webhook`, `verify_signature`, `get_balance_summary`, `list_withdrawals`.

**Día 3 — Webhook receiver**:
3. Router `services/api/routers/ecartpay_webhook.py` con HMAC verification.
4. Tabla `ecartpay_webhook_events` con UNIQUE(webhook_id) para dedup.
5. Handler para `transfer.created` + `withdrawals.paid` que persista evento + actualice `cart.cod_status`.

**Día 4 — Reconciliación**:
6. Job que match `transfer.created.reference_id` contra `shipment.tracking_number` para vincular dinero ↔ shipment.

**Día 5 — Smoke E2E sandbox**:
7. Crear shipment COD sandbox → simular delivery → verificar webhook Envia → verificar webhook Ecart Pay (`transfer.created`).

**Total**: ~5 días-dev efectivos (paralelizable con cierre G.P1.1 COD del dossier Envia).

### Backlog post-MVP

- UI dashboard merchant para balance + retiros (1 día).
- Integración Siigo facturación (2-3 días, defer hasta KAIU lo pida).
- Cliente Ecart Pay como PSP alternativo (NO scope actual).

---

## 9. Validaciones humanas pendientes

> **INTERVENCIÓN HUMANA REQUERIDA** — bloqueantes antes de implementar EP.G.P0.

### Confirmaciones oficiales recibidas 2026-05-07

Founder confirmó con ejecutivo Envia/Ecart Pay las siguientes
respuestas (VER también `envia-dossier-2026-05-05.md` sección L.10):

- **Payout cycle**: semanal, martes + viernes ✅
- **Comisión por COD**: $5,000 COP fijo (NO porcentaje) ✅
- **Retención**: NO hay ✅
- **Mínimo**: no hay explícito; constraint práctico: el COD debe cubrir
  los $5,000 de comisión (NO tiene sentido COD < $5,000) ✅

Items siguientes (EP.V.1 a EP.V.6) NO fueron confirmados por
ejecutivo. **Decisión founder 2026-05-07**: "basarnos en la
documentación" → arrancar implementación EP.G.P0 con docs como
referencia, ajustar empíricamente con primer tenant productivo si
aparecen sorpresas runtime.



### EP.V.1 — Vinculación cuenta Ecart Pay ↔ cuenta Envia (per-tenant onboarding)
- **RESPONSABLE**: Founder + Envia/Ecart Pay account manager.
- **PASOS**: confirmar si al activar COD en Envia se provisiona auto cuenta Ecart Pay vinculada o si requiere onboarding manual separado.
- **CRITERIO ÉXITO**: documento que defina el flow exacto de onboarding tenant.

### EP.V.2 — Public+Private API keys: dónde y cómo se obtienen para Colombia
- **RESPONSABLE**: Founder.
- **PASOS**: login a panel Ecart Pay con cuenta CO sandbox → ubicar Settings → Developers → API Keys.
- **CRITERIO ÉXITO**: keys sandbox CO obtenidas y almacenadas en Vault test-env.

### EP.V.3 — KYC requirements para activar cuenta Ecart Pay Colombia
- **RESPONSABLE**: Founder + soporte Ecart Pay.
- **PASOS**: solicitar checklist KYC formal (cédula, RUT, certificación bancaria, prueba de domicilio).
- **CRITERIO ÉXITO**: lista cerrada de docs requeridos por país.

### EP.V.4 — Schema empírico webhook `transfer.created` para flujo COD-Envia
- **RESPONSABLE**: Founder.
- **PASOS**: crear shipment COD sandbox → esperar entrega simulada → capturar webhook `transfer.created` → persistir en `docs/research/empirical-evidence/ecartpay-transfer-created-2026-XX-XX.json`.
- **CRITERIO ÉXITO**: schema JSON congelado con campos como `amount`, `currency`, `reference_id`, `available_at`, `fee` confirmados.

### EP.V.5 — Confirmar que el campo `reference_id` en `transfer.created` mapea a `tracking_number` Envia
- **RESPONSABLE**: Founder (junto con EP.V.4).
- **PASOS**: comparar `transfer.created.reference_id` vs el `tracking_number` del shipment Envia que generó el COD.
- **CRITERIO ÉXITO**: regla de mapeo confirmada empíricamente. Si NO mapea directamente, identificar campo alternativo (puede ser `notes`, `description` u otro).

### EP.V.6 — Política exacta de retenciones fiscales Colombia (ReteFuente, ReteIVA, ReteICA)
- **RESPONSABLE**: Founder + asesor contable Colombia.
- **PASOS**: confirmar si Ecart Pay deposita gross o aplica retenciones automáticas. Si aplica, qué % y cuáles retenciones.
- **CRITERIO ÉXITO**: tabla `retenciones × supuesto fiscal merchant (régimen común vs simplificado)`.

### EP.V.7 — IPs origen webhooks Ecart Pay (defensa segunda)
- **RESPONSABLE**: Founder + soporte Ecart Pay.
- **PASOS**: solicitar listado IPs origen webhook delivery.
- **CRITERIO ÉXITO**: CIDR confirmados (mitigación complementaria al HMAC).

---

## 10. Veredicto final

### DECISION FINAL
**GO arquitectónico, scope limitado**. Ecart Pay es la pieza monetaria correcta para H.2.4 COD, pero **no requiere implementación de cliente HTTP completo en MVP**. Lo mínimo viable es: webhook receiver con HMAC-SHA256 + reconciliación contra shipments. La auto-creación de webhooks programática (vía POST /api/webhooks) puede deferirse a Sprint posterior con onboarding manual en Sprint 1.

### VALIDAR EN DOCUMENTACIÓN OFICIAL
Antes de cerrar EP.G.P0:
- Confirmar HMAC base string format empíricamente (EP.L.11 advierte sobre JSON.stringify whitespace sensitivity).
- Confirmar lista exacta de eventos suscritos al webhook (al registrarlo via POST /api/webhooks): debe incluir `transfer.created` + `withdrawals.paid`. **NO** suscribir a all-events (ruido).
- Validar timezone del `available_at` campo en `transfer.created` — la doc no aclara si es UTC o America/Mexico_City.

### RIESGO
**Bajo**. La superficie técnica es pequeña (1 cliente delgado + 1 receiver + 1 tabla). Riesgos residuales:
- **EP.L.6** (creación de retiros NO programática) — significa que el merchant SIEMPRE entra a panel Ecart Pay para retirar. UX subóptimo pero no bloqueante MVP.
- **EP.L.8** (política comercial 0% comisión Colombia) — riesgo de cambio sorpresivo. Mitigación: alerta automática si `transfer.created.fee != 0`.
- **EP.L.4** (KYC sin docs) — bloqueante onboarding pero NO bloqueante código.

### IMPACTO OPERATIVO
- Esfuerzo MVP COD-Ecart Pay = **~5 días-dev** (paralelizable con cierre dossier Envia).
- Bloqueante humano principal: **EP.V.1 (onboarding tenant flow)** + **EP.V.4 (schema empírico transfer.created)**.

### INTERVENCIÓN HUMANA REQUERIDA
7 validaciones (EP.V.1–EP.V.7) listadas en §9. EP.V.1, EP.V.2, EP.V.4, EP.V.5 son bloqueantes técnicos directos. EP.V.3, EP.V.6, EP.V.7 son hardening/legal/operational.

---

## Fuentes

- [Ecart Pay overview](https://docs.ecartpay.com/docs/all-about-ecart-pay)
- [Authorization Token](https://docs.ecartpay.com/docs/authorization-token)
- [API Keys](https://docs.ecartpay.com/docs/api-keys)
- [Accounts](https://docs.ecartpay.com/docs/accounts)
- [Customers](https://docs.ecartpay.com/docs/customers-1)
- [Orders](https://docs.ecartpay.com/docs/orders)
- [Payouts](https://docs.ecartpay.com/docs/payouts)
- [Confirmations (payouts)](https://docs.ecartpay.com/docs/confirmations)
- [Withdrawals](https://docs.ecartpay.com/docs/withdrawals)
- [Transfers](https://docs.ecartpay.com/docs/transfers)
- [Summaries](https://docs.ecartpay.com/docs/summaries)
- [Webhooks Overview](https://docs.ecartpay.com/docs/webhooks-in-ecart-pay)
- [Webhook Events](https://docs.ecartpay.com/docs/webhook-events)
- [Webhook Authentication](https://docs.ecartpay.com/docs/webhook-authentication)
- [Backend Integration](https://docs.ecartpay.com/docs/backend-integration)
- [Payment Gateways](https://docs.ecartpay.com/docs/payment-gateways)
- [Billings](https://docs.ecartpay.com/docs/billings)
- [Billing Providers](https://docs.ecartpay.com/docs/billing-providers)
- [Chargebacks](https://docs.ecartpay.com/docs/chargebacks)
- [Error Reference](https://docs.ecartpay.com/docs/error-reference-guide)
- [HTTP Status Codes](https://docs.ecartpay.com/docs/http-status-code-guide)
- [SDKs](https://docs.ecartpay.com/docs/sdks)
- [MCP Server](https://docs.ecartpay.com/docs/mcp) — rechazado por A.0.1
- [Payins](https://docs.ecartpay.com/docs/payins)
- [Changelog](https://docs.ecartpay.com/changelog)
- [Sumsub partnership con Ecart Pay (KYC vendor)](https://sumsub.com/customers/ecartpay/)

**Cifras de help.envia.com (Cloudflare 403 — citadas vía SERP snippets oficiales 2026-05-07)**:
- [Withdraw COD Money](https://help.envia.com/en/withdraw-cod/) — fees 5,000 COP, retiros martes/viernes 9:30 AM México, 24-48h banco.
- [Cash on Delivery (COD)](https://help.envia.com/en/shipments-cod/) — 72h post-shipment, países disponibles (excluye AR/CL/US/BR), requiere phone number.
- [Cash on Delivery section](https://help.envia.com/en/cod/) — overview comisiones.
- [Automatic COD Billing](https://help.envia.com/en/automatic-cod-billing/) — monthly summary commissions invoicing.
- [Confirmation by WhatsApp for COD](https://help.envia.com/en/confirmation-cod/) — feature opcional.
- [Servientrega Colombia](https://help.envia.com/servientrega-co/) — DANE sender code requirement (snippet vía SERP).
