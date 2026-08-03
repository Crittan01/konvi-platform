> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Dossier Wompi Colombia — 2026-05-05

**Fecha**: 2026-05-05 · **Sesión**: investigación previa Sem 0 (J.0.0) · **Sin pruebas en vivo**.
**Fuente**: `https://docs.wompi.co/en/docs/colombia/*` (público).

## 1. Autenticación

- Cuatro llaves diferenciadas por prefijo:
  - `pub_*` — pública (Bearer en GET transactions, widget, tokenize en frontend).
  - `prv_*` — privada (POST transactions, payment_links, payment_sources, void).
  - `*_events_*` — secret de webhooks (verificación firma SHA256).
  - `*_integrity_*` — secret para hash integrity del Widget/Checkout Web.
- Por ambiente: `pub_test_`, `prv_test_`, `test_events_`, `test_integrity_` (Sandbox) vs `pub_prod_`, `prv_prod_`, `prod_events_`, `prod_integrity_` (Producción).
- Base URLs: Sandbox `https://sandbox.wompi.co/v1`; Producción `https://production.wompi.co/v1`.
- Header: `Authorization: Bearer <KEY>`.
- **NO documentado oficialmente**: rotación programática de llaves, scoping per-merchant dentro de una cuenta, expiración de llaves, mecanismo de revocación. Se obtienen del dashboard "Developers > Secrets for technical integration".
- URL: https://docs.wompi.co/en/docs/colombia/ambientes-y-llaves/

## 2. Payment Links

- `POST /v1/payment_links` con `Authorization: Bearer prv_*`.
- Body documentado:
  - Requeridos: `name` (≤100), `description` (≤255), `single_use` (bool — true = una APPROVED), `collect_shipping` (bool), `currency` (`"COP"` único soportado).
  - Opcionales: `amount_in_cents` (null = monto abierto), `expires_at` (ISO 8601 UTC), `redirect_url`, `image_url`, `sku` (≤36), `customer_data` (array, máx 2 campos custom con label + required), `taxes[]` con type `VAT|CONSUMPTION`.
- `GET /v1/payment_links/:id` (sin auth — público).
- Lifecycle: `amount_in_cents` inmutable post-creación. Ítem expira por `expires_at` o por `single_use=true` tras una APPROVED.
- URL pública del checkout: `https://checkout.wompi.co/l/{id}`.
- **Multi-currency**: solo COP. Wompi declara "support more currencies in the future" pero NO hay USD/EUR hoy.
- URL: https://docs.wompi.co/en/docs/colombia/links-de-pago/

## 3. Transactions endpoint

- `GET /v1/transactions/{id}` con `Authorization: Bearer pub_*` (la pública basta).
- Schema (`data`): `id`, `reference`, `status`, `amount_in_cents`, `currency`, `payment_method_type`, `status_message`, `created_at`, `customer_email`, `payment_method` (objeto con `type/brand/last_four`), `merchant`.
- Estados: `PENDING` → terminal `APPROVED | DECLINED | VOIDED | ERROR`. `VOIDED` es exclusivo para tarjetas.
- También `GET /v1/transactions?reference=...` para buscar por reference si no se conoce el `id`.
- **NO documentado oficialmente**: rate limits explícitos, polling intervals (sí 2-3 s para flujos 3DS y 2 s para `payment_sources`), `finalized_at`, lista exhaustiva de `status_message`.
- URLs: https://docs.wompi.co/en/docs/colombia/transacciones/ , https://docs.wompi.co/en/docs/colombia/seguimiento-de-transacciones/

## 4. Webhook events

- Tipos oficiales (solo 3): `transaction.updated`, `nequi_token.updated`, `bancolombia_transfer_token.updated`. NO existe `subscription.*` documentado.
- Payload: `{ "event": "...", "data": {...}, "sent_at": "...", "timestamp": <int>, "signature": { "properties": [...], "checksum": "..." } }`.
- Firma: SHA256 plano (NO HMAC). Concatenación = valores de `signature.properties` (paths relativos a `data`) + `timestamp` (entero) + `events_key`. Comparar con `signature.checksum` o header `X-Event-Checksum`.
- Retry policy: si no recibe HTTP 200, reintenta hasta 3 veces a los 30 min, 3 h y 24 h.
- **NO documentado oficialmente**: IP allowlist, `event.id` estable. URLs de webhook se configuran por ambiente en dashboard (Sandbox/Prod separadas).
- URL: https://docs.wompi.co/en/docs/colombia/eventos/

## 5. Refund / Void / Dispute

- **Void**: `POST /v1/transactions/{id}/void` con `Bearer prv_*`. Solo aplica a tarjetas (CARD), antes de captura/finalización del settlement.
- **Refund**: NO hay endpoint público documentado en docs.wompi.co. La única operación reversa documentada es `void`. Refunds posteriores a settlement se manejan por dashboard / soporte (sin API REST oficial).
- **Dispute / chargeback**: NO documentado en docs.wompi.co — es flujo operativo gestionado por Bancolombia/franquicia (Visa/Mastercard); timeframes los fijan las redes (típicamente 120 días Visa/MC), no Wompi. NO hay API de disputes.
- Reason codes: `DECLINED` lleva `status_message` (free text), pero no hay catálogo enumerado de reason codes en docs públicas.
- URL: https://docs.wompi.co/en/docs/colombia/transacciones/

## 6. Métodos de pago Colombia

- Tipos `payment_method.type` documentados: `CARD`, `NEQUI`, `PSE`, `BANCOLOMBIA_TRANSFER`, `BANCOLOMBIA_QR`, `BANCOLOMBIA_COLLECT` (efectivo en corresponsales), `BANCOLOMBIA_BNPL` (4 cuotas, mín 100k), `PCOL` (Puntos Colombia), `DAVIPLATA`, `SU_PLUS` (cuotas 35k–5M).
- Campos por método varían: PSE requiere `user_type/user_legal_id_type/financial_institution_code`; NEQUI `phone_number`; CARD `token+installments`; BANCOLOMBIA_TRANSFER `user_type+payment_description`.
- **Filtrado**: NO hay parámetro de Payment Links que limite métodos al cliente — el checkout muestra los habilitados a nivel merchant/cuenta. Para subset por checkout es vía API directa (`POST /v1/transactions`) eligiendo `type`.
- **Fees**: NO documentadas en docs.wompi.co. Públicas en sitios de partners: ~2.79 % + COP 900 tarjeta; ~2.65 % + COP 700 PSE. Validar contrato por tenant.
- URL: https://docs.wompi.co/en/docs/colombia/metodos-de-pago/

## 7. Tokenized cards / Payment Sources

- Flow tres pasos:
  1. `POST /v1/tokens/cards` (frontend con `pub_*`) → `tok_*` con cardholder data. Análogos: `/v1/tokens/nequi`, `/v1/tokens/daviplata`, `/v1/tokens/bancolombia_transfer`.
  2. `POST /v1/payment_sources` (backend con `prv_*`) — body: `type`, `token`, `customer_email`, `acceptance_token`, `accept_personal_auth` → retorna `payment_source_id`.
  3. `POST /v1/transactions` con `payment_source_id` (+ `installments` para tarjeta).
- PCI scope: Wompi PCI DSS certificado, datos sensibles NUNCA pasan por servidores merchant (tokens en frontend con SDK Wompi.js o iframe).
- Customer consent: requiere ambos `acceptance_token` (Habeas Data Ley 1581) en cada creación de payment source o transacción donde se recolecte data personal.
- **Token expiration**: NO documentada explícitamente — tokens de tarjeta heredan validez de la tarjeta; expiración de token Nequi/Daviplata depende del usuario.
- URL: https://docs.wompi.co/en/docs/colombia/fuentes-de-pago/

## 8. Subscripciones / cobros recurrentes

- NO hay endpoint `/subscriptions` REST. La estrategia oficial es:
  - `payment_sources` (Card o Nequi) → re-cargar con `POST /v1/transactions` cuando merchant decide.
  - `payment_sources` con 3DS → cobros automáticos protegidos por **3RI (3D Secure 2.2 Requestor Initiated)**. Solo Mastercard. Activación previa por equipo de fraude Wompi.
  - DaviPlata: pagos automáticos disponibles vía payment source.
- En el módulo Payouts (Pagos a Terceros) sí existe `dispersionDatetime` + `recurring: { interval: "biweek"|"month" }`, pero eso es para dispersión a terceros, NO cobro a clientes.
- **NO hay**: schedule fijo de cobros, dunning automático, gestión de fallos en cadena, manejo de `subscription.*` events.
- URLs: https://docs.wompi.co/en/docs/colombia/fuentes-de-pago/ , https://docs.wompi.co/en/docs/colombia/fuentes-de-pago-3ds/

## 9. Reconciliación + Settlement

- Documentación pública de Wompi Colombia es delgada en este punto. Lo que existe:
  - Dashboard "Balances" (sección Payouts) muestra saldo por banco/cuenta linked.
  - Reportes consolidados de transacciones (CSV/dashboard); no hay Balance API REST pública para Wompi Online Payments (la Balance API documentada es del producto Payouts).
  - Settlement T+N: NO documentado oficialmente; en práctica los partners reportan T+1 a T+3 según producto y banco.
- **NO documentado**: API de statements, invoices, escrow multi-merchant para SaaS B2B, splits programáticos a sub-cuentas.
- Para SaaS B2B con múltiples comercios: Wompi requiere **una cuenta merchant por comercio** (sub-cuentas no documentadas como API). Onboarding manual cliente-por-cliente. El flujo "marketplace" no está soportado vía API pública.
- URL: https://docs.wompi.co/en/docs/colombia/que-es-pagos-a-terceros/ (Payouts, no Online Payments).

## 10. Compliance + Security

- **PCI DSS**: Wompi posee certificación PCI DSS nivel "el más alto"; merchant queda fuera del scope de almacenamiento de datos de tarjeta si usa tokens.
- **3DS v2.2**: Mastercard + Visa para cargos puntuales; 3RI (recurrentes) solo Mastercard. Browser info obligatorio (`browser_color_depth`, `_screen_height`, `_screen_width`, `_language`, `_user_agent`, `_tz`). Challenge se renderiza en iframe vía `srcDoc`. Polling cada 2-3 s.
- **Habeas Data (Ley 1581 Colombia)**: dos `acceptance_token` obligatorios — `presigned_acceptance` (privacidad) y `presigned_personal_data_auth` (procesamiento PII). Ambos JWT con permalink a PDF que debe mostrarse al cliente. Endpoint `GET /v1/merchants/{public_key}` para obtenerlos.
- **Anti-fraude**: gestionado por equipo de fraude Wompi (3DS, scoring); no hay reglas configurables vía API pública.
- **KYC merchant**: onboarding manual en `comercios.wompi.co`. NO documentado en docs públicas el set exacto de documentos / checklist KYC.
- **TOS**: NO referenciables vía URL pública en docs.wompi.co — viven en contrato con Bancolombia.
- **SLA disputas**: NO documentado por Wompi; aplican plazos de redes Visa/MC.
- URLs: https://docs.wompi.co/en/docs/colombia/transacciones-con-3d-secure-v2/ , https://docs.wompi.co/en/docs/colombia/tokens-de-aceptacion/

---

## Análisis de gaps código actual

Revisado contra `services/api/integrations/wompi_client.py` y `services/api/routers/wompi_webhook.py`:

| # | Gap | Estado en repo | Riesgo |
|---|---|---|---|
| H.3.1 | `GET /v1/transactions/{id}` no implementado | Solo se confía en webhook | Webhook lost → orden queda pending_payment indefinido (mitigado por TTL pero no resuelto) |
| H.3.2 | `POST /v1/transactions/{id}/void` no implementado | No existe función | Imposible cancelar pre-captura desde backoffice |
| H.3.3 | Refund API: NO existe en Wompi público | Bloqueante real | Manejo manual obligatorio por dashboard (intervención humana) |
| H.3.4 | Retry + circuit breaker en `httpx.Client` | `timeout=15s`, sin retries, sin breaker | Caída transitoria Wompi → create_payment_link falla → cliente no recibe link |
| H.3.5 | Métodos pago per-tenant | No expuesto (filtrado lo hace Wompi) | OK por arquitectura — no es gap real |
| H.3.6 | Saved cards / payment_sources | No implementado | Bloquea recurrencia y "comprar de nuevo" |
| H.3.7 | 3DS / 3RI | No implementado | Bloquea cobros automáticos B2C recurrentes |
| H.3.8 | Acceptance tokens (Habeas Data) | No se obtienen ni envían en payment_links | Payment Links NO requiere acceptance_token (Wompi los maneja en el checkout hosted), por eso no falla — pero si se migra a `POST /transactions` directo será gap legal |
| H.3.9 | Integrity signature widget | No aplica (no se usa Widget/Checkout Web embedido) | OK — usamos hosted Payment Link |

### Hallazgos adicionales del crawl (no estaban en H.3.x)

- **Dedup por `signature.checksum`** (línea 99-129 webhook): correcto. Wompi NO documenta `event.id` estable; el checksum es la mejor heurística disponible.
- **Algoritmo SHA256 properties data-relative** (línea 97-122): coincide con docs (sept-2024+); el fallback root-relative añadido es defensivo y no contradice spec. Mantener.
- **`single_use=True` siempre** (línea 230): correcto para flujo orden-única; NO permitir multi-use porque Wompi no expira la suma de transacciones del link.
- **`collect_shipping=False`**: correcto — el address sale del flujo conversacional, no del checkout.
- **Currency hardcoded "COP"**: correcto, Wompi NO soporta otra hoy.
- **Email-lowercase + phone canónico**: alineado con schema Wompi (`phone_number_prefix` + `phone_number`).

## Recomendaciones priorizadas

### P0 (bloquean operación / compliance)
- **P0-1 H.3.4 Retry + circuit breaker**: envolver `create_payment_link` con tenacity (3 reintentos exponenciales 1s/2s/4s, solo en 5xx/timeouts, NO en 4xx) y circuit breaker per-tenant (e.g. 5 fallos → open 60 s → half-open). Sin esto, una caída transitoria de Wompi corta la conversión.
- **P0-2 H.3.1 GET transaction de respaldo**: cuando `pending_payment` supera TTL (35 min) sin webhook, hacer poll `GET /v1/transactions?reference={order_id}` para reconciliar. Reduce ventana de "limbo" a 0.

### P1 (cierra gaps funcionales)
- **P1-1 H.3.2 Void endpoint**: implementar `void_transaction(prv_key, env, txn_id)` para acción de backoffice. Útil cuando merchant detecta pago tarjeta dudoso pre-settlement.
- **P1-2 Reason codes mapping**: parsear `status_message` en webhook DECLINED y mapearlo a categorías legibles para el cliente (insuficient funds / 3DS failed / restricted card). Wompi no enumera, pero hay patrones reconocibles en producción.
- **P1-3 Payments table audit-trail**: agregar columna `wompi_payment_method_type` y `wompi_status_message` desde webhook, permite reportes por método sin re-consultar Wompi.

### P2 (capacidades futuras)
- **P2-1 H.3.6 Payment sources** (saved cards): requiere migrar de Payment Links hosted a flujo widget/checkout-web con `Wompi.js` SDK (frontend tokeniza) + `acceptance_token` + `accept_personal_auth` → backend crea payment_source. Cambio de UX significativo.
- **P2-2 H.3.7 3RI recurrentes**: solo después de P2-1 + activación con equipo de fraude Wompi. Solo Mastercard. Útil para subscripciones SaaS o re-orden automática.

### P3 (defer / out-of-scope confirmado)
- **P3-1 H.3.3 Refund API**: NO existe en Wompi público. Documentar como "intervención humana requerida" en runbook (dashboard Wompi > Transacciones > Reembolso). NO buscar workaround técnico.
- **P3-2 Multi-currency**: NO soportado por Wompi. Si SaaS expande fuera de Colombia, evaluar Wompi Panamá u otro PSP.
- **P3-3 Marketplace splits**: Wompi Online Payments NO ofrece API de splits/sub-cuentas. Para SaaS B2B con escrow multi-merchant: una cuenta Wompi por tenant (modelo actual del repo es correcto: `tenant_integrations.credentials` per-tenant).

## Validar en documentación oficial (gates antes de implementar)

- Antes de P0-1: confirmar en https://docs.wompi.co/en/docs/colombia/errores/ qué HTTP codes retorna Wompi en sobrecarga (¿429? — no documentado, sólo 401/404/422). Asumir 5xx + timeouts como retryables.
- Antes de P0-2: validar que `GET /v1/transactions?reference=...` está soportado para pública (la doc lo menciona pero solo muestra ejemplo con `id`).
- Antes de P1-1: confirmar exact requirements de `void` (¿solo `APPROVED`? ¿hay ventana temporal?). Docs sólo dicen "certain statuses" sin enumerar.
- Antes de P2-1: leer https://docs.wompi.co/en/docs/colombia/widget-checkout-web/ completa + https://docs.wompi.co/en/docs/colombia/transacciones-con-3d-secure-v2/.

## Intervención humana requerida

- **RESPONSABLE**: tenant onboarding ops.
- **PASOS**: cada nuevo tenant debe (a) crear cuenta en `comercios.wompi.co`, (b) completar KYC con Bancolombia, (c) generar 4 llaves en dashboard, (d) configurar webhook URL de producción, (e) entregar `prv_*` + `*_events_*` para Vault.
- **INSUMOS**: NIT, RUT, certificado bancario, datos representante legal.
- **CRITERIO DE ÉXITO**: smoke test sandbox + un cobro real <50k aprobado con webhook recibido + validado.

## Veredicto final

**GO** — Wompi cubre las necesidades core de pagos B2C en Colombia (tarjeta, PSE, Nequi, Daviplata, Bancolombia). El stack actual de Payment Links hosted es la opción correcta de menor complejidad y menor scope PCI.

**Limitaciones reales** (no son del código, son de Wompi):
- Sin refund API → escalación manual operativa.
- Sin multi-currency → barrera para expansión LATAM.
- Sin marketplace API → modelo Modelo B (key per tenant) confirmado correcto.
- Webhook events limitados a 3 tipos.

**Próximos pasos**: ejecutar P0-1 + P0-2 en Sem 4 del roadmap (H.3.1 + H.3.2). P1 después.

## Fuentes

- [Environments and Keys](https://docs.wompi.co/en/docs/colombia/ambientes-y-llaves/)
- [Payment Links](https://docs.wompi.co/en/docs/colombia/links-de-pago/)
- [Transactions](https://docs.wompi.co/en/docs/colombia/transacciones/)
- [Transaction Tracking](https://docs.wompi.co/en/docs/colombia/seguimiento-de-transacciones/)
- [Events / Webhooks](https://docs.wompi.co/en/docs/colombia/eventos/)
- [Payment Methods](https://docs.wompi.co/en/docs/colombia/metodos-de-pago/)
- [Payment Sources & Tokenization](https://docs.wompi.co/en/docs/colombia/fuentes-de-pago/)
- [3DS v2 Sandbox](https://docs.wompi.co/en/docs/colombia/transacciones-con-3d-secure-v2/)
- [3RI Automatic Recurrent](https://docs.wompi.co/en/docs/colombia/fuentes-de-pago-3ds/)
- [Acceptance Tokens (Habeas Data)](https://docs.wompi.co/en/docs/colombia/tokens-de-aceptacion/)
- [Errors](https://docs.wompi.co/en/docs/colombia/errores/)
- [Quick Start](https://docs.wompi.co/en/docs/colombia/inicio-rapido/)