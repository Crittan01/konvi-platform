# F.1/F.2 vs Meta Cloud API — Gap Audit (rev. 106 Sem 6 pre-HSM)

**Sesión**: 2026-05-08.
**Estado tras ejecución**: ✅ Sem 6 pre-HSM cerrado en la misma sesión. Items A.1, A.2, A.4, A.5, A.6, A.8 ejecutados; A.3 cancelado por decisión arquitectónica (ver §7.bis abajo); A.7 (`MetaTierLimiter`) diferido a Sem 7 dentro de F2 HSM. Suite tests **+22 nuevos** (`test_meta_hmac_per_tenant.py`).

**Re-revisión 2026-05-08 (post-clarificación founder)**: A.2 fue **simplificada** tras clarificar el modelo arquitectónico real con el founder. Ver §7.quat al final. La fuente única de verdad arquitectónica ahora es [`docs/research/meta-app-architecture-2026-05-08.md`](./meta-app-architecture-2026-05-08.md).
**Scope**: validar reusabilidad del framework común (F.1 webhook framework + F.2 IntegrationClient base + F.11 TenantCredentialsFacade) para implementar **F2 HSM templates** y subscripciones webhook adicionales (`message_template_status_update`, `phone_number_quality_update`, etc.) sin reescribir.
**Disparador**: orden recomendado al founder y aceptado — auditar framework antes de iniciar HSM (~11 días) para evitar duplicar lógica ad-hoc.
**Fuente principal**: [`docs/research/whatsapp-meta-dossier-2026-05-05.md`](./whatsapp-meta-dossier-2026-05-05.md).

---

## 1. TL;DR ejecutivo

| Componente | Estado para Meta HSM | Acción |
|---|---|---|
| **F.1 webhook framework** | 🟢 90% reusable | 1 gap menor (multi-field dispatch) + migrar `connector-whatsapp` a usarlo |
| **F.2 IntegrationClient base** | 🟢 100% reusable | Construir `MetaBusinessManagementClient` extendiendo F.2 |
| **F.11 TenantCredentialsFacade** | 🟢 100% genérico | Documentar campos esperados (`access_token`, `app_secret`, `waba_id`, `phone_number_id`) |
| **Rate limiting tier-based per-WABA** | 🔴 Gap real | F.2 + F.1 tienen RPS-bucket; Meta tier es **unique recipients/24h** — counter nuevo |
| **HMAC verification per-tenant** | 🔴 Gap conector | `connector-whatsapp/dependencies/meta.py` usa `META_APP_SECRET` global env-var → debe migrar a F.1 con `secret_resolver` per-tenant via F.11 |
| **Webhook field subscription** | 🔴 Gap parser | `services/parser.py` solo procesa `messages` field; falta `message_template_status_update`, `phone_number_quality_update`, statuses delivery |
| **`whatsapp_sender.send_template()`** | 🔴 Ausente | Construir extendiendo cliente actual; aplicar F.2 patterns |
| **DB schema `whatsapp_templates`** | 🔴 Ausente | Migración + helpers |

**Veredicto**: el framework F.1+F.2+F.11 **es reusable casi al 100%** sin extensiones arquitectónicas mayores. Los gaps son de **integración** (migrar conector existente, agregar parser de campos nuevos, construir cliente Business Management API encima de F.2). Se confirma orden recomendado al founder: arrancar Sem 7 con HSM templates apoyado en framework actual + 5 ajustes localizados.

**Estimado total ajustes de framework**: ~3-4 días-dev. Esto se hace **antes** de empezar el F2 HSM grande (~11 días) para no construir el HSM directamente sobre código ad-hoc del conector.

---

## 2. Auditoría detallada por componente

### 2.1 F.1 webhook framework

Ubicación: [`services/api/lib/webhook_framework/`](../../services/api/lib/webhook_framework/).

**Capacidades verificadas**:

| Funcionalidad Meta requerida | F.1 actual | Estado |
|---|---|---|
| `X-Hub-Signature-256` header con `sha256=` prefix + HMAC SHA-256 con app_secret | `signature.py:HMACSha256Strategy` con `prefix="sha256="` y `secret_resolver` callback | ✅ Coincide |
| Constant-time compare (`hmac.compare_digest`) | `signature.py:93` | ✅ |
| GET handshake `hub.mode=subscribe` + `hub.verify_token` + `hub.challenge` | NO está en F.1 (es ruta GET aparte, fuera del flow webhook normal) | ✅ Aceptable — handshake se queda en router-level |
| `message_template_status_update` payload field | `extract_event_uid` + `normalize` abstractos — subclass decide | ✅ Compatible (sin cambio framework) |
| Multi-field webhook (un POST con `messages[]` + `statuses[]` + `message_template_status_update`) | `WebhookHandler.handle()` ejecuta `extract_event_uid` UNA vez → 1 evento por POST | ⚠️ Gap menor (ver §3.1) |
| 200 OK <100ms + procesamiento async | `connector-whatsapp/routers/webhook.py` usa `BackgroundTasks` (no F.1 todavía) | ⚠️ Gap migración |
| Idempotency `meta_message_id` | `idempotency.py:IdempotencyStrategy` con `event_uid` arbitrario | ✅ |
| Rate limit per-tenant inbound | `rate_limit.py:TokenBucketRule` opcional | ✅ |

**Conclusión F.1**: **reusable 90%**. 1 gap menor (multi-field dispatch) + 1 task de migración (mover `connector-whatsapp` a usar F.1). No requiere extensión arquitectónica.

---

### 2.2 F.2 IntegrationClient base

Ubicación: [`services/api/lib/integration_client/base.py`](../../services/api/lib/integration_client/base.py).

**Capacidades verificadas**:

| Necesidad Meta Graph API | F.2 actual | Estado |
|---|---|---|
| Bearer token auth | `get_auth_headers()` abstract — subclass | ✅ |
| Base URL configurable | `get_base_url()` abstract | ✅ |
| Retry + circuit breaker | `retry.py` + `circuit.py` | ✅ |
| Idempotency-Key local (Meta NO lo soporta server-side) | `idempotency.py:hash_request()` + cache local con TTL | ✅ |
| Mapeo error 429 (rate limit) → `ProviderUnavailableError` retriable | `default_is_retriable` + `map_error()` overridable | ✅ |
| Mapeo error semántico 200 OK con `error.code` (Meta) | `validate_response()` overridable | ✅ |
| Backoff exponencial errores 130429 / 131056 | `RetryPolicy.compute_delay()` con jitter | ✅ |

**Conclusión F.2**: **reusable 100%**. Construir `MetaCloudClient` para `/messages` (texto, image, template) + `MetaBusinessManagementClient` para CRUD templates `/{WABA_ID}/message_templates`. Ambos extienden `IntegrationClient`.

---

### 2.3 F.11 TenantCredentialsFacade

Ubicación: [`services/api/lib/credentials_facade.py`](../../services/api/lib/credentials_facade.py).

**Verificación estructural** (file:line):

- `_read_from_source()` (línea 176-229) lee `tenant_integrations.credentials` JSONB **sin restricción de schema** → cualquier campo nombrado pasa por Vault `{field}_secret_id` o plaintext fallback.
- `KNOWN_SERVICES` (línea 44-47) ya incluye `"connector-whatsapp"` y `"orchestrator"` → forensics audit válido.
- TTL caché 5min (línea 40) — apropiado para Meta porque rotación de tokens es manual, no auto-refresh OAuth.

**Campos Meta que F.11 deberá resolver**:
```jsonc
// tenant_integrations WHERE provider='whatsapp', credentials JSONB:
{
  "phone_number_id": "...",                  // requerido outbound /messages
  "phone_number_id_secret_id": "<vault>",    // alt vault path
  "waba_id": "...",                          // requerido templates CRUD
  "access_token_secret_id": "<vault>",       // Bearer Graph API
  "app_secret_secret_id": "<vault>",         // HMAC X-Hub-Signature-256 (NUEVO per-tenant)
  "verify_token_secret_id": "<vault>"        // GET handshake hub.verify_token (NUEVO per-tenant)
}
```

**Conclusión F.11**: **100% genérico**. No requiere cambios. Sólo documentar el schema canónico Meta para que el código de templates lo encuentre consistente.

---

### 2.4 connector-whatsapp existente (gap principal)

Ubicación: [`services/connector-whatsapp/`](../../services/connector-whatsapp/).

**Gaps identificados**:

#### Gap C-1 🔴 — HMAC verification global en lugar de per-tenant

**Archivo**: [`services/connector-whatsapp/dependencies/meta.py`](../../services/connector-whatsapp/dependencies/meta.py).

```python
# Estado actual (línea 10):
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
```

Funciona en mono-tenant; en multi-tenant productivo cada WABA tiene **su propio app_secret**. No podemos compartir secret entre tenants — Meta lo rota independientemente y un compromiso afecta solo un WABA.

**Fix**: migrar a F.1 `HMACSha256Strategy` con `secret_resolver` que recibe headers/payload, extrae el `phone_number_id` del payload Meta, hace lookup en `tenant_integrations` con `phone_number_id` y devuelve el `app_secret` per-tenant (vía F.11). Resolution determinística vs payload propio Meta.

```python
# Pseudo target:
strategy = HMACSha256Strategy(
    header_name="X-Hub-Signature-256",
    secret_resolver=lambda req: facade.get(
        tenant_id=resolve_tenant_from_payload(req),
        provider="whatsapp",
        credential_name="app_secret",
    ),
)
```

**Subtleza**: el `secret_resolver` actual de F.1 recibe `headers: dict[str, str]`, no el body parseado. Para Meta necesitamos **el body**. Opción: cambiar `secret_resolver` signature a `(headers, raw_body) → str`. Compatible con resto (Wompi, Telegram) que ya pueden ignorar `raw_body`.

**Esfuerzo**: 0.5d (cambio signature + tests Wompi/Telegram + nuevo test Meta).

#### Gap C-2 🔴 — Parser solo procesa `messages` field

**Archivo**: [`services/connector-whatsapp/services/parser.py`](../../services/connector-whatsapp/services/parser.py).

Cuando Meta envía un POST con `entry[].changes[].field = "message_template_status_update"`, el parser actual lo ignora. Para F2 HSM esto es **bloqueante**: sin escuchar el field, no nos enteramos de templates aprobados/rechazados → UI tenant queda mostrando `PENDING` indefinidamente.

**Fix**: extender `parse_webhook_payloads()` para detectar `change.field` y rutear a un dispatcher que mapee:
- `messages` → existing flow (mensaje inbound)
- `messages` + `statuses[]` → nuevo flow (delivery receipts a `messages.delivered_at/read_at`)
- `message_template_status_update` → upsert `whatsapp_templates.meta_status`
- `phone_number_quality_update` → upsert `tenant_integrations.meta.quality_rating`
- `account_alerts` / `account_review_update` → log + alerta operadores
- `message_template_quality_update` → upsert `whatsapp_templates.quality`

**Esfuerzo**: 1.5d (parser dispatcher + 4 handlers nuevos + tests por field).

#### Gap C-3 🔴 — `webhook.py` no usa F.1 base handler

**Archivo**: [`services/connector-whatsapp/routers/webhook.py`](../../services/connector-whatsapp/routers/webhook.py).

Hoy ad-hoc: HMAC dependency + `BackgroundTasks` + `decouple_and_enqueue` directo. F.1 ofrece el flow completo (signature → idempotency → rate-limit → normalize → enqueue) ya implementado.

**Fix**: implementar `MetaWebhookHandler(WebhookHandler)` en `services/connector-whatsapp/handlers/meta.py` que usa F.1. El router queda mínimo:

```python
@router.post("/webhook")
async def receive_message(request: Request):
    handler = MetaWebhookHandler(...)
    raw = await request.body()
    try:
        result = await handler.handle(
            raw_body=raw,
            headers=dict(request.headers),
            query_params=dict(request.query_params),
            client_ip=request.client.host if request.client else None,
        )
        return JSONResponse(content=result, status_code=200)
    except WebhookError as e:
        resp = to_http_response(e)
        return JSONResponse(content=resp["payload"], status_code=resp["status"], headers=resp["headers"])
```

**Esfuerzo**: 1d (refactor webhook.py + tests).

---

### 2.5 Rate limiting tier-based per-WABA (gap real)

**Necesidad Meta** ([dossier sec. 4.3](./whatsapp-meta-dossier-2026-05-05.md)):
- Tiers: 250 / 1K / 10K / 100K / unlimited **unique recipients/24h** (sliding window).
- Q1-Q2 2026: Meta elimina 1K + 10K → 250 → 100K directo si quality verde.
- Excederlo → `131048` Spam rate limit + quality drop (sanción operativa).

**F.2 actual**: `TokenBucketRule(capacity, refill_per_sec)` — pattern RPS, **no unique-recipients-24h**. Diferente noción.

**Fix**: nuevo helper `MetaTierLimiter`:

```python
@dataclass
class MetaTierState:
    tenant_id: str
    waba_id: str
    tier_capacity: int                      # 250 / 1000 / 10000 / 100000 / -1
    unique_recipients_24h: set[str]         # Sliding window — purge >24h
    last_warning_at: float | None

class MetaTierLimiter:
    """
    Sliding 24h window, per-(tenant, waba). Cuenta phone destinatarios
    únicos. Lectura desde DB (`messages` table) on init + memoria local
    durante runtime. Persistir cada N minutos para sobrevivir restart.
    """
    def consume(tenant_id, waba_id, recipient_phone) -> bool:
        # True si dentro del tier; False si rechazaría.
```

Tier actualizable vía webhook `phone_number_quality_update` (F.1 dispatcher rutea, handler upsert). Si tenant excede `tier_capacity * 0.8` → alerta Telegram operadores (F.2 + Telegram dossier).

**Esfuerzo**: 2d (helper + persistencia + tests + alerta + handler webhook).

**Decisión arquitectónica**: este componente NO es general-purpose para los 5 providers. Vive en `services/api/lib/meta_tier_limiter.py` (módulo Meta-específico) y NO contamina F.2. Justifica una abstracción nueva `OutboundQuotaTracker` solo si MeLi/otros expone tiers similares; por ahora YAGNI.

---

## 3. Gaps menores (no bloqueantes pero anotar)

### 3.1 Multi-field webhook dispatch en F.1

**Caso**: un POST Meta puede contener `entry[]` con varios `changes[]` (cada uno un field distinto). F.1 `WebhookHandler.handle()` extrae UN `event_uid` por request → trataría todo como un evento.

**Mitigación actual (suficiente para Meta)**: el `extract_event_uid()` puede retornar un ID compuesto del primer field/change y `normalize()` puede emitir múltiples normalized events con un solo `enqueue` que los itera. F.1 sigue siendo válido, sólo el subclass debe resolver el split internamente.

**Decisión**: NO modificar F.1. Documentar el patrón en `MetaWebhookHandler` (subclass) como ejemplo.

### 3.2 Verify-token GET handshake separado

`hub.challenge` es endpoint GET, fuera del flow `WebhookHandler.handle()` (que es POST-only). Se queda en el router como ruta aparte (similar a hoy). NO requiere ajustes framework.

### 3.3 Graph API version migration v21.0 → v22.0+

Meta ya requiere v22.0+ desde 9-Sep-2025 (dossier sec. P0-2). Es un constante en `services/ai-orchestrator/whatsapp_sender.py:8` y `services/ai-orchestrator/services/meta_media.py:7`. Cambio de 1 línea + smoke test. **Esfuerzo**: 0.5d.

**Decisión**: hacerlo dentro del bloque pre-HSM porque F2 introducirá nuevos endpoints que requieren la versión correcta.

---

## 4. Plan de acción Sem 6 (pre-HSM)

Total estimado: **~5 días-dev** (incluye Graph API version + multi-field doc).

| # | Item | Archivo principal | Esfuerzo | Bloquea HSM |
|---|---|---|---|---|
| **A.1** | Cambiar `secret_resolver` signature de F.1 a `(headers, raw_body) → str` | `services/api/lib/webhook_framework/signature.py` | 0.5d | SÍ |
| **A.2** | Migrar `connector-whatsapp/dependencies/meta.py` a usar F.1 + F.11 | `services/connector-whatsapp/handlers/meta.py` (nuevo) | 1d | SÍ |
| **A.3** | Refactor `connector-whatsapp/routers/webhook.py` para usar `MetaWebhookHandler` (extiende F.1) | `services/connector-whatsapp/routers/webhook.py` | 1d | SÍ |
| **A.4** | Extender `services/parser.py` con dispatcher por `change.field` (4 fields nuevos) | `services/connector-whatsapp/services/parser.py` | 1.5d | SÍ |
| **A.5** | Migrar `META_API_VERSION` v21 → v22 + smoke test | 2 archivos | 0.5d | SÍ |
| **A.6** | Documentar schema canónico `tenant_integrations.whatsapp.credentials` | `.context/06-contracts.md` | 0.25d | NO |
| **A.7** | Construir `MetaTierLimiter` (sliding 24h unique recipients) | `services/api/lib/meta_tier_limiter.py` (nuevo) | 2d | NO (HSM puede salir sin esto, pero recomendable antes de primer broadcast) |
| **A.8** | Tests E2E del refactor: GET handshake + POST messages + POST template_status_update | `tests/test_meta_webhook_handler.py` | 1d | SÍ |

**Total bloqueantes HSM**: A.1+A.2+A.3+A.4+A.5+A.8 = **5 días-dev**.
**Adicional recomendado pre-broadcast**: A.7 = **2 días-dev**.

Estos 5 días sostienen los siguientes ~11 días de F2 HSM templates en una **base sólida y auditable**. Sin ellos, F2 acaba duplicando lógica HMAC, parser, rate-limit ad-hoc para Meta — exactamente la trampa que el plan K trataba de evitar.

---

## 5. Lo que NO se hace en Sem 6

| Item | Razón |
|---|---|
| Construir `MetaCloudClient` outbound `/messages` | Sale en Sem 7 dentro de F2 (extiende F.2) |
| Construir `MetaBusinessManagementClient` para templates CRUD | Sale en Sem 7 dentro de F2 |
| `whatsapp_sender.send_template()` | Sale en Sem 7 dentro de F2 |
| Migración `whatsapp_templates` table | Sale en Sem 7 dentro de F2 |
| UI tenant template manager | Sale en Sem 7 dentro de F2 |
| Embedded Signup onboarding | P2 backlog (~8-10d + 2-6 semanas review Meta) |
| Interactive messages (button, list, cta_url, location_request) | P2 backlog (~4d) |

---

## 6. Verificación (Definition of Done Sem 6)

- [ ] `verify_meta_signature` migrado a F.1 con secret per-tenant. Test multi-tenant verifica que tenant A con secret X no acepta firma calculada con secret Y de tenant B.
- [ ] Parser dispatcher cubre `messages`, `statuses`, `message_template_status_update`, `phone_number_quality_update` (mocks contra payloads reales del dossier sec. 5).
- [ ] Smoke E2E `scripts/uat/smoke_meta_webhook.py` corre verde: GET handshake + 4 fields POST.
- [ ] `META_API_VERSION = "v22.0"` en ambos archivos. Smoke envío text + image OK.
- [ ] `MetaTierLimiter` construido + test sliding window 24h pasa.
- [ ] `.context/06-contracts.md` documenta schema canónico Meta credentials.
- [ ] validate.sh 13 OK / 0 ERROR / suite tests verde + nuevos tests añadidos.

---

## 7. Decisiones registradas

1. ✅ F.1 + F.2 + F.11 son reusables casi al 100% — **NO requieren refactor mayor**.
2. ⚠️ **REVISADA durante ejecución**: NO migrar `connector-whatsapp` a usar F.1 (ver §7.bis). Migración inline en `dependencies/meta.py` con misma garantía per-tenant.
3. ✅ `secret_resolver` signature cambia a `(headers, raw_body)` — único cambio breaking del framework, controlado.
4. ✅ `MetaTierLimiter` queda como módulo Meta-específico (`lib/meta_tier_limiter.py`), NO se generaliza a F.2 todavía (YAGNI hasta segundo provider con tier).
5. ✅ Multi-field webhook dispatch se resuelve en `parse_webhook_events()` (parser nuevo en connector), sin tocar F.1 base.
6. ✅ Graph API v21 → v22 incluido en bloque pre-HSM (oportunidad).
7. ✅ Estimado Sem 6 pre-HSM: ejecutado en una sesión (8 items menores).

## 7.bis Decisión arquitectónica nueva — connector-whatsapp NO migra a F.1

Durante ejecución de A.2 se descubrió que `services/connector-whatsapp` es **deploy unit independiente** en Render (`rootDir: services/connector-whatsapp` en `render.yaml`). NO puede importar `services/api/lib/webhook_framework/` sin cross-service coupling que rompería el aislamiento de deploys.

**Opciones evaluadas**:

| # | Opción | Pros | Contras |
|---|---|---|---|
| A | Mover `webhook_framework/` a top-level package compartido | Reuso máximo | Requiere reorganizar `render.yaml` + paths de imports en 4 servicios; no trivial |
| B | Symlink/duplicar el módulo en cada deploy unit | DRY parcial | Frágil; symlinks no funcionan bien en Render Buildpacks |
| C | **Mantener HMAC inline en connector-whatsapp con misma garantía per-tenant** | Cero cross-service coupling; deploy aislado preservado; lógica idéntica funcional | Pequeña duplicación (~80 LOC HMAC + cache + lookup) |

**Decisión C aceptada**: el connector mantiene `dependencies/meta.py` inline con:
- Lookup `phone_number_id` → `tenant_integrations` per-tenant.
- Vault-first secret resolution (con plaintext fallback + WARN).
- Cache TTL 5min (mismo pattern F.11 inline).
- Backward compat con `META_APP_SECRET` env var legacy (con WARN).

F.1 sigue siendo el patrón canónico para webhooks que viven dentro de `services/api/` (Wompi, MeLi, Envia inbound). Cuando/si el connector se consolide en `services/api/` (futuro refactor), migrar a F.1 será trivial.

**Trade-off documentado**: ~80 LOC de duplicación de patrones HMAC + cache + Vault, a cambio de aislamiento de deploy unit. Aceptado.

## 7.quat Corrección post-clarificación founder (2026-05-08, mismo día)

Tras la primera implementación de A.2, conversación con el founder reveló:
- **No es partner Meta** (no Tech Provider Program).
- Tiene **UNA Meta App** "Commerce Ops App" (id=`819229210624423`) creada en su cuenta personal Facebook.
- Configuró WhatsApp + Webhooks en esa App.
- KAIU (Kaiu Natural Living) es el primer tenant + es del founder mismo (eCommerce real).
- Otros tenants futuros agregarán sus propias WABAs a la **misma** Meta App vía Solution Partner App + System User token.

**Implicación crítica**: el `app_secret` de la Meta App es **GLOBAL** (de la App), no per-tenant. Mi implementación A.2 inicial intentaba lookup per-tenant del `app_secret` con fallback global — eso era **arquitecturalmente incorrecto** (el lookup nunca iba a encontrar nada porque ningún tenant tiene ni nunca tendrá su propio `app_secret`).

**Cambios aplicados**:
- ✅ `services/connector-whatsapp/dependencies/meta.py` reescrito (simplificado):
  - HMAC verify usa **`META_APP_SECRET` global directo** (del env var en Render).
  - Removido lookup per-tenant del `app_secret` (~80 LOC menos).
  - **Mantenido** lookup `phone_number_id → tenant_id` con propósito FORENSICS (loguear tenant_id por webhook + future routing). NO afecta HMAC.
  - Si `META_APP_SECRET` no configurado → 503 (server misconfigured).
  - Cache TTL 5min para forensics lookup (incluyendo negativos).
- ✅ Tests actualizados: HmacGlobalTests + TenantResolutionForensicsTests (22 verde).
- ✅ `.context/06-contracts.md` §7.1-§7.3 reescrito con modelo correcto.
- ✅ KAIU `tenant_integrations.credentials.waba_id = '2159052118202272'` agregado vía UPDATE (estaba NULL — bloqueante para F2 HSM).
- ✅ Doc nueva: [`docs/research/meta-app-architecture-2026-05-08.md`](./meta-app-architecture-2026-05-08.md) — fuente única de verdad arquitectónica.
- ✅ Doc nueva: [`docs/onboarding/whatsapp-tenant-setup.md`](../onboarding/whatsapp-tenant-setup.md) — guía paso-a-paso para tenants nuevos.
- ✅ Checklist humano: [`docs/onboarding/H1-H5-checklist.md`](../onboarding/H1-H5-checklist.md) — trámites Meta pendientes (Business Verification + App Review).

**Trámites humanos detectados** (no bloquean código pero sí producción multi-tenant):
- H1: decidir nombre platform (founder no está seguro de "Commerce Ops").
- H2: crear Business Portfolio platform + transferir Meta App `819229210624423` del personal a ese portfolio.
- H3: iniciar Business Verification del portfolio (1-3 sem Meta).
- H4: submit App Review post-verification (1-2 sem Meta).
- H5: doc onboarding ✅ ya creada.

**Lección aprendida**: aplicar regla "no suposiciones" más estricto. Antes de codear A.2 debí haber confirmado el modelo de App con el founder. La doc de arquitectura ahora documenta esto explícitamente para futuras sesiones.

## 7.ter Items NO ejecutados Sem 6

| Item | Razón | Plan |
|---|---|---|
| A.3 (refactor router con `MetaWebhookHandler`) | Cancelado — connector mantiene inline (§7.bis). Router actual con `verify_meta_signature` dep + `BackgroundTasks` + dispatcher integrado en `decouple_and_enqueue` ES suficiente. | — |
| A.7 (`MetaTierLimiter`) | Diferido a Sem 7 dentro de F2 HSM | Construir cuando exista la suscripción a `phone_number_quality_update` que mantiene `tier` actualizado en `tenant_integrations.credentials.tier` |

---

**Branch**: `phase-0-pre-prod` (sin commits a `develop`/`main`).
**Próximo paso**: ejecutar A.1-A.5 + A.8 en orden secuencial. A.7 (tier limiter) puede paralelizarse o adelantarse a Sem 7 si time-box.
