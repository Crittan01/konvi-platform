# Segregación total de ambientes — diseño canónico (verificado contra código 2026-08-14)

**Este documento es la fuente de verdad de cómo se separan los ambientes en Konvi, integración por integración.** Escrito tras verificación en código (no suposición). Para el estado operativo de los ambientes ver `environments.md`.

---

## 1. Principio rector

La arquitectura **Model B per-tenant** (ADR-0023) hace que la mayoría de las credenciales de terceros vivan en **datos (DB/Vault), no en código**. Por eso la segregación de ambientes se logra principalmente **por datos y por deploy unit**, no por lógica condicional:

- **STG** y **PRD** son deploys distintos con **DBs distintas** y **env vars distintas**.
- Las integraciones per-tenant se separan porque cada tenant vive en su DB con sus propias llaves en Vault.

---

## 2. Los 2 ambientes (qué los separa de verdad)

| Capa | **STG** | **PRD** |
|---|---|---|
| Cómputo | Local VM (Makefile: api :8001, connector :8000, orchestrator, web :3000) | Render: `konvi-web/connector/api/orchestrator` |
| Base de datos | Supabase OSS local (podman, `127.0.0.1:54321`) — **datos sintéticos** | Supabase cloud (`xmelwnhhphksbpdjmbbp`) — **datos reales** |
| Keys Supabase | demo públicas del CLI (no secretas) | reales (rotación B2) |
| Dominio público webhooks | ngrok (`NGROK_DOMAIN_*`) | hoy `*.onrender.com` → futuro `api.konvi.com` |
| Protección | `_env_guard.py` clasifica `dev-safe` | `_env_guard.py` `prelaunch`→`prod` fail-closed tras `LAUNCHED=True` |

**Regla de oro:** STG nunca escribe en PRD. PRD solo recibe código vía `git push origin develop:production` y migraciones por protocolo seguro.

---

## 3. Integración por integración (qué requiere cada una por ambiente)

### 3.1 Wompi (pagos)

| Qué | STG | PRD |
|---|---|---|
| Cuenta/dashboard | Wompi **TEST** (llaves `pub_test_`/`prv_test_`/`test_events_`/`test_integrity_`) | Wompi **PROD** (llaves `prod_*`) |
| Llaves en Konvi | tenant STG con `environment='sandbox'` + keys test en Vault | tenant PRD con `environment='production'` + keys prod en Vault |
| URL de eventos (webhook) | `POST {ngrok-api}/api/v1/webhooks/wompi` (registrada en el dashboard Wompi TEST) | `POST https://konvi-api.onrender.com/api/v1/webhooks/wompi` (dashboard Wompi PROD) → futuro `api.konvi.com` |
| Cómo decide el código | `wompi_base_url()` lee `tenant_integrations.meta.environment` per-tenant (`integrations/wompi_client.py:124`) → sandbox.wompi.co vs production.wompi.co | igual |

**Punto crítico:** Wompi tiene **una sola URL de webhook** en Konvi; el tenant se resuelve del payload (`payment_link_id → order → tenant_id`) y la firma se verifica con el `events_key` de ESE tenant. STG y PRD no chocan porque son dashboards Wompi distintos apuntando a URLs distintas.

### 3.2 Meta WhatsApp (Model B)

| Qué | STG | PRD |
|---|---|---|
| Meta App | Una **Meta App de desarrollo** (modo dev de Meta) con su propio WABA de prueba | La **Meta App de producción del tenant** |
| Credenciales | app_secret/verify_token/access_token de la app dev → Vault del tenant STG | las de la app prod → Vault del tenant PRD |
| Webhook URL | `GET/POST {ngrok-connector}/api/v1/whatsapp/webhook/{tenant_id_stg}` (registrada en la Meta App dev) | `…/api/v1/whatsapp/webhook/{tenant_id_prd}` en el connector PRD (hoy onrender → futuro dominio) |
| Cómo decide el código | el `tenant_id` del PATH es la autoridad; HMAC con el app_secret per-tenant de Vault (`connector/dependencies/meta.py`) | igual |

**Punto crítico:** el connector sirve UN endpoint por tenant (`/webhook/{tenant_id}`). Una Meta App de prueba apunta a la URL ngrok del tenant STG; la de prod a la URL del tenant PRD. Mismo código, routing por tenant.

### 3.3 Aveonline (envíos)

| Qué | STG | PRD |
|---|---|---|
| Cuenta | la misma cuenta Aveonline del tenant (no hay sandbox del proveedor) | igual |
| Guías | tenant STG con `real_guides_enabled=false` → **dry-run** (`bloquegenerarguia="0"`, no factura) | `real_guides_enabled=true` → guías reales |
| Doble compuerta | env global `AVEONLINE_GENERATE_REAL_GUIDES` × flag per-tenant (`shipping_guides.py:261-262`) | ambas true en prod hoy |
| Webhook | `{PUBLIC_WEBHOOK_URL=ngrok}/api/v1/webhooks/aveonline/{tenant_id_stg}` | `{PRD}/api/v1/webhooks/aveonline/{tenant_id_prd}` (registrado vía API con secret per-tenant) |

### 3.4 Mercado Libre

| Qué | STG | PRD |
|---|---|---|
| App de plataforma | una **segunda app MeLi de prueba** (otro client_id/secret) con `MELI_REDIRECT_URI` a ngrok/staging | la app MeLi de prod con redirect a PRD |
| Env vars | `MELI_CLIENT_ID/SECRET/REDIRECT_URI/AUTH_URL` del entorno local | las de Render |
| Tokens OAuth | per-tenant en Vault del tenant STG | per-tenant en Vault del tenant PRD |
| Webhook | `POST {ngrok-api}/api/v1/meli/webhook` | `POST {PRD}/api/v1/meli/webhook` (defensa: allowlist IPs oficiales) |

### 3.5 Telegram (notificaciones operador)

| Qué | STG | PRD |
|---|---|---|
| Bot | un **bot de prueba** (otro token de BotFather) | el bot de prod del tenant |
| Token | Vault del tenant STG | Vault del tenant PRD |
| Webhook | `setWebhook` manual (HITL) a `{ngrok-api}/api/v1/integrations/telegram/webhook` con el secret | `setWebhook` a la URL PRD con el secret global |
| Secret | `TELEGRAM_WEBHOOK_SECRET` del entorno | igual (env global por deploy) |

### 3.6 Resend (email transaccional)

| Qué | STG | PRD |
|---|---|---|
| API key | sin key → **simula** (no envía, loguea "Email simulated") o key de test | `RESEND_API_KEY` prod + dominio verificado |
| Dominio remitente | `RESEND_FROM_EMAIL` de test | el del dominio verificado |

### 3.7 Gemini (LLM)

| Qué | STG | PRD |
|---|---|---|
| API key | una key de dev (auth key, restringida a Generative Language API) | la key prod (auth key) |
| Separación | solo por API key (no hay sandbox del proveedor) | igual |

### 3.8 Supabase (DB/Auth/Vault)

| Qué | STG | PRD |
|---|---|---|
| Proyecto | OSS local podman (`127.0.0.1:54321`, ref `konvi-platform`) | cloud (`xmelwnhhphksbpdjmbbp`) |
| Keys | demo públicas del CLI | reales (rotación B2) |
| Vault (secretos per-tenant) | los del tenant STG | los del tenant PRD |

---

## 4. Las APIs que Konvi expone por ambiente

| Servicio | STG (local) | PRD (hoy) | PRD (futuro dominio) |
|---|---|---|---|
| Core API | `http://localhost:8001` | `https://konvi-api.onrender.com` | `https://api.konvi.com` |
| Connector WhatsApp | `http://localhost:8000` (vía ngrok para Meta) | `https://konvi-connector.onrender.com` | `https://connector.konvi.com` o path en el dominio |
| Web | `http://localhost:3000` | `https://konvi-web.onrender.com` | `https://app.konvi.com` |
| Orchestrator | proceso local | `https://konvi-orchestrator.onrender.com` (health) | interno |

### URLs de webhook externas (verificadas en routers)

| Proveedor | Path (se monta sobre el host del ambiente) |
|---|---|
| Wompi | `POST /api/v1/webhooks/wompi` |
| Meta WhatsApp | `GET/POST /api/v1/whatsapp/webhook/{tenant_id}` (connector) |
| Aveonline | `POST /api/v1/webhooks/aveonline/{tenant_id}[/{secret}]` |
| Mercado Libre | `POST /api/v1/meli/webhook` |
| Telegram | `POST /api/v1/integrations/telegram/webhook` |

**Guard anti-drift:** `scripts/check_no_ngrok.sh` (en `validate.sh`, CI) **prohíbe URLs ngrok en render.yaml/services/apps** → en PRD nunca se filtra una URL de túnel.

---

## 5. Qué falta para la segregación total limpia (gaps reales)

| # | Gap | Tipo | Dónde se cierra |
|---|---|---|---|
| 1 | **Dominio propio** — los webhooks de PRD cuelgan de `*.onrender.com` | DNS/founder + Render custom domain | OQ-4; knobs listos: `PUBLIC_WEBHOOK_URL`, `WHATSAPP_CONNECTOR_URL`, `NEXT_PUBLIC_*_HOST` |
| 2 | **Dev cloud** para UAT con webhooks reales sin ngrok | founder (crear proyecto Supabase dev) | PLAN §A #16, checklist `environments.md` §1/§2 |
| 3 | **Guard anti-mezcla de datos** — abortar si un tenant STG tiene `environment='production'` (Wompi) o Meta App prod contra ngrok | agente (ejecutable) | extensión de `_env_guard.py` |
| 4 | **MeLi app de prueba** — hoy solo hay config de plataforma PRD | founder (crear app MeLi dev) | docs/integrations/mercadolibre.md |
| 5 | **setWebhook Telegram por ambiente** documentado | ya documentado como HITL manual | `docs/integrations/telegram.md` |

---

## 6. Verificación de la segregación (cómo se certifica)

1. **Cómputo/datos**: `.env.local` → `dev-safe`; `.env.prd-backup` → `prelaunch` (verificado empíricamente 2026-08-14 vía `_env_guard.classify`).
2. **Sin ngrok en prod**: `check_no_ngrok.sh` en CI.
3. **Anti-mezcla de tenants** (gap #3): pendiente — extensión del env_guard.
4. **Health por ambiente**: `scripts/admin/verify_credential_rotation.py` (PRD) + smoke local (Makefile `status`).

---

*Fuentes verificadas en código 2026-08-14: routers de webhooks (`services/api/main.py:336-350`, `connector-whatsapp/routers/webhook.py`), clients de integraciones (`wompi_client.py`, `aveonline_client.py`, `meli_client.py`, `meta.py`), `render.yaml`, `.env.example`, `apps/web/lib/webhook-urls.ts`.*
