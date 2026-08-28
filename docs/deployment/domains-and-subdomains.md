# Dominios y Subdominios

Última actualización: 2026-08-27

## Estado actual

- **Custom domain `api.konvi.co` CREADO en Render** (2026-08-27, vía Render API sobre
  `konvi-api`, id `cdm-da8fek4s728c73bjrre0`) — `verificationStatus: unverified`
  hasta que exista el DNS. **INERTE mientras tanto**: el subdominio
  `https://konvi-api.onrender.com` sigue funcionando intacto (los webhooks de
  Meta/Wompi/Aveonline/MeLi/Telegram NO se cortan — transición sin prisa).
- Web/console siguen en sus subdominios onrender (`konvi-web.onrender.com`).
- Dominio custom para web (www.konvi.co / app.konvi.co): NO creado — fuera del
  alcance de Track 3 (3.1 cubre solo el API, que es donde apuntan los webhooks).

## Paso [F] pendiente — registro DNS (único paso irreducible del founder)

En el panel DNS del registrador de `konvi.co` (donde se compró el dominio):

| Campo | Valor |
|---|---|
| Tipo | `CNAME` |
| Nombre/Host | `api` |
| Apunta a | `konvi-api.onrender.com` |
| TTL | default (o 300) |

- Render detecta el CNAME y emite el TLS automáticamente (Let's Encrypt) — la
  verificación del custom domain pasa a `verified` sola.
- Verificación del lado nuestro (una vez propagado, minutos–horas según TTL):
  `curl -sf https://api.konvi.co/health` → 200 y el custom domain en Render
  queda `verified`.
- Fuente oficial: https://render.com/docs/custom-domains (sección "Add a custom
  domain" → CNAME al subdominio onrender del servicio).

## Fase 2 — migración de webhooks al dominio nuevo (SOLO cuando `api.konvi.co/health` responda 200)

Orden y mecanismo por proveedor (cero corte: el subdominio onrender sigue activo
hasta que cada proveedor quede migrado y verificado):

1. **Telegram** — vía Bot API (`setWebhook`), lo ejecuta [A] con el token del
   Vault: `POST https://api.telegram.org/bot<token>/setWebhook` con la URL nueva
   del webhook del connector. Doc oficial: https://core.telegram.org/bots/api#setwebhook
2. **Aveonline** — vía su API oficial (`webhookPersonalizadoApi`), lo ejecuta [A]
   con el cliente ya conforme a la doc (docs/integrations/aveonline.md).
3. **Wompi (prod)** — dashboard Wompi → comercio → webhook de eventos: cambiar la
   URL a `https://api.konvi.co/webhooks/wompi` (path canónico vigente en
   `services/connector-whatsapp`... verificar path exacto en el router antes de
   tocar el dashboard). [F] o [A] con acceso al dashboard.
4. **Meta WhatsApp** — Meta App Dashboard → WhatsApp → Configuración → Webhook
   callback URL. [F] (consola Meta). OJO: el verify_token NO cambia.
5. **MeLi** — App de Mercado Libre → webhook de notificaciones. Condicionado a S6
   (el marketplace aún no opera).

Solo cuando TODOS los proveedores estén migrados y verificados (eventos llegando
al dominio nuevo): opcionalmente `renderSubdomainPolicy: disabled` en el
servicio — NO hacerlo antes (apagaría el subdominio onrender que hoy recibe todo).

## Consideraciones

- Mantener `APP_URL` alineado al dominio activo (hoy sigue siendo onrender para
  web; el custom domain es solo del API).
- Revisar `ALLOWED_ORIGINS` en API/connector tras cualquier cambio de dominio.
- Si algún proveedor exige verificación de dominio propia (Meta la hace por
  verify_token, no por dominio), se resuelve por proveedor en su dossier
  (`docs/integrations/`).
