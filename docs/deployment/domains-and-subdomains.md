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

El DNS de `konvi.co` vive en **Cloudflare** (NS: laylah/trevor.ns.cloudflare.com —
verificado 2026-08-27 con `dig NS konvi.co`). Pasos exactos (fuente oficial:
https://render.com/docs/configure-cloudflare-dns):

1. [Cloudflare Dashboard](https://dash.cloudflare.com) → selecciona el dominio `konvi.co`.
2. **DNS → Records → Add record**:
   - Tipo: `CNAME`
   - Nombre: `api`
   - Target: `konvi-api.onrender.com`
   - **Proxy status: `DNS only` (nube GRIS)** — OBLIGATORIO al inicio: con proxy
     activado (nube naranja) Render no puede verificar el dominio ni emitir el TLS
     (los requests irían a Cloudflare en vez de a Render). Una vez emitido el
     certificado, puedes volver a `Proxied` si quieres (opcional, la doc lo permite).
   - Save.
3. Si existiera algún registro `AAAA` para `api` (hoy no existe — el subdominio no
   resolvía antes de este paso), eliminarlo: Render usa IPv4 y los AAAA interfieren.
4. **NO tocar** los registros existentes del apex/`www` de konvi.co (hoy resuelven
   vía Cloudflare a otro destino — fuera del alcance).
5. Avisa al agente — la verificación la dispara él vía API
   (`POST …/custom-domains/{id}/verify` → 202, endpoint confirmado) y el TLS se
   emite solo (Let's Encrypt). Cuando `verificationStatus=verified` y
   `curl -sf https://api.konvi.co/health` → 200, se abre la Fase 2 (webhooks).

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
