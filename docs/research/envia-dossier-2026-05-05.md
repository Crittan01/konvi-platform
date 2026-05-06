# Dossier Envia.com — 2026-05-05

**Fecha**: 2026-05-05 · **Sesión**: investigación previa Sección H.2 plan maestro · **Sin pruebas en vivo**.
**Fuente primaria**: `https://docs.envia.com/docs/*` (público).
**Cobertura**: Shipping API + Queries API + Geocodes API + Webhooks + MCP.
**Alcance**: foco Colombia (CO). Modelo B confirmado (api_token per tenant en Vault).

---

## 1. TL;DR ejecutivo

Envia es un **agregador de logística multi-carrier** con cobertura de **12 países** (Argentina, Brasil, Canadá, Chile, **Colombia**, España, Francia, Guatemala, India, Italia, México, EE.UU.) y **100+ transportistas** integrados detrás de una sola API REST con autenticación Bearer ([getting-started](https://docs.envia.com/docs/getting-started)). Para Colombia la documentación lista al menos 12 carriers: `coordinadora`, `serviEntrega`, `tcc`, `interRapidisimo`, `envia` (carrier propio), `deprisa`, `dhl`, `fedex`, `cabify`, `cainiao`, `lastMile`, `noventa9Minutos` ([supported-carriers](https://docs.envia.com/docs/supported-carriers)). Modelo de negocio: **per-shipment markup** sobre la tarifa del carrier (no documentado el spread). Producción "creates actual shipments and **charges your account**" ([authentication](https://docs.envia.com/docs/authentication)).

Tres APIs separadas con bases distintas:

| API | Sandbox | Producción |
|---|---|---|
| Shipping | `https://api-test.envia.com/` | `https://api.envia.com/` |
| Queries | `https://queries-test.envia.com/` | `https://queries.envia.com/` |
| Geocodes | (sin sandbox) | `https://geocodes.envia.com/` |

**Decisión arquitectónica clave**: Envia es el stack correcto para Colombia (acceso a 70+ carriers via 1 contrato técnico). El esfuerzo restante para cierre P0+P1 ronda **9-10 días-dev** (idempotency local + webhooks E2E + polling + COD + insurance + Fase 2 flag per-tenant).

---

## 2. Hallazgos clave

### 2.1 Endpoints Shipping API
Verbo + path documentados ([core-workflow](https://docs.envia.com/docs/core-workflow), [quickstart](https://docs.envia.com/docs/quickstart)):

- `POST /ship/rate/` — cotiza tarifas de un carrier. Retorna `data[]` con `totalPrice`, `currency`, `deliveryEstimate`. **Una cotización por request, un carrier por request** ("The rate endpoint accepts one carrier per request"). NO retorna un `rate_id` reutilizable.
- `POST /ship/generate/` — compra y emite la etiqueta. Devuelve `trackingNumber`, `shipmentId`, `label` (PDF URL).
- `POST /ship/generaltrack/` — consulta tracking de uno o varios `trackingNumbers`.
- `POST /ship/pickup/` — agenda recogida con el carrier. Body: `carrier`, `pickupDate`, `pickupTimeStart`, `pickupTimeEnd`, `pickupAddress`, `trackingNumbers[]`. Respuesta: `confirmation` (e.g. `PKP-2026-04150001`), `status`, `date`, `timeFrom/timeTo` ([pickups](https://docs.envia.com/docs/pickups)).
- `POST /ship/cancel/` — anula etiqueta. Documentación admite ventana ("possible until cancellation window expired").

### 2.2 Autenticación
Header `Authorization: Bearer <ENVIA_TOKEN>` ([authentication](https://docs.envia.com/docs/authentication)). Token se obtiene en dashboard → "Desarrolladores → Acceso de API". Tokens son **por ambiente** (sandbox-token NO autentica producción y viceversa). **No documentado**: scopes granulares, expiración, sub-cuentas, API keys per-merchant dentro de cuenta master, rotación programática.

### 2.3 Sandbox vs Producción
La página `/docs/sandbox-vs-production` retorna **404**, pero los hechos diferenciales aparecen distribuidos en [authentication](https://docs.envia.com/docs/authentication), [quickstart](https://docs.envia.com/docs/quickstart) y [integration-guide](https://docs.envia.com/docs/integration-guide):

- **Sandbox** simula precios ("simulated prices that may differ from production rates"), genera labels **no válidos para retiro real** ("sandbox labels are not valid for carrier pickup"), y tracking es simulado.
- **Producción** "creates actual shipments and charges your account": cada `/ship/generate/` debita el saldo prepagado de la cuenta.
- Producción exige flujo "validate balance before creating labels" ([integration-guide](https://docs.envia.com/docs/integration-guide)).
- Webhooks deben **registrarse separadamente** por ambiente ([production-checklist](https://docs.envia.com/docs/production-checklist): "Registered separate webhook URLs for sandbox and production").

### 2.4 Modelo de cotización rate→generate
- `rate` y `generate` son operaciones **independientes**: no hay token de sesión, no hay `rate_id` reutilizable, no hay TTL oficial documentado entre ambos pasos ([core-workflow](https://docs.envia.com/docs/core-workflow): "you must repeat the rate request or store the selected service details before calling generate").
- El cliente debe persistir lo seleccionado y enviarlo de nuevo en `generate`. Si el precio cambió, Envia cobrará la tarifa vigente al momento de `generate`.
- **Implicación arquitectónica**: el patrón "cart-as-SoT con recotización lazy" del repo (ADR-0011 §6.4.1) **es exigido por la propia limitación de Envia**, no es over-engineering.

### 2.5 Additional services documentados
([additional-services](https://docs.envia.com/docs/additional-services))

| Identifier | Parámetro requerido | Aplica a | Notas |
|---|---|---|---|
| `envia_insurance` | `amount` (declared value) | Parcel, LTL | Cobertura por Envia |
| (carrier_insurance) | — | Parcel, LTL, FTL | Cobertura por términos del carrier; **identifier no documentado** |
| `cash_on_delivery` | `amount` | Parcel | "Integrated with Ecart Pay for automated payment reconciliation"; rate response devuelve `cashOnDeliveryCommission` y `cashOnDeliveryAmount` |
| `electronic_signature` | — | Parcel | Firma digital legal |
| (pickup_point_delivery) | — | Parcel | identifier no documentado |
| (delivery_appointment) | — | LTL, FTL | identifier no documentado |
| (hydraulic_ramp) | — | LTL | identifier no documentado |
| (dedicated_service) | — | FTL | identifier no documentado |

---

## 3. Multi-tenant compatibility

**Modelo B (key per tenant) — único viable confirmado.**

- La documentación de [authentication](https://docs.envia.com/docs/authentication) **no menciona** sub-cuentas, multi-account ni API keys por merchant dentro de una cuenta master. La capacidad existe a nivel marketplace caso de uso ("Marketplace Multi-Seller Shipping" en [integration-guide](https://docs.envia.com/docs/integration-guide)) pero **no se expone en API pública**.
- Modelo A (cuenta master + metadata `additional_information` para distinguir tenant) tiene tres bloqueos:
  1. La factura/balance es única por cuenta → imposible repartir débitos por tenant.
  2. Webhooks llegan a una sola URL sin tenant_id (no hay header de cuenta).
  3. Cancelación / soporte sin trazabilidad por tenant.
- **Decisión confirmada**: cada tenant onboarda su propia cuenta Envia, su propio token sandbox y producción, almacenado en `tenant_integrations.credentials.api_token` con cifrado (Vault).
- **Ausente en docs Envia**: programa "partner" oficial (que sí existe en otros agregadores como ShipEngine). Cualquier modelo Modelo A queda no soportado contractualmente.

---

## 4. Limitaciones documentadas

Limitaciones **citadas textualmente desde docs públicos**:

| # | Limitación | Cita / fuente |
|---|---|---|
| L.1 | **Errores con HTTP 200**: `"Some Shipping API errors return HTTP 200 with `\"meta\": \"error\"` in the body instead of a 4xx status code"` ([error-codes](https://docs.envia.com/docs/error-codes)) — exige inspeccionar siempre el campo `meta` |
| L.2 | **Sin Idempotency-Key server-side**: ni en [error-codes](https://docs.envia.com/docs/error-codes), ni en [integration-guide](https://docs.envia.com/docs/integration-guide), ni en [production-checklist](https://docs.envia.com/docs/production-checklist) se menciona un header `Idempotency-Key`. Idempotencia es responsabilidad del cliente |
| L.3 | **Sin firma HMAC en webhooks**: la guía [webhooks](https://docs.envia.com/docs/webhooks) **no menciona** HMAC, secrets, headers `X-Signature` ni IP allowlist. La única recomendación de seguridad es HTTPS + `2xx <5s` + idempotencia local |
| L.4 | **Sin TTL oficial entre `rate` y `generate`**: no aparece en [core-workflow](https://docs.envia.com/docs/core-workflow). El precio cobrado es el vigente en `generate` |
| L.5 | **Webhook delivery semantics no formalizadas**: "No explicit delivery guarantee model stated (at-least-once vs exactly-once); retry policy not documented" ([webhooks](https://docs.envia.com/docs/webhooks)). La guía recomienda "implement idempotency by tracking processed events" |
| L.6 | **Cancelación de pickup**: la documentación de [pickups](https://docs.envia.com/docs/pickups) **no incluye** endpoints de reschedule/cancel pickup |
| L.7 | **Tracking events no enumerados**: [webhook-types](https://docs.envia.com/docs/webhook-types) sólo expone `GET /webhook-types` para listar tipos en runtime; los schemas de payload **no están en docs** y deben descubrirse empíricamente con "Test Webhook" |
| L.8 | **Cobertura per-carrier dispersa**: la matriz de capabilities (¿qué carrier soporta `cash_on_delivery`? ¿`envia_insurance`?) NO existe en docs como tabla. Hay que combinar [supported-carriers](https://docs.envia.com/docs/supported-carriers) con [Queries API](https://docs.envia.com/docs/queries-api-overview) en runtime |
| L.9 | **Sin SLA documentado**: ni latencia, ni uptime, ni RTO/RPO formales en docs |
| L.10 | **Identifiers de servicios incompletos**: `carrier_insurance`, `pickup_point_delivery`, `delivery_appointment`, `hydraulic_ramp`, `dedicated_service` **no exponen identifier en docs** ([additional-services](https://docs.envia.com/docs/additional-services)) |
| L.11 | **Webhook secret rotable: no soportado**: el body de creación documentado en [webhooks](https://docs.envia.com/docs/webhooks) sólo tiene `type_id`, `url`, `active`. **No hay campo `secret`/`token`** |
| L.12 | **Códigos HTTP retornables**: `400, 401, 422, 429, 500, 502, 503` ([error-codes](https://docs.envia.com/docs/error-codes)) + el caso especial 200+`meta:error` |

---

## 5. Lo que tenemos vs lo que ofrece (auditoría code-by-code)

Revisado contra `services/api/integrations/envia_client.py` (12 métodos) y `services/api/routers/shipping.py`:

### 5.1 Métodos implementados en `envia_client.py`

| Método cliente | Endpoint Envia | Estado | Comentario |
|---|---|---|---|
| `get_rates` | `POST /ship/rate/` | ✅ Activo Fase 1 | Maneja `meta:"error"` (línea 78) y caso `code+message` sin data (línea 89) — bien |
| `generate_label` | `POST /ship/generate/` | ⚠️ Detrás de `ENVIA_PHASE2_ENABLED` | NO inspecciona `meta:"error"` (línea 110): retorna `resp.json()` directamente. Riesgo L.1 |
| `track_shipments` | `POST /ship/generaltrack/` | ⚠️ Detrás de flag | Mismo riesgo L.1: no audita `meta` |
| `schedule_pickup` | `POST /ship/pickup/` | ⚠️ Detrás de flag | Idem |
| `cancel_shipment` | `POST /ship/cancel/` | ⚠️ Detrás de flag | Idem |
| `get_available_carriers` | Queries `GET /available-carrier/{country}/{type}` | ✅ Activo | Ruta legacy de 2 segmentos |
| `get_available_carriers_with_shipment_type` | Queries `GET /available-carrier/{country}/{international}/{shipment_type_id}` | ✅ Activo | Ruta nueva de 3 segmentos |
| `get_states_by_country` | Queries `GET /state` | ✅ Activo | |
| `get_cities_by_state` | Queries `GET /city` | ✅ Activo | |
| `get_city_by_code` | Queries `GET /city/{code}` | ✅ Activo | |
| `get_address_structure` | Queries `GET /generic-form` | ✅ Activo | |
| `validate_zip_code` | Geocodes `GET /zipcode/{country}/{zipcode}` | ✅ Activo | DANE 8-dígitos OK |

### 5.2 Capacidades documentadas Envia que NO usamos

| Capacidad Envia | ¿La usamos? | Impacto comercial |
|---|---|---|
| `additional_services.cash_on_delivery` | ❌ No | **Alto** — COD es ~30-40% del e-commerce Colombia (Servientrega, Coordinadora) |
| `additional_services.envia_insurance` | ❌ No | Medio — exigido por Coordinadora para cargas >$2M COP |
| `additional_services.carrier_insurance` | ❌ No | Medio |
| `additional_services.electronic_signature` | ❌ No | Bajo — útil B2B |
| Webhooks (cualquier tipo) | ❌ No | **Crítico** — sin webhooks tracking se queda sin actualización |
| `Queries /webhook-types` | ❌ No | Bloqueante para registrar webhooks |
| `Queries /webhooks` (CRUD) | ❌ No | Idem |
| Polling tracking de respaldo | ❌ No | Sin webhooks **y** sin polling = ceguera operativa |
| MCP Server | ❌ No (rechazado) | Decisión Plan A.0.1 — el LLM no decide verdad transaccional |

### 5.3 Estado del flag Fase 2

`services/api/routers/shipping.py:41`:
```python
ENVIA_PHASE2_ENABLED = os.getenv("ENVIA_PHASE2_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
```

Es **global por proceso**, no per-tenant. Implicación: cuando se habilite generation/tracking/pickup/cancel, todos los tenants quedan habilitados en simultáneo. Para rollout gradual hace falta migrar a flag per-tenant en `tenant_integrations.feature_flags`.

### 5.4 Enforcement país = CO

`shipping.py:64-87`: `_normalize_country` fuerza default `CO` y normaliza state a 3 chars. Pero NO hay un guard `if country != "CO": raise 400`. Una entrada con `country="MX"` se procesaría sin objeción por el router (Envia respondería con error de carrier no disponible — fallback débil). **Gap**: enforcement runtime explícito.

---

## 6. Gaps críticos priorizados

### P0 (bloquean operación / riesgo financiero) — Sem 4-5

- **G.P0.1 — Idempotency local en `generate_label`**. Sin Idempotency-Key server-side (L.2), un retry de red o un doble-click del operador puede emitir 2 etiquetas → 2 débitos. Mitigación: hash determinista `sha256(tenant_id|cart_id|carrier|service)` persistido en tabla `envia_label_locks` (UNIQUE), con TTL 24h.
- **G.P0.2 — Webhook receiver E2E** con HMAC propio vía URL secret-token. Como Envia no firma (L.3, L.11), la única defensa es: registrar URL `https://api.example.com/webhooks/envia/<tenant_id>?token=<rotable-uuid>` y validar en endpoint que el token coincide con el secret almacenado en `tenant_integrations`. Rotable per-tenant.
- **G.P0.3 — Polling tracking de respaldo**. Webhooks at-least-once sin garantía formal (L.5). Implementar cron cada N minutos que llame `track_shipments` para shipments en estado no-terminal con última actualización >N min.
- **G.P0.4 — Auditar `meta:"error"` en TODOS los métodos Fase 2**. Hoy `generate_label`, `track_shipments`, `schedule_pickup`, `cancel_shipment` retornan `resp.json()` sin inspeccionar `meta` (L.1) → riesgo de tratar errores como éxitos.

### P1 (cierra gaps funcionales) — Sem 6

- **G.P1.1 — Cash on Delivery**: integrar `additional_services.cash_on_delivery` en payload de `rate` y `generate`. Persistir `cashOnDeliveryCommission` por carrier en `cart_proposals.shipping_breakdown`. Conciliar payouts vía Ecart Pay → requiere validación V.1 + V.3.
- **G.P1.2 — Insurance enforcement**: cuando `cart_total > UMBRAL` (ej. 2M COP) o carrier=`coordinadora`, **forzar** `envia_insurance` con `amount=cart_subtotal`. Sin esto, Coordinadora rechaza generate o limita responsabilidad.
- **G.P1.3 — Fase 2 flag per-tenant**: migrar `ENVIA_PHASE2_ENABLED` global → `tenant_integrations.feature_flags.envia_phase2_enabled`. Permite rollout pilot con 1 tenant.
- **G.P1.4 — Capabilities matrix per-carrier per-tenant**: cachear en `tenant_carrier_capabilities` qué carriers tiene activos cada tenant, qué `additional_services` soporta, qué `sender_code` requiere. Refresh diario via Queries API.
- **G.P1.5 — Smoke E2E test** sandbox: rate → generate → mock webhook → cancel. Bloqueante de "ready for prod".

### P2 (hardening) — Sem 7-8

- **G.P2.1 — Cache 24h Queries API** (carriers, states, cities). Hoy se pega cada cotización; ahorra tokens y latencia.
- **G.P2.2 — Circuit breaker per-tenant** sobre el cliente HTTP (5 fallos consecutivos → open 60s → half-open). Mismo patrón que H.3.4 Wompi.
- **G.P2.3 — Runtime enforcement `country=='CO'`**: rechazar 400 si origen o destino no-CO antes de llamar Envia.
- **G.P2.4 — Reintentos exponenciales** (1s/2s/4s, 3 max) sólo para 5xx + timeouts + 429. NO para 400/401/422 ([error-codes](https://docs.envia.com/docs/error-codes)).
- **G.P2.5 — Métricas Prometheus**: latencia per-endpoint, ratio de `meta:error`, errores 5xx, tasa de webhooks duplicados.

### P3 (defer / fuera de scope) — Backlog

- **G.P3.1 — Branded tracking page**: hosted page propio en lugar de redireccionar al carrier.
- **G.P3.2 — RMA / returns flow**: Envia tiene endpoints de retorno no auditados aquí.
- **G.P3.3 — MCP**: rechazado (Plan A.0.1 — el LLM no decide verdad transaccional).

---

## 7. ¿Estamos sobre-ingeniando o sub-aprovechando?

**Sobre-ingeniería**: NO. El patrón "cart-as-SoT con recotización lazy" del repo es **estrictamente requerido por las limitaciones de Envia**, no una elección de diseño excesiva. Específicamente, compensa **3 limitaciones documentadas**:

1. L.4 (sin TTL oficial rate→generate) → recotización lazy garantiza que el precio cobrado sea el vigente.
2. L.2 (sin Idempotency-Key) → idempotencia local con hash determinista evita doble-cobro.
3. L.5 (webhook semantics no formalizadas) → cart como SoT permite reconstruir estado desde DB si se pierde un evento.

**Sub-aprovechamiento**: SÍ, en tres ejes críticos:

- **COD** (L.10/G.P1.1): no se está exponiendo un servicio que cubre un segmento sustancial del e-commerce colombiano.
- **Insurance** (G.P1.2): no se está cumpliendo requisito implícito de Coordinadora para cargas medias-altas.
- **Capabilities matrix** (G.P1.4): el cliente HTTP existe pero no aprovecha Queries API para descubrir qué cada tenant puede usar — se está cotizando "a ciegas" con whitelist hardcoded.

---

## 8. Recomendaciones priorizadas

### Sem 4-5 — P0 (idempotencia, observabilidad, defensa webhook)
1. **G.P0.4 + G.P0.1**: refactor `envia_client.py` para que `generate_label/track/pickup/cancel` inspeccionen `meta:"error"` igual que `get_rates` ya hace. Crear tabla `envia_label_locks` (UNIQUE hash). Estimado: 1.5 días.
2. **G.P0.2**: router `POST /webhooks/envia/{tenant_id}` con query `?token=<secret>`. Validar token contra `tenant_integrations.envia_webhook_secret` (rotable). Persistir evento en `envia_webhook_events` con dedup por payload-hash. Estimado: 2 días.
3. **G.P0.3**: cron en `services/ai-orchestrator/worker.py` (o nuevo job) que cada 30 min llame `track_shipments` para shipments en `in_transit` con `last_update > 6h`. Estimado: 1 día.

### Sem 6 — P1 (capabilities, COD, insurance)
4. **G.P1.4**: tabla `tenant_carrier_capabilities` + refresh job diario. Estimado: 1 día.
5. **G.P1.1**: extender `cart_proposals` con `additional_services` y propagar a `rate`/`generate`. Persistir `cashOnDeliveryCommission`. Estimado: 1.5 días.
6. **G.P1.2**: regla de negocio "insurance forzado si total>2M o carrier=coordinadora". Estimado: 0.5 días.
7. **G.P1.3**: migrar flag global → per-tenant. Estimado: 0.5 días.
8. **G.P1.5**: smoke E2E sandbox. Estimado: 1 día.

**Total P0+P1 estimado**: ~9-10 días-dev efectivos.

### Sem 7-8 — P2 (hardening)
9-13. Cache + circuit breaker + country guard + retry policy + métricas. Estimado: ~3-4 días.

---

## 9. Validaciones humanas pendientes

> **INTERVENCIÓN HUMANA REQUERIDA** — bloqueantes antes de implementar P1.

### V.1 — Ecart Pay payout cycle, fees, retención
- **RESPONSABLE**: Founder + Envia Sales (Colombia).
- **PASOS**: solicitar a account manager Envia (a) ciclo de payout COD (T+N), (b) % comisión Ecart Pay, (c) retenciones fiscales aplicables (ReteFuente, ReteIVA, ReteICA por municipio), (d) requerimientos KYC para activar Ecart Pay.
- **INSUMOS**: NIT cuenta Envia, certificación bancaria.
- **CRITERIO DE ÉXITO**: documento firmado o email oficial con tabla de fees + ciclo + retenciones.
- **JUSTIFICACIÓN**: docs Envia sólo declaran "deposited to your registered account according to the payment schedule" sin números.

### V.2 — Carriers exactos que soportan COD en cuenta sandbox del tenant
- **RESPONSABLE**: Founder.
- **PASOS**: (a) llamar `Queries /available-carrier/CO/0/1` con token sandbox; (b) por cada carrier listado, cotizar `rate` con `additional_services.cash_on_delivery`; (c) registrar cuáles aceptan vs cuáles devuelven `meta:"error"` o `code` de feature no soportada.
- **INSUMOS**: token sandbox + script de barrido.
- **CRITERIO DE ÉXITO**: matriz `carrier × cod_supported` persistida.
- **JUSTIFICACIÓN**: la matriz NO está en docs ([supported-carriers](https://docs.envia.com/docs/supported-carriers) sólo lista formats de label, no capabilities).

### V.3 — Shape exacto del webhook `cash_on_delivery_paid` (o equivalente)
- **RESPONSABLE**: Founder (sandbox empírico).
- **PASOS**: (a) `GET queries-test.envia.com/webhook-types` para obtener catálogo runtime; (b) registrar webhook con `type_id` candidato a COD; (c) crear shipment COD en sandbox; (d) capturar payload entregado al endpoint Test Webhook.
- **INSUMOS**: cuenta sandbox activa, ngrok o equivalente.
- **CRITERIO DE ÉXITO**: schema JSON congelado en `docs/research/envia-webhook-payloads/cod-paid.example.json`.
- **JUSTIFICACIÓN**: docs Envia explícitamente recomiendan "Use the Test Webhook endpoint to see the real payload format for your webhook type before building your handler" ([webhooks](https://docs.envia.com/docs/webhooks)).

### V.4 — DANE sender code per carrier
- **RESPONSABLE**: Founder + ops carrier (especialmente Servientrega).
- **PASOS**: confirmar para cada carrier CO si requieren `senderCode`/`originCode`/equivalente, formato esperado (DANE 5 vs 8 dígitos), si lo provee Envia automáticamente o lo arma el merchant.
- **INSUMOS**: cuenta carrier directa o documentación interna de Envia.
- **CRITERIO DE ÉXITO**: tabla `carrier × sender_code_required × format`.
- **JUSTIFICACIÓN**: la doc pública [supported-carriers](https://docs.envia.com/docs/supported-carriers) no detalla esto. Servientrega históricamente exige código de remitente registrado.

### V.5 — IPs allowlist de webhooks Envia (defensa segunda)
- **RESPONSABLE**: Founder + soporte Envia.
- **PASOS**: solicitar por ticket el listado de IPs de origen desde donde Envia entrega webhooks.
- **INSUMOS**: ticket de soporte abierto.
- **CRITERIO DE ÉXITO**: listado de IPs (CIDR) recibido por escrito.
- **JUSTIFICACIÓN**: docs públicos NO declaran IPs. Esta validación es defensa-en-profundidad complementaria al token rotable per-tenant; si Envia confirma IPs estáticas, se puede agregar firewall match en el ingress de Render.

---

## 10. Veredicto final

### DECISION FINAL
**GO arquitectónico**. Envia es el stack correcto para Commerce Ops Platform en Colombia: 1 contrato técnico habilita acceso a 70+ carriers (Servientrega, Coordinadora, TCC, Interrapidísimo, Envia carrier propio, Deprisa, DHL, FedEx, etc.). Modelo B (key per tenant) es el único viable y ya está implementado correctamente.

### VALIDAR EN DOCUMENTACIÓN OFICIAL
Antes de cerrar P0+P1, gatilear:
- Antes de G.P0.2 (webhook receiver): leer empíricamente `GET queries-test.envia.com/webhook-types` (catálogo runtime) — V.3.
- Antes de G.P1.1 (COD): cerrar V.1 + V.2.
- Antes de G.P1.2 (insurance): leer carrier-by-carrier qué `additional_services` aceptan — V.2.
- Antes de cualquier llamada a Geocodes con cargo: verificar que Geocodes API es free-tier o ya está en plan del tenant ([authentication](https://docs.envia.com/docs/authentication) menciona "balance" sin desagregar Geocodes).

### RIESGO
**Medio-bajo**. Riesgos residuales no eliminables:
- **Sin SLA documentado** (L.9) — mitigación: circuit breaker + observabilidad propia (G.P2.5).
- **Sin firma webhook nativa** (L.3) — mitigación: token rotable per-tenant en URL (G.P0.2).
- **Ecart Pay payout payload semi-documentado** (L.5 + V.3) — mitigación: descubrimiento empírico antes de prod.
- **Errores HTTP 200** (L.1) — mitigación: auditar todos los métodos (G.P0.4).

### IMPACTO OPERATIVO
- Esfuerzo P0+P1 = **~9-10 días-dev efectivos**.
- Bloqueante humano principal: **V.1 (Ecart Pay terms)** — sin esto no hay COD productivo.
- Bloqueante humano secundario: **V.3 (webhook payload empírico)** — sin esto el receiver es teórico.

### INTERVENCIÓN HUMANA REQUERIDA
5 validaciones (V.1–V.5) listadas en §9. Todas anteceden la implementación de P1; G.P0.* (P0) puede empezar sin ellas porque son cambios cliente-side e idempotency local.

---

## Fuentes

- [Getting Started](https://docs.envia.com/docs/getting-started)
- [Quickstart](https://docs.envia.com/docs/quickstart)
- [Authentication](https://docs.envia.com/docs/authentication)
- [Integration Guide](https://docs.envia.com/docs/integration-guide)
- [Core Workflow](https://docs.envia.com/docs/core-workflow)
- [Domestic Shipping Workflow](https://docs.envia.com/docs/domestic-shipping-workflow)
- [Pickup & Manifest Workflow](https://docs.envia.com/docs/pickup-manifest-workflow)
- [Pickups](https://docs.envia.com/docs/pickups)
- [Delivery Estimate](https://docs.envia.com/docs/delivery-estimate)
- [Additional Services](https://docs.envia.com/docs/additional-services)
- [Webhooks Guide](https://docs.envia.com/docs/webhooks)
- [Webhook Types (runtime)](https://docs.envia.com/docs/webhook-types) — sólo expone `GET /webhook-types`; payloads no documentados
- [Error Response Formats](https://docs.envia.com/docs/error-codes)
- [Production Readiness Checklist](https://docs.envia.com/docs/production-checklist)
- [Supported Carriers](https://docs.envia.com/docs/supported-carriers)
- [Shipping API Introduction](https://docs.envia.com/docs/envia-shipping-api-introduction)
- [Queries API Overview](https://docs.envia.com/docs/queries-api-overview)
- [MCP Server](https://docs.envia.com/docs/mcp-overview) — auditado y rechazado (Plan A.0.1)
- [Changelog](https://docs.envia.com/docs/changelog)

URLs **404** detectadas (no existen aunque a veces se referencian): `/docs/sandbox-vs-production`, `/docs/rate`, `/docs/generate`, `/docs/tracking`, `/docs/cancel`, `/docs/cash-on-delivery`. La información equivalente sí está distribuida en las páginas listadas arriba.
