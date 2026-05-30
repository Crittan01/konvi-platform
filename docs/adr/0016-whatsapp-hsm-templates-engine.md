# ADR-0016 — WhatsApp HSM Templates Engine (Sem 7 F2)

**Status**: Accepted · 2026-05-18
**Sesión**: rev. 106 Sem 7 F2 items 1-6.b
**Plan refs**: H.4.2-H.4.4 (HSM templates, tier rate limit, delivery receipts) + I.4.1-I.4.7 (HSM opt-in per-tenant + billing tracking) + MA-7 (compliance decoradores ventana 24h).
**Predecessor refs**: ADR-0002 (Meta Business Policy compliance), ADR-0011 §6 (payment lifecycle), F.2 (`IntegrationClient` base con retry+CB+idempotency).

---

## Context

Meta WhatsApp Cloud API impone una **Customer Service Window (CSW) de
24h** rolling: dentro de la ventana, el bot puede responder con texto
libre (`text`, `image`, `interactive`) a **costo $0**. Fuera de la
ventana, **solo se permiten Highly Structured Messages (HSM
Templates)** previamente aprobados por Meta, con **Per-Message Pricing
(PMP)** según categoría (UTILITY ~$0.004 USD, MARKETING ~$0.025 USD,
AUTHENTICATION ~$0.0135 USD — tarifas Colombia Mayo 2026).

Hoy (pre-Sem 7) la plataforma sólo soporta mensajería **dentro** de
CSW: el bot responde a inbound del cliente. Esto deja **2 gaps
operativos críticos** que impactan revenue del tenant:

1. **Payment reminder fuera de CSW**: F1 cron rev. 103 dispara a los
   25 min post-orden con `pending_payment`. Si cliente abrió chat >24h
   antes (frecuente — picos AM/PM con conversaciones cortas), el
   recordatorio es bloqueado por ventana cerrada → cliente nunca
   completa pago.
2. **Cart abandoned >24h**: cliente añade items, no avanza, cierra
   conversación. Pasa CSW → no podemos retomarlo. Pérdida directa
   estimada ~30-40% de carritos colombianos.

Además, Meta exige template lifecycle estricto:
- Submit a `POST /{WABA_ID}/message_templates` con `components` específicos.
- Review 15min-48h. Estado `PENDING → APPROVED | REJECTED | DISABLED`.
- Webhook `message_template_status_update` notifica cambios.
- Quality scoring per template + per phone number (`GREEN | YELLOW | RED`).
- Rate limits tier-based per WABA (1k/10k/100k/unlimited mensajes/24h).
- Sin opt-in del cliente → MARKETING templates pueden disparar **bloqueo
  permanente del número** (Meta Business Policy violation, ADR-0002).

El reto arquitectónico: integrar HSM al cart-as-SoT y al cron worker
sin violar:
- **ADR-0002**: ventana 24h enforce + opt-out automático.
- **ADR-0011 §A.0.1**: LLM no decide verdad transaccional → template
  selection es determinística por código, no por LLM.
- **Habeas Data Ley 1581**: MARKETING requiere `contacts.consent_given=true`.
- **Plan A.0.1**: no parches — engine modular reusable para futuros
  templates (order_shipped, review_request, etc.).

---

## Decision

### D1. Modelo de datos en 1 tabla + columnas idempotencia

```
whatsapp_templates (catálogo per tenant, lifecycle Meta-side)
  ↓ name+language lookup runtime
whatsapp_sender.send_whatsapp_template() → Meta POST /messages
  ↓ persist
messages (mensaje outbound con meta_message_id)
```

**`whatsapp_templates`**: catálogo per-tenant con todos los templates
registrados. Status FSM: `LOCAL_DRAFT → PENDING → APPROVED |
REJECTED | DISABLED | PAUSED`. Columnas clave:

- `meta_template_id` TEXT — devuelto por Meta tras submit. NULL hasta
  ese momento (LOCAL_DRAFT).
- `components` JSONB — payload completo de Meta (HEADER, BODY, FOOTER,
  BUTTONS). Fuente de verdad: nuestro repo (no Meta).
- `parameter_format` ENUM(POSITIONAL, NAMED) — default POSITIONAL.
- `quality_score` JSONB — última lectura webhook (`{score, reasons[]}`).
- `submitted_at`, `last_status_change_at` — auditoría.
- `language` TEXT — `es_CO` default; Meta exige par exacto.
- UNIQUE `(tenant_id, name, language)` — un nombre canónico por tenant+lang.

**Columnas idempotencia per-cron** (NO en `whatsapp_templates`, en
las tablas downstream):
- `orders.payment_reminder_sent_at TIMESTAMPTZ` — F1 cron rev. 103
  (ya existía).
- `conversation_carts.abandoned_reminder_sent_at TIMESTAMPTZ` — F2
  cron item 6.b (nuevo).

Justificación: estos timestamps viven en las tablas de dominio porque
representan **eventos del flujo de negocio**, no del template. Si el
template `payment_reminder_v1` rotara a `v2`, queremos que la idempotencia
siga atada al **ordenamiento** (un cliente recibe payment_reminder UNA
vez por orden, sea template v1 o v2), no al template.

### D2. Submit lifecycle — admin scripts, no auto

**Decisión**: el submit a Meta se ejecuta **manualmente** via
`scripts/admin/submit_template_to_meta.py`, no automáticamente al
crear un `LOCAL_DRAFT`. Razones:

1. **Review tiempo Meta 15min-48h** — submit prematuro de templates
   con typos requiere `delete + re-submit` que cuenta como rate limit
   en el WABA (Meta limita N templates submits/mes).
2. **Onboarding tenants nuevos** se beneficia de pre-validación humana
   (tenant tech lead revisa componentes antes de submit).
3. **Multi-language** — si tenant agrega `es_MX` mañana, queremos
   batch submit deliberado.

Webhook `message_template_status_update` actualiza status async cuando
Meta termina review. Handler `template_events.persist_template_status_update`
mapea `event.status` → `whatsapp_templates.status` + persiste
`status_reason` (en caso REJECTED).

### D3. Send-time validation determinística

`whatsapp_sender.send_whatsapp_template()` valida **antes** de POST a
Meta:

1. Template existe en `whatsapp_templates` con `(tenant_id, name,
   language)` → `TEMPLATE_ERR_TEMPLATE_NOT_FOUND` si no.
2. `status == 'APPROVED'` → `TEMPLATE_ERR_TEMPLATE_NOT_APPROVED` si no.
3. `body_params` length == placeholders count en `components.BODY.text`
   → `TEMPLATE_ERR_PARAM_COUNT_MISMATCH` si no.
4. Tenant tiene credenciales WABA + token resolubles → `TEMPLATE_ERR_NO_CREDENTIALS`.

Si **todas** pasan, build `components` Meta-format y POST. Errores
Meta runtime (rate limit, auth expirado) se mapean a códigos
estructurados (`TEMPLATE_ERR_META_AUTH | META_RATE_LIMIT | META_OTHER |
TIMEOUT | UNKNOWN`).

**Por qué NO permitir send a `PENDING`**: Meta rechaza el POST con error
opaco; mejor fallar local explícito.

### D4. Categorías y compliance gates

3 categorías HSM, 3 enforcement paths distintos:

| Categoría | Use case | Enforcement |
|---|---|---|
| **UTILITY** | payment_reminder, order_confirmation, order_shipped | Sin consent extra; transaccional permitido siempre fuera CSW. |
| **MARKETING** | cart_abandoned_24h, promo, newsletter | `contacts.consent_given=true` **OBLIGATORIO**. Skip silencioso si no. |
| **AUTHENTICATION** | OTP login, verify | No usado en MVP (futuro). |

Implementación gate (item 6.b worker.py):
```python
# F1 payment_reminder (UTILITY): no consent check
await self._try_send_payment_reminder_hsm(...)

# Cart abandoned (MARKETING): consent check obligatorio
if not contact.consent_given:
    self._metrics["cart_abandoned_reminders_skipped_no_consent"] += 1
    continue
```

Justificación: Habeas Data Ley 1581 ART. 9 — tratamiento de datos
con fines comerciales requiere consent expreso. Transaccional
(payment_reminder) es **continuación del flujo iniciado por el cliente**
(orden creada) — no requiere consent adicional (ADR-0003 §2).

### D5. F1 + HSM complementariedad (NO redundante)

F1 rev. 103 sigue siendo el camino **primario** dentro de CSW (free-form,
$0). HSM es **fallback** sólo si CSW está cerrada:

```
F1 cron tick:
  ├─ CSW abierta (<24h) → free-form "Hola, te recordamos que tu pedido…" → $0
  └─ CSW cerrada (>24h) → HSM payment_reminder_v1 → ~$0.004 USD
```

ROI calculado: payment_reminder convierte ~25% de pendientes; ticket
medio KAIU ~$80K COP ≈ $20 USD. Costo HSM $0.004. **ROI ~5000:1**
incluso si UTILITY pasa a $0.01 USD futuro.

Por qué F1 no se sustituye 100% por HSM: dentro de CSW, free-form es
**$0** y permite mensaje contextual personalizado. HSM template es
rígido (`{{1}}` placeholders, sin tono natural). Mejor experiencia
cliente + costo cero.

### D6. Idempotencia cron via columnas timestamp

`orders.payment_reminder_sent_at` (existente F1) +
`conversation_carts.abandoned_reminder_sent_at` (nuevo F2 item 6.b).

```sql
WHERE abandoned_reminder_sent_at IS NULL
  AND status IN ('open', 'abandoned')
  AND updated_at < NOW() - INTERVAL '24 hours'
  AND updated_at > NOW() - INTERVAL '72 hours'
```

Por qué TIMESTAMPTZ y no BOOLEAN: queremos saber **cuándo** se envió
para auditoría + posible re-envío manual via admin script. NULL = no
enviado; timestamp = enviado en ese instante.

Threshold 24h-72h en cart_abandoned: <24h aún puede recuperarse
free-form (CSW abierta); >72h cliente probablemente perdido (carrito
expira via TTL separado).

Índice parcial para performance del cron:
```sql
CREATE INDEX conversation_carts_abandoned_pending_idx
  ON conversation_carts (tenant_id, updated_at)
  WHERE abandoned_reminder_sent_at IS NULL
    AND status IN ('open', 'abandoned');
```

### D7. Cliente HTTP Meta — extiende F.2 IntegrationClient

`MetaBusinessManagementClient(IntegrationClient)` reusa retry +
circuit breaker + idempotency baseline (MA-1) del framework. Decisión:
endpoints template-CRUD (`POST /{WABA_ID}/message_templates`) NO son
idempotentes server-side en Meta, pero el cliente F.2 cachea response
local 24h por `(tenant_id, request_hash)` evitando submits duplicados
en retries.

Métodos:
- `create_template(name, language, category, components, parameter_format)`
- `list_templates(waba_id)`
- `get_template(template_id)`
- `delete_template(template_id)`

Errores mapeados:
- `MetaAuthError` (401, 190) → token expirado → operador rota.
- `MetaRateLimitError` (429) → retry con backoff exponencial.
- `MetaTemplateError` (400 con `error.code ∈ {130472, 132000, 132001}`)
  → template invalid → admin corrige + re-submit.

### D8. Webhook handlers separados, no inline

3 event types Meta entrega al webhook:
- `message_template_status_update` → status FSM transition.
- `message_template_quality_update` → `quality_score` JSONB update.
- `phone_number_quality_update` → futuro: pause sends si phone RED.

Decisión: handlers en `services/connector-whatsapp/services/template_events.py`
separados del handler de `messages`. Razones:

1. **Failure isolation** — si quality_update falla, no rompe inbound
   pipeline de mensajes.
2. **Test surface** — 17 tests dedicados (item 4) cubren todos los
   shapes Meta documentados.
3. **Future extension** — `phone_number_quality_update` y futuros
   eventos comparten infra.

Idempotencia at-least-once: dedupe por `(tenant_id, event_uid)` en
`webhook_events_seen` (framework F.4).

### D9. Multi-tenant — credenciales via Vault

Cada tenant trae su **propio WABA + access_token**. Resolución
runtime via `tenant_integrations.credentials.{waba_id, access_token}`
(Vault Helper F.11 cuando esté disponible).

**Decisión**: NO compartir templates entre tenants. Si tenant A
registra `payment_reminder_v1` y tenant B quiere lo mismo, B submite
el suyo (mismo nombre OK, diferentes WABAs en Meta). Justificación:
- Aislamiento total — el WABA del tenant es **suyo** comercialmente.
- Branding per-tenant (mensaje puede variar tono).
- Compliance per-tenant (DPA tenant-specific).

Seed por defecto (item 6.a): `scripts/admin/seed_templates_for_tenant.py`
+ migración `20260523000000_seed_kaiu_templates.sql` precarga 4
templates LOCAL_DRAFT para tenant KAIU como ejemplo replicable.

### D10. Métricas + billing tracking (I.4.6 MA-5)

`worker.py._metrics` track per-cycle:
- `payment_reminders_sent_via_hsm`
- `payment_reminders_hsm_failed`
- `payment_reminders_hsm_not_approved`
- `cart_abandoned_reminders_sent`
- `cart_abandoned_reminders_skipped_no_consent`
- `cart_abandoned_reminders_hsm_failed`
- `cart_abandoned_reminders_hsm_not_approved`

Futuro (Sem 11 MA-5): `tenant_billing_events` recibirá emisión
automática por cada HSM enviado:
```python
emit_billing_event(
    tenant_id=tenant_id,
    provider='meta_whatsapp',
    event_type='hsm_message_sent',
    units=1,
    unit_cost_usd=0.004,  # cached al momento
    metadata={'category': 'utility', 'template_name': 'payment_reminder_v1'},
)
```

Founder dashboard verá costo HSM per-tenant para pricing decisions.

### D11. Compliance ventana 24h — decorador F.9 (MA-7)

`send_whatsapp_template` es **el único path** permitido fuera CSW.
Outbound free-form (`whatsapp_sender.send_message`) ya verifica
ventana (ADR-0002 §4). Pero esta verificación es **runtime** —
queremos que el código que llama HSM esté **explícito** sobre la
intención de salir del CSW.

Decisión MA-7 (Sem 2-3 framework): decorador `@enforce_csw_template_only_outside_24h`
en endpoints/funciones que pueden generar outbound. Si CSW cerrada y
caller no marca explícitamente `template_name=...`, la operación se
rechaza al nivel de decorador, no del cliente Meta.

Status: decorador aún no implementado (Sem 2-3 pendiente). Por ahora,
la verificación vive en `whatsapp_sender.send_message` (text path) +
`worker._try_send_payment_reminder_hsm` (HSM intent explícito).

---

## Consequences

### Positivas
- Tenant puede contactar clientes **fuera CSW** sin violar Meta
  Business Policy (engine determinístico, gates explícitos).
- F1 mantiene path $0 dentro CSW, HSM solo fallback — costo controlado.
- Habeas Data Ley 1581 enforced para MARKETING (skip silencioso sin
  consent).
- Cliente HTTP reusa framework F.2 (retry+CB+idempotency baseline) —
  no boilerplate.
- Webhook handlers aislados (failure isolation pipeline messages).
- Métricas per-template + per-tipo permiten observability + futuro
  billing aggregator (MA-5).
- Engine channel-agnóstico — futuros `order_shipped_v1`,
  `review_request_v1`, `nps_v1` reusan `send_whatsapp_template()` sin
  cambio.

### Negativas / Trade-offs
- **Submit manual** — onboarding tenant nuevo requiere 1 paso operador
  (`submit_template_to_meta.py --all-drafts`). Aceptable pre-Sem 11
  (UI tenant manager item 5 lo absorberá).
- **Templates per-tenant duplicados** — 50 tenants × 4 templates = 200
  filas en `whatsapp_templates`. Aceptable: ledger Meta-side ya tiene
  ese N.
- **Costo HSM cargado al tenant SaaS hoy** — billing aggregator MA-5
  aún no implementado, así que el costo Meta lo asume Konvi. Estimado
  10 tenants × 100 reminders/día × $0.004 = $4 USD/día ≈ $120/mes
  inicialmente. Manejable hasta Sem 11.
- **`parameter_format=POSITIONAL` solo** — NAMED soportado por Meta
  pero no usado MVP. Si tenant pide NAMED, agregar Sem 11+.

### Riesgos
- **Token Meta expira** (System User tokens long-lived pero rotables).
  Mitigación: error `TEMPLATE_ERR_META_AUTH` se loguea + cron alerta
  operador via Telegram (MA-6 health dashboard).
- **Template REJECTED por Meta** — typo, palabras prohibidas (drogas,
  apuestas, ofertas exageradas). Mitigación: webhook
  `message_template_status_update` con `status_reason` persiste el
  motivo; admin script `submit_template_to_meta.py` permite re-submit
  tras corrección.
- **Quality score RED en phone number** — Meta puede pausar el WABA si
  cae <2.5. Mitigación: webhook `phone_number_quality_update` (handler
  ya implementado item 4) + métrica `tenant_provider_health` (MA-6)
  alerta antes de pausa.
- **Cliente reporta SPAM** — Meta puede bloquear MARKETING category
  per template. Mitigación: D4 enforcement consent_given + Sem 11
  detector STOP/opt-out (H.4.1) marca contact `consent_given=false`
  ante palabras como "no más", "stop", "elimina mi número".
- **Rate limit Meta** — tier inicial 1k msgs/24h por WABA es alcanzable
  para tenant con 500 reminders/día. Mitigación: tier upgrade automático
  por Meta con quality score GREEN; H.4.3 implementará TokenBucket
  per-tenant para evitar saturar.

---

## Implementation plan

| Item | Esfuerzo | Estado |
|---|---|---|
| 1. Migration `whatsapp_templates` + helpers Python | 1d | ✅ commit ae1c7cd |
| 2. `MetaBusinessManagementClient` extends F.2 | 1d | ✅ commit 0966351 |
| 3. `send_whatsapp_template` en orchestrator + 25 tests | 1.5d | ✅ commit bb588f7 |
| 4. Webhook handlers `template_events` + 17 tests | 1d | ✅ commit 44c66ea |
| 5. UI Tenant Console template manager | 2d | ⏳ next |
| 6.a. Seed KAIU templates + admin scripts | 0.5d | ✅ commit ca514da |
| 6.b. F1 extendido HSM + cron cart_abandoned + 12 tests | 1d | ✅ commit 66f99ad |
| 7. ADR-0016 (este documento) | 0.5d | ✅ este commit |
| MA-7 decorador `@enforce_csw_template_only_outside_24h` | 0.5d | ⏳ Sem 2-3 framework |
| H.4.3 Tier-based rate limit per-tenant | 2d | ⏳ Sem 8 |
| H.4.4 Webhook delivery receipts persistence | 1d | ⏳ Sem 8 |
| MA-5 emit billing events HSM | 0.5d | ⏳ Sem 11 |

---

## Verification

### Tests unitarios (estado al cierre item 6.b)
- `tests/test_whatsapp_templates_helper.py`: 10 tests CRUD helper.
- `tests/test_meta_business_management_client.py`: 14 tests cliente HTTP.
- `tests/test_whatsapp_sender_template.py`: 25 tests send_whatsapp_template.
- `tests/test_connector_template_events.py`: 17 tests handlers webhook.
- `tests/test_worker_hsm_reminders.py`: 12 tests F1 fallback + cron cart abandoned.

**Total HSM tests**: 78. Suite global: 1998 verde, 13 OK validate.sh.

### UAT scenarios pendientes (Sem 8)
- **S36**: opt-out STOP detector marca `consent_given=false`.
- **S37**: HSM UTILITY (`payment_reminder_v1`) — orden pending_payment
  con CSW cerrada → HSM enviado → cliente recibe + paga.
- **S38**: HSM MARKETING (`cart_abandoned_24h_v1`) — carrito 25h sin
  actividad + contact consent_given=true → HSM enviado + cliente
  reactivado.

### Métricas producción-ready (Sem 14 cierre Fase 1)
- HSM delivery rate ≥99% (medido vs webhook status).
- 0 HSM enviados sin `consent_given=true` para MARKETING.
- 0 HSM enviados a templates `status != 'APPROVED'`.
- Quality score per template + per phone GREEN sostenido 30d.
- Tier WABA upgrade automático a 10k msgs/24h tras 30d GREEN.

---

## References

- Plan: `/home/ansible/.claude/plans/declarative-wondering-patterson.md`
  secciones H.4.1-H.4.4 + I.4.1-I.4.7 + MA-1 (idempotency) + MA-7
  (compliance decoradores).
- ADR-0002: Meta Business Policy compliance (ventana 24h, opt-out).
- ADR-0003: Habeas Data compliance strategy (consent gates).
- ADR-0011 §6: payment lifecycle + F1 cron rev. 103.
- Dossier WhatsApp/Meta: `docs/research/whatsapp-meta-dossier-2026-05-05.md`
  (PMP pricing tablas + tier rate limits + webhook event shapes).
- Código:
  - `services/api/lib/whatsapp_templates.py` — helper Python.
  - `services/api/lib/meta_business_management_client.py` — cliente HTTP.
  - `services/ai-orchestrator/whatsapp_sender.py` — `send_whatsapp_template`.
  - `services/connector-whatsapp/services/template_events.py` — webhook handlers.
  - `services/ai-orchestrator/worker.py` — F1 HSM fallback + cron cart abandoned.
  - `scripts/admin/submit_template_to_meta.py` — submit + re-submit.
  - `scripts/admin/send_payment_reminder.py` — demo + soporte manual.
- Migraciones:
  - `supabase/migrations/20260522000000_whatsapp_templates.sql`
  - `supabase/migrations/20260523000000_seed_kaiu_templates.sql`
  - `supabase/migrations/20260524000000_cart_abandoned_reminder.sql`
