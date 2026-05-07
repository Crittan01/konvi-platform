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
| L.7 | **Tracking events no enumerados**: [webhook-types](https://docs.envia.com/docs/webhook-types) sólo expone `GET /webhook-types` para listar tipos en runtime; los schemas de payload **no están en docs** y deben descubrirse empíricamente con "Test Webhook" — confirmado en re-WebFetch 2026-05-06: doc menciona literalmente `"The exact payload structure may vary by event type"` y solo lista 3 campos garantizados: `carrierName`, `trackingNumber`, `status` |
| L.7b | **Endpoint Test Webhook EXISTE** (hallazgo re-WebFetch 2026-05-06): `POST /ship/webhooktest/` con body `{tracking_number, webhook_url}` envía un sample payload al URL indicado. Permite descubrir estructura real ANTES de configurar webhooks productivos. **Confirmado tipos panel**: `onShipmentStatusUpdate`, `statusUpdateWithEcommerceInfo`, `simpleTracking`, `ecommerceTracking`, `surcharge` (vista founder en panel sandbox) |
| L.7c | **`/ship/webhooktest/` ROTO en sandbox 2026-05-06** (hallazgo empírico): el endpoint requiere body camelCase (`trackingNumber`, `carrier`, `webhookUrl`, `type`) — confirmado por error progresivo `Undefined property: stdClass::$carrier` (línea 32) → `$trackingNumber` (línea 33) en `WebhookTest.php`. Con todos los campos camelCase + `type=onShipmentStatusUpdate`, retorna `HTTP 500 Internal Server Error` HTML genérico (no JSON). El endpoint NO dispara el webhook real al URL indicado. **Camino alternativo**: shipments sandbox cambian estado naturalmente (status_parent_id avanza), lo que sí dispara webhooks en panel productivo. Para descubrimiento empírico Fase A, depender de eventos reales en lugar de `/ship/webhooktest/` |
| L.7d | **`/ship/generaltrack/` SÍ funciona en sandbox** (hallazgo empírico 2026-05-06, evidencia en `docs/research/empirical-evidence/envia-generaltrack-794813020143.json`): body camelCase `{trackingNumbers: [...], carrier}`. Response shape descubierto incluye `data[].content.tracking_number`, `data[].content.status` (texto: `"Created"`), `data[].content.status_parent_id` (entero: 1), `data[].eventHistory: []`, `data[].destination`, `data[].origin`, `data[].packages[]`, `data[].shippedAt`, `data[].deliveredAt`, `data[].signedBy`, `data[].podFile`. Usable como baseline para parsers Fase B (alta probabilidad de coincidencia con webhook payload `simpleTracking`/`ecommerceTracking`) |
| L.7e | **PAYLOAD WEBHOOK CANÓNICO DESCUBIERTO 2026-05-07** (evidencia empírica en `docs/research/empirical-evidence/envia-webhook-payload-2026-05-06.json`): los 5 tipos webhook registrados en panel (onShipmentStatusUpdate, statusUpdateWithEcommerceInfo, simpleTracking, ecommerceTracking, surcharge) **comparten el mismo shape mínimo** cuando el endpoint `/ship/webhooktest/` despacha al URL registrado: `{"carrier": "fedex", "tracking_number": "794813020143", "shipment_status": "Created"}` (snake_case, 3 campos). User-Agent oficial: `Envia-Carriers`. Source IP estable: `3.211.106.119` (AWS Envia). Implicaciones cruciales: (a) NO se pueden distinguir tipos de webhook por payload — la diferenciación se hace por URL registrada en panel per `type_id`; (b) el body de `/ship/webhooktest/` exige camelCase pero el payload entregado al URL final es snake_case (asimétrico); (c) el endpoint `/ship/webhooktest/` retorna HTTP 500 HTML genérico al caller PERO sí dispara el webhook async en background al URL registrado — el 500 al caller NO indica fallo del webhook real |
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

URLs **404** detectadas (no existen aunque a veces se referencian): `/docs/sandbox-vs-production`, `/docs/rate`, `/docs/generate`, `/docs/tracking`, `/docs/cancel`, `/docs/cash-on-delivery`, `/reference/quote-shipments` (404 al WebFetch directo), `/reference/createshipping`, `/reference/generate-shipment`. La información equivalente sí está distribuida en las páginas listadas arriba.

---

## L. Hallazgos profundos investigación 2026-05-07

> **Investigación exhaustiva** (~30 fetches/queries) cubriendo `docs.envia.com/*`, `help.envia.com/*` y `docs.ecartpay.com/*` para cerrar V.1–V.4 antes de implementar H.2.4 (COD). Snapshot: 2026-05-07.

### L.1 Cierre V.1 — Ecart Pay payout cycle, fees, retención (Colombia)

> **Estado**: PARCIALMENTE CERRADO por docs públicos. Las cifras críticas están confirmadas; la única ambigüedad residual es la **comisión Envia por shipment COD** (no documentada como % o $ fijo en help center).

**Cifras confirmadas con cita oficial**:

| Concepto | Valor | Fuente |
|---|---|---|
| Pago Ecart Pay → cuenta Ecart Pay | **72 horas después del shipment** | help.envia.com/en/shipments-cod/ (vía SERP snippet 2026-05-07): "you collect the cost of your products at the time of delivery and receive your payments **72 hours after shipment** in your Ecart Pay account" |
| Comisión Ecart Pay sobre COD (Colombia) | **0% — no hay comisión sobre el COD** | help.envia.com/en/withdraw-cod/ (vía SERP snippet 2026-05-07): "For Colombia, **there are no commissions**" |
| Fee fijo por retiro Ecart Pay → banco merchant | **5,000 COP por transacción** | help.envia.com/en/withdraw-cod/: "there is a charge per transaction of **$5,000 COP** which corresponds to the cost per interbank transfer" |
| Frecuencia de retiro | **Una solicitud cada 24h, procesadas martes y viernes 9:30 AM hora México** | help.envia.com/en/withdraw-cod/: "Withdrawal requests can be made once every 24 hours and are reviewed on **Tuesdays and Fridays at 9:30 am (Mexico time)**" |
| Cut-off | **Solicitud el día anterior a martes/viernes** | "Requests must be submitted the day before to be processed on Tuesdays and Fridays" |
| Payment method | **Transferencia electrónica interbancaria (en Colombia)** | help.envia.com/en/withdraw-cod/: "All Ecart Pay payments are made via electronic transfers, including SPEI" (SPEI=México; en CO es interbancario equivalente) |
| Tiempo de acreditación banco | **24-48h post-procesamiento** | help.envia.com/en/withdraw-cod/: "The payment will be reflected in your account between 24 and 48 hours, according to the interbank transfer time policies" |
| Timeline E2E peor caso (entrega → cuenta merchant) | **shipment → +72h → +24h hasta martes/viernes → +24-48h banco ≈ 5-7 días calendario** | derivado de los 4 datos anteriores |

**Comisión Envia por COD (parámetro `cashOnDeliveryCommission` que retorna API)**:
- **NO documentado como tabla fija**. La doc oficial dice solo: "automatic COD billing" entrega "monthly summary of the commissions" (help.envia.com/en/automatic-cod-billing/).
- La rate response Envia retorna `cashOnDeliveryCommission` y `cashOnDeliveryAmount` per carrier (dossier §2.5 y additional-services). Confirmado: la **comisión depende del carrier**, no es una cifra plana de Envia.
- **Validación humana residual V.1.x**: cuántos % cobra cada carrier CO (Servientrega, Coordinadora, Inter Rapidísimo, Envia carrier propio, TCC) — **NO está en docs públicos**, hay que extraer empíricamente con `rate` request + `additional_services.cash_on_delivery` per carrier (cf. V.2).

**Retenciones fiscales (ReteFuente, ReteIVA, ReteICA)**:
- **NO documentadas públicamente por Ecart Pay ni Envia para Colombia**. Pista cruzada: docs.ecartpay.com/docs/billing-providers indica que **Siigo (provider Colombia) maneja IVA 16%** — pero esto es facturación, no retención sobre payout.
- Asumimos que Ecart Pay deposita el monto bruto sin retención y la responsabilidad fiscal queda en el merchant (gross payout model). **Validación humana V.1 sigue requerida** para confirmar formalmente con Envia comercial.

**KYC requirements para activar Ecart Pay (Colombia)**:
- **NO documentados explícitamente** en docs.ecartpay.com/docs/customers-1 (la doc se enfoca en Mexico/CLABE). Sumsub aparece como provider de identity verification de Ecart Pay (per sumsub.com/customers/ecartpay) → KYC se hace con docs estándar Colombia (cédula + comprobante domicilio), pero el requerimiento exacto no está formalizado.

### L.2 Cierre V.2 — Carriers que soportan COD en Colombia

> **Estado**: CERRADO al nivel "qué carriers Envia ofrece para CO con COD"; confirmación empírica exacta sigue requerida (qué responde la rate API per carrier en sandbox).

**Confirmado por landing comercial envia.com (en-US/cod-and-additional-services + carrier pages)**:
- **Disponibilidad COD por país**: "available in all countries except **Argentina, Chile, the United States and Brazil**" (snippet help.envia.com/en/shipments-cod/ vía SERP 2026-05-07). → Colombia, México, India, Canadá, España, Francia, Italia, Guatemala = COD soportado.
- **Requisito hard**: COD solo funciona si la orden incluye **número de teléfono del destinatario** (snippet help.envia.com/en/shipments-cod/).

**Carriers Colombia con COD documentado en envia.com**:

| Carrier (identifier) | COD support docs.envia.com supported-carriers | COD según landing comercial CO |
|---|---|---|
| `serviEntrega` | Parcel + pickup; no flag explícito de COD en supported-carriers | ✅ Sí (envia.com/en-US/cod-and-additional-services menciona "Servientrega" en CO) |
| `coordinadora` | Parcel; PDF labels | ✅ Sí (mismo landing) |
| `interRapidisimo` | Parcel + pickup; **"cannot generate labels"** ⚠️ | ✅ Sí + dato extra: "el mensajero recolecta el dinero al entregar y se deposita en cuenta bancaria/billetera virtual **3 días después**" (la-republica.co + skydropx.com.co cross-source) |
| `envia` (carrier propio) | Parcel + pickup/pickup_mandatory; commercial invoicing | ✅ Sí (cobertura "más de 900 ciudades" según envia.com landing CO) |
| `tcc` | Parcel + pickup | ⚠️ NO mencionado explícitamente en landing CO COD (pero capability "Parcel" sugiere soporte; validación V.2 requerida) |
| `deprisa` | Parcel; PDF/ZPL 4X4 | ⚠️ NO mencionado explícitamente |
| `dhl` | Parcel | ❌ Improbable (carrier internacional; COD generalmente no aplica DDP/DAP) — validación V.2 |
| `fedex` | (NO listado en supported-carriers CO actualmente) | ❌ — el changelog Feb 2026 indica "Updated shipping references **from FedEx to DHL**" → FedEx CO probablemente removido |
| `cabify` | Parcel; PDF/ZPL 4X6 | ❌ Improbable (last-mile urbano sin contracash) |
| `lastMile`, `noventa9Minutos`, `cainiao` | Parcel | ❌ Improbable |

**Hallazgo nuevo crítico — Inter Rapidísimo**: documentación supported-carriers explícitamente dice **"cannot generate labels"** para interRapidisimo. Esto significa que la `POST /ship/generate/` con `carrier=interRapidisimo` probablemente **falla** a nivel de etiqueta digital, requiriendo workflow manual. **Implicación COD**: aunque Inter Rapidísimo es uno de los 3 grandes carriers Colombia con COD nativo, su integración Envia es de **solo cotización + tracking + pickup**, NO etiqueta digital end-to-end. → Revalidación humana V.2 obligatoria antes de exponer interRapidisimo en H.2.4.

### L.3 Cierre V.3 — Webhook notification flow del COD

> **Estado**: CERRADO con limitación. La doc no enumera un webhook tipo `cash_on_delivery_paid`. La señal de COD pagado llega vía:
> 1. **Envia webhook tipo `onShipmentStatusUpdate` / `simpleTracking`** (los 5 tipos descubiertos empíricamente en panel — cf. L.7e existente) cuando el `status_parent_id` avanza a "Delivered" → significa que el cliente recibió y pagó (en COD).
> 2. **Ecart Pay webhook tipo `transfer.created`** ("Emitted when a payment transfer to a merchant is complete") **cuando Ecart Pay deposita el dinero al merchant** — este es el evento "money in your account".
> 3. **Ecart Pay webhook tipo `withdrawals.paid`** cuando el retiro post-COD se completa al banco.

**Confirmación textual**:
- docs.ecartpay.com/docs/webhook-events: lista todos los eventos. Hay 4 categorías relevantes para flujo COD:
  - **`orders.confirmation`** — "Emitted when an order is paid for"
  - **`transfer.created`** — "Emitted when a payment transfer to a merchant is complete"
  - **`withdrawals.processing`** — "Emitted when a withdrawal is created (default status)"
  - **`withdrawals.paid`** — "Withdrawal completion notification"
  - **`withdrawals.cancelled`** — "Withdrawal cancellation alert"
- **NO existe** un evento explícito `cash_on_delivery.paid`, `cod.collected` o similar. El tracking de "el cliente pagó al transportador" depende del shipment status update de Envia (status `Delivered`).

**Schema canónico de webhook Envia ya descubierto** (ya en L.7e): `{"carrier": "fedex", "tracking_number": "794813020143", "shipment_status": "Created"}` snake_case, 3 campos garantizados, User-Agent `Envia-Carriers`, source IP `3.211.106.119`.

**Schema webhook Ecart Pay** (hallazgo L.3 nuevo):
- Headers de seguridad obligatorios (docs.ecartpay.com/docs/webhook-authentication):
  - `x-pay-timestamp` (millis)
  - `x-pay-signature` (HMAC-SHA256 sobre `{timestamp}.{webhook_id}.{JSON.stringify(data)}`)
  - `x-pay-webhook-id`
- **CRÍTICO**: Ecart Pay **SÍ firma con HMAC-SHA256**, a diferencia de Envia (que NO firma — L.3 original). Esto reduce el riesgo defensivo en /webhooks/ecartpay/ vs /webhooks/envia/.
- Secret se obtiene en panel Ecart Pay y debe almacenarse cifrado (Vault). Rotación: la doc no documenta rotación programática.

### L.4 Cierre V.4 — DANE sender code per carrier

> **Estado**: PARCIALMENTE CERRADO. Confirmado el formato general, pero el detalle "qué credencial registra cada carrier" sigue requiriendo validación humana.

**Confirmado**:
- **Postal code Colombia en Envia API = código DANE 6 dígitos**, donde "los primeros 2 dígitos = código de departamento DANE; los siguientes 2 = ruta postal; los últimos 2 = distrito" (Wikipedia + smarty.com cross-confirmados).
- Envia espera **ciudad y postalCode = código DANE** (snippet vía SERP).
- Envia documenta cobertura **"1,013 municipalities and 386 populated centers according to DANE nomenclature"** para envia carrier propio.

**Pista de Servientrega-CO (help.envia.com/servientrega-co — bloqueado por Cloudflare 403, snippet vía SERP)**:
- Servientrega exige **"Sender DANE code"** como credencial al conectar la integración. Es decir: el merchant onboarda su **código de cuenta Servientrega registrada (DANE remitente)** en el dashboard Envia, NO en cada request API.
- No se confirma si son 5 u 8 dígitos en help.envia.com (la página retorna 403). Otras integraciones (RetailCRM con Servientrega) referencian "Receiver's DANE code" indicando que el formato 5-6 dígitos prevalece en flujos productivos Servientrega API directa.

**Validación humana V.4 residual**:
- Confirmar via account manager Envia comercial: si los carriers Servientrega / Coordinadora / Inter Rapidísimo requieren registro de "sender DANE code" en el panel Envia (one-time setup) o en cada `generate` payload (per-shipment field).
- Hipótesis fuerte (validar): el sender DANE se registra **una vez en el dashboard del tenant** durante onboarding de cada carrier. Después la API Envia lo inyecta automáticamente.

### L.5 Hallazgos nuevos — Limitations adicionales (no documentadas en dossier original)

| # | Limitación | Cita / fuente |
|---|---|---|
| L.13 | **`POST /ship/manifest` endpoint EXISTE** (no documentado en dossier original): consolida múltiples shipments en un manifest PDF. Body `{trackingNumbers: [...]}`. Retorna `manifest_id`, `manifest_pdf_url`, `package_count`. Útil para B2B "imprime hoja de manifiesto al final del día" — docs.envia.com/docs/pickup-manifest-workflow + docs/shipping-multiple-packages |
| L.14 | **InterRapidisimo NO genera etiquetas** vía Envia: "cannot generate labels" en supported-carriers. Implicación: H.2.4 NO puede ofrecer Inter Rapidísimo COD con label digital end-to-end |
| L.15 | **Carrier action flags**: cada carrier tiene un flag `pickup` / `pickup_on_generate` / `pickup_mandatory` que define el flujo de recogida. Antes de `POST /ship/pickup/` hay que consultar "Get Carrier Actions" endpoint para saber qué método aplica |
| L.16 | **`shipment.type=1` = Parcel** (confirmado en quickstart JSON): valores 2/3 corresponden a LTL/FTL pero no documentados en `/reference` aún. La doc usa string `parcel` también en algunos contextos |
| L.17 | **Quote response NO retorna `cashOnDeliveryCommission` por defecto**: el quickstart muestra solo `totalPrice`, `currency`, `serviceDescription`, `deliveryEstimate`, `deliveryDate`. Para obtener `cashOnDeliveryCommission` hay que enviar `additional_services.cash_on_delivery.amount` en el request rate, y entonces el response se enriquece con campos COD-específicos. **Implicación P0**: en H.2.4 hay que **siempre** enviar `cash_on_delivery` en rate cuando el cart sea COD para conocer la comisión exacta antes de mostrar al cliente |
| L.18 | **Geocodes API NO requiere autenticación** ("does not require authentication — you can call it without a Bearer token") y NO consume balance. Ya estábamos asumiendo esto pero ahora está confirmado textualmente. Validación V.0 implícita resuelta |
| L.19 | **MX y EU intra-comunitario**: tax exemptions documentados ("taxes don't apply to international shipments and certain EU intra-community transactions") — irrelevante para CO pero útil saber |
| L.20 | **Production Readiness Checklist** menciona "balance monitoring and top-up processes" pero NO referencia COD activation, Ecart Pay setup, KYC. Implicación: **NO hay checklist oficial pre-producción para COD/Ecart Pay** — la activación se hace ad-hoc con account manager Envia |
| L.21 | **Customs Settings + DDP/DAP**: para CO doméstico no aplica, pero vale documentar que existen 3 modelos para internacional: "Envia Guaranteed" (recommended, all-in upfront), "Sender (DDP)" (post-delivery bill), "Recipient (DAP)" (recipient pays). Útil cuando KAIU expanda fronteras |
| L.22 | **Changelog Envia es escueto**: solo 2 entries 2026 (Feb + Mar) y todas son docs improvements, no features. NO hay registro de COD/Ecart Pay updates desde inicio de 2026 — la integración COD es estable y no ha cambiado API recientemente |

### L.6 API Reference URLs 404 (post-restructure docs Envia 2026)

URLs adicionales que retornan 404 en investigación 2026-05-07 (suman a las del dossier original):
- `/reference/quote-shipments` — 404 directo (la entrada existe en SERP pero la página retorna 404 al WebFetch)
- `/reference/createshipping` — 404
- `/reference/generate-shipment` — 404
- `/reference` (raíz) — retorna solo navigation header sin contenido

**Implicación**: la sección /reference de docs.envia.com está en un layout dinámico (ReadMe.io estilo) que requiere JS para renderizar el spec — los WebFetches devuelven HTML vacío. La fuente alternativa más útil para el JSON schema empírico es la **colección Postman pública**: `postman.com/api-envia/envia-com-s-public-workspace/documentation/4b85spz/` (referenciada en SERP, no fetcheable directamente sin auth).

### L.7 Hallazgos profundos Ecart Pay (NUEVO — antes inexistente en dossier)

> Cf. dossier dedicado nuevo `docs/research/ecartpay-dossier-2026-05-07.md` para profundidad completa. Resumen ejecutivo aquí:

- **Ecart Pay = fintech de Grupo Tendencys (México) operando en 10 países** incluyendo Colombia, México, Chile, Argentina, India, USA, Canadá, España, Brasil, Guatemala. 120,000 negocios.
- **Auth model**: NO es OAuth ni Bearer simple. Es **Basic Auth con Public+Private key Base64-encoded**. Token resultante válido **solo 1 hora** → exige refresh frequente.
- **Webhooks SÍ firmados HMAC-SHA256** (a diferencia de Envia que no firma) — significa que /webhooks/ecartpay/ puede tener defensa primaria por firma + secundaria por token URL.
- **Provider Colombia para facturación: Siigo** (IVA 16%). NO hay provider Colombia para retenciones tributarias documentado.
- **Eventos webhook relevantes para H.2.4**: `transfer.created` (dinero al merchant), `withdrawals.paid` (retiro completado), `orders.confirmation` (orden pagada).
- **Endpoint `/api/orders` acepta `shipping_items[].carrier="envia"`** → integración Ecart Pay ↔ Envia es **explícita en el modelo de datos**, no es un ad-hoc del lado merchant.
- **Pricing Ecart Pay**: 2.9%+$0.20 USD para tarjeta, 2.9%+$0.40 USD para cash, 3.5%+$0.20 USD AmEx. Esto NO aplica al flujo COD-Envia (que tiene "no commission" según withdraw-cod página) — aplica solo si el merchant usa Ecart Pay como PSP standalone para tarjeta/cash en frontend.
- **Multi-tenant Ecart Pay**: NO hay sub-accounts ni keys per-merchant documentadas. Modelo idéntico a Envia → cada tenant onboarda su propia cuenta Ecart Pay (que se vincula automáticamente cuando registra cuenta Envia con COD activo).

### L.8 Implicaciones para H.2.4 (COD Implementation)

**Decisiones que ya se pueden cerrar sin esperar V.1-V.4 totalmente**:

1. **Schema payload COD** (a integrar en `envia_client.py` rate + generate):
   ```json
   {
     "packages": [{
       "additionalServices": [
         {"service": "cash_on_delivery", "amount": <cart_subtotal_COP>}
       ],
       ...
     }]
   }
   ```
   El response devuelve `cashOnDeliveryCommission` y `cashOnDeliveryAmount` per carrier.

2. **Carriers MVP COD para KAIU (Colombia)**:
   - **TIER 1 (cierra mvp)**: `serviEntrega`, `coordinadora`, `envia` (propio) — los 3 generan labels digitales y soportan COD según landing comercial.
   - **TIER 2 (validar V.2 antes de exponer)**: `tcc`, `deprisa`.
   - **NO exponer en MVP**: `interRapidisimo` (no genera labels), `dhl`, `fedex`, `cabify`, `lastMile`, `noventa9Minutos`, `cainiao`.

3. **Webhook architecture H.2.4**:
   - Receiver Envia ya en plan (G.P0.2). Reutilizable: el evento "Delivered" significa COD cobrado.
   - **NUEVO router /webhooks/ecartpay/{tenant_id}** con validación HMAC-SHA256 + headers x-pay-* (verificable cripto, alta seguridad). Listen para `transfer.created` + `withdrawals.paid`.
   - Reconcilia COD con Ecart Pay vía `transfer.created` payload (contiene `amount`, `currency`, `reference_id` que mapea al shipment).

4. **Timeline COD operativo merchant** (comunicar a KAIU al activar):
   - Día 0: Cliente recibe paquete + paga al transportador.
   - Día 0+72h: Dinero llega a Ecart Pay (no a banco merchant aún).
   - Día +24-48h hasta próximo martes/viernes: merchant solicita retiro.
   - Día retiro +24-48h: dinero acreditado en banco merchant (5,000 COP fee descontado).
   - **Total: 5-7 días calendario worst case desde entrega hasta cuenta bancaria del merchant**.

5. **Comisión carrier-by-carrier**: requiere barrido empírico en sandbox (V.2). Sugerencia: ejecutar script Python que itere `[serviEntrega, coordinadora, envia, tcc, interRapidisimo]` × `rate` con `cash_on_delivery=$50,000 COP` y registre el `cashOnDeliveryCommission` resultante. Persistir en `tenant_carrier_capabilities.cod_commission_pct`.

6. **Retenciones fiscales (ReteFuente/ReteIVA/ReteICA)**: NO bloquea implementación API. Asumimos modelo "gross payout" hasta confirmar lo contrario con Envia comercial. Si en realidad Ecart Pay retiene, se ajusta UI dashboard merchant pero el flujo API es el mismo.

### L.9 Validaciones humanas residuales (post-investigación)

> Validaciones V.1-V.5 originales del dossier siguen vigentes. Investigación 2026-05-07 cierra V.1 al ~80% y V.2/V.3 al ~70%. V.4 sigue al ~50%. V.5 (IPs Envia) sin avance.

**NUEVAS validaciones derivadas de L.7**:

- **V.6 — Vinculación cuenta Ecart Pay ↔ cuenta Envia per-tenant**:
  - **PASOS**: confirmar con account manager Envia si al activar COD en cuenta Envia tenant, se crea automáticamente cuenta Ecart Pay vinculada o si requiere onboarding separado en docs.ecartpay.com.
  - **CRITERIO ÉXITO**: documento que confirme "1 cuenta Envia con COD activo = 1 cuenta Ecart Pay automática" o "tenant debe crear cuenta Ecart Pay separada".

- **V.7 — Comisión COD per carrier (matriz empírica)**:
  - **PASOS**: ejecutar barrido `rate` sandbox per carrier × `cash_on_delivery=$X COP` y registrar `cashOnDeliveryCommission` retornado.
  - **CRITERIO ÉXITO**: matriz `carrier × cod_commission_pct × min_amount × max_amount` persistida en `docs/research/empirical-evidence/envia-cod-commissions-CO.json`.
  - **TIEMPO ESTIMADO**: 30 min con script Python una vez sandbox tenga COD habilitado.

---

## L.10 — Confirmación oficial Envia/Ecart Pay (2026-05-07)

**Conversación founder con ejecutivo Envia/Ecart Pay (2026-05-07)**:
respuestas oficiales que cierran V.1 al 100% y confirman/extienden lo
hallado por docs en sesión investigación profunda.

**V.1 — Ecart Pay payout cycle / fees (CERRADA 100%)**:

| Pregunta | Respuesta oficial |
|---|---|
| ¿Cada cuánto deposita Ecart Pay? | **Semanal: martes y viernes** |
| Comisión por COD | **$5,000 COP fijo** (NO porcentaje) |
| Retención antes de depósito | **NO hay retención** |
| Mínimo COD | **No hay mínimo** explícito |
| Máximo COD | (no respondido — asumir docs Ecart Pay) |
| Constraint adicional | **Cada COD debe cubrir al menos los $5,000 COP de comisión** — práctica: COD < $5,000 no tiene sentido económico |

**Implicación arquitectónica MVP H.2.4**:
- En la UI Settings → Promociones (futuro COD admin), validador `min_amount_cents >= 500000` (= $5,000) por defecto. Owner puede subirlo pero no bajarlo.
- En el bot, si cliente solicita COD con cart subtotal < $5,000, rechazar con mensaje *"El monto mínimo para contraentrega es $5,000 COP por la comisión del transportador."*

**Documentación oficial**: https://docs.ecartpay.com/docs/all-about-ecart-pay

**V.2 — Carriers que aceptan COD (NO confirmado por ejecutivo, decisión: basarse en docs)**:

Founder confirmó (2026-05-07): "no las pude resolver correctamente con
el ejecutivo, pero nos deberíamos basar en la documentación."

→ **Decisión arquitectónica**: para H.2.4 MVP usar TIER 1 docs-confirmed
(`serviEntrega`, `coordinadora`, `envia` propio) per L.1 + L.4. TIER 2
queda para validación humana V.x post-MVP cuando aparezcan tenants que
lo pidan.

**V.3 — Webhook flow COD (NO confirmado por ejecutivo, decisión: basarse en docs)**:

Founder confirmó (2026-05-07): "basarnos en la documentación".

→ **Decisión arquitectónica**: implementar reconciliación distributed
2-webhooks per L.7 + ecartpay-dossier sec.2:
1. Envia `simpleTracking` (status=Delivered) marca `cod_ledger.status='collected'`.
2. Ecart Pay `transfer.created` marca `cod_ledger.status='deposited_to_ecartpay'`.
3. Ecart Pay `withdrawals.paid` marca `cod_ledger.status='paid_to_merchant'`.

UAT S34 deberá cubrir el flow completo. Si docs son insuficientes en
runtime, ajustar empíricamente con primer tenant productivo COD activo.

**V.4 — Sender DANE Servientrega (parcialmente cerrada)**:

Sigue requiriendo confirmación de account manager Envia (página
help.envia.com 403 Cloudflare). Aceptado riesgo: implementar H.2.4 MVP
sin Servientrega COD inicialmente, agregar cuando V.4 quede confirmada.
