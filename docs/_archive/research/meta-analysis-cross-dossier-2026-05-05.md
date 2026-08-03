> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Meta-Análisis Cross-Dossier — Oportunidades de mejora no captadas individualmente

**Sesión**: 2026-05-05 · **Disparador**: founder pidió "Prefiero esperar quizas en el Dossier identifiques oportunidades de mejora no captados".

**Insumos** (9 dossiers persistidos, 266 KB total):

| Dossier | Archivo | Tamaño |
|---|---|---|
| Supabase | `supabase-dossier-2026-05-05.md` | 20 KB |
| Wompi | `wompi-dossier-2026-05-05.md` | 17 KB |
| Render | `render-dossier-2026-05-05.md` | 26 KB |
| WhatsApp/Meta | `whatsapp-meta-dossier-2026-05-05.md` | 43 KB |
| Envia | `envia-dossier-2026-05-05.md` | 26 KB |
| MercadoLibre | `mercadolibre-dossier-2026-05-05.md` | 31 KB |
| Sender (email) | `sender-email-dossier-2026-05-05.md` | 24 KB |
| Telegram | `telegram-dossier-2026-05-05.md` | 35 KB |
| Cloudflare | `cloudflare-dossier-2026-05-05.md` | 32 KB |

**Hipótesis del meta-análisis**: cada dossier identificó gaps específicos del proveedor. Pero al cruzar 9 tecnologías, emergen **patrones repetidos** que ningún dossier individual ve. Cada patrón implica una abstracción/framework reutilizable que evita duplicar trabajo en N integraciones.

---

## Sección 1 — Top 10 patrones cross-cutting (oportunidades arquitectónicas)

### Patrón 1 — Webhook signature heterogeneity → "HMAC propio sobre URL secret-token" como estándar interno

**Evidencia cross-dossier**:
| Provider | Firma webhook nativa |
|---|---|
| Wompi | SHA256 plain (NO HMAC) |
| Meta WhatsApp | HMAC SHA-256 (`X-Hub-Signature-256`) |
| Envia | ❌ Sin firma nativa |
| MeLi | IP allowlist + dedup distribuido (no firma) |
| Telegram | `X-Telegram-Bot-Api-Secret-Token` (string plano, no HMAC) |

**Insight no captado individualmente**: 4 de 5 webhooks NO tienen HMAC nativo robusto. El patrón obvio (HMAC SHA-256 con secret rotable) emerge como estándar interno común. La sección H.1.F.1 del plan ya lo prevé pero el dossier individual no menciona que este patrón es **universal**, no Envia-específico.

**Recomendación arquitectónica**:
- Implementar `WebhookSecretManager` centralizado: `tenant_webhook_secrets(tenant_id, integration, secret_hash, rotated_at, expires_at, audit_log)`.
- Rotación trimestral automática + UI Settings → "Rotar secreto webhook" per integración.
- Audit log integral: cada uso de secret se registra para forensics Habeas Data.

---

### Patrón 2 — Idempotency-Key server-side ausente en 6 de 9 → cliente-side cache obligatorio

**Evidencia cross-dossier**:
| Provider | Idempotency-Key server-side |
|---|---|
| Wompi | ❌ (cierto desde ADR-0011 sólo lifecycle local) |
| Envia | ❌ (documentado explícito) |
| MeLi | ⚠️ Sólo en Mercado Pago, no en items/orders |
| Meta WhatsApp | ⚠️ `messaging_product` dedup parcial, no general |
| Telegram | ❌ |
| Sender (Resend/SES/SendGrid) | ⚠️ varía — Resend sí tiene `Idempotency-Key`, SES/Postmark parcial |
| Render API | ❌ |
| Cloudflare API | ⚠️ varía por endpoint |
| Supabase | ✅ con UNIQUE constraints en DB |

**Insight no captado**: la falta de idempotency es la regla, no la excepción. El framework F.5 (idempotency local cache) NO es Envia-específico — debe ser baseline en `IntegrationClient` base (F.2).

**Recomendación arquitectónica**:
- `IntegrationClient.execute()` calcula `request_hash = SHA256(method + url + sorted_body)` y consulta `outbound_idempotency_cache` antes del POST.
- TTL configurable per-endpoint (24h default).
- Migración Supabase: tabla unificada `outbound_idempotency_cache(provider, tenant_id, request_hash, response_json, created_at, expires_at)`.
- Cleanup pg_cron diario para purgar vencidos.

---

### Patrón 3 — Multi-tenant onboarding fricción heterogénea → wizard centralizado

**Evidencia cross-dossier**:
| Provider | Onboarding tenant |
|---|---|
| WhatsApp | Embedded Signup (Tech Provider) — semi-automatizable |
| Wompi | Manual: 4 keys per tenant en panel Wompi → copiar a UI Settings |
| Envia | Manual: API key per tenant en panel Envia → copiar a UI Settings |
| MeLi | OAuth 2.0 auth code grant — automatizable con redirect |
| Telegram | Manual: `@BotFather` 3 min/tenant — **no automatizable** por diseño Telegram |
| Sender | DNS setup SPF/DKIM/DMARC per dominio — manual |
| Cloudflare for SaaS | Custom hostnames API — automatizable |

**Insight no captado**: cada proveedor tiene flujo distinto. Tenant nuevo enfrenta **5-7 pasos manuales** dispersos sin guía. Friction alta = abandono onboarding.

**Recomendación arquitectónica nueva** (no estaba en plan H/I/J):
- **Onboarding Wizard** Tenant Console — UI step-by-step que guía:
  1. ¿Vas a vender vía WhatsApp? → Embedded Signup link + verificación callback
  2. ¿Aceptas pagos Wompi? → instrucciones panel Wompi + form 4 keys
  3. ¿Despachos vía Envia? → instrucciones panel Envia + form API key
  4. ¿Vendes en MeLi? → botón "Conectar con MercadoLibre" (OAuth)
  5. ¿Notificaciones operadores Telegram? → instrucciones `@BotFather` + form bot token
  6. (Opcional) ¿Email transaccional? → DNS records SPF/DKIM/DMARC + verificación
- Tracking progreso (`tenant_onboarding_status` table): cada tenant ve su % completado.
- Bloqueo de funciones según paso: no permite crear orden si Wompi no configurado.

**Esfuerzo estimado**: ~5-7d (Sem 10 idealmente, antes de cierre Fase 1).

---

### Patrón 4 — Pricing models heterogéneos → "tenant_billing_aggregator" obligatorio

**Evidencia cross-dossier**:
| Provider | Pricing model |
|---|---|
| Meta WhatsApp | PMP per-message (categoría: utility ~$0.005, marketing ~$0.012, auth, service) — Colombia subió tarifas Oct-2025 |
| Wompi | % per transacción (no flat) |
| Envia | Per-shipment markup variable |
| MeLi | % over sale + listing fee |
| Telegram | Free |
| Render | Per-tier flat ($7-25/svc) + add-ons |
| Cloudflare | Per-tier ($0/$25/$250) + add-ons |
| Sender (Resend) | Per-volume ($20/$90/$500 mes) |
| Supabase | Per-tier flat + uso DB |

**Insight no captado**: tenant que vende $X millones/mes consume diferente de cada provider. Sin agregador, tenant no ve "tu costo plataforma este mes = $Y" desglosado. Founder no puede pricing tenant correctly sin aggregator.

**Recomendación arquitectónica nueva**:
- Tabla `tenant_billing_events(tenant_id, provider, event_type, units, unit_cost_usd, created_at, metadata jsonb)`.
- Cada acción cobrable emite evento: WhatsApp HSM enviado, transacción Wompi confirmada, label Envia generado, email Resend enviado, etc.
- Dashboard Tenant Console "Costos del mes" con desglose por provider.
- Founder dashboard "Costos por tenant" para pricing decisions y markup.

**Esfuerzo**: ~4-5d (Sem 10-11) + UI 2d (Sem 11).

---

### Patrón 5 — Webhook delivery at-least-once SIN garantía → polling backup como patrón universal

**Evidencia cross-dossier**:
| Provider | Webhook reliability documentada |
|---|---|
| Wompi | At-least-once con retry 30min/3h/24h (tres intentos solamente) |
| Meta WhatsApp | Retry policy variable, sin SLA documentado |
| Envia | At-least-once SIN garantía formal documentada |
| MeLi | `/myfeeds` recovery endpoint — confirma que pueden perderse webhooks |
| Telegram | Retry 24h con backoff (auto-stop tras 24h) |

**Insight no captado**: 5 de 5 proveedores admiten implícita o explícitamente que webhooks pueden perderse. Polling backup NO es Envia-específico — debe ser baseline para webhooks críticos.

**Recomendación arquitectónica**:
- `services/ai-orchestrator/worker.py` cron 6h por integración:
  - Wompi: poll transacciones recientes con `status='pending'` last 24h (ya parcial post-ADR-0011)
  - Envia: poll shipments recientes con `status IN ('labeled', 'in_transit')` last 30d (planeado H.2.3)
  - MeLi: usar `/myfeeds` recovery endpoint diario
  - WhatsApp: poll message status para mensajes outbound recientes sin webhook delivery_status
  - Telegram: re-invocar `getUpdates` si webhook detecta gap (raro)
- Métrica `polling_diff_rate` per provider — si >5% señal de webhook health degradado.

---

### Patrón 6 — Sandbox vs prod paridad documentada como problemática → smoke E2E mandatorio per provider

**Evidencia cross-dossier**:
| Provider | Sandbox/prod paridad |
|---|---|
| Wompi | Sandbox auto-confirma (no DECLINED real) |
| Envia | Sandbox returns mock data parcial |
| Meta WhatsApp | Test Number gratis pero limitado a 5 destinatarios verificados |
| Sender (SES) | 200 emails/24h a destinatarios verificados (sandbox) |
| MeLi | Sandbox limitado, sin todos los topics |

**Insight no captado**: cada provider tiene fricción sandbox distinta. Smoke E2E debe ser obligatorio per provider antes de cada release a producción, NO opcional ni puntual.

**Recomendación arquitectónica**:
- `scripts/uat/smoke_{provider}_sandbox_prod.py` per provider (ya planeado para Envia, faltan los otros 4).
- CI Job nightly que ejecuta los 5 smokes contra sandbox + reporta paridad.
- Dashboard "Salud Sandbox vs Prod" en Platform Console (futuro).

---

### Patrón 7 — Authentication patterns múltiples → "tenant_credentials_facade" unificado

**Evidencia cross-dossier**:
| Provider | Esquema auth |
|---|---|
| Wompi | 4 keys: `pub_`/`prv_`/`events_`/`integrity_` |
| Envia | Bearer token único per cuenta |
| MeLi | OAuth 2.0 (access 6h + refresh) |
| WhatsApp | System User Access Token + App Secret |
| Telegram | Bot token simple |
| Sender (Resend) | API key |
| Render | API key (multi-scope) |
| Cloudflare | API token (multi-scope) |
| Supabase | service_role + anon + JWT user |

**Insight no captado**: 9 esquemas distintos en Vault. Sin facade, código está plagado de "obtener key X de tenant Y" boilerplate.

**Recomendación arquitectónica**:
- `TenantCredentialsFacade` clase única: `get(tenant_id, provider, credential_name) → SecretStr`.
- Caché in-memory con TTL 5min (evita hit Vault per request).
- Audit log: cada acceso queda registrado (`credential_access_log`) para forensics.
- Endpoint Settings → "Rotar credencial X" emite evento + revoca caché.

---

### Patrón 8 — Provider quality monitoring fragmentado → "tenant_provider_health" dashboard unificado

**Evidencia cross-dossier**:
| Provider | Estados de salud monitoreables |
|---|---|
| Meta WhatsApp | 4 quality states: GREEN/YELLOW/RED/FLAGGED + tier (1K/10K/100K/unlimited) |
| Wompi | Status states matrix transacciones (APPROVED/DECLINED/PENDING/VOIDED/ERROR) |
| Envia | Shipment status enum (rate/labeled/picked_up/in_transit/delivered/cancelled/failed) |
| MeLi | CBT score (no expuesto vía API directa, requiere parseo HTML — limitación) |
| Telegram | webhook_info estado (pending updates, last error) |

**Insight no captado**: cada dossier identifica monitoring per-proveedor pero NADIE lo unifica. Tenant ve N dashboards dispersos en cada panel provider — friction alta.

**Recomendación arquitectónica nueva**:
- Tabla `tenant_provider_health(tenant_id, provider, metric, value, threshold, status, observed_at)`.
- Cron diario que poll métricas de cada provider:
  - WhatsApp: `GET /{phone_number_id}` → quality_rating + messaging_limit_tier
  - Wompi: poll últimas 24h transacciones → calcular % declined
  - Envia: stale shipments detection (creados >5d sin tracking update)
  - MeLi: scrapping CBT score (manual o vía endpoint si existe)
  - Telegram: `getWebhookInfo` → pending_update_count + last_error_message
- UI Tenant Console "Salud integraciones" con semáforo por provider.
- Alerta Telegram al operador si algún semáforo cambia a RED.

**Esfuerzo**: ~3-4d (Sem 11).

---

### Patrón 9 — Forward-looking changes 2025-2026 → changelog watching automatizado

**Evidencia cross-dossier**:
| Provider | Cambio breaking 2025-2026 documentado |
|---|---|
| Meta WhatsApp | PMP pricing Jul-2025, Tier elimination Q1-Q2 2026, BSUID (Business-Scoped User ID) Q3 2026, On-Premise sunset Oct-2025 |
| Cloudflare | Page Rules deprecated → migrar a Cache/Configuration/Origin Rules |
| Sender (Gmail/Yahoo) | DMARC obligatorio 2026 |
| Wompi | Pricing review periódico (founder validar Jul/Sep) |

**Insight no captado**: cambios breaking ya **documentados** que afectan código existente. Sin watching, tenant queda con código obsoleto.

**Recomendación arquitectónica**:
- Tabla `provider_changelog_watch(provider, version_seen, last_check, alert_on_change_url)` con cron semanal que hace WebFetch a docs/changelog y compara hash.
- Si cambio detectado → notificación Telegram al equipo con URL específica + diff resumido (LLM-generated).
- Re-investigar dossier completo si cambio mayor (ej. WhatsApp PMP Jul-2025 hubiera disparado este patrón).

**Alternativa más liviana** (recomendada inicialmente): mantener `docs/research/changelog-watch.md` con frecuencia recomendada de re-investigación per provider:
- WhatsApp: cada 3 meses (cambia frecuente)
- Wompi: cada 6 meses
- Envia: cada 6 meses
- MeLi: cada 6 meses (limitado por 403 portal)
- Resto: cada 12 meses

---

### Patrón 10 — Compliance Habeas Data + Meta Business Policy + PCI + GDPR cruzan providers → enforcement unificado F.9 obligatorio

**Evidencia cross-dossier**:
| Compliance | Aplica a providers |
|---|---|
| Habeas Data Ley 1581 (CO) | TODOS (datos personales fluyen por todos) |
| Meta Business Policy | WhatsApp |
| Meta Commerce Policy | WhatsApp + futuro Messenger/Instagram |
| Wompi Terms of Service | Wompi |
| Envia TOS | Envia |
| MeLi CBT (Comportamiento Leal Comercio) | MeLi |
| Telegram Bot Privacy | Telegram |
| PCI DSS (futuro) | Wompi tokenized cards |
| GDPR/CCPA (futuro) | Cualquier provider con datos UE/CA |
| DMARC obligatorio Gmail/Yahoo 2026 | Sender |

**Insight no captado**: cada dossier menciona su compliance pero NADIE lo cruza. F.9 (compliance decoradores) en plan H.1 está mencionado pero no detallado.

**Recomendación arquitectónica concreta para F.9**:

```python
# services/api/lib/compliance/decorators.py

@requires_consent(scope='whatsapp_marketing')
async def send_marketing_template(...): ...

@enforce_meta_24h_window
async def send_whatsapp_outbound(...): ...

@enforce_csw_template_only_outside_24h
async def send_whatsapp_proactive(...): ...

@audit_data_access(reason='SAR_response')
async def export_contact_data(...): ...

@scoped_to_country('CO')
async def envia_quote(...): ...

@requires_verified_dkim_spf
async def send_transactional_email(...): ...

@enforce_pci_scope
async def store_payment_method(...): ...  # futuro
```

**Recomendación adicional**: tabla `compliance_enforcement_log` registrando cada decorator hit + outcome (allowed/blocked) — permite auditoría regulatoria + métrica de gates evitando producción incidente.

**Esfuerzo F.9 ampliado**: ~4-5d (era 3d en plan H.1) — Sem 2-3 framework común.

---

## Sección 2 — Riesgos arquitectónicos cross-cutting NO captados individualmente

### Riesgo Cross-1 — Multi-tenant data leakage cross-provider

**Patrón observado**: cada provider tiene su propio `tenant_id` mapping interno (Envia API key, MeLi user_id, WhatsApp WABA, Wompi merchant_id). Sin **registry centralizado**, fallo de mapping silencioso = mensaje del tenant A llega al cliente del tenant B.

**Telegram dossier ya identificó instancia concreta**: `_send_telegram_reply` toma "primer tenant activo" → cross-talk. Pero el patrón es **general**, no Telegram-específico.

**Mitigación**: tabla `tenant_provider_identity(tenant_id, provider, provider_internal_id)` con UNIQUE constraint `(provider, provider_internal_id)` (un internal_id no puede mapearse a 2 tenants). Tests cross-tenant: webhook con identity X → solo tenant Y procesa.

---

### Riesgo Cross-2 — Sin region LATAM en stack actual

**Patrón observado**: Render (sin LATAM nativo, Virginia ~80-110ms RTT desde Colombia), Supabase (revisar — el dossier supone US-East default), MeLi (LATAM nativo ✅), Wompi (Colombia ✅), Envia (LATAM ✅).

**Insight cross**: 50% del stack está en US-East. Latencia compuesta cliente Colombia → Cloudflare LATAM → Render Virginia → Supabase US-East = ~150-200ms+ total para una operación. Cloudflare edge LATAM (Bogotá) ayuda a reducir TTFB pero el bottleneck Render+Supabase persiste.

**Mitigación corto plazo**: aceptar latencia. Mitigación largo plazo (post-MVP): evaluar Supabase región más cercana (Brasil o México disponibles), evaluar Render Workspace Pro región preference.

---

### Riesgo Cross-3 — Documentación de proveedores opaca/inestable

**Evidencia**:
- MeLi dossier: portal `developers.mercadolibre.com.*` bloquea WebFetch (403 Cloudflare) → re-validación manual obligatoria.
- Envia dossier: múltiples URLs canónicas son 404 (`/docs/rate`, `/docs/generate`, etc.).
- Wompi dossier: Sender retornó 404 en página de pricing Email API SendGrid (terceros con docs frágiles).

**Insight cross**: dossiers de hoy pueden quedar desactualizados sin que sepamos. **Re-investigar trimestral** mínimo + capturar versión de docs (`Last-Modified` header si disponible).

**Mitigación**: en cada dossier guardar `<commit_hash>` de fecha investigada + URLs validadas que retornaron 200 OK. CI test que pingue las 50+ URLs cada semana y alerte si > N% retornan 404.

---

### Riesgo Cross-4 — Logs rate limit Render 6000 lines/min/instance silentes

**Render dossier identifica**: excedente de logs descartado silenciosamente. Pero ningún otro dossier menciona observabilidad — implícito Render es la fuente.

**Insight cross**: en pico de tráfico (Black Friday tenant grande) podemos perder logs forensics críticos para Habeas Data. El audit log Habeas Data NO debe ir a Render logs sino directamente a Supabase tabla append-only.

**Mitigación**: separar streams:
- Logs operacionales rutina → Render stdout (best-effort, OK perder en picos)
- Logs forensics regulatorios (Habeas Data, transacciones Wompi, webhooks) → Supabase tabla `audit_log_*` (durabilidad garantizada)
- Logs estructurados de alto volumen → futuro Logpush a R2 (Cloudflare) o S3

---

### Riesgo Cross-5 — Provider downtime cascada

**Patrón observado**: dependencias entre providers. Wompi caído → bot WhatsApp no puede generar payment_link → tenant pierde ventas. Meta WhatsApp caído → bot offline → ningún canal opera. MeLi webhook delay → orden no aterriza → cliente paga pero no se genera shipment Envia.

**Sin captura individual**: dossiers piensan en silos. Pero **fallo en cascada** es real.

**Mitigación**:
- Circuit breaker per provider (planeado F.2) ya cubre el aspecto técnico.
- **Adicional**: status page público con health de cada integración + degradación graceful documentada.
  - Wompi caído: bot avisa "Sistema de pagos en mantenimiento, te genero el link en 5 min" + retry pgmq.
  - Meta caído: nuevos clientes no pueden contactar; clientes existentes en MeLi/Telegram siguen.
  - MeLi caído: ventas WhatsApp continúan; ventas MeLi quedan en backlog.

---

## Sección 3 — Cambios al plan maestro J derivados del meta-análisis

### Cambios concretos al plan H/I/J

| # | Sección plan | Cambio propuesto | Esfuerzo |
|---|---|---|---|
| MA-1 | F.5 (idempotency cache local) | Reescribir como `IntegrationClient.outbound_idempotency` baseline en F.2 — **no** opcional | ya cubierto |
| MA-2 | H.1 framework común | Agregar componente F.10: `WebhookSecretManager` con rotación trimestral + audit | +1.5d |
| MA-3 | H.1 framework común | Agregar componente F.11: `TenantCredentialsFacade` unificado (caché 5min + audit) | +2d |
| MA-4 | I (extensibilidad) | Agregar **I.7 nuevo**: Onboarding Wizard 5-7 pasos guiados | +5-7d (Sem 10) |
| MA-5 | I (extensibilidad) | Agregar **I.8 nuevo**: `tenant_billing_aggregator` + UI desglose costos por provider | +6-7d (Sem 10-11) |
| MA-6 | J (producción-ready) | Agregar **J.2.11 nuevo**: `tenant_provider_health` dashboard unificado | +3-4d (Sem 11) |
| MA-7 | F.9 compliance | Detallar 7+ decoradores (no 1) — esfuerzo aumenta de 3d a 4-5d | +1-2d (Sem 2-3) |
| MA-8 | J.2.7 observability | Separar streams: forensics → Supabase tabla; operacional → Render | +1d (Sem 11) |
| MA-9 | (todos los webhooks) | Agregar **MA-9 cross-cutting**: polling backup pattern para los 5 webhook providers (no solo Envia) | +2d (Sem 4-5) |
| MA-10 | (todos los providers) | Agregar **MA-10 cross-cutting**: `tenant_provider_identity` table + UNIQUE cross-mapping | +1d (Sem 2-3) |
| MA-11 | docs/research/ | Agregar `changelog-watch.md` política re-investigación per provider | +0.25d |

**Total esfuerzo adicional emergente del meta-análisis**: ~22-26 días-dev distribuidos en Sem 2-11.

**Impacto en roadmap**: cierre Fase 1 se mueve de Sem 12 → Sem 13-14 (~13-14 semanas en lugar de 12). Justificable: 22-26d adicionales evitan bug arquitectónicos en producción que costarían incidentes 5-10x más caros en post-deploy.

---

## Sección 4 — Recomendación final cross-cutting

### Decisión 1 — Reframe Cloudflare P1 → P2 condicional

**Justificación cross-dossier**:
- Cloudflare dossier confirma Pro $25/mo cubre 8 de 10 necesidades P0/P1, **pero**:
- **Tunnel NO resuelve static egress IPs hacia Wompi/Meta** — gap Render P1 que asumía cubría queda abierto.
- **Wompi/Meta/Envia NO exigen allowlist por IP** (validan firma) — el gap "static egress IP" del Render dossier estaba sobrestimado.
- Custom hostnames son virtualmente gratis ($0.10/mo) → punto fuerte para storefront futuro pero NO bloqueante MVP.

**Recomendación final**: Cloudflare **opt-in Sem 11 si demanda lo justifica**, no mandatorio para deploy. Render Starter $7/svc × 4 = $28/mo cubre baseline producción 5-20 tenants. Cloudflare entra cuando: (a) primer tenant >50K msg/mes, (b) ataque DDoS L7 real, (c) demanda comercial custom domains masivo.

### Decisión 2 — Sender sigue como Resend Pro $20/mo (sin cambio)

**Justificación**: ningún patrón cross-cutting cuestiona la elección Resend. Validación humana V "sender = Sender.net o genérico" sigue pendiente pero no bloquea.

### Decisión 3 — Cross-cutting items emergentes (MA-1 a MA-11) deben integrarse al plan J

**Justificación**: 22-26d adicionales evitan refactor masivo post-producción. Mejor 13-14 semanas a producción robusta que 12 semanas a producción frágil.

### Decisión 4 — Re-investigación trimestral mínimo per provider

**Justificación**: docs WhatsApp cambiaron 4 veces en 2025 (PMP, tier elim, BSUID, On-Prem sunset). Sin watching, código queda obsoleto silente.

---

## Sección 5 — Top 5 sorpresas reales del meta-análisis (lo que NO esperábamos)

1. **4 de 5 webhooks NO tienen HMAC nativo** — el patrón "HMAC propio sobre URL secret-token" emerge como estándar interno **universal**, no Envia-específico. Componente F.10 nuevo en framework H.1.

2. **Cloudflare Tunnel NO resuelve static egress IPs hacia upstream APIs** — el gap Render que asumimos resolvería queda abierto. **Pero** Wompi/Meta/Envia no exigen allowlist por IP (validan firma) → gap se vuelve no-blocking. Reframe Cloudflare P1 → P2.

3. **Telegram dossier identificó bug arquitectónico latente** (`telegram_webhook.py:174-184`: "primer tenant activo") que es **patrón general** cross-provider — toda integración multi-tenant sin `tenant_provider_identity` registry tiene riesgo equivalente.

4. **Pricing models heterogéneos requieren `tenant_billing_aggregator` que NO estaba en plan original** — sin él, founder no puede pricing tenant correctly. Item nuevo I.8.

5. **Documentación de 2 providers (MeLi 403 Cloudflare, Envia URLs 404) no es de fiar** — re-investigación trimestral obligatoria + CI test ping URLs semanal.

---

## Sección 6 — Próximos pasos concretos

1. **Aprobar este meta-análisis** (founder review).
2. **Reclasificar Cloudflare en plan J** P1 → P2 condicional.
3. **Integrar MA-1 a MA-11** en plan H/I/J con esfuerzo +22-26d, ajuste roadmap a 13-14 semanas.
4. **Crear `docs/research/changelog-watch.md`** con frecuencia recomendada per provider.
5. **Validación humana V "sender = Sender.net o genérico"** — confirmar con founder.
6. **Iniciar Sem 1** (CI/CD pipeline + validate.sh extendido) — sin esperar más dossiers.

---

**Total aporte de los 9 dossiers**: 266 KB documentación + 11 patrones cross-cutting + 5 riesgos arquitectónicos no captados individualmente + 11 cambios concretos al plan + 4 decisiones finales.

**Veredicto**: ~22-26 días-dev adicionales son justificables. Roadmap pasa de 12 → 13-14 semanas pero producción será **robusta, no frágil**. Sin meta-análisis, hubiéramos repetido patrones por integración 5 veces (esfuerzo total >50d en duplicaciones).