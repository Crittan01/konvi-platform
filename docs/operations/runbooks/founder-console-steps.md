# Pasos pendientes del founder (consolas externas) — Track 1/2 remanentes + Track 4

> Consolidado 2026-08-28. Cada paso: qué es, clicks exactos con fuente oficial,
> y qué valido/certifico yo (el agente) después de tu confirmación. Nada aquí es
> suposición: lo que no tiene fuente pública verificable está marcado como tal.
> Orden sugerido = el de esta lista (por deadline e impacto).

---

## 1. ⚠️ Deadline Meta 2026-09-30 — método de pago en cada WABA

**Qué es:** desde 2026-10-01 los service messages (free-form en ventana 24h — TODO
el tráfico del bot y operadores) se cobran, y una WABA **sin método de pago
registrado al 2026-09-30 deja de recibir TODOS los service messages**. Model B:
cada tenant tiene su WABA → cada WABA necesita su método de pago.
Fuente: [doc oficial Meta pricing/non-template-messages](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/non-template-messages) (Track 6, fetch 2026-08-22) + `docs/integrations/whatsapp-meta.md`.

**Pasos (por cada WABA de tenant, empezando por la de KAIU):**
1. [WhatsApp Manager](https://business.facebook.com/wa/manage/home/) → selecciona la WABA.
2. **Configuración de la cuenta** (Account settings) → **Métodos de pago**.
3. **Agregar método de pago** (tarjeta) → guardar.

**Mi validación después:** `GET /{waba_id}` vía Graph API con el System User token —
campo de billing. Y la verificación dura: el primer service message post-2026-10-01
llegando sin error 131049/131026 de cobro. Registro el resultado en whatsapp-meta.md.

## 2. WABA hygiene — desuscribir el app PROD de la WABA de prueba

**Qué es:** la WABA de prueba `2159052118202272` (STG) tiene 3 apps suscritas
(medido hoy vía `GET /{waba}/subscribed_apps` con el System User token de STG):
`KAIU Chat - Test` (912826941411258 — la de STG, **se queda**), `WA DevX Webhook
Events 1P App` (app propia de Meta — benigna) y **`KAIU Chat` (2024793711712790 —
el app de PROD: sale)**. Dos apps sobre la misma WABA = webhooks duplicados
(hallazgo del plan de segregación S2, 2026-08-16).

**Pasos (consola Meta del app de PROD):**
1. [developers.facebook.com/apps/2024793711712790](https://developers.facebook.com/apps/2024793711712790) (app "KAIU Chat").
2. **WhatsApp → Configuración de API** → la suscripción a la WABA de prueba
   `2159052118202272` → desuscribir.
   (Alternativa por API si me pasas el System User token del app prod:
   `DELETE /{waba_id}/subscribed_apps` con ESE token — la API desuscribe el app
   del token, [doc de referencia del endpoint](https://developers.facebook.com/docs/whatsapp/business-management-api/manage-phone-numbers). NO la ejecuto con el
   token de STG: eso desuscribiría el app de prueba y rompería STG.)

**Mi validación después:** re-corro `GET /{waba}/subscribed_apps` — deben quedar
solo `KAIU Chat - Test` (+ la 1P de Meta). El tráfico STG se verifica con un
mensaje real al número de prueba.

## 3. M19 — rotar el verify_token dev (cierra la fila B2)

**Qué es:** el verify_token dev `konvi-dev-direct-2026` quedó en claro en una
migración backfill del repo (`20260622_…_backfill_konvi_dev.sql:11`).
**Runbook ejecutable ya escrito:** `docs/operations/runbooks/credential-rotation.md`
§2 **paso 11** — exige actualizar la consola Meta del tenant dev Y la DB en la
misma ventana (si se hace un solo lado, el webhook del tenant dev queda roto).

**Pasos:** seguir el paso 11 del runbook (console Meta del tenant dev + yo actualizo
la fila en DB en la misma ventana — coordinado contigo en vivo).

**Mi validación:** handshake del webhook con el token nuevo (GET verify → 200) +
mensaje real al número de prueba STG llegando al inbox.

## 4. Anular la guía UAT 86732771636

**Qué es:** la guía real de UAT (COORDINADORA, $7.530, generada 2026-08-03) sigue
viva en la cuenta Aveonline. **La anulación individual NO existe por API**
(verificado dos veces: UAT 2026-08-03 `cancelarGuia` "parametro incorrecto" +
dossier CAN-1 reconfirmado 2026-08-22 — sin página en el devsite). Solo panel.

**Pasos:** [panel Aveonline](https://guias.aveonline.co) → sección de guías →
buscar la **86732771636** → anular/cancelar. (No hay fuente pública para el label
exacto del botón — es su panel autenticado; si el label difiere, me dices cuál
es y lo documento.)

**Mi validación después:** la guía en nuestra DB pasa a `cancelled` (vía webhook
`ANULADA` — ahora sí registrado y funcional tras el fix RS256 — o vía polling de
estados) + timeline del pedido refleja la anulación.

## 5. Resend — registrar el webhook de eventos (STG + PRD)

**Qué es:** el receptor `POST /api/v1/webhooks/resend` está desplegado (Track 6)
pero el webhook nunca se registró en el dashboard Resend (la key STG es
sending_access y no gestiona webhooks — 401 verificado 2026-08-22).
Fuente: `docs/integrations/resend.md` §2 + [docs Resend webhooks](https://resend.com/docs/dashboard/webhooks/introduction).

**Pasos (por ambiente — STG y prod):**
1. [resend.com/webhooks](https://resend.com/webhooks) → **Add webhook**.
2. URL: `https://api.konvi.co/api/v1/webhooks/resend` (prod) — para STG la del
   túnel vigente (hoy: `https://francesco-unoiled-damion.ngrok-free.dev/api/v1/webhooks/resend`).
3. Eventos: `email.*` (sent/delivered/bounced/complained/failed/suppressed).
4. Copiar el **signing secret** (`whsec_…`) que Resend muestra al crearlo y
   pasármelo (o pegarlo en Render tú mismo: servicio `konvi-api` → env
   `RESEND_WEBHOOK_SECRET`).

**Mi validación después:** seteo/verifico la env var en Render vía API + redeploy si
hace falta + te hago llegar un evento de prueba (un email real de comprobante en
STG) → debe aparecer la fila en `email_events` con firma válida + dedup.

## 6. Wompi prod keys (Track 1.1 — cuando un tenant pase a operativo)

**Qué es:** el flujo de payment links ya está LIVE en prod para cualquier tenant
que cargue llaves productivas (dossier `docs/integrations/wompi.md`). La activación
comercial es tuya (B6): el nombre del comercio en Wompi debe ser **"KONVI"**
(constraint #2 de la Fase 0 fiscal: una cuenta Wompi = un nombre comercial).
Fuente: [docs.wompi.co ambientes-y-llaves](https://docs.wompi.co/en/docs/colombia/ambientes-y-llaves/) (Track 6, revalidada 2026-08-22).

**Pasos:**
1. [dashboard.wompi.co](https://dashboard.wompi.co) → el comercio KONVI →
   **llaves de producción** (`prv_prod_…`, `prod_events_…`; opcionales
   `pub_prod_…` + integrity para el futuro checkout embebido).
2. Consola prod → **Integraciones → Wompi** → pegar llaves (environment
   `production`) → guardar.
3. En el dashboard Wompi (prod): registrar el webhook de eventos con la URL
   `https://api.konvi.co/api/v1/webhooks/wompi`.

**Mi validación después:** 1 transacción real con reconciliación 3 capas
(link generado → pago → webhook → orden confirmed) — es el "smoke de dinero real"
del cierre (Track 1, al final con todo certificado).

## 7. S6 — App de prueba Mercado Libre

**Qué es:** condición para que el marketplace opere (Track 2). MeLi **no tiene
sandbox** — se prueba con test users en prod (máx 10 por app, expiran a los 60
días). Fuente: `docs/infra/environment-segregation-plan.md` §S6 (verificado
2026-08-16) + [doc MeLi test users](https://developers.mercadolibre.com.co/es_ar/testing).

**Pasos:**
1. [dev.mercadolibre.com](https://developers.mercadolibre.com) → **Crear aplicación**
   de prueba para KAIU (o usar la app existente si ya la creaste).
2. Generar 2 **test users** (vendedor + comprador) en la app.
3. Pasarme el app id + los test users creados.

**Mi validación después:** OAuth del test user vendedor contra nuestro conector +
1 publicación de prueba + sync de stock medido.

## 8. B3 — visto bueno legal del contrato tenant

**Qué es:** `docs/legal/contract-template-tenant.md` ya declara Aveonline único
operador (corregido 2026-08-02). Falta el visto bueno de tu abogado antes de
firmar con tenants. Externo al repo — sin validación técnica de mi parte; al
cerrarlo actualizo PLAN.md §A.

## 9. B6 — Fase 0 fiscal (6 acciones externas)

Sin cambios: contador SaaS · facturación DIAN activa · pólizas E&O + Cyber ·
abogado revisó contrato tipo (solapa con #8) · nombre comercio Wompi = "KONVI" ·
autodiagnóstico exclusión IVA cloud. Constraints y triggers SAS:
`.context/04-next-steps.md` §"Fase 0 fiscal".

## 10. A1 — MFA obligatorio (Track 4, cuando decidas)

Runbook ejecutable ya escrito: `docs/operations/runbooks/mfa-mandatory-rollout.md`
(día 0 / día X con gracia, rollback documentado). Flip `MFA_MANDATORY_ENABLED=true`
en Render. Lo ejecuto yo con tu visto bueno del día y la ventana de gracia.

---

*Cuando completes cualquiera, dímelo y corro su validación — cada cierre queda
registrado en `docs/PLAN.md` §E + los documentos vivos.*
