# Runbook — Dominio custom para la Tenant Console (`app.konvi.co`)

> Objetivo: mover el backoffice de `https://konvi-web.onrender.com` a
> `https://app.konvi.co` (subdominio de `konvi.co`, que ya está en Cloudflare).
> El apex `konvi.co` queda para el landing (Cloudflare Pages).

**Por qué un mini-cutover y no solo DNS:** la URL vieja está cableada en 3 lugares
que hay que actualizar coordinadamente, o se rompen login y emails:
1. Env vars de Render (`APP_URL`, `NEXT_PUBLIC_APP_URL` en konvi-web).
2. Supabase Auth (`site_url` + redirect allow-list).
3. DNS + custom domain en Render.

## INTERVENCION HUMANA — founder + asistente

- **RESPONSABLE:** founder (Render domain, Cloudflare DNS, Supabase Auth dashboard) + asistente (env vars render.yaml + deploy).
- **CRITERIO DE ÉXITO:** `https://app.konvi.co` carga la consola con SSL válido, login OK, y los emails (recovery/confirm) usan `app.konvi.co`.
- **REVERSIBLE:** sí — revertir env vars + redirect URLs + quitar el dominio; `konvi-web.onrender.com` sigue funcionando en paralelo durante la transición.

## Orden (importante — no romper login en el medio)

### Paso 1 — Render: agregar el custom domain (founder, ~2 min)
Dashboard → **konvi-web** → **Settings → Custom Domains → Add Custom Domain** → `app.konvi.co`.
Render muestra un **target DNS** (un CNAME, típicamente a `konvi-web.onrender.com` o un host de Render). **Copialo.**

### Paso 2 — Cloudflare: CNAME (founder, ~2 min + propagación)
En `konvi.co` (Cloudflare) → **DNS → Add record**:
- Type: **CNAME**, Name: **`app`**, Target: **el que dio Render**.
- Proxy status: **DNS only (nube gris)** al principio → deja que Render provisione el SSL. *(Si luego querés el proxy de Cloudflare (nube naranja), poné SSL/TLS mode = **Full (strict)** para no romper el cert de Render.)*
- Esperar a que en Render el dominio pase a **Verified / Certificate Issued** (minutos).

### Paso 3 — Actualizar la URL de la app (asistente + deploy)
En `render.yaml` (konvi-web), cambiar a `https://app.konvi.co`:
- `APP_URL`
- `NEXT_PUBLIC_APP_URL` *(se **bakea en el bundle del browser** en build → dispara rebuild de konvi-web)*
- *(grep `render.yaml` por `konvi-web.onrender.com` y actualizar cualquier otra referencia a la URL del web.)*
Luego **deploy** `develop → production` (protocolo actual).

### Paso 4 — Supabase Auth (founder, dashboard, ~2 min)
Prod → **Authentication → URL Configuration**:
- **Site URL** → `https://app.konvi.co`
- **Redirect URLs** → agregar `https://app.konvi.co/**`, `https://app.konvi.co/auth/callback`, `https://app.konvi.co/auth/confirm`.
- Dejar las de `konvi-web.onrender.com` **durante la transición** (no romper sesiones activas); quitarlas al final.

### Paso 5 — Verificar
- `https://app.konvi.co` carga con candado (SSL OK).
- Login OK (el hook de auth ya validado sigue igual).
- Pedir un recovery/confirm → el email trae links con `app.konvi.co` (no localhost ni onrender).
- Un pago/flujo que genere email transaccional → link correcto.

### Paso 6 — (Opcional, después) consolidar
- Redirect 301 de `konvi-web.onrender.com` → `app.konvi.co` (o dejar onrender como fallback interno).
- Quitar las redirect URLs viejas de Supabase Auth.

## Rollback
Revertir env vars a `konvi-web.onrender.com` + redeploy, y restaurar Site URL/redirects en Supabase. El dominio en Render/Cloudflare se puede quitar sin afectar el onrender.

## Notas
- **Meta/Wompi/webhooks NO cambian:** apuntan a konvi-connector/konvi-api (sus propias URLs), no al web. Si a futuro querés `api.konvi.co`/`hooks.konvi.co`, es otro cutover análogo (+ actualizar la Meta App callback + Wompi).
- El hook de `custom_access_token_hook` es independiente del dominio (no se toca).
