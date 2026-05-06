# Dossier Render — 2026-05-05

**Fecha**: 2026-05-05 · **Sesión**: investigación previa Sem 0 (J.0.0) · **Sin pruebas en vivo**.
**Fuente**: `https://render.com/docs/*` + `https://render.com/pricing` (público).
**Servicios live actuales**: `web` (Next.js 14), `api` (FastAPI), `connector-whatsapp` (FastAPI), `ai-orchestrator` (FastAPI). Todos en Free tier.

---

## 1. TL;DR ejecutivo

**Qué es**: PaaS opinionado tipo Heroku-moderno. Empaqueta Web Services, Private Services, Background Workers, Cron Jobs, Postgres administrado, Key Value (Valkey/Redis), Static Sites y Blueprints (IaC) detrás de un dashboard único, con TLS automático, deploys zero-downtime y red privada por workspace+región.

**Modelo de negocio**: workspace plans (Hobby/Pro/Scale/Enterprise) que desbloquean features (autoscaling, preview envs, retención de logs, custom domains incluidos, soporte) **+ compute prorrateado por segundo** según el instance type elegido por servicio. Es decir: pagas plan de workspace **y** el size de cada servicio.

**Free tier es bloqueante para producción** (confirmado, doc oficial):
- Sleep tras `15 minutes without receiving any inbound traffic`. Despertar tarda `about one minute` (cold start de 60s — letal para webhook Meta/Wompi). URL: `/docs/free`.
- Cuota `750 Free instance hours` por workspace/mes; agotadas → `Render suspends all of your Free web services until the start of the next month`. URL: `/docs/free`.
- Filesystem efímero, Postgres free `expire 30 days after creation` (gracia 14d), Key Value free sin persistencia.
- Sin SLA, sin autoscaling, sin preview envs, sin Pre-deploy command, sin Private Links.

**Recomendación de tier para Commerce Ops Platform (5–20 tenants Colombia)**:
- Workspace **Pro** (mínimo) — desbloquea autoscaling, preview envs, HTTP request logs, retención 14d, Private Links, environment isolation.
- Compute por servicio: `Starter` para `web` (estático SSR liviano), `Standard` para `api` y `connector-whatsapp` (críticos, SLA-sensible), `Standard` o `Pro` para `ai-orchestrator` (latencia LLM + carga variable).
- Región **Virginia (us-east)** — la más cercana a Colombia entre las 5 disponibles. **No hay región LATAM**.
- Costo estimado producción: **USD 130–280/mes** (workspace Pro + 4 services + Postgres no aplica porque seguimos en Supabase). Ver §10.

**URLs raíz**: `https://render.com/docs` · `https://render.com/pricing`.

---

## 2. Hallazgos clave

### 2.1 Instance types y planes de servicio
La doc de Blueprint Spec lista los siguientes `plan` válidos para servicios:
`free`, `starter`, `standard`, `pro`, `pro plus`, `pro max`, `pro ultra` (varía por service type). URL: `/docs/blueprint-spec`.

⚠️ **Las páginas `/docs/instance-types` y los detalles de pricing por instance type no están públicamente accesibles vía URLs estables** — la página `/pricing` carga contenido dinámico que WebFetch no resuelve completo. Cifras precisas (RAM/CPU/USD) **deben validarse con el dashboard o Render Sales** antes de cualquier compromiso. Ver §9.

### 2.2 Regiones disponibles
5 regiones, **ninguna en Latinoamérica**. URL: `/docs/regions`.
- Oregon, USA (us-west)
- Ohio, USA (us-east-2)
- **Virginia, USA (us-east)** — la más cercana a Colombia
- Frankfurt, Germany (eu-central)
- Singapore (ap-southeast)

`Render doesn't currently support changing the region for an existing service or database` — migrar región implica recrear servicios. URL: `/docs/regions`.

### 2.3 Latencia desde Colombia
🔴 **No documentado oficialmente por Render**. Estimación pública (Cloudflare/AWS RTT Colombia↔Virginia): ~80–110 ms RTT. Crítico para:
- Webhooks WhatsApp Meta (timeout ~10s, ok).
- Wompi callbacks (sin timeout estricto, ok).
- Frontend a usuarios COL: depende de CDN — Render **no tiene CDN nativo documentado** (ver §6).

### 2.4 Networking
- **Private Network**: `Render services in the same region can communicate over their shared private network, without traversing the public internet`. Hostnames internos estables. URL: `/docs/private-network`.
- Aislamiento por workspace+región. **No VPC peering** (no documentado). Sí hay `Private Links` (Pro+) hacia AWS para Snowflake / MongoDB Atlas.
- **Static outbound IPs**: ❌ **No nativos**. La doc dice literal: `Interested in unique, Render-native static IPs for your workspace? Please upvote this feature request`. IPs salientes son **CIDR compartidos por región** (rangos publicados). Recomienda QuotaGuard como workaround. URL: `/docs/static-outbound-ip-addresses`.
- HTTP/2 ✅, WebSockets ✅, IPv4 only (`Remove any AAAA records from your domain`). URL: `/docs/custom-domains`.
- **HTTP request timeout máximo**: ⚠️ **no documentado** explícitamente. Heurística: el timeout efectivo del proxy Render no aparece en `/docs/web-services` ni en troubleshooting; se asume 100–120s por convención Cloudflare upstream pero **VALIDAR**.

### 2.5 Runtimes nativos
`Node.js/Bun, Python, Ruby, Go, Rust, Elixir`. Build toolkit incluye `Git, curl, wget, jq, PostgreSQL client, ImageMagick, FFmpeg`. Soporte Docker para custom images. URL: `/docs/native-runtimes`.

Port binding obligatorio: `0.0.0.0:$PORT` (default 10000). Reservados: 18012, 18013, 19099. URL: `/docs/web-services`.

### 2.6 Health checks
Configurables por path. Cada `few seconds`. Timeout 5s. Acción de fallo: 15s consecutivos → de-routing temporal; 60s consecutivos → `automatically restarts the instance`. Deploy se cancela si todas las instancias no pasan health en 15 minutos. URL: `/docs/health-checks`.

### 2.7 Deploys
Zero-downtime por defecto (excepto servicios con persistent disk — incompatible con escalado horizontal). Build cap **120 min**, pre-deploy 30 min, start 15 min. Pre-deploy command **solo en paid tiers**. Deploy hooks via URL única GET/POST. URL: `/docs/deploys`.

### 2.8 DDoS y TLS
DDoS protection: `free distributed denial-of-service protection to every application` vía infraestructura Cloudflare en el edge. URL: `/docs/ddos-protection`. **WAF nativo NO documentado**, **bot protection NO documentado**, **rate limiting nativo NO documentado** — gaps críticos para B2B Colombia (ver §6).

TLS: certificados gestionados automáticamente, incluyendo wildcards. HTTP→HTTPS redirect automático. URL: `/docs/custom-domains`.

---

## 3. Multi-tenant compatibility

### 3.1 Workspaces
Container top-level de billing y miembros. Un workspace = un plan (Hobby/Pro/Scale/Enterprise). Página `/docs/workspaces` da 404 — la información está distribuida en `/docs/free` (cuotas por workspace) y `/pricing` (tiers).

### 3.2 Projects & Environments
URL: `/docs/projects-environments`. Cada **project** agrupa servicios+DBs por aplicación. Cada project contiene 1+ **environments** (ej: `production`, `staging`).
- `Network isolation`: si activas, los servicios dentro del environment se comunican entre sí pero **no pueden alcanzar servicios fuera del mismo environment** vía la red privada. ✅ útil para aislar prod vs staging.
- **Protected environments**: solo Admin puede hacer acciones destructivas (eliminar, suspender, ver env vars).

### 3.3 Estrategias multi-tenant evaluadas
| Estrategia | Soporta Render | Notas |
|---|---|---|
| **Un único deployment, tenancy lógico por DB (`tenant_id`)** | ✅ | Es nuestro patrón actual. Render trata todos los tenants con la misma flota — autoscaling absorbe carga agregada. |
| **Un service por tenant** | ⚠️ Costoso | Cada service paga compute. 20 tenants × 4 services × `starter` ≈ explosión de costo. **No recomendado**. |
| **Un environment por tenant** | ⚠️ Posible | Network isolation entre envs. Pero cada env multiplica recursos. Solo justificable para tenants enterprise dedicados. |
| **Un project por tenant** | ⚠️ Posible | Misma economía que un env por tenant. Útil si necesitas billing separado o RBAC por tenant cliente. |

**Veredicto**: para 5–20 tenants, **un único deployment con tenancy lógica** (igual que Supabase con RLS por `tenant_id`). Reservar dedicated environments solo para tenants enterprise que paguen un tier especial.

### 3.4 Secrets per-tenant
- Las **environment variables son por servicio** o vía **Environment Groups** (compartidos entre N servicios). URL: `/docs/configure-environment-variables`.
- **Secret files** (paths `/etc/secrets/<filename>`) con cap combinado de `1 MB` por servicio o env group.
- ❌ **NO hay primitiva nativa "secret per tenant"**. El patrón debe seguir siendo Supabase Vault + lookup en runtime con `tenant_id` (igual que hoy). Render solo gestiona secrets del **deployment**, no del **dominio multi-tenant**.

### 3.5 Custom domains per-tenant
URL: `/docs/custom-domains`.
- Hobby: 2 dominios. Pro: 15. Scale: 25. **Adicional: $0.25/dominio/mes**.
- ✅ **Wildcard domains soportados** (`*.example.org`) con 3 CNAME records (`*`, `_acme-challenge`, `_cf-custom-hostname`).
- TLS automático para wildcards.
- Para SaaS multi-tenant donde cada cliente quiere `cliente.commerceops.co`: usar **wildcard** + un único registro DNS, o resolver cada subdominio del lado app router. ✅ viable.

---

## 4. Limitaciones documentadas

### 4.1 Free tier (deal-breakers)
- Sleep `15 minutes without receiving any inbound traffic`. Wake `about one minute`. URL: `/docs/free`.
- Cuota `750 Free instance hours` por workspace/mes — global, no por servicio. Agotada = todo suspendido.
- Filesystem efímero (no relevante para nosotros, no usamos local FS).
- Postgres free `expire 30 days after creation` (no relevante, usamos Supabase).
- Sin SLA, sin autoscaling, sin preview envs, sin Pre-deploy command, sin Private Links, sin retención de logs > 7d.

### 4.2 Logs
URL: `/docs/logging`.
- Retención: **Hobby 7d / Pro 14d / Scale,Enterprise 30d**.
- Rate limit: `a maximum of 6,000 application-generated log lines per minute` por instancia. Excedente se descarta silenciosamente — **gap operativo si tenemos picos de debug**.
- HTTP request logs solo en **Pro+**.
- Búsqueda con wildcards y regex RE2. Filter por `level, instance, method, status_code, host, path`.

### 4.3 Build
URL: `/docs/deploys`.
- Build cap: **120 min**.
- Pre-deploy: **30 min** (solo paid).
- Start: **15 min** (deploy se cancela si no pasa health en este tiempo).
- Pipeline minutes incluidos varían por plan (no encontrados en doc pública — VALIDAR).

### 4.4 Cron jobs
URL: `/docs/cron-jobs`.
- Sintaxis cron estándar UTC. Garantía: `at most one run of a given cron job is active at a given time`.
- **Max execution: 12 horas** por run.
- Billing: prorrateado por segundo + `mínimo $1/mes por cron job`.
- ⚠️ **Retry policy NO documentada explícitamente** — si una ejecución falla, NO hay retry automático documentado. Si necesitamos retry hay que codificarlo o usar Workflows (beta).

### 4.5 Persistent disks
URL: `/docs/disks`.
- Solo paid services. Mismos SSDs que Postgres/Key Value. Encriptados at-rest.
- Snapshots automáticos cada 24h, retención `at least 7 days`.
- ❌ **No reduce size**. ❌ Bloquea zero-downtime deploys. ❌ No soporta multi-instance scaling. ❌ No cron jobs.
- Para Commerce Ops: **no usamos disks** (Supabase Storage para archivos), sin riesgo.

### 4.6 Request/payload limits
- **Request timeout HTTP máximo**: ⚠️ **no documentado oficialmente**. La única referencia es troubleshooting Node.js (`server.keepAliveTimeout` configurable hasta 120s). Asumir cap edge ≈ 100s por convención Cloudflare. **VALIDAR con Render Sales**.
- **Max payload size**: ⚠️ **no documentado**.
- WebSockets: ✅ soportados, sin límite de duración documentado.

### 4.7 Outbound static IP
❌ **No nativo**. Requiere proxy externo (QuotaGuard u otro). URL: `/docs/static-outbound-ip-addresses`.

---

## 5. Lo que tenemos vs lo que ofrece

Auditoría de los 4 servicios actuales (`web`, `api`, `connector-whatsapp`, `ai-orchestrator`) contra capacidades Render:

| Capacidad | Doc URL | Disponible | Usándola | Acción |
|---|---|---|---|---|
| Autoscaling CPU/mem | `/docs/scaling` | Pro+ | ❌ Free no permite | P0: subir a Pro y configurar |
| Zero-downtime deploys | `/docs/deploys` | All paid | ⚠️ implícito free, sin garantía | P1: confirmar al subir |
| Preview environments | `/docs/preview-environments` | Pro+ | ❌ no usados | P2: activar para PRs |
| Health checks | `/docs/health-checks` | All | ⚠️ parcial — no todos servicios | P0: añadir `healthCheckPath` a 4 servicios |
| Blueprints (`render.yaml`) | `/docs/blueprint-spec` | All | ❌ no usado, deploys manuales | P1: codificar IaC |
| Environment Groups | `/docs/configure-environment-variables` | All | ❓ verificar | P1: consolidar shared envs |
| Private Network | `/docs/private-network` | All paid (Pro para isolation) | ⚠️ no validado | P1: routing api↔orch interno |
| Custom domains | `/docs/custom-domains` | All paid | ❓ producción aún sin custom | P0: provisionar `*.commerceops.co` |
| Persistent disks | `/docs/disks` | All paid | ❌ no aplica | — |
| Background workers | `/docs/background-workers` | All paid | ❌ ai-orchestrator es web service | P3: evaluar reclasificar a worker |
| Cron jobs | `/docs/cron-jobs` | All paid | ❓ ¿lo usamos? — actualmente Supabase pg_cron | — (Supabase ya cubre) |
| Datadog integration | `/docs/datadog` | All paid | ❌ no integrado | P2: monitoring |
| DDoS protection | `/docs/ddos-protection` | All (free) | ✅ activo | — |

**Hallazgos**:
- **Sub-aprovechamos** Blueprints (IaC), preview envs, autoscaling y env groups.
- **No sobre-ingenierizamos** — los 4 services tienen separación natural (web/api/connector/orquestador) que Render encaja bien.
- `ai-orchestrator` actualmente es Web Service, pero conceptualmente podría ser Background Worker si su único trigger fueran colas; hoy expone HTTP — **dejarlo como web service**.

---

## 6. Gaps críticos (P0/P1/P2/P3)

### 🔴 P0 — Bloqueantes producción
1. **Free tier sleep + cold start 60s** → migrar a paid antes de onboarding clientes reales. URL: `/docs/free`.
2. **Sin región LATAM** → latencia ~80–110ms desde Colombia. No hay solución dentro de Render. Mitigar con CDN externo (Cloudflare) para frontend; aceptar latencia para backend. URL: `/docs/regions`.
3. **Health checks no configurados en todos los servicios** → riesgo de deploy con instancia rota sin detección. URL: `/docs/health-checks`.
4. **Sin custom domain en producción** → riesgo de bloqueo en `*.onrender.com` (cuestionable para clientes B2B).

### 🟠 P1 — Alto impacto pre-launch
5. **Sin static outbound IPs** → Wompi/Meta/Envia podrían pedir allowlist de IPs en planes empresariales. Render no los provee nativo. Workaround: QuotaGuard ($) o aceptar el riesgo si los proveedores aceptan CIDR. URL: `/docs/static-outbound-ip-addresses`. **VALIDAR con Wompi/Envia/Meta si aceptan rangos CIDR**.
6. **Sin WAF nativo** → no hay reglas L7 (SQLi, XSS) ni rate limiting por IP nativo. Dependemos de DDoS L3/L4 Cloudflare upstream. Mitigación: Cloudflare frontend con WAF Pro ($20/mes), o codificar rate limiting en FastAPI middleware. URL: `/docs/ddos-protection`.
7. **Sin IaC** → toda config en dashboard, no versionada. Migrar a `render.yaml`. URL: `/docs/blueprint-spec`.
8. **Logs retención 14d Pro** → para auditoría/forense necesitamos > 30d. Stream a Datadog o S3. URL: `/docs/logging`.

### 🟡 P2 — Mejoras operativas
9. **Sin monitoring nativo** (más allá de logs/notifications básicas). Integrar Datadog ($31/host/mes) o New Relic. URL: `/docs/datadog`.
10. **Preview environments no activados** → riesgo de regresión sin smoke test pre-merge. Activar al subir a Pro. URL: `/docs/preview-environments`.
11. **Cron retry policy no documentada** → si usamos Render cron en futuro, codificar idempotencia y retry en el script.
12. **CDN nativo no documentado** → frontend `web` (Next.js) sirve estáticos sin edge caching nativo Render. Resolver con Cloudflare delante de `web.onrender.com`.

### 🟢 P3 — Backlog / nice-to-have
13. **Background Workers vs Web Services para ai-orchestrator** — evaluar si el orquestador sería más eficiente como worker puro consumiendo cola.
14. **Workflows (beta)** — Render promueve Workflows para `managed queuing, automatic retries, and rapid spin-up`. Evaluar madurez. URL: `/docs/background-workers`.
15. **VPC peering / Private Link a AWS** — si llegamos a Snowflake/Mongo. Hoy no aplica.

---

## 7. ¿Estamos sobre-ingeniando o sub-aprovechando?

### 7.1 Cuatro servicios separados — ¿es correcto?
✅ **Sí, mantener la separación**. Justificación:
- `web` (Next.js SSR) tiene perfil de carga distinto (frontend, sesiones humanas) vs `api` (FastAPI, llamadas backend) vs `connector-whatsapp` (webhooks Meta, latency-critical) vs `ai-orchestrator` (LLM calls, CPU-bound, latency tolerante).
- Cada uno se beneficia de **autoscaling independiente** — concentrar todo en un mono-service desperdicia compute en horas valle.
- Falla aislada: si el orquestador se cae, webhooks no se pierden (cola intermedia).
- Render cobra prorrateado por segundo: 4 services × Starter ≈ similar a 1 service × Standard pero con mejor aislamiento.

### 7.2 ¿Render Postgres en lugar de Supabase?
❌ **No migrar**. Supabase ya provee Auth + RLS + Realtime + Storage + pg_cron + pgmq + Vault, todo lo cual habría que reconstruir sobre Render Postgres + servicios externos. El dossier de Supabase ya cierra esta decisión.

### 7.3 ¿Background workers nativos Render?
❓ **Evaluar fase 13**. Hoy Supabase pgmq + ai-orchestrator FastAPI cumple. Si la cola crece > 1000 msg/s, considerar mover a Render Background Worker dedicado consumiendo Key Value/pgmq.

### 7.4 ¿Cron jobs nativos Render?
❌ **No**. Supabase pg_cron + Edge Functions ya cubre el caso (carrito abandonado, stock reservations). Render cron añadiría costo ($1/mes mínimo) sin valor extra dado nuestro stack.

### 7.5 Sub-aprovechamiento confirmado
- **IaC con `render.yaml`** — manualidad innecesaria.
- **Preview environments** — coste cero adicional en Pro, falta de uso es desperdicio.
- **Environment Groups** — probable duplicación de env vars entre servicios (a verificar).
- **Datadog integration** — observabilidad reactiva, dependemos de logs+notifications básicas.

---

## 8. Recomendaciones priorizadas

### Sem 0 (pre-launch, **obligatorias antes de onboarding**)
1. ✅ **Migrar workspace a Pro** — desbloquea autoscaling, preview envs, HTTP request logs, retención 14d, network isolation.
2. ✅ **Subir 4 servicios a `Starter` mínimo** (`web`, `connector-whatsapp` críticos a `Standard`). Validar dimensionamiento real con métricas de carga.
3. ✅ **Configurar `healthCheckPath` en los 4 servicios** vía dashboard o `render.yaml`.
4. ✅ **Migrar a IaC**: crear `render.yaml` raíz declarando los 4 servicios + region `virginia` + plans + env groups.
5. ✅ **Provisionar custom domain** `*.commerceops.co` con wildcard. 3 CNAMEs según `/docs/custom-domains`.
6. ✅ **Cloudflare como frontend** (proxy) → suma WAF, rate limiting, CDN edge para assets, bot protection. Render queda detrás como origin.

### Sem 1 (operación)
7. ⚙️ **Autoscaling Pro** en `api` y `ai-orchestrator` (min 1, max 3). Target CPU 70% / memory 80%.
8. ⚙️ **Datadog integration** — stream logs + métricas + APM Python (FastAPI). Costo ~USD 31/host/mes.
9. ⚙️ **Preview environments automáticos** para PRs — Smoke test antes de merge.
10. ⚙️ **Environment Groups** consolidar `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE`, `WOMPI_PUBLIC_KEY`, etc. compartidos. Reduce drift.
11. ⚙️ **Network isolation** activar entre `production` env y futuros `staging`/`preview`.

### Sem 2+ (sostenibilidad)
12. 🛠️ **Validar con Wompi/Meta/Envia** si aceptan los CIDR rangos de Render Virginia, o requerimos QuotaGuard.
13. 🛠️ **Stream logs a S3 o Logtail** para retención > 30d (auditoría Habeas Data Ley 1581).
14. 🛠️ **Webhook notifications** Render → Slack canal `#ops` para deploy failures.
15. 🛠️ **Evaluar Render Workflows beta** cuando carga de cola justifique.

---

## 9. Validaciones humanas pendientes

> INTERVENCION HUMANA REQUERIDA
> RESPONSABLE: Founder + AI Architect
> CRITERIO DE EXITO: documento firmado con respuestas oficiales de Render Sales antes de migrar Free→Pro.

Preguntas a Render (`sales@render.com` o chat in-dashboard):

1. **¿Plan empresarial con región LATAM (Brasil/México)?** — la doc lista solo 5 regiones; preguntar roadmap. Crítico para latencia COL.
2. **¿Static outbound IPs disponibles en plan Enterprise?** — `/docs/static-outbound-ip-addresses` dice "feature request"; preguntar si ya existe en Enterprise.
3. **¿SLA documentado con uptime guarantee y service credits?** — la URL `/docs/sla` da 404 público; preguntar si existe en Pro/Scale.
4. **¿Descuentos por volumen / commitment anual?** — para 4 servicios + workspace Pro vs Scale.
5. **¿Pricing exacto de instance types?** — `Starter`, `Standard`, `Pro`, `Pro Plus`, `Pro Max`, `Pro Ultra`: USD/mes, RAM, vCPU. La página `/pricing` no resuelve cifras vía WebFetch — confirmar en dashboard live al crear servicio.
6. **¿Cap real de HTTP request timeout?** — no documentado; afecta diseño de jobs largos en `ai-orchestrator`.
7. **¿Pipeline build minutes incluidos por plan?** — no documentado claramente.
8. **¿Cron retry policy nativa?** — confirmar si hay retry automático o si depende del script.
9. **¿WAF / bot protection / rate limiting nativos?** — la doc menciona DDoS L3/L4 Cloudflare; pregunta explícita por L7.
10. **¿Render Workflows beta — disponibilidad GA y pricing?** — alternativa a Background Workers manuales.

---

## 10. Veredicto final

### Decisión arquitectónica: ✅ **GO con Render Pro**, con condiciones

**Mantener Render** como PaaS productivo. Razones:
- Stack actual (4 services FastAPI/Next) calza nativamente — runtimes nativos cubren el 100% de nuestro código.
- Costo razonable: USD 130–280/mes para producción multi-tenant de 5–20 tenants.
- DX excelente: deploys automáticos por git push, dashboard claro, Blueprints IaC.
- DDoS Cloudflare upstream "gratis", TLS automático, private networking entre servicios.

**Condiciones para go-live**:
1. **No usar Free tier en producción** (sleep + sin SLA = inaceptable).
2. **Cloudflare obligatorio frontend** — cubre los gaps WAF, CDN, rate limiting, bot protection que Render no provee nativos.
3. **Aceptar latencia LATAM ~80–110ms RTT desde Colombia hacia Virginia** — sin alternativa Render-nativa.
4. **Plan de fuga**: tener `render.yaml` y Dockerfiles que permitan migrar a Fly.io o AWS ECS en < 1 semana si Render falla en SLA o sube precios drásticamente.

### Costo total mensual estimado para producción (5–20 tenants)

| Componente | Plan | USD/mes (estimado) |
|---|---|---|
| Workspace Render Pro | Pro | ~25–35 base (validar con Sales) |
| `web` (Next.js SSR) | Starter o Standard | 7–25 |
| `api` (FastAPI) | Standard | 25–50 |
| `connector-whatsapp` (FastAPI) | Standard | 25–50 |
| `ai-orchestrator` (FastAPI) | Standard o Pro | 25–85 |
| Custom domains adicionales (15+ wildcard) | $0.25 c/u | 0–10 |
| Datadog integration (1 host) | — | ~31 |
| Cloudflare WAF Pro (frontend) | — | ~20 |
| QuotaGuard static IP (si requerido) | Standard | 19–29 |
| **TOTAL** | | **~150–340 USD/mes** |

Sumado a Supabase ($25–80) + Wompi (transactional %) + Twilio/Meta (per message): **TCO infra ~200–500 USD/mes** para 5–20 tenants medianos.

### Comparativa breve con alternativas

| Plataforma | Pro | Contra |
|---|---|---|
| **Railway** | Región Sao Paulo (LATAM) ✅, similar DX a Render | Madurez menor, sin SLA documentado, ecosistema más pequeño |
| **Fly.io** | 30+ regiones incluyendo Bogotá ✅ y Sao Paulo, edge nativo, IPv6 first | Más complejo (Firecracker VMs, Nomad), curve de aprendizaje, sin managed Postgres tan pulido |
| **AWS ECS Fargate** | Región sa-east-1 ✅, máxima flexibilidad, ecosistema completo (WAF, CloudFront, Route53) | DX inferior, más DevOps overhead, pricing complejo, tiempo para ramp-up alto |
| **Render** | DX óptimo, integración Git nativa, IaC simple, soporte 4 services + DDoS gratis | Sin región LATAM, sin static IPs nativos, sin WAF L7, sin SLA público claro |

**Conclusión**: Render es la elección correcta para Sem 0 → Sem 6 (velocidad de delivery > optimización LATAM). Re-evaluar Fly.io o Railway si Render no suma región LATAM en 12 meses o si latencia hacia clientes finales se convierte en queja recurrente.

---

## Apéndice — URLs investigadas

- `/docs` (root)
- `/docs/free`
- `/docs/web-services`
- `/docs/regions`
- `/docs/scaling`
- `/docs/private-services`
- `/docs/private-network`
- `/docs/configure-environment-variables`
- `/docs/blueprint-spec`
- `/docs/custom-domains`
- `/docs/background-workers`
- `/docs/cron-jobs`
- `/docs/preview-environments`
- `/docs/deploys`
- `/docs/notifications`
- `/docs/datadog`
- `/docs/ddos-protection`
- `/docs/static-outbound-ip-addresses`
- `/docs/logging`
- `/docs/health-checks`
- `/docs/disks`
- `/docs/native-runtimes`
- `/docs/projects-environments`
- `/pricing`

URLs probadas que devolvieron 404 (no existen como documentación pública estable): `/docs/cronjobs`, `/docs/instance-types`, `/docs/workspaces`, `/docs/projects`, `/docs/environments`, `/docs/networking`, `/docs/cdn`, `/docs/sla`, `/docs/environment-groups`. Información correspondiente extraída de páginas vecinas o marcada como pendiente de validación con Render Sales.
