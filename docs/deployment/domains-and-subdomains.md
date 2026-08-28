# Dominios y Subdominios

Última actualización: 2026-08-27

## Estado actual

- **`api.konvi.co` LIVE** (2026-08-27): verified + TLS emitido + `/health` 200 — apunta a
  `konvi-api`. Recibe TODOS los webhooks no-Meta (Wompi/Resend/Aveonline/MeLi/Telegram viven
  en el servicio API; verificado contra `services/api/main.py`).
- **`app.konvi.co` LIVE** (2026-08-27): verified + `/login` 200 — la consola en dominio de
  marca (konvi-web). Registrado del lado Render antes de esta sesión; el founder agregó el
  CNAME en la misma pasada que el de `api`.
- `PUBLIC_WEBHOOK_URL` (konvi-api) y `NEXT_PUBLIC_WEBHOOK_HOST` (konvi-web) apuntan a
  `https://api.konvi.co` (render.yaml + Render) — las URLs de webhook que la consola muestra y
  las que se registran en setup ya salen con el dominio propio.
- Los subdominios onrender SIGUEN activos (transición sin corte; `renderSubdomainPolicy`
  intacto). Nota operativa medida: durante el switchover de un redeploy hubo un blip de
  ~segundos SOLO en el dominio custom (onrender intacto) — esperable y auto-recuperado;
  registrarlo al planear ventanas.
- Meta WhatsApp: su webhook vive en el CONNECTOR (`konvi-connector.onrender.com`,
  `/api/v1/whatsapp/webhook/{tenant_id}`) — **decisión 2026-08-27: queda ahí** (server-to-server,
  sin cara al usuario; un futuro `connector.konvi.co` es opcional — Hobby incluye 2 dominios y
  ya se usan api+app; flip vía `NEXT_PUBLIC_CONNECTOR_WEBHOOK_HOST` sin tocar componentes).

## Fase 2 — estado por proveedor (2026-08-27)

1. **Telegram** — sin tenant prod con Telegram conectado → nada que migrar; futuros setups
   (`POST /telegram/setup`) registran con el dominio nuevo vía `PUBLIC_WEBHOOK_URL`.
2. **Aveonline** — tenant prod conectado: **[F] 1 click** en la consola: Integraciones →
   Aveonline → sección "Webhook" → **"Configurar webhook"** → confirmar. El endpoint
   re-registra (upsert por empresa, `webhookPersonalizadoApi` oficial) con la URL nueva
   `https://api.konvi.co/api/v1/webhooks/aveonline/{tenant_id}` y rota el secret con gracia
   de 7 días (el viejo sigue válido mientras Aveonline migra). La sección muestra la URL —
   debe leerse `api.konvi.co` después del click.
3. **Wompi (prod)** — cuando se configuren las keys prod ([F] Track 1/2), registrar el webhook
   en el dashboard Wompi con `https://api.konvi.co/api/v1/webhooks/wompi`.
4. **Resend** — el registro del webhook en el dashboard Resend (pendiente [F] Track 6) usa
   desde ya `https://api.konvi.co/api/v1/webhooks/resend` (+ `RESEND_WEBHOOK_SECRET` en Render).
5. **MeLi** — condicionado a S6.
6. **Meta** — ver decisión arriba: no migrar (connector onrender).

## Registro DNS — ✅ EJECUTADO 2026-08-27

El founder agregó en Cloudflare (DNS de konvi.co — verificado con `dig NS`):
`CNAME api → konvi-api.onrender.com` y `CNAME app → konvi-web.onrender.com`,
ambos **DNS only** (nube gris — con proxy activado Render no puede verificar ni
emitir TLS; [guía oficial Render↔Cloudflare](https://render.com/docs/configure-cloudflare-dns)).
La verificación se disparó vía Render API (`POST …/custom-domains/{id}/verify` → 202)
y ambos dominios quedaron `verified` con TLS emitido + health 200. Regla persistente:
no agregar registros AAAA para estos subdominios (Render es IPv4) y no tocar los
registros del apex (Worker `konvi-landing`) ni los de correo (MX/SPF/DKIM/DMARC).

## Migración de webhooks (Fase 2) — SUPERADA por el estado al 2026-08-27

El plan original por proveedor quedó ejecutado donde aplica — ver §"Fase 2 — estado
por proveedor" arriba (fuente de verdad del estado). Solo si TODOS los proveedores
migran algún día: opcionalmente `renderSubdomainPolicy: disabled` en el servicio —
NO hacerlo antes (apagaría el subdominio onrender que hoy recibe todo).

## Consideraciones

- Mantener `APP_URL` alineado al dominio activo (hoy sigue siendo onrender para
  web; el custom domain es solo del API).
- Revisar `ALLOWED_ORIGINS` en API/connector tras cualquier cambio de dominio.
- Si algún proveedor exige verificación de dominio propia (Meta la hace por
  verify_token, no por dominio), se resuelve por proveedor en su dossier
  (`docs/integrations/`).
