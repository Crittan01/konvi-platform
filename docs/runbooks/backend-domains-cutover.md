# Runbook — Dominios branded para API y Connector (`api.konvi.co` + `webhook.konvi.co`)

> Continúa el cutover de dominio (tras `app.konvi.co` para el web). Da dominio
> propio a los 2 servicios que reciben webhooks de proveedores, para que las URLs
> que el tenant registra en Meta/Wompi/MeLi/Aveonline/Telegram sean **branded y
> estables** en vez de `*.onrender.com` (atado a Render).
>
> **No es funcional-urgente** (onrender funciona) pero sí recomendado para producto.
> **onrender sigue vivo en paralelo** → los tenants ya registrados NO deben re-registrar.

## Mapa de webhooks → servicio → dominio

| Integración | Servicio | Endpoint | Dominio branded |
|---|---|---|---|
| WhatsApp (Meta) | **connector** | `/api/v1/whatsapp/webhook/{tenant_id}` | **`webhook.konvi.co`** |
| Wompi | **api** | `/api/v1/webhooks/wompi` | **`api.konvi.co`** |
| Mercado Libre | **api** | `/api/v1/meli/webhook` | **`api.konvi.co`** |
| Aveonline | **api** | `/api/v1/webhooks/aveonline/{tenant_id}` | **`api.konvi.co`** |
| Telegram | **api** | `/api/v1/integrations/telegram/webhook` | **`api.konvi.co`** |

**Solo WhatsApp vive en el connector; el resto en el api → 2 dominios cubren todo.**

## Env vars afectadas (por servicio) — el código YA lo soporta (solo config)

| Env var | Servicio | Lee | Valor branded | Nota |
|---|---|---|---|---|
| `NEXT_PUBLIC_WEBHOOK_HOST` | web | frontend (display de webhooks del **api**) | `https://api.konvi.co` | **build-time → rebuild** de konvi-web |
| `NEXT_PUBLIC_CONNECTOR_WEBHOOK_HOST` | web | frontend (display webhook WhatsApp) | `https://webhook.konvi.co` | **build-time → rebuild** |
| `WHATSAPP_CONNECTOR_URL` | api | `integrations.py:147` (URL WhatsApp que el api devuelve al tenant) | `https://webhook.konvi.co` | runtime |
| `PUBLIC_WEBHOOK_URL` | api | `integrations.py:828` (base webhook **Aveonline**) | `https://api.konvi.co` | ⚠️ **hoy fallback = placeholder `YOUR_PUBLIC_HOST`** — probablemente Aveonline webhook está roto/sin setear; verificar |
| `API_URL` | web + orchestrator | llamadas **internas** al api | *(dejar onrender — interno, directo)* | NO branded: es service-to-service |
| `ALLOWED_ORIGINS` | api | CORS | ya incluye `app.konvi.co` ✅ | — |

> **Regla:** solo las URLs **tenant-facing** (que se registran en proveedores) van branded. El `API_URL` **interno** (orchestrator→api, web-server→api) se queda en onrender: es más directo y no lo ve nadie externo.

---

## INTERVENCION HUMANA REQUERIDA
- **RESPONSABLE:** founder (Render custom domains + Cloudflare CNAMEs) + asistente (codificar env vars en render.yaml + deploy).
- **CRITERIO DE ÉXITO:** `https://api.konvi.co/health` y `https://webhook.konvi.co/health` responden con SSL válido; el onboarding de un tenant nuevo muestra las URLs branded; onrender sigue funcionando para los ya registrados.
- **REVERSIBLE:** sí — revertir env vars + quitar dominios; onrender nunca se cae.

## Orden (no rompe nada — onrender queda vivo)

### Paso 1 — Render: agregar los 2 custom domains (founder, ~4 min)
- Dashboard → **`konvi-api`** → Settings → Custom Domains → Add → `api.konvi.co` → copiar el target.
- Dashboard → **`konvi-connector`** → Settings → Custom Domains → Add → `webhook.konvi.co` → copiar el target.

### Paso 2 — Cloudflare: 2 CNAMEs (founder, ~3 min)
En `konvi.co` → DNS → Add record (x2):
| Name | Target | Proxy |
|---|---|---|
| `api` | *(target de konvi-api)* | **DNS only (gris)** |
| `webhook` | *(target de konvi-connector)* | **DNS only (gris)** |
Esperar a que Render marque ambos **Verified / Certificate Issued**.

### Paso 3 — Env vars (asistente: codifico en render.yaml + deploy)
En `render.yaml`:
- konvi-web: `NEXT_PUBLIC_WEBHOOK_HOST=https://api.konvi.co`, `NEXT_PUBLIC_CONNECTOR_WEBHOOK_HOST=https://webhook.konvi.co` *(rebuild web — son NEXT_PUBLIC)*.
- konvi-api: `WHATSAPP_CONNECTOR_URL=https://webhook.konvi.co`, `PUBLIC_WEBHOOK_URL=https://api.konvi.co`.
Luego **deploy** `develop → production` (protocolo actual, autorización founder).

### Paso 4 — Verificar
```bash
curl -I https://api.konvi.co/health          # 200
curl -I https://webhook.konvi.co/health      # 200
# CORS del api desde el web branded (debe permitir app.konvi.co — ya OK):
curl -sI -X OPTIONS https://api.konvi.co/api/v1/whatsapp/tenant-config \
  -H 'Origin: https://app.konvi.co' -H 'Access-Control-Request-Method: GET' | grep -i access-control-allow-origin
```
- En el backoffice, abrir el setup de un tenant → las webhook URLs mostradas deben ser `api.konvi.co` / `webhook.konvi.co`.
- **Meta verify:** al registrar `webhook.konvi.co/.../whatsapp/webhook/{tenant_id}` en Meta, el GET-challenge (hub.verify_token) debe responder 200 desde el connector.

### Paso 5 — Re-registro (NO forzado)
- **Tenants ya registrados:** siguen con la URL onrender → **funciona** (Render mantiene ambos dominios). No tocar.
- **Tenants nuevos:** el onboarding ya muestra las URLs branded.
- *(Opcional, después)* migrar a los ya registrados a la URL branded, tenant por tenant.

## Pendientes/verificaciones aparte
1. **Aveonline `PUBLIC_WEBHOOK_URL`** — verificar en el dashboard si está seteada hoy; si no, Aveonline registra `https://YOUR_PUBLIC_HOST/...` (roto). Este runbook la fija a `api.konvi.co`.
2. **MeLi OAuth redirect (`MELI_REDIRECT_URI`)** — es el callback OAuth (no webhook). Verificar en dashboard a dónde apunta y si debe pasar a `api.konvi.co` (+ actualizar la app de MeLi del tenant).
3. **`API_URL` interno** — se deja en onrender a propósito (service-to-service directo). No cambiar salvo que se quiera todo branded.

## Rollback
Revertir las env vars a los defaults onrender + redeploy; quitar los custom domains de Render. onrender nunca dejó de funcionar, así que no hay downtime.

## Nota de arquitectura (topología final)
```
konvi.co          → landing (público)
app.konvi.co      → Tenant Console (web)                    ✅
api.konvi.co      → konvi-api  (Wompi/MeLi/Aveonline/Telegram + backend)
webhook.konvi.co  → konvi-connector (WhatsApp/Meta)
platform.konvi.co → Platform Console (Konvi interno, futuro fase 12)
```
