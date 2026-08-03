> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Dossier Supabase — 2026-05-05

**Fecha**: 2026-05-05 · **Sesión**: investigación previa Sem 0 (J.0.0) · **Sin pruebas en vivo**.
**Fuente**: `https://supabase.com/docs/*` + `https://supabase.com/pricing` (público).

## 1. TL;DR

**Qué es**: Postgres-as-a-Service multi-capa (DB + Auth + Storage + Realtime + Edge Functions + Vault + Queues + Cron) construido sobre Postgres puro y open source. El producto es Postgres + extensiones + servicios alrededor, no un BaaS opaco.

**Modelo de negocio**: SaaS por consumo con 4 planes — Free $0, Pro $25, Team $599, Enterprise (custom). Sobre el plan Pro: overage por DB (~$0.125/GB), MAU ($0.00325), egress ($0.09/GB), Edge Functions ($2/M), Realtime connections ($10/1000), Realtime messages ($2.50/M).

**Costos para nuestro caso (Pro tier, 1 tenant medio, ~5k MAU)**: $25 base + $10 compute Micro. Probable rango operativo: **$35-80/mes**. SOC2/ISO27001 solo en Team ($599) — relevante para B2B.

URLs raíz: `https://supabase.com/docs` · `https://supabase.com/pricing`.

---

## 2. Hallazgos clave (10 dimensiones)

### 2.1 Auth
- **Métodos**: email+password, magic link, OTP (SMS+email), OAuth social, SAML SSO (solo Team/Enterprise), phone, anonymous. Doc: `/docs/guides/auth`.
- **JWT**: estructura `header.payload.signature`. Claims obligatorios: `iss, aud, exp, iat, sub, role, aal, session_id, email, phone, is_anonymous`. Opcionales: `app_metadata, user_metadata, amr, jti, nbf`. URL: `/docs/guides/auth/jwts`.
- **Custom claims**: vía `custom_access_token_hook` (Free/Pro). Permite inyectar `tenant_id` en `app_metadata`. URL: `/docs/guides/auth/auth-hooks/custom-access-token-hook`.
- **Sesiones**: access token default 1h, refresh token rotativo de un solo uso (con ventana de gracia 10s para SSR). Pro+ permite single-session-per-user, time-boxed sessions, inactivity timeouts. URL: `/docs/guides/auth/sessions`.
- **MFA**: TOTP (estándar) + Phone (Teams/Enterprise para "Advanced MFA"). AAL1 vs AAL2 codificado en JWT. **No hay recovery codes nativos** documentados — se gestiona vía `mfa.unenroll()`. URL: `/docs/guides/auth/auth-mfa`.
- **Password policy**: configurable (longitud mínima, complejidad: digits/lower/upper/symbols). HIBP breach detection requiere **Pro+**. URL: `/docs/guides/auth/password-security`.
- **Rate limits / brute force**: token bucket, ~30 burst. IP-based para verify, refresh, MFA challenges, anonymous sign-ins (no customizables). Customizables: OTP, signup, password reset (per-user). URL: `/docs/guides/auth/rate-limits`.
- **Email templates**: customizables vía dashboard. SMTP propio recomendado (built-in solo para project members). Default 30 msg/h con SMTP custom (ajustable). URL: `/docs/guides/auth/auth-smtp`.
- **Webhook events** (auth hooks): `before-user-created`, `send-email`, `send-sms`, `mfa-verification` (Team+), `password-verification` (Team+), `custom-access-token`. **No vi documentado evento `user.deleted`** — VALIDAR.
- **Signing keys**: rotación zero-downtime, asimétrico RS256/EC recomendado, JWKS endpoint `https://<project>.supabase.co/auth/v1/.well-known/jwks.json` cacheado 10min en edge. URL: `/docs/guides/auth/signing-keys`.

### 2.2 RLS
- **Funciones helper**: `auth.uid()`, `auth.jwt()`. **Crítico**: usar `raw_app_meta_data` (no editable por usuario) para autorización; `raw_user_meta_data` es editable y NO sirve para policies de seguridad. URL: `/docs/guides/database/postgres/row-level-security`.
- **Performance**: indexes sobre columnas usadas en policies (mejora 99.94%), envolver `(select auth.uid())` para caching (94.97%), siempre filtrar por tenant explícitamente en queries (94.74%), usar `security definer` para lookups (99.99%), siempre `TO authenticated` en `CREATE POLICY` (99.78% para anon).
- **Bypass**: `service_role` bypass total. Alternativa: rol con `bypassrls`.
- **Multi-tenant**: patrón documentado es `tenant_id` en JWT claim → policy compara con columna. Útil con `custom_access_token_hook`.
- **Testing**: doc menciona pgTAP, repos públicos `GaryAustin1/RLS-Performance` y discussion `supabase#14576`.

### 2.3 Realtime
- **3 primitivas**: Broadcast (mensajes low-latency cliente↔cliente), Presence (estado compartido), Postgres Changes (eventos INSERT/UPDATE/DELETE). URL: `/docs/guides/realtime`.
- **RLS-aware**: Postgres Changes evalúa RLS por evento por suscriptor. **Limitación crítica**: RLS NO se aplica a DELETE (Postgres no puede verificar acceso a registros borrados). DELETE no soporta filtros. URL: `/docs/guides/realtime/postgres-changes`.
- **Cuotas (`/docs/guides/realtime/quotas`)**:
  - Conexiones concurrentes: Free 200, Pro 500 (10k sin spend cap), Team/Ent 10k+
  - Messages/seg: Free 100, Pro 500 (2500 sin cap), Team/Ent 2500+
  - 100 channels/conexión (todos los planes)
  - Broadcast payload: 256KB Free → 3MB+ Enterprise
- **Errores documentados**: `too_many_channels`, `too_many_connections`, `too_many_joins`.
- **Performance**: Postgres Changes single-threaded — bottleneck a escala (autorización N suscriptores × M eventos).

### 2.4 Vault
- **Tecnología**: extensión Postgres con AEAD vía libsodium. Encryption key fuera de la DB. URL: `/docs/guides/database/vault`.
- **API**: `vault.create_secret()`, `vault.update_secret()`, view `vault.decrypted_secrets`.
- **Limitaciones**: no hay versionado/rotación nativo documentado; cualquiera con SELECT a la view ve secretos descifrados → **debe gestionarse con grants explícitos**.
- **Audit log**: NO documentado nativo. VALIDAR.
- **Límite secrets**: NO documentado. VALIDAR vs Edge Function secrets (límite 100, 48 KiB c/u).
- **Multi-tenant**: documentación NO da patrón explícito; el patrón actual del repo (`tenant_id/<provider>/<key>` como nombre) es heurística válida, pero el aislamiento real lo da quien tenga grant a la view.

### 2.5 Storage
- **Buckets**: 3 tipos — Files, Analytics (Iceberg), Vector. Public vs private. URL: `/docs/guides/storage`.
- **CDN**: 285+ ciudades, transformaciones on-the-fly (resize/compress).
- **File size**: Free 50MB, Pro/Team 500GB por archivo, Enterprise custom. Configurable per-bucket. URL: `/docs/guides/storage/uploads/file-limits`.
- **MIME restrictions**: per-bucket configurables (sin lista cerrada documentada).
- **Signed URLs**: `createSignedUrl(path, ttl_seconds)`. Default ejemplo 3600s. URL: `/docs/guides/storage/serving/downloads`.
- **RLS storage**: policies sobre `storage.objects`. Por default niega todo upload sin policy. Service key bypass.

### 2.6 pg_cron / Supabase Cron
- **Disponibilidad**: extensión Postgres en todos los planes paid (Free podría tener limitaciones por auto-pause).
- **Sintaxis**: cron estándar (segundo→anual). Manejable vía SQL o dashboard (`Integrations → Cron`).
- **Límites**: máx **8 jobs concurrentes recomendado**, máx **10 minutos** por ejecución. URL: `/docs/guides/cron`.
- **Logging**: tabla `cron.job_run_details`. Dashboard provee UI.
- **Integración**: SQL inline, funciones DB (zero latency), o HTTP a Edge Functions.
- **Estado actual del repo**: usado en `20260502000000_stock_reservations.sql` y `20260504000000_carts_abandonment_cron.sql`.

### 2.7 pgmq (Queues)
- **Disponibilidad**: extensión `pgmq` (Postgres 15.6.1.143+). Activable desde dashboard. URL: `/docs/guides/queues`.
- **Tipos**: Basic (logged), Unlogged (transient, posible pérdida), Partitioned (Coming Soon).
- **API expuesta a clientes vía `pgmq_public`**: `send`, `send_batch`, `read`, `pop`, `archive`, `delete`. Falta exponer create/drop (admin only). URL: `/docs/guides/queues/api`.
- **Visibility timeout**: parámetro `sleep_seconds` (oculta por N segundos tras lectura).
- **Retries**: NO hay retry/DLQ nativo documentado en Supabase. Lo que hay: `archive(queue, msg_id)` mueve a tabla de archivo. **Pattern de retry/DLQ es responsabilidad del consumidor** (re-`send` con backoff o queue DLQ separada).
- **Exactly-once**: la doc lo afirma "within visibility parameters" — efectivamente at-least-once con dedupe por visibility timeout.
- **Estado actual del repo**: ya activo en `20260420000004_whatsapp_outbound_queue.sql` con `pgmq.create('whatsapp_outbound_messages')`.
- **VALIDAR**: límite de queues por proyecto (no documentado).

### 2.8 Edge Functions / RPC
- **Runtime**: Deno + TypeScript (no Python). URL: `/docs/guides/functions`.
- **Limits** (`/docs/guides/functions/limits`):
  - Memoria: 256MB
  - Duración: Free 150s, Paid 400s
  - CPU time: 2s (sin async I/O)
  - Idle timeout: 150s
  - Bundle size: 20MB
  - Funciones por proyecto: Free 100, Pro 500, Team 1000, Enterprise unlimited
  - Secrets: 100/proyecto, 256 chars nombre, 48 KiB valor
- **Cold starts**: existen, recomendado para operaciones cortas e idempotentes.
- **Custom domains**: requiere domain custom para servir HTML.
- **Restricciones**: puertos mail bloqueados, sin Node APIs nativas, sin multithreading.
- **Cuándo usar qué**:
  - Edge Function: webhook receivers, integraciones HTTP, notifications
  - Database Functions (`plpgsql`): lógica transaccional, RLS-aware, zero network
  - PostgREST RPC: exponer funciones DB como HTTP a frontend con RLS

### 2.9 Backups + DR
- **Daily backups**: Pro 7d, Team 14d, Enterprise 30d. Free **sin backups gestionados**. URL: `/docs/guides/platform/backups`.
- **PITR**: add-on para Pro+/Team/Enterprise. RPO ~2 minutos (WAL cada 2min). Requiere Compute Small mínimo.
- **Restore**: causa downtime proporcional al tamaño DB. Custom roles requieren reset password post-restore.
- **Encryption at rest**: NO documentado en la guía de backups. VALIDAR.
- **Cross-region replication**: NO documentado como feature standard. Read Replicas sí soportan multi-región (ver 2.10).

### 2.10 Scaling, Performance, Pricing
- **Compute** (`/docs/guides/platform/compute-add-ons`):

| Tier | CPU | RAM | Max conn |
|---|---|---|---|
| Micro | 2-core ARM shared | 1GB | 60 |
| Small | 2-core ARM shared | 2GB | 90 |
| Medium | 2-core ARM shared | 4GB | 120 |
| Large | 2-core ARM dedicated | 8GB | 160 |
| XL | 4-core ARM dedicated | 16GB | 240 |

- **Pooling** (`/docs/guides/database/connecting-to-postgres`):
  - Direct (5432, IPv6 default): backends persistentes, migraciones
  - Supavisor session mode (5432): backends IPv4
  - Supavisor transaction mode (6543): serverless/edge — sin prepared statements
  - Dedicated PgBouncer (6543): paid, co-located
- **Read replicas** (`/docs/guides/platform/read-replicas`): geo-routing automático desde abr-2025. Solo SELECT vía REST GET. NO soporta Auth/Storage/Realtime aún. Plan availability NO documentada explícitamente — VALIDAR (típicamente Pro+).
- **Auto-pause**: Free pausa proyecto tras 1 semana inactivo, máx 2 proyectos activos.
- **Overage triggers Pro**: DB >8GB, MAU >100k, storage >100GB, egress >250GB, Edge Functions >2M, Realtime conn >500, Realtime msgs >5M.

---

## 3. Multi-tenant compatibility (B2B Colombia)

**SÍ es compatible**, con la arquitectura actual:
- `app_current_tenant()` + RLS + `service_role` con `scoped_table` ya alineado con patrón canónico Supabase.
- `custom_access_token_hook` permite poner `tenant_id` en JWT → RLS más limpio para frontend.
- Vault per-tenant con naming `<tenant>/<provider>/<key>` es funcional, pero falta capa de aislamiento real (rol que solo vea sus secretos).
- Realtime con RLS permite Inbox per-tenant correcto.
- Storage RLS permite buckets compartidos con namespacing por `tenant_id` en path.

**Riesgos B2B**:
- SOC2/ISO27001 solo en Team ($599/mes) — si los clientes lo exigen contractualmente, el escalón es Team obligatorio.
- SAML SSO solo Team+ — clientes enterprise lo van a pedir.
- DPA estándar en Pro+ (validar firmado con Supabase).

---

## 4. Limitaciones documentadas

- Realtime Postgres Changes single-threaded → bottleneck con muchos suscriptores.
- DELETE events Realtime no respetan RLS (entrega solo PK) y no soportan filtros.
- pg_cron máx 8 jobs concurrentes, 10min timeout por job.
- pgmq sin DLQ/retry nativo — hay que codificarlo.
- Edge Functions 256MB / 400s / Deno only (no Python).
- HIBP requiere Pro+, MFA Phone requiere Team+, SSO requiere Team+.
- Auth tokens >1h "discouraged" por seguridad; <5min "discouraged" por carga.
- Built-in SMTP solo project members → producción exige SMTP custom.
- Vault sin audit log nativo documentado.
- Backups: Free sin backups; Pro 7d; PITR es add-on extra.
- Read replicas no soportan Auth/Storage/Realtime aún.

---

## 5. Lo que tenemos vs lo que ofrece

Auditoría rápida del repo:

| Capacidad Supabase | Estado en repo | Observación |
|---|---|---|
| Postgres + RLS | USANDO | `app_current_tenant()` + scoped_table OK |
| Auth | USANDO parcial | Posiblemente sin `custom_access_token_hook` (no encontré config) |
| Realtime Postgres Changes | USANDO | Inbox tenant console (`apps/web/app/dashboard/inbox/page.tsx`) |
| Vault | USANDO | `services/api/vault_helper.py` + `integrations.py`, `meli_client.py` |
| pg_cron | USANDO | `stock_reservations`, `carts_abandonment_cron` |
| pgmq | USANDO | `whatsapp_outbound_messages` |
| Storage | NO confirmado en grep | VALIDAR — habrá uso de imágenes/adjuntos |
| Edge Functions | NO USANDO | Toda la lógica está en FastAPI (Render) |
| MFA TOTP | NO confirmado | Probablemente NO activo |
| HIBP password breach | NO confirmado | Probablemente NO activo |
| Auth Hooks (send_email/sms) | NO confirmado | Probablemente NO activo |
| Read replicas | NO USANDO | |
| PITR | NO confirmado | VALIDAR estado contratado |
| Custom SMTP | NO confirmado | Crítico para producción |
| Signing keys asymmetric | NO confirmado | VALIDAR — default es HS256 en proyectos viejos |

Archivos relevantes auditados:
- `services/api/vault_helper.py`
- `services/api/dependencies/auth.py`
- `services/api/main.py`
- `supabase/migrations/20260420000004_whatsapp_outbound_queue.sql`
- `supabase/migrations/20260502000000_stock_reservations.sql`
- `supabase/migrations/20260504000000_carts_abandonment_cron.sql`

---

## 6. Gaps críticos priorizados

### P0 (seguridad / compliance / runtime)
1. **MFA TOTP para tenant admins**. B2B Colombia + Habeas Data 1581 lo justifica. Esfuerzo: 1-2 días (UI + recovery flow custom).
2. **Custom SMTP en producción**. 30 msg/h built-in es insuficiente y solo project members. Esfuerzo: 0.5d (Resend/SES + DKIM/DMARC/SPF).
3. **Asymmetric JWT signing keys (RS256)**. Permite validar JWT en FastAPI sin tocar Auth server, vía JWKS. Esfuerzo: 1d (rotación segura + update FastAPI verifier).
4. **PITR confirmado**. Si no está activo, contratarlo. RPO 2min vs 24h hace diferencia regulatoria.
5. **HIBP breach detection**. Activable en dashboard Pro+. Esfuerzo: 5min toggle.

### P1 (robustez)
6. **Auth Hooks `before-user-created` + `custom_access_token`** para inyectar `tenant_id` en JWT. Simplifica RLS y evita roundtrip a `tenant_users`. Esfuerzo: 1-2d.
7. **DLQ pattern para pgmq**. Hoy `whatsapp_outbound_messages` no tiene DLQ. Esfuerzo: 1d (queue secundaria + max_attempts en payload).
8. **Vault audit / rol restringido**. Crear rol `tenant_secrets_reader` con grants per-schema/path. Esfuerzo: 1-2d.
9. **Storage RLS policies per-tenant** si se usan adjuntos/imágenes. Esfuerzo: 0.5d/bucket.

### P2 (escalado)
10. **Read replica para queries analíticas** (reportes, exports Habeas Data). Esfuerzo: setup 1h + adaptar clients.
11. **pg_cron job count auditing**. Validar que no superamos 8 jobs concurrentes con la suma de todos los crons multi-tenant.
12. **Realtime quota monitoring**. 500 conn concurrentes Pro alcanza para ~50 tenants activos simultáneos sin overage.

### P3 (futuro)
13. **Edge Functions para webhooks de baja latencia** (Wompi, Meta). Hoy todo va a FastAPI/Render. Migración parcial reduciría latencia y costo Render. Esfuerzo: alto (reescribir en Deno).
14. **Read replicas multi-región** si entramos a México/Chile.
15. **SAML SSO** cuando algún cliente lo pida (requiere upgrade Team).

---

## 7. ¿Sobre-ingeniando o sub-aprovechando?

**Sub-aprovechando** en estos puntos:
- Lógica que vive en FastAPI/Render podría vivir en Database Functions con RLS-aware (zero latency, zero cost compute extra).
- Auth Hooks no usados → RLS más complejo de lo necesario.
- MFA, HIBP, signing keys asimétricas: capacidades incluidas en plan que no se aprovechan.
- Read replicas para reportes — pagamos compute primario para queries analíticas.

**Sobre-ingeniando** marginal:
- Connector WhatsApp como servicio propio cuando podría ser Edge Function + pgmq. Pero ya está construido y en producción → mantener.
- `service_role` bypassing RLS en routers es decisión correcta documentada, no over-engineering.

**Veredicto general**: el stack actual respeta principios canónicos Supabase, pero deja sobre la mesa **3-4 capacidades de seguridad incluidas en el plan** que ya pagamos.

---

## 8. Recomendaciones priorizadas (esfuerzo concreto)

| # | Acción | Esfuerzo | Plan req. | Impacto |
|---|---|---|---|---|
| 1 | Habilitar HIBP password breach detection | 5min | Pro | Seguridad |
| 2 | Custom SMTP (Resend/SES) + DKIM/DMARC/SPF | 0.5d | Pro | Producción |
| 3 | Migrar a asymmetric JWT signing (RS256) | 1d | Pro | Seguridad + perf |
| 4 | Activar/confirmar PITR | 1h | Pro+addon | Compliance |
| 5 | MFA TOTP para tenant admins | 1-2d | Pro | Compliance |
| 6 | `custom_access_token_hook` con `tenant_id` | 1-2d | Pro | RLS simpler |
| 7 | DLQ pattern en pgmq queues | 1d | Pro | Robustez |
| 8 | Vault: rol restringido + naming audit | 1-2d | Pro | Seguridad |
| 9 | Storage RLS policies por tenant | 0.5d/bucket | Pro | Seguridad |
| 10 | Read replica para reportes | 0.5d | Pro | Perf |

---

## 9. Validaciones humanas pendientes

INTERVENCION HUMANA REQUERIDA — preguntas para Supabase Sales / dashboard:

1. ¿El proyecto `***SUPABASE_PROJECT_REF_REDACTED***` tiene PITR activo? (consola → Database → Backups).
2. Plan actual contratado: ¿Free, Pro, Team? ¿Compute size?
3. ¿Vault tiene audit log nativo o se construye con triggers? Sales response.
4. ¿Cross-region replication disponible en plan Pro o requiere Enterprise? Sales response.
5. ¿Read replicas disponibles en Pro o requieren Team? (no documentado claramente).
6. ¿DPA firmado con Supabase para Habeas Data 1581 / GDPR? — consultar legal.
7. ¿Existen límites no documentados de queues pgmq por proyecto? (Sales).
8. ¿Cuál es el comportamiento exacto de `auto-pause` si nuestro Free tier estuviera asociado a algún sub-proyecto?
9. ¿Hay límite documentado de secrets en Vault por proyecto? (no encontrado en docs).
10. ¿Dropbox de eventos `user.deleted` para Habeas Data Article 17 — existe webhook nativo o hay que pollear `auth.users`?

---

## 10. Veredicto final go/no-go

**GO arquitectónico — confirmado para fase actual y siguientes 12-18 meses.**

Razones:
- Stack canónico ya validado (RLS multi-tenant, Vault, Realtime, pg_cron, pgmq todos en uso).
- Pricing predecible bajo overage controlados (DB y MAU son los disparadores principales).
- Compliance path claro: Habeas Data certificado + SOC2/ISO27001 disponibles si se requieren contractualmente (paso a Team).
- Capacidades incluidas en plan suficientes para roadmap; no detecto bloqueante arquitectónico.

**Condicionantes no negociables** antes de pasar a producción multi-cliente real:
- Custom SMTP (P0 #2) — built-in es insuficiente.
- PITR contratado o backup strategy alternativa.
- Asymmetric JWT signing.
- MFA al menos para tenant owners.

**Cuándo evaluar salida**:
- Si superamos 100k MAU sostenidos y >250GB egress mes a mes (overage Pro empieza a pesar) — re-evaluar Team o Enterprise commitment.
- Si exigen residencia de datos en Colombia (Supabase no tiene región CO documentada — VALIDAR).
- Si Realtime Postgres Changes se convierte en bottleneck por single-thread — migrar Inbox a Broadcast o sistema externo.

**DECISION FINAL**: continuar con Supabase, ejecutar P0 + P1 antes del próximo lanzamiento.

**VALIDAR EN DOCUMENTACION OFICIAL**: residencia de datos en LATAM, Vault audit log, límites de queues por proyecto, evento `user.deleted`.

**RIESGO**: dependencia fuerte de Postgres extensions (pgmq/pg_cron). Mitigación: lógica está en SQL portable, salida a otro Postgres es viable con esfuerzo medio.

**IMPACTO OPERATIVO**: ninguno disruptivo en el corto plazo si se ejecutan los P0.