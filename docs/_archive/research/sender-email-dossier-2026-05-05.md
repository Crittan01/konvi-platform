> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Dossier Sender Email Transactional — 2026-05-05

**Fecha**: 2026-05-05 · **Sesión**: investigación previa Sem 0 (J.0.0) · **Sin pruebas en vivo**.
**Fuentes**: docs públicos `resend.com/docs`, `postmarkapp.com`, `docs.aws.amazon.com/ses`, `twilio.com/docs/sendgrid`, `sender.net/pricing`.
**Alcance**: Konvi Platform — SaaS B2B multi-tenant Colombia. **Estado actual: NO hay sender de email transaccional integrado**. Casos de uso pendientes: magic-link/OTP login (Supabase Auth Custom SMTP), notificaciones tenant→cliente (orden creada, pago recibido, despacho), notificaciones internas (alerta error, daily digest), respuestas Habeas Data SAR (Ley 1581 exige medio escrito).
**Aviso de ambigüedad**: el founder mencionó "sender" en su lista de proveedores. Ese término **no es unívoco** — puede referirse a Sender.net (proveedor literal con ese nombre, focus marketing/LATAM) o a un nombre genérico para el sender transaccional ("el sender de email"). Este dossier compara los 5 candidatos relevantes y deja la desambiguación como validación humana CRÍTICA (§ 9).

## 1. TL;DR ejecutivo

- **Recomendación primaria**: **Resend** como proveedor inicial.
  - Tier free: 3.000 emails/mes, 100/día, sin tarjeta.
  - Tier Pro: USD 20/mes por 50.000 emails (overage USD 0.90/1.000), USD 35/mes por 100.000.
  - DX moderno (`POST /emails`, SDK Node/Python idiomático, React Email integration). Ajuste con stack `apps/web` Next.js 14.2.
  - Multi-tenant viable vía custom domains + API keys con scoping `sending_access` por dominio.
  - Webhooks completos (18 event types vía Svix) — habilita audit log Habeas Data.
- **Fallback enterprise**: SendGrid (Twilio) si volumen >500K/mes o se necesitan subusers nativos con dedicated IP per tenant (requiere plan **Pro o Premier**, hasta 15 subusers; más, soporte).
- **Alternativa de costo extremo**: Amazon SES (USD 0.10 / 1.000 = ~9× más barato que Resend a volumen, USD 5/mes para 50K). Costo: setup IAM/SigV4 + sandbox approval (24 h hábil) + DKIM Easy DKIM por dominio + ausencia de UI dev-friendly.
- **Excluir como primary**:
  - **Sender.net** — focus marketing (newsletters/automation/popups). API transaccional poco documentada en pricing público; no es candidato serio para nuestros casos.
  - **Postmark** — excelente reputación de deliverability transaccional y servers como sub-tenants, pero ~10–15× más caro por overage que Resend (USD 1.20–1.80 / 1.000 vs USD 0.90).
- **Costo mensual estimado** (asumiendo MVP <50K emails/mes): **~USD 20/mes** con Resend Pro. Esfuerzo integración: **2–3 días-dev** (DKIM/SPF dominio principal + librería SDK + webhook handler + plantillas).

## 2. Hallazgos clave por candidato

### 2.1 Resend

- **Endpoint base**: `POST https://api.resend.com/emails`. Auth: `Authorization: Bearer re_xxx`. Batch: `POST /emails/batch` (≤100 mensajes/llamada, sin attachments ni `scheduled_at`).
- **Pricing** (USD):
  - Free: 3.000/mes, 100/día.
  - Pro USD 20/mes (50K) o USD 35/mes (100K). Overage USD 0.90/1.000.
  - Scale USD 90 (100K nuevo tier con features), USD 350 (500K), USD 650 (1M), USD 1.150 (2.5M).
  - Enterprise: dedicated IPs, SLA, SSO, retention flexible (custom).
- **Features**: HTML/text/React, attachments ≤40 MB post-Base64, idempotency key (256 chars, expira 24 h), `scheduled_at` (lenguaje natural o ISO 8601), `tags` (key/value), `template` con variables, `topic_id` (suscripciones).
- **Rate limit default**: 5 req/s/team → HTTP 429.
- **Recipients máx por email**: 50 (to+cc+bcc).
- **Webhooks (18 eventos)**: `email.sent | delivered | bounced | complained | opened | clicked | failed | delivery_delayed | received | scheduled | suppressed`, más `domain.*` y `contact.*`. Retry: 5 s / 5 min / 30 min / 2 h / 5 h / 10 h. Deduplicación vía `svix-id` (Svix subyacente). At-least-once.
- **Deliverability**: no publica scores oficiales; warm-up automático en infraestructura compartida (sin commit explícito). Dedicated IP solo en Enterprise.
- URLs:
  - https://resend.com/pricing
  - https://resend.com/docs/api-reference/emails/send-email
  - https://resend.com/docs/api-reference/emails/send-batch-emails
  - https://resend.com/docs/dashboard/webhooks/introduction
  - https://resend.com/docs/dashboard/webhooks/event-types
  - https://resend.com/docs/api-reference/api-keys/create-api-key
  - https://resend.com/docs/dashboard/domains/introduction
  - https://resend.com/docs/send-with-nodejs

### 2.2 Sender.net

- **Pricing** (no muestra cifras directas para todos los tiers; valores capturados):
  - Free Forever: 2.500 suscriptores, 15.000 emails/mes (con sender branding).
  - Standard: remueve branding, 3 seats, SMS, A/B.
  - Professional: 10 seats, créditos SMS, automation multichannel; **dedicated IPs solo en planes con >20.000 suscriptores**.
  - Enterprise: SSO SAMLv2, SLA, success manager.
- **Foco real**: marketing (newsletters/automation/landing pages/popups). Transaccional aparece como "core feature" pero **el pricing público no separa transactional API ni publica overage por 1.000 transaccionales**.
- **API transaccional**: existencia confirmada por pricing pero documentación pública dispersa; redirección desde `help.sender.net/support/...` → `sender.net/help/` no devolvió detalles de endpoint/auth en este pase.
- **Riesgo arquitectónico**: producto LATAM-friendly por marketing, no transaccional B2B. Para Habeas Data SAR / OTP / orden-creada NO es la elección óptima.
- URL: https://www.sender.net/pricing/

### 2.3 SendGrid (Twilio)

- **Endpoint base**: `POST https://api.sendgrid.com/v3/mail/send` (también `https://api.eu.sendgrid.com` para EU). Auth: Bearer API key.
- **Límites por mensaje**:
  - `personalizations[]` máx 1.000 (1 personalization = 1 destinatario lógico).
  - 1.000 cc, 1.000 bcc, 1.000 reply_to.
  - 10 categorías por mensaje, custom args ≤10.000 bytes, substitutions ≤10.000 bytes.
  - `send_at` (Unix ts) — máx 72 h en el futuro.
  - `batch_id` para agrupar y permitir cancelación vía Scheduled Sends API.
- **Subusers (multi-tenant nativo)**:
  - **Requiere plan Pro o Premier (Email API) o Advanced Marketing Campaigns**.
  - Hasta 15 subusers estándar; más → soporte.
  - Cada subuser: username/password propios, dedicated IP asignable, estadísticas separadas.
- **Pricing público**: páginas de pricing redireccionan en cadena (sendgrid.com → twilio.com/sendgrid). En este pase **no se obtuvieron cifras numéricas oficiales actualizadas vía WebFetch**; los planes nominales son Free / Essentials / Pro / Premier (ver § 9 — VALIDAR EN DOCUMENTACION OFICIAL).
- URLs:
  - https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send
  - https://www.twilio.com/docs/sendgrid/ui/account-and-settings/subusers
  - https://www.twilio.com/en-us/sendgrid/email-api/pricing (pendiente captura)

### 2.4 Postmark

- **Concepto multi-tenant**: **Servers** (un server = "carpeta" lógica con API token propio, tracking propio, inbound propio). Recomendación oficial: "give each client their own server" → encaja con multi-tenant per-tenant aislado. Cada server admite hasta 10 message streams (transactional vs broadcast).
- **Pricing** (USD, todos los tiers transaccionales arrancan en 10.000 emails/mes incluidos):
  - Developer: USD 0/mes — 100 emails/mes (testing).
  - Basic: USD 15/mes — 5 dominios custom, 45 días retention. Overage USD 1.80/1.000.
  - Pro: USD 16.50/mes — 10 dominios, inbound, hasta 365 días retention. Overage USD 1.30/1.000.
  - Platform: USD 18/mes — dominios ilimitados, inbound, teams. Overage USD 1.20/1.000.
  - Dedicated IP: desde USD 50/mes/IP (solo para clientes >300K emails/mes, Pro+).
  - Custom retention: USD 5/mes (Pro+). DMARC monitoring: USD 14/mes/dominio.
- **Attachment máx**: 10 MB (incluye headers + content + attachments) — más restrictivo que Resend/SES.
- **Webhooks**: bounce, inbound, open, delivery, click, spam complaint, subscription change, SMTP API errors.
- URLs:
  - https://postmarkapp.com/pricing
  - https://postmarkapp.com/manual

### 2.5 Amazon SES

- **Pricing** (USD): outbound USD 0.10 / 1.000 emails. Inbound USD 0.10 / 1.000. Attachments USD 0.12/GB. Dedicated IP estándar USD 24.95/mes/IP. Dedicated IP Managed USD 15/mes/account + tiered (USD 0.08–0.02 / 1.000). Virtual Deliverability Manager USD 0.07/1.000 (≤10M/mes).
- **Free tier nuevo**: 3.000 message charges/mes durante 12 meses post-activación (independiente de EC2).
- **Sandbox (default al crear cuenta)**:
  - Solo envío a direcciones/dominios verificados o al simulator.
  - Máx 200 emails/24 h.
  - Máx 1 email/segundo.
  - Suppression list management deshabilitado.
  - **Production access**: solicitud vía consola o `aws sesv2 put-account-details --production-access-enabled --mail-type TRANSACTIONAL ...`. Respuesta inicial AWS Support en 24 h.
- **Quotas post-sandbox**: ajustables (sending rate y daily volume varían por cuenta). 50 destinatarios máx por mensaje (To+Cc+Bcc, no ajustable). 40 MB por mensaje (SES v2/SMTP). 10 MB en SES v1.
- **Multi-tenant**: 3 mecanismos:
  1. **Configuration sets** (hasta 10.000) — agrupan reglas (event destinations, IP pools, suppression). Aplican vía header de email o como default por identidad.
  2. **Identidades verificadas** — hasta 10.000 por región (dominios/emails).
  3. **Easy DKIM** (SES genera key) o **BYODKIM** (1024–2048 bits) por identidad. Inheritance subdomain → parent.
- **Auth**: IAM SigV4 (no Bearer). API v1 y v2 separadas. Rate limit API control plane: 1 req/s para todas las acciones excepto `SendEmail/SendRawEmail/SendTemplatedEmail`.
- **Eventos**: SNS / SQS / Firehose / CloudWatch / EventBridge — vía configuration set event destinations (≤10 destinations/config set).
- URLs:
  - https://aws.amazon.com/ses/pricing/
  - https://docs.aws.amazon.com/ses/latest/dg/Welcome.html
  - https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html
  - https://docs.aws.amazon.com/ses/latest/dg/using-configuration-sets.html
  - https://docs.aws.amazon.com/ses/latest/dg/quotas.html
  - https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim.html

## 3. Multi-tenant compatibility

| Capacidad | Resend | Sender.net | SendGrid | Postmark | Amazon SES |
|---|---|---|---|---|---|
| Sub-cuentas / sub-tenants | No nativo (vía API keys + dominios) | No documentado | **Subusers** (Pro/Premier) | **Servers** (todos los tiers) | Configuration sets + identidades |
| Custom domain per tenant (DKIM/SPF) | Sí, múltiples dominios sin límite documentado | No documentado público | Sí (Domain Authentication) | Sí (5/10/∞ según tier) | Sí (≤10.000 identidades/región) |
| API key scoping per dominio | **Sí** (`sending_access` + restrict to domain) | No documentado | Sí (subuser key) | Sí (server token) | IAM policy con `Resource:identity` |
| Webhooks por tenant | Múltiples endpoints (no confirmado explícito) | No documentado | Por subuser | Por server | Por configuration set (event destination) |
| Estadísticas separadas per tenant | Vía `tags` | N/A | Por subuser | Por server | Por configuration set |
| Dedicated IP per tenant | Solo Enterprise | Plan ≥20K subs | Sí (Pro/Premier subuser) | USD 50/mes/IP (Pro+, >300K) | USD 24.95/mes/IP estándar |

**Implicación arquitectónica**: si elegimos Resend, multi-tenant se modela vía:
1. Un dominio plataforma (`mail.commerce-ops.co`) → DKIM/SPF a nivel plataforma → emails `noreply+<tenant_slug>@mail.commerce-ops.co` o subdominio por tenant `<tenant>.mail.commerce-ops.co` si tenants premium quieren branding.
2. API key única backend (no per-tenant) — el `tenant_id` viaja en `tags` para audit log.
3. Webhook único `/api/webhooks/resend` que demultiplexa por `tags.tenant_id`.

Si en el futuro un tenant exige dominio propio (ej. `noreply@<tenant>.com`), Resend lo permite agregando dominios; el tenant configura DNS.

## 4. Limitaciones documentadas

| Aspecto | Resend | SendGrid | Postmark | Amazon SES |
|---|---|---|---|---|
| Rate limit default | 5 req/s/team | No publicado en mail/send | No publicado | 1/s sandbox; ajustable post |
| Attachment máx | 40 MB (Base64) | Base64 (límite no único publicado) | 10 MB (incluye todo) | 40 MB v2 / 10 MB v1 |
| Recipients/email | 50 (to+cc+bcc) | 1.000 personalizations (1 = 1 dest) | No publicado | 50 (no ajustable) |
| Sandbox | No (free tier es producción) | No (free es producción) | No | **Sí** (200 emails/24h, dest verificados) |
| IP shared default | Sí | Sí | Sí | Sí |
| IP warm-up obligatorio | Auto-managed | Sí (dedicated) | Sí (dedicated) | Sí (dedicated) |
| Inbox testing | `delivered@resend.dev` y `bounced@resend.dev` | Sandbox mode + mailbox simulator | Bounce testing addresses | Mailbox simulator (`success@simulator.amazonses.com` etc.) |
| Idempotency | `idempotencyKey` (24 h) | Manual vía custom args | Manual | Manual / `MessageDeduplicationId` (SQS-driven) |

## 5. Lo que necesitamos vs lo que ofrecen

| Caso de uso | Volumen estimado / mes | Resend | SendGrid | Postmark | Amazon SES | Sender.net |
|---|---|---|---|---|---|---|
| Magic link / OTP (Supabase Custom SMTP) | bajo (~1K usuarios × 3 logins = 3K) | OK SMTP/HTTP | OK | OK ideal | OK | Posible (no claro) |
| Notif. tenant→cliente (orden, pago, despacho) | medio (10–50K) | OK Pro USD 20 | Pro+ requerido para subusers | OK Basic USD 15 | OK USD 1–5 | No óptimo |
| Notif. internas (alerta error, daily digest) | bajo (<1K) | OK free | OK | OK | OK | OK |
| Habeas Data SAR responses (Ley 1581) | muy bajo (<100) | OK + audit log webhooks | OK + categorías | OK + retention 365d (Pro) | OK + S3 archive | Riesgoso (no transactional-first) |
| Templates con variables | — | `template` + variables, React Email | Dynamic Templates Handlebars | Templates con Mustachio | SES Templates (≤500KB, ≤20K templates) | Builder marketing (no transactional API) |
| Audit log delivery events (Habeas Data) | requerido | Webhooks 18 eventos | Webhooks completos | Webhooks completos | SNS/Firehose/EventBridge | Limitado |

**Conclusión funcional**: Resend, SendGrid, Postmark y SES cubren los 5 casos. Sender.net cubre marketing pero no es candidato confiable para SAR ni magic-link.

## 6. Gaps críticos (independientes del proveedor)

### P0 — bloqueantes deliverability

- **SPF + DKIM por dominio principal**: registro DNS TXT SPF (`v=spf1 include:<provider> -all`) y DKIM (CNAME o TXT — Easy DKIM SES; CNAME `resend._domainkey...` Resend). Sin esto: spam folder o rechazo Gmail/Outlook. Aplicable a todos los proveedores.
- **From address verificado**: dominio o email "From" debe estar verificado en el proveedor. SES/Resend rechazan envío si no.
- **Bounce + complaint handling**: DEBE existir endpoint que reciba `email.bounced` y `email.complained`, marque el destinatario como `suppressed` en BD propia, y NO reintente. Sin esto: degradación rápida de reputación de IP.
- **Habeas Data audit log**: cada envío relacionado con SAR / consent / dato personal del cliente final DEBE persistir en `audit_log` con `provider_message_id`, `tenant_id`, `delivered_at`, `event_type` para evidencia ante SIC. Webhooks de delivery son la fuente.

### P1 — recomendados deliverability

- **DMARC** (`v=DMARC1; p=quarantine; rua=mailto:dmarc@...`): opcional pero requerido por Gmail/Yahoo desde 2026 para senders >5K/día.
- **List-Unsubscribe header (RFC 8058)**: para emails no-transaccionales (digest, marketing futuro). Para transaccionales puros (OTP, factura) no aplica.
- **Custom domain per tenant**: branding tenant. Decisión: ofrecer como feature de plan superior o usar dominio plataforma uniforme. **Sin decisión humana — ver § 9**.

### P2 — opcionales

- **Dedicated IP**: solo si volumen >300K/mes (Postmark) o >100K (Resend Enterprise). Hoy fuera de alcance.
- **DMARC monitoring service** (Postmark USD 14/dominio o gratuita en Resend dashboard).

## 7. ¿Estamos sobre-ingeniando o sub-aprovechando?

- **Sub-aprovechado**, severamente. Hoy la única vía de comunicación tenant→cliente es WhatsApp (vía connector-whatsapp). Esto deja huecos:
  - **Habeas Data SAR (Ley 1581)** exige medio escrito, durable, auditable. WhatsApp NO es ese medio (mensajes pueden expirar, encriptación E2E impide al data controller probar contenido). Email es el canal estándar aceptado por SIC.
  - **Magic link / OTP login Supabase**: hoy delegado a Supabase Auth con SMTP por defecto (4 emails/h, dominio `noreply@mail.app.supabase.io` — **no production-ready**). El gap dossier Supabase ya marca "Custom SMTP" como obligatorio antes de prod.
  - **Notificaciones tenant**: cliente final que no tiene WhatsApp activo (o que opt-out) queda sin canal de notificación de orden/pago/despacho.
- **NO over-engineering** en escoger Resend tier USD 20/mes. Es el mínimo viable.
- **Riesgo over-engineering futuro**: implementar custom domain per tenant en MVP. Recomendación: posponer hasta tener tenant que lo demande explícitamente; arrancar con dominio plataforma.

## 8. Recomendaciones priorizadas

### DECISION FINAL recomendada

- **Adoptar Resend como sender transaccional primary** del platform.
- Plan inicial: **Pro USD 20/mes** (50K emails/mes incluidos).
- Dominio único plataforma: `mail.<dominio-platform>.co` con SPF + DKIM + DMARC en DNS.
- Sender único: `noreply@mail.<dominio-platform>.co` (con `Reply-To` opcional al tenant).
- Multi-tenant vía `tags={tenant_id, message_type}` (no subusers/sub-cuentas).
- Webhook handler en `services/api/routers/resend_webhook.py` consumiendo Svix events → persistir a `email_delivery_events` (nueva tabla) con `tenant_id`, `provider_message_id`, `event_type`, `occurred_at`.
- Configurar Supabase Auth → Custom SMTP apuntando a Resend SMTP (`smtp.resend.com:587`, user `resend`, pass `re_*` API key).

### Alternativas y triggers de migración

- **Migrar a SendGrid Pro** si:
  - Volumen >500K/mes Y necesitamos subusers nativos con dedicated IP per tenant.
  - Algún tenant enterprise exige IP dedicada propia con stats aisladas.
- **Migrar a Amazon SES** si:
  - Volumen >100K/mes Y costo es crítico (SES = ~10× más barato a volumen).
  - Acepto 2–3 días extra de setup (sandbox approval, IAM, Easy DKIM por dominio, suppression list custom, integración SNS/SQS para events).
- **Adoptar Postmark como segundo proveedor** si:
  - Necesitamos retention legal >90 días en provider (default Postmark Pro = 365 d) sin construirlo nosotros. Postmark tier Basic USD 15 ofrece 45 d.

### Excluidos

- **Sender.net**: no es candidato. Producto enfocado a marketing/automation/popups. La API transaccional no está documentada al nivel requerido para SAR Habeas Data o OTP.
- **Postmark como primary**: excelente producto pero overage 1.5× Resend (USD 1.30 vs 0.90/1.000) sin ventaja arquitectónica decisiva en MVP. Reservar como segunda opinión deliverability si Resend muestra problemas.

## 9. Validaciones humanas pendientes

### INTERVENCION HUMANA REQUERIDA — desambiguación "sender"

- **CRÍTICO**: confirmar con founder si "sender" en su lista (`render, sender, superbase, whatsapp, meta, messenger, instagram, wompi, mercado libre, telegram`) se refiere a:
  - (a) Sender.net específico (proveedor literal, marketing-first, LATAM).
  - (b) "El sender de email" genérico (placeholder pendiente de elegir proveedor).
- **RESPONSABLE**: founder.
- **PASOS**: pregunta directa en próxima sesión, una sola.
- **INSUMOS**: este dossier (TL;DR §1 + recomendación §8).
- **CRITERIO DE EXITO**: respuesta inequívoca; si (a), evaluar si Sender.net cubre uso transaccional o si reemplazar por Resend; si (b), proceder con Resend según §8.

### INTERVENCION HUMANA REQUERIDA — volumen estimado

- **PASOS**: estimar emails/mes proyectados año 1 (suma OTP login + notif tenant + notif interna + SAR). Define tier (free 3K vs Pro 50K vs Pro 100K).
- **CRITERIO DE EXITO**: rango con cota superior para dimensionar Pro vs Scale.

### INTERVENCION HUMANA REQUERIDA — política de dominio multi-tenant

- **PASOS**: decidir entre:
  1. Dominio único plataforma `noreply@mail.<platform>.co` para todos los tenants (MVP recomendado).
  2. Custom domain per tenant (cada tenant configura DNS) — feature plan premium futuro.
- **CRITERIO DE EXITO**: decisión documentada en `.context/03-rules.md` o ADR específico.

### INTERVENCION HUMANA REQUERIDA — formato SAR Habeas Data

- **RESPONSABLE**: DPO / Legal interno.
- **PASOS**: definir plantilla exacta de email respuesta SAR (acceso/rectificación/supresión Ley 1581 art. 8) — campos obligatorios, lenguaje formal, footer con contacto DPO, formato adjunto si aplica.
- **CRITERIO DE EXITO**: plantilla aprobada legal + integrada como template en Resend.

### INTERVENCION HUMANA REQUERIDA — DNS dominio principal

- **RESPONSABLE**: ops / founder con acceso a registrar.
- **PASOS**: agregar a DNS del dominio plataforma:
  - `TXT @ "v=spf1 include:amazonses.com include:_spf.resend.com -all"` (ajustar a proveedor final).
  - `CNAME resend._domainkey ...` (valores entregados por Resend dashboard al verificar dominio).
  - `TXT _dmarc "v=DMARC1; p=quarantine; rua=mailto:dmarc@<platform>.co; pct=100"`.
- **CRITERIO DE EXITO**: dominio en estado `verified` en Resend dashboard; envío de prueba a Gmail llega a inbox (no spam).

### VALIDAR EN DOCUMENTACION OFICIAL

- SendGrid Email API pricing exacto por tier — `https://www.twilio.com/en-us/sendgrid/email-api/pricing` no fue capturable en este pase (404 / redirect cadena).
- Resend rate limits específicos para webhook delivery y para batch endpoint.
- Postmark exactly cuántos message streams por server en cada tier.
- SES BYODKIM para multi-tenant: si BYODKIM es viable cuando el tenant aporta su key vs si Easy DKIM cubre todos los casos.

## 10. Veredicto final

**Go arquitectónico** sobre Resend.

- **Costo mensual estimado**: USD 20/mes (Pro 50K emails) en MVP. Crece a USD 35/mes (100K) o Scale USD 90 (100K nuevo tier) si volumen real lo exige.
- **Esfuerzo de integración**: 2–3 días-dev efectivos.
  - Día 1: alta cuenta Resend, verificación dominio (SPF/DKIM/DMARC), API key con scope `sending_access` restringida a dominio plataforma. Configurar Supabase Auth Custom SMTP. Smoke test magic link.
  - Día 2: cliente Python en `services/api/integrations/resend_client.py`, plantilla orden-creada / pago-recibido / despacho-enviado / SAR-response, helper `send_email(tenant_id, to, template_id, vars, tags)`.
  - Día 3: webhook handler `services/api/routers/resend_webhook.py` con verificación firma Svix, persistencia en tabla `email_delivery_events`, suppression list propia para destinatarios bounced/complained.
- **Riesgos identificados**:
  - **Deliverability inicial**: dominio nuevo sin warm-up. Mitigación — empezar con volumen bajo (notif internas), escalar gradualmente a notif cliente final, monitorear dashboard Resend bounces/complaints.
  - **Bounce handling crítico**: si webhook handler no marca suppressed correctamente, retry rápido degrada reputación. Mitigación — test E2E con `bounced@resend.dev`.
  - **Multi-tenant DKIM**: si en el futuro tenants exigen dominio propio, multiplicación de identidades verificadas y soporte DNS por tenant. Mitigación — dejar abstracción `from_domain` en helper desde día 1, aunque hoy hardcoded a dominio plataforma.
  - **Supabase Custom SMTP rate**: Resend Pro 5 req/s ≈ 18.000/h. Suficiente para magic link pero no para campañas masivas (lo que de todas formas no aplica a transactional).
  - **Vendor lock**: bajo. Migración a SendGrid o SES es ~1 día-dev (cambiar adapter); plantillas son texto + variables, no propietarias.

**RIESGO**: Si el founder confirma "sender" = Sender.net y exige usarlo por razones de relación comercial / pricing LATAM, este dossier requiere segunda iteración profundizando API transaccional Sender.net (no documentada públicamente al detalle requerido) antes de confirmar viabilidad para SAR / OTP.

**IMPACTO OPERATIVO**: habilitar email transaccional desbloquea (a) Supabase Custom SMTP — pre-requisito producción, (b) Habeas Data SAR — pre-requisito legal Ley 1581, (c) notificaciones tenant→cliente — funcionalidad de producto. Sin email transaccional la plataforma NO puede ir a producción cumpliendo norma colombiana.