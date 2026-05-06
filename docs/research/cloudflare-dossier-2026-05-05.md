# Dossier Cloudflare — 2026-05-05

**Fecha**: 2026-05-05 · **Sesión**: investigación previa Sem 0 (J.0.0) · **Sin pruebas en vivo**.
**Fuente**: `https://developers.cloudflare.com/*` + `https://www.cloudflare.com/plans/` + `https://www.cloudflare.com/network/` (público).
**Estado actual**: ❌ **NO usamos Cloudflare hoy**. Tráfico Render expuesto vía `*.onrender.com` con DDoS L3/L4 upstream Cloudflare (sin nuestro control) pero sin WAF L7, sin CDN, sin custom domains gestionados.
**Contexto**: dossier complementario al de Render (`render-dossier-2026-05-05.md` §6 P1) que identifica a Cloudflare como solución cuasi-mandatoria a 4 gaps de Render: ausencia de WAF, CDN, IPs salientes estáticas y región LATAM.

---

## 1. TL;DR ejecutivo

**Qué es**: red anycast global con presencia en `100+ países` y, en Colombia, 4 ciudades (`Bogotá, Medellín, Barranquilla, Cali`). URL: `/network/`. Provee como capa frontend: DNS gestionado, CDN, TLS automático, WAF L7, Rate Limiting, Bot Protection, DDoS L3-L7, Tunnel para egreso, custom hostnames per-tenant, Workers (serverless edge), R2 (object storage sin egress fee), Web Analytics privacy-first y Turnstile (CAPTCHA-less).

**Modelo de pricing** (zona/dominio = unit of billing, NO per-request en planes base):

| Plan | USD/mes (annual / monthly) | Target |
|---|---|---|
| **Free** | 0 / 0 | personal/hobby |
| **Pro** | 20 / 25 | sites pequeñas, baseline producción |
| **Business** | 200 / 250 | apps con compliance/PCI o tráfico crítico |
| **Enterprise** | contract | SLA, BYOIP, soporte dedicado, mTLS |

URL: `/application-services/products/ssl/` (única página oficial donde aparecen los precios anuales 20/200 vs mensuales 25/250).

**Add-ons clave a tener en cuenta** (cobro adicional al plan, URL `/plans/`):
- Advanced Certificate Manager: desde `$10/mo`.
- Argo Smart Routing + Smart Shield: desde `$5/mo`.
- Load Balancing: desde `$5/mo`.
- Workers (serverless): Free 100k req/día; Paid `$5/mo` base.
- R2 storage: `$0.015/GB-mo`, Class A `$4.50/M req`, Class B `$0.36/M req`. Egress 0. Free 10 GB-mo.
- Log Explorer / Logpush a R2: `$1/GB ingested` (10 GB free). Logpush requiere Enterprise (excepto Workers Trace Events).
- Cloudflare for SaaS: 100 hostnames incluidos; adicionales `$0.10 c/u`. URL: `/cloudflare-for-platforms/cloudflare-for-saas/plans/`.

**Recomendación tier para Commerce Ops Platform (5–20 tenants Colombia)**:
- **Pro $25/mo** (mensual) o **$20/mo** (annual). Cubre 80 % de los gaps Render: WAF custom rules, full Managed Rules, Rate Limiting (2 reglas), Super Bot Fight Mode, CDN tiered, 20 Page Rules.
- **Cloudflare for SaaS bundleado en Pro**: 100 custom hostnames sin costo adicional → suficiente para storefront tenant `tienda.tenant-x.com` por bastante tiempo. Pasa a `$0.10` por hostname extra a partir de #101.
- **NO adoptar inicialmente**: Workers, R2, Turnstile (no resuelven problema priorizado), Bot Management Enterprise, Logpush.

**Esfuerzo setup**: ~1–2 días (DNS migration + nameserver change + CNAME a `*.onrender.com` + SSL verify + WAF rules iniciales OWASP + rate-limit por endpoint webhook).

---

## 2. Hallazgos clave

### 2.1 DNS y onboarding
- Zone-based: para usar la mayoría de productos hay que **delegar nameservers de la zona a Cloudflare**. URL: `/fundamentals/get-started/`.
- DNS authoritative anycast incluido en **todos los planes** (incl. Free). Sin costo adicional.
- Time to propagation: depende de TTL del registrar actual; Cloudflare sugiere TTL bajo (5 min) horas antes de migrar.
- Universal SSL gratis en todos los planes. Compatibilidad declarada: `Cloudflare is compatible with your existing SSL configuration`. URL: `/application-services/products/ssl/`.

### 2.2 CDN / Cache
URL: `/cache/`.
- Cache **disponible en todos los planes**. Frecuentemente accedidos (imágenes, video, HTML estático) cacheados automáticamente en el edge anycast.
- **Cache Rules**: configurar qué se cachea y por cuánto tiempo (granularidad path/host/header).
- **Tiered Cache**: jerarquía de POPs para reducir tráfico al origin.
- **Cache Reserve**: persistencia extendida (add-on, costo adicional no documentado en página overview).
- **Purge API**: disponible en todos los planes; instant purge por URL / tag (tag-based purge solo Enterprise).

### 2.3 SSL/TLS
URL: `/application-services/products/ssl/`.
- **Universal SSL** gratis (Let's Encrypt / Google Trust Services).
- **Advanced Certificate Manager**: add-on `$10/mo`, permite custom hostnames más flexibles, validación DCV delegada, certificados con vigencia configurable.
- **Custom certificate upload**: solo Enterprise (con CSR propio).
- TLS 1.3, HTTP/2, HTTP/3 incluidos.

### 2.4 WAF
URL: `/waf/`.

| Capacidad | Free | Pro | Business | Enterprise |
|---|---|---|---|---|
| Custom Rules | sí (limit no especificado en overview) | sí | sí | sí (ilimitado) |
| Managed Rules (free ruleset) | sí | sí (ruleset completo) | sí | sí |
| Managed Rules (full OWASP / Cloudflare-managed) | parcial | sí | sí | sí |
| Rate Limiting Rules | 1 | 2 | 5 | 100 |
| Attack Score (1 field) | — | — | sí | — |
| Attack Score (full) | — | — | — | sí |
| Account-level analytics + alerts | — | — | sí | sí |
| Sensitive Data Detection | — | — | — | sí |
| Account-level WAF + managed IP lists | — | — | — | sí |
| Advanced Rate Limiting (paid add-on) | — | — | — | sí |
| Malicious uploads detection | — | — | — | sí (add-on) |

`The pre-configured managed rulesets...are regularly updated, offering advanced zero-day vulnerability protections`. URL: `/waf/`.

### 2.5 Rate Limiting
URL: `/waf/rate-limiting-rules/`. Es el feature más asimétrico entre planes:

| Aspecto | Free | Pro | Business | Enterprise |
|---|---|---|---|---|
| Rules | 1 | 2 | 5 | 100 |
| Campos de match | Path, Verified Bot | + Host, URI, Full URI, Query | + Method, Source IP, User-Agent | + headers, Bot Mgmt fields |
| Granularidad counter | IP | IP | IP + NAT | + JA3/JA4, JSON, body, custom |
| Counting period max | 10 s | 1 min | 10 min | 65 535 s |
| Mitigation timeout max | 10 s | 1 h | 1 día | 1 día |

Acción `Block` detiene la evaluación. Hay un retraso `up to a few seconds` entre detectar y enforcar — relevante para webhooks: la primera ráfaga puede pasar al origin.

### 2.6 DDoS
URL: `/ddos-protection/`.
- **Todos los planes incluyen DDoS L3-L7 unmetered**. `standard, unmetered DDoS protection (layers 3-7)`.
- Free/Pro/Business: adaptive protection limitada (`only error adaptive rules`), 1 ruleset override, alertas estándar.
- Enterprise: enhanced adaptive con proactive false-positive detection.
- Enterprise + Advanced DDoS add-on: 10 ruleset overrides, profiling avanzado (country, UA, query, ML-scores).
- Advanced TCP/DNS protection: solo Magic Transit (no aplica a HTTP/Render).

### 2.7 Bot Protection
URL: `/bots/`.
- **Bot Fight Mode** (Free): toggle simple, challenge a bots conocidos.
- **Super Bot Fight Mode** (Pro/Business): granularidad por categoría (definitely automated, likely automated, verified bots), challenge/block configurable, exclude WAF rules.
- **Bot Management** (Enterprise): per-request `bot score` (1-99), custom rules, per-endpoint, analytics detallado, integración con WAF expressions.

### 2.8 Page Rules vs Cache/Configuration/Origin Rules
URL: `/rules/page-rules/`.
- Page Rules **deprecated** según el title de la página oficial (`Page Rules (deprecated)`). Cloudflare empuja a **Cache Rules / Configuration Rules / Origin Rules** modernos.
- Limit Page Rules legacy: Free 3 / Pro 20 / Business 50 / Enterprise 125. Para builds nuevas usar Rules engines modernos (sin límite duro publicado).

### 2.9 Workers (serverless edge)
URL: `/workers/platform/pricing/`.

| Recurso | Free | Paid ($5/mo base) |
|---|---|---|
| Requests | 100 000/día | 10 M/mes incluidos; `$0.30/M` overage |
| CPU time / invocación | 10 ms | 30 M ms-CPU/mes incluidos; `$0.02/M` overage. Max 30 s default, 5 min stand, 15 min cron. |
| KV reads | 100 k/día | 10 M/mes; `$0.50/M` |
| KV writes | 1 k/día | 1 M/mes; `$5/M` |
| KV storage | 1 GB | 1 GB + `$0.50/GB-mo` |
| Durable Objects | — | 1 M req/mes; `$0.15/M` + `$12.50/M GB-s` |

Para Commerce Ops: NO necesitamos Workers en producción Sem 0–11. Útil sólo para edge logic per-tenant futuro (A/B test, geofencing, cache invalidation).

### 2.10 R2 Object Storage
URL: `/r2/pricing/`.

| Tier | Storage $/GB-mo | Class A (writes/list) | Class B (reads) | Egress |
|---|---|---|---|---|
| Standard | 0.015 | $4.50 / M | $0.36 / M | 0 |
| Infrequent Access | 0.010 | $9.00 / M | $0.90 / M | $0.01/GB retrieval |
| Free tier | 10 GB-mo | 1 M / mes | 10 M / mes | 0 |

`Egress free` es el diferencial vs S3. Alternativa potencial a Supabase Storage si el volumen explota — **no priorizado**: Supabase Storage cubre nuestro use case actual sin migración.

### 2.11 Cloudflare for SaaS (custom hostnames per tenant)
URLs: `/cloudflare-for-platforms/cloudflare-for-saas/`, `.../start/getting-started/`, `.../plans/`.

- Permite que cada tenant use su propio dominio (`tienda.tenant-x.com`) con CNAME hacia un `cname target` propio (`*.customers.commerce-ops.com`) y certificado emitido y rotado automáticamente por Cloudflare (Let's Encrypt o Google Trust Services).
- **Disponible en Free, Pro, Business** (bundled). En Enterprise va como add-on.
- **100 custom hostnames incluidos** en todos los tiers no-Enterprise. Adicionales: `$0.10` cada uno. Cap: 50 000.
- Setup:
  1. Zona en Cloudflare (Free OK).
  2. Habilitar Cloudflare for SaaS en la zona.
  3. Crear `fallback origin`: A/AAAA/CNAME proxied apuntando al backend (en nuestro caso `*.onrender.com`).
  4. Crear `cname target` (proxied), p.ej. `customers.commerce-ops-platform.com`.
  5. Por tenant: crear `custom hostname` vía API/Dashboard (TLS min, CA, validación HTTP o TXT, wildcard sí/no).
  6. Tenant crea CNAME `tienda.tenant-x.com` → `customers.commerce-ops-platform.com`.
  7. Validación cert + hostname → **Active** → tráfico fluye.
- Enterprise-only: custom CSR, mTLS enforcement, wildcard custom hostnames, custom firewall rulesets per hostname, Apex Proxying / BYOIP.

### 2.12 Tunnel (`cloudflared`)
URL: `/cloudflare-one/connections/connect-networks/`.
- Daemon que abre conexión **outbound-only** desde el origin hacia Cloudflare. Permite exponer servicios sin abrir puertos públicos ni disponer de IP estática.
- Sustituye necesidad de `static outbound IP` desde la perspectiva del **origin tras Cloudflare**: el origin nunca recibe tráfico externo directo.
- Pero **NO resuelve el otro problema**: las llamadas salientes de nuestro backend hacia Wompi/Meta siguen siendo egress de Render con CIDR compartido. Tunnel no proporciona IP estática hacia terceros.
- Para egress hacia terceros con IP estable, la solución correcta es Argo Tunnel + un proxy Worker o un servicio externo tipo QuotaGuard. Cloudflare no documenta una IP saliente fija per-zone reutilizable.

### 2.13 Web Analytics
URL: `/web-analytics/`.
- `Privacy-first analytics for your website without changing DNS or using Cloudflare proxy`. Cookieless. Disponible en todos los planes.
- RUM data (incluye Core Web Vitals según docs vinculadas), Filters, Rules, Dimensions.
- Alternativa gratis a GA4 o Plausible. Útil como baseline sin costo.

### 2.14 Turnstile (CAPTCHA-less)
URL: `/turnstile/plans/`.
- Free: hasta 20 widgets, 10 hostnames/widget, analítica 7 días. Ilimitadas challenge requests.
- Enterprise (contract): 200 hostnames/widget, analítica 30 días, ephemeral IDs, off-label.
- WCAG 2.2 AAA. Funciona aunque el sitio NO esté en Cloudflare CDN.
- Para Commerce Ops: **no priorizado** — añade fricción UX a flujo conversacional WhatsApp-first.

### 2.15 Logpush
URL: `/logs/logpush/`.
- **Solo Enterprise** (excepción: Workers Trace Events está disponible en Workers Paid).
- Push near-real-time a destinos externos (R2, S3, GCS, SIEMs).
- `cannot backfill historical data` — failed jobs = pérdida permanente.
- Cap: 4 jobs por zona.

### 2.16 Red global
URL: `/network/`.
- Presencia en `100+ países`, `hundreds of cities`. Anycast (todo tráfico procesado en POP más cercano, sin backhaul).
- Colombia: **Bogotá, Medellín, Barranquilla, Cali**. 4 cities → latencia local <20 ms para usuarios COL.
- 13 000+ peerings con ISPs/cloud providers/enterprise networks.
- Tbps capacity total: no publicado en la página. Históricamente >300 Tbps (no citable de fuente actual).

---

## 3. Multi-tenant compatibility

### 3.1 Custom hostnames per tenant
**El feature killer** para Commerce Ops es Cloudflare for SaaS:

- Cada tenant crea CNAME desde su dominio (`tienda.tenant-x.com`) hacia nuestro `customers.commerce-ops-platform.com`.
- API REST permite: `POST /custom_hostnames` con `hostname`, `ssl.method`, `ssl.type`, `ssl.wildcard` → Cloudflare emite cert, valida (HTTP-01 o TXT), levanta el hostname.
- El tenant **NO** necesita una cuenta Cloudflare. **NO** transfiere su DNS. Solo agrega el CNAME en su registrar.
- 100 hostnames bundled en Pro → cubre los 5–20 tenants previstos sin add-on.

### 3.2 WAF per-zone vs per-hostname
- Plan Pro/Business: las reglas WAF se aplican **a nivel zona** (afectan a todos los hostnames). Esto es OK para reglas globales (block country, rate limit `/api/webhooks/*`, OWASP managed).
- Para reglas **per-tenant** (p.ej. block país específico solo para tenant X): requiere Enterprise (custom firewall rulesets per custom hostname). Para 5–20 tenants iniciales esto NO es bloqueante; reglas globales bastan.

### 3.3 Rate Limiting multi-tenant
- En Pro tenemos 2 reglas. Diseño viable:
  - Regla 1: rate-limit `/api/*` por IP (10 req/s burst, 100 req/min).
  - Regla 2: rate-limit `/webhook/*` por IP (más estricto, p.ej. 30 req/min).
- Granularidad por `tenant_id` requeriría leer header/path → Pro permite Path/URI/Query. ✅ alcanza.
- Si necesitamos rate-limit per-tenant `tenant_id` extraído de body JSON, eso es **Advanced Rate Limiting** (Enterprise add-on). No prioritario.

### 3.4 SSL automation
- Cloudflare maneja la renovación de certs Let's Encrypt automáticamente. **Cero intervención humana** post-setup, vs Render que también renueva pero **per custom domain** sin API masiva amistosa.
- Para 20 tenants con custom hostnames, automatizar via Cloudflare API es trivial; Render no expone API equivalente para SaaS.

### 3.5 Pricing multi-tenant resumido

| Tenants con custom hostname | Plan Pro | Costo extra |
|---|---|---|
| 1–100 | $25/mo | $0 |
| 101–500 | $25/mo | $0.10 × (n-100) = $10–$40/mo |
| 1 000 | $25/mo | $90/mo |
| 50 000 (cap) | $25/mo | $4 990/mo |

---

## 4. Limitaciones documentadas

1. **WAF Custom Rules**: el número exacto en Pro/Business no aparece en la página `/waf/` overview; solo se confirma `unlimited` en Enterprise. Validar en dashboard al provisionar (PendingHumano §9).
2. **Page Rules legacy**: deprecated. Migrar a Cache/Configuration/Origin Rules engines.
3. **Logpush solo Enterprise**: para tener logs estructurados pusheados a S3/R2 sin estar en Enterprise hay que apoyarse en Workers + binding a R2 manualmente, o sólo consumir Web Analytics + dashboards básicos.
4. **Logs retention**: Web Analytics retención no especificada en docs públicas; Turnstile Free 7 días; Enterprise 30 días.
5. **Logpush cap**: 4 jobs por zona.
6. **Rate Limiting ventana**: Free 10s, Pro 1 min, Business 10 min. Diseñar reglas a esa granularidad.
7. **Workers Free**: 100k req/día (`30 M req/mes`) — no compite con Paid si nuestro tráfico crece.
8. **Workers CPU**: 10 ms Free / 30 ms-CPU típico Paid. Tareas largas requieren `Workers Unbound` legacy o ahora bundled en Standard plan ($5/mo).
9. **Logpush latency / backfill**: no backfill — si el job falla y se cae, ese batch se pierde.
10. **Cloudflare for SaaS**: hostnames manejados via SaaS NO pueden usar Argo, Early Hints, Page Shield, Spectrum, Wildcard DNS sobre ellos.
11. **Cloudflare for SaaS Apex**: A-record apex (no-CNAME) requiere `Apex Proxying / BYOIP` add-on Enterprise. Tenants con apex `tenant-x.com` (sin subdomain) no son soportables en Pro.
12. **Tunnel ≠ static egress IP**: Tunnel protege el origin entrante, NO da IP saliente fija para llamadas a Wompi/Meta.
13. **DNS migration**: requiere cambiar nameservers en el registrar. Si DNS lo maneja terceros (cliente), hay coordinación humana.
14. **Cache de respuestas dinámicas**: por defecto Cloudflare NO cachea HTML dinámico (Next.js SSR). Hay que configurar Cache Rules con `Cache Everything` y respetar `Cache-Control` headers de Next.

---

## 5. Lo que necesitamos vs lo que ofrece

| Necesidad Commerce Ops | Cloudflare feature | Plan mínimo | Cubre 100 % |
|---|---|---|---|
| WAF L7 (Render no tiene) | WAF Managed + Custom Rules | Pro | ✅ |
| CDN (Render no tiene) | Cache + Tiered Cache + Cache Rules | Free | ✅ |
| DDoS L7 (Render solo L3/L4) | DDoS Managed Rulesets | Free | ✅ |
| Rate limit por endpoint | Rate Limiting Rules (2 reglas) | Pro | ✅ |
| Bot protection | Super Bot Fight Mode | Pro | ✅ baseline |
| Custom hostnames per tenant | Cloudflare for SaaS (100 incluidos) | Pro | ✅ |
| SSL gestionado per tenant | Universal SSL + SaaS auto-renewal | Pro | ✅ |
| Static egress IP hacia Wompi/Meta | (Tunnel NO resuelve) | — | ❌ |
| Región LATAM efectiva (latency) | Anycast + Bogotá/Medellín/Barranquilla/Cali | Free | ✅ (latency edge a usuario; origin sigue Virginia) |
| Edge functions per tenant | Workers | Workers Paid $5 | ⚠️ no priorizado |
| Object storage masivo sin egress | R2 | Pay-as-go | ⚠️ no priorizado |
| Anti-CAPTCHA en formularios | Turnstile | Free | ⚠️ UX agrega fricción WhatsApp-first |
| Logs centralizados a SIEM | Logpush | Enterprise | ❌ no priorizado |
| Analítica privacy-first | Web Analytics | Free | ✅ |
| Per-tenant WAF firewall ruleset | Custom Rulesets per Hostname | Enterprise | ❌ no priorizado |

**Veredicto**: Pro $25/mo cubre 8 de 10 necesidades P0/P1. Los 2 gaps restantes (static egress IP, per-tenant WAF) NO son bloqueantes para Sem 0–11.

---

## 6. Gaps críticos priorizados

### P1 — adopción Pro como capa frontend
- Estado: no adoptado.
- Costo: **$25/mo** (mensual) o **$20/mo** (annual) plan Pro.
- Beneficio: cubre WAF L7, CDN, Rate Limiting, Bot Protection, DDoS L7 adaptive — los 4 gaps Render P1 documentados. URL: `/plans/`.
- Esfuerzo: 1–2 días setup (DNS migration, CNAME wiring, SSL verify, WAF rules iniciales).
- Sin Cloudflare frontend, en producción multi-tenant escala estamos expuestos a:
  - Attacks L7 sin WAF → costos Render por compute + impactos disponibilidad.
  - Latencia LATAM peor (todo va a Virginia sin edge cache).
  - Sin rate-limit edge → un tenant abusivo / scraper agota nuestro origin.

### P1 — Cloudflare for SaaS para storefront tenant
- Estado: no adoptado.
- Costo incremental: **$0/mo** hasta 100 tenants (bundled en Pro). `$0.10/cert/mo` extra desde el #101.
- Beneficio: cada tenant `tienda.tenant-x.com` con SSL gestionado vía API automática.
- Esfuerzo: 0.5 día integración API + UI flow para que tenant copie CNAME en su DNS.
- Alineado con futuro storefront (J.0.0.4 según `.context/00-product.md`).
- URL: `/cloudflare-for-platforms/cloudflare-for-saas/plans/`.

### P2 — Web Analytics privacy-first
- Estado: no adoptado.
- Costo: $0.
- Beneficio: alternativa GA4/Plausible sin cookies, compliance Habeas Data Ley 1581 (no transfiere PII fuera de COL/UE).
- Esfuerzo: incluir snippet JS en `apps/web/`. ~1 h.

### P3 — Workers para edge logic per-tenant
- Estado: no adoptado.
- Costo: $5/mo si superamos Free (100k req/día).
- Beneficio: A/B test, geofencing, cache invalidation custom, redirect by tenant.
- Esfuerzo: solo cuando aparezca caso concreto. **NO priorizar**.

### P3 — R2 para assets futuros
- Estado: no adoptado.
- Costo: dentro de Free 10 GB-mo.
- Beneficio: egress 0 vs Supabase Storage costos crecientes con uso.
- **NO priorizar** mientras Supabase Storage cubra.

---

## 7. ¿Estamos sobre-ingeniando o sub-aprovechando?

🔴 **Sub-aprovechando severo**.

- Hoy Render expone `*.onrender.com` y dominios custom **sin WAF L7, sin CDN nativo, sin rate-limit edge, sin custom hostname API multi-tenant**. La protección DDoS upstream Render ↔ Cloudflare cubre L3/L4 pero NO L7 — bots e injection siguen llegando al origin.
- Un solo tenant con tráfico abusivo (scraper, brute force webhook, ataque conducido) puede tirar el origin Render compartido por todos.
- 5 tenants actuales = riesgo aceptable hoy. **20 tenants en producción multi-tenant SaaS B2B Colombia = inaceptable** sin WAF + rate-limit edge.
- Adoptar Pro $25/mo es **baseline producción SaaS**, no over-engineering. Los productos competidores (Shopify, BigCommerce, Tiendanube) operan tras Cloudflare/Akamai/Fastly desde el día 1.

⚠️ **Over-engineering prevenir**:
- Workers paid sin caso de uso.
- R2 mientras Supabase Storage basta.
- Bot Management Enterprise ($250+) cuando Super Bot Fight Mode (Pro) cubre.
- Logpush Enterprise cuando Web Analytics + dashboards básicos cubren.
- Turnstile en flow WhatsApp-first donde no hay formularios humanos masivos.

---

## 8. Recomendaciones priorizadas

### DECISION FINAL recomendada
**Adoptar Cloudflare Pro $25/mo en Sem 11** (post integraciones P0 Wompi/Meta), **previo a abrir tenants externos**.

Ventana **Sem 11**:
1. Sem 11 día 1–2: DNS migration. Cambiar nameservers del dominio de plataforma → Cloudflare. Verificar registros A/CNAME existentes propagados. SSL Universal automático.
2. Sem 11 día 3: configurar **proxy CNAME** para `api.commerce-ops.com`, `app.commerce-ops.com`, `webhook.commerce-ops.com` → `*.onrender.com` (proxied=ON). Verificar HTTPS funciona end-to-end.
3. Sem 11 día 3–4: WAF rules iniciales:
   - Activar Managed Ruleset (Cloudflare Free + OWASP Core).
   - Custom Rules: bloquear `cf-ipcountry NE COL+US` para `/admin` (definir lista de paises permitidos).
   - Rate Limit Rule 1: `/api/*` 100 req/min/IP.
   - Rate Limit Rule 2: `/webhook/*` 60 req/min/IP.
   - Skip WAF en paths de webhook que requieran signature pasthru (Wompi/Meta).
4. Sem 11 día 5: Cache Rules — Next.js static assets (`/_next/static/*`) Cache TTL = 1 año. HTML dinámico bypass.
5. Sem 11 día 5: smoke tests S1–S25 UAT con tráfico via Cloudflare. Validar webhook signature verification sigue funcionando.

### Sem 12 — Cloudflare for SaaS
- Activar SaaS sobre la zona.
- Crear `cname target` `customers.commerce-ops.com`.
- Implementar UI tenant-side: input dominio → backend llama API Cloudflare `POST /zones/{id}/custom_hostnames` → muestra CNAME que el tenant debe poner en su DNS → polling de status.
- Bundled (no costo extra hasta 100 tenants).

### NO adoptar inicialmente
- **Workers**: ningún caso de uso edge real Sem 0–11.
- **R2**: Supabase Storage cubre.
- **Turnstile**: flow WhatsApp-first; UX impactaría conversion.
- **Bot Management Enterprise**: Super Bot Fight Mode (Pro) suficiente.
- **Logpush**: requiere Enterprise; Web Analytics + Render logs cubren observabilidad inicial.
- **Argo Smart Routing add-on**: $5/mo extra; beneficio marginal sobre Anycast estándar.
- **Advanced Certificate Manager**: solo si requerimos custom CSR o multi-CA (no aplica).

---

## 9. Validaciones humanas pendientes

> INTERVENCION HUMANA REQUERIDA
> RESPONSABLE: Founder + AI Architect
> CRITERIO DE EXITO: documento firmado con respuestas oficiales antes de migrar nameservers.

1. **¿Quién maneja el DNS hoy del dominio de plataforma?**
   - Si es Render (DNS gestionado por Render): cambio relativamente directo, mover NS al registrar y delegar a Cloudflare.
   - Si es registrar externo (GoDaddy, Cloudflare Registrar, Namecheap…): cambiar NS en panel registrar a los de Cloudflare.
   - Si es Cloudflare Registrar: trivial.
   - **Acción**: confirmar registrar y custodio del dominio.

2. **Modelo comercial custom hostnames per tenant**:
   - ¿Incluido en plan tenant o cobro extra?
   - ¿Quién paga si el tenant llega al hostname #101 ($0.10/mo extra)? ¿Cliente o Commerce Ops?
   - **Acción**: definir en pricing comercial Sem 11.

3. **WAF rules iniciales** — definir whitelist:
   - ¿Bloquear países fuera de COL+US+EU? Sí/No por tenant.
   - ¿Whitelist IPs corporativas (oficina Bogotá, VPN equipo)?
   - ¿Skip WAF en webhooks externos de Wompi/Meta para preservar headers de signature? — confirmar IPs/CIDR oficiales de Meta y Wompi.
   - **Acción**: documentar en `.context/03-rules.md` o `docs/security/`.

4. **Rate limiting target**:
   - ¿Rate limit por IP (default Pro) o por tenant_id (requiere Advanced Rate Limiting Enterprise)?
   - **Recomendación**: empezar IP+path con 2 reglas Pro. Reevaluar tras 3 meses con datos reales.

5. **Cloudflare account ownership**:
   - ¿Cuenta Cloudflare a nombre de Commerce Ops legal entity con MFA + 2 admins?
   - ¿Quién custodia API token con scope `Zone:Edit + SSL Cert:Edit`?
   - **Acción**: crear cuenta y definir RBAC Sem 11.

6. **Plan annual vs monthly**:
   - Annual Pro $20 vs monthly $25 → **$60/año ahorro**. Si flujo de caja permite, ir annual.

7. **Vendor lock-in moderado**:
   - DNS authoritative en Cloudflare = dependencia. Plan B: mantener export DNS (BIND zonefile) versionado en repo.
   - Custom hostnames per tenant: si migramos out, cada tenant tiene que cambiar CNAME nuevamente. **Aceptar**.

8. **Latencia adicional edge → origin Render Virginia**:
   - Cloudflare Bogotá → Render Virginia: ~80–110 ms RTT.
   - Cliente final → Cloudflare Bogotá: <20 ms.
   - **Net**: latencia total similar a hoy (cliente → Render Virginia directo) pero CON edge cache hits para assets estáticos = mejor experience.

9. **Compliance / Habeas Data Ley 1581**:
   - Cloudflare procesa logs/metadata en sus POPs (incluyendo Bogotá). Anexo: revisar `cloudflare.com/trust-hub/` y firmar DPA si necesario.
   - Web Analytics es cookieless → menor riesgo PII vs GA4.

10. **Webhook signature verification** crítica:
    - Wompi y Meta firman webhooks. Cloudflare por default NO modifica payloads, pero:
      - WAF puede bloquear si rule mismatch.
      - Cache puede comer respuesta si configuración errónea (NUNCA cachear `/webhook/*`).
      - Compresión: revisar que body raw llegue intacto a verificación HMAC.
    - **Acción**: smoke test con webhooks Wompi+Meta tras setup Cloudflare antes de cutover producción.

---

## 10. Veredicto final

### Decisión arquitectónica: ✅ **GO con Cloudflare Pro**

**Cloudflare Pro $25/mo es mandatorio para producción SaaS B2B multi-tenant Colombia**. Los gaps Render documentados (WAF L7 ausente, CDN ausente, edge LATAM ausente, custom hostnames per tenant inexistentes) se resuelven simultáneamente con un único producto a costo bajo.

### Costo total mensual estimado para producción

| Componente | Plan | USD/mes |
|---|---|---|
| Cloudflare Pro plan (zona principal) | Pro annual | 20 (annual) |
| Custom hostnames 5–20 tenants | Bundled 0–100 incluidos | 0 |
| Custom hostnames 101–500 (futuro escalado) | $0.10/cert | 0–40 |
| Web Analytics | Free | 0 |
| Workers (no adoptar Sem 0–11) | — | 0 |
| R2 (no adoptar Sem 0–11) | — | 0 |
| **Subtotal Cloudflare hoy** | | **$20–25/mo** |
| **Subtotal Cloudflare con 200 tenants** | | **$30–35/mo** |

Sumado al TCO infra completo (Render Pro $150–340 + Supabase $25–80 + Wompi % + Meta per message): **+$20–35 por capa frontend Cloudflare = +6–10 % TCO total**, gana WAF + CDN + custom domains + rate-limit + bot protection. **Mejor ratio coste/beneficio del stack**.

### Riesgos mitigados

- DDoS L7 adaptive ✅
- Inyección SQL / XSS / OWASP top 10 vía Managed Ruleset ✅
- Scraping / brute force vía Rate Limiting + Bot Fight Mode ✅
- Latencia LATAM mejorada (assets cacheados en Bogotá) ✅
- Custom domains per tenant gestionados con API ✅

### Riesgos residuales

- **Vendor lock-in moderado**: DNS authoritative + SSL gestionado por Cloudflare. Plan de fuga: zonefile BIND export periódico, certificados re-emitibles via ACM o Let's Encrypt directo.
- **Latencia edge → origin** ~80–110 ms (Cloudflare Bogotá → Render Virginia). Aceptable; sin alternativa hasta que Render abra LATAM o migremos a Fly.io.
- **Static egress IPs hacia Wompi/Meta**: Cloudflare NO resuelve este gap específico. Solución paralela: QuotaGuard, AWS NAT Gateway proxy, o esperar Render Enterprise static IPs.
- **Rate-limit per `tenant_id`**: requiere Advanced Rate Limiting Enterprise. Aceptar limit per-IP+path en Pro.
- **Logpush requiere Enterprise**: conformarnos con Web Analytics + Render logs hasta que volumen y compliance demanden Enterprise.

### Comparativa breve con alternativas

| Solución | Pro | Contra |
|---|---|---|
| **Cloudflare Pro** | DX óptimo, anycast LATAM, WAF/CDN/SaaS bundled, $25/mo | DNS migration, vendor lock-in moderado |
| **AWS CloudFront + WAF** | Ecosistema AWS completo, IPs estáticas posibles vía Global Accelerator | Costo más alto y variable, DX inferior, sin custom hostname API equivalente |
| **Fastly** | Edge computing potente (Compute@Edge), control granular | Pricing más complejo, sin SaaS multi-tenant tan empaquetado |
| **Akamai** | Líder enterprise, capacidades avanzadas | Costo enterprise, setup pesado, overkill para 5–20 tenants |
| **Self-host nginx + ModSecurity tras Render** | Sin vendor extra | Requiere otro service Render, mantenimiento, sin anycast LATAM |

**Conclusión**: Cloudflare Pro es la elección correcta para Sem 11. Re-evaluar add-ons (Workers, Advanced Rate Limiting, BYOIP) cuando crezcan los tenants o aparezca un caso comercial específico.

---

## Apéndice — URLs investigadas

### Páginas que respondieron con contenido útil
- `https://www.cloudflare.com/plans/`
- `https://www.cloudflare.com/network/`
- `https://www.cloudflare.com/application-services/products/ssl/`
- `https://developers.cloudflare.com/fundamentals/get-started/`
- `https://developers.cloudflare.com/waf/`
- `https://developers.cloudflare.com/waf/rate-limiting-rules/`
- `https://developers.cloudflare.com/ddos-protection/`
- `https://developers.cloudflare.com/cache/`
- `https://developers.cloudflare.com/bots/`
- `https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/`
- `https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/start/getting-started/`
- `https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/plans/`
- `https://developers.cloudflare.com/workers/platform/pricing/`
- `https://developers.cloudflare.com/r2/pricing/`
- `https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/`
- `https://developers.cloudflare.com/web-analytics/`
- `https://developers.cloudflare.com/turnstile/`
- `https://developers.cloudflare.com/turnstile/plans/`
- `https://developers.cloudflare.com/logs/logpush/`
- `https://developers.cloudflare.com/rules/page-rules/`

### URLs probadas que devolvieron 404 / sin pricing inline
- `https://developers.cloudflare.com/rate-limiting/` (404)
- `https://developers.cloudflare.com/page-rules/` (404, redirige a `/rules/page-rules/`)
- `https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/pricing/` (404 — pricing en `/plans/`)
- `https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/billing/` (404)

Información correspondiente extraída de páginas vecinas (`/plans/`, `/waf/rate-limiting-rules/`).
