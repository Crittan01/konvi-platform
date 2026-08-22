# PLAN DE CIERRE CONTROLADO — lo que falta, por ambiente

> Estado: VIGENTE · Creado 2026-08-19 tras cerrar S0/S7/S8 + B2 paso 10 (P0 muerto) + G23 + DB password.
> Cada ítem tiene: ambiente donde se ejecuta · owner ([F] founder dashboard / [A] agente) · pasos · verificación.
> Regla de oro (sin cambios): STG nunca escribe en PRD. PRD solo recibe código vía `git push origin develop:production` + migraciones por protocolo seguro.
> Detalle por plataforma (URLs, límites, fuentes oficiales): [`infra/environment-segregation-plan.md`](infra/environment-segregation-plan.md).

---

## Track 1 — Dinero real (habilita cobros en PRD)

| # | Ítem | Ambiente | Owner | Pasos | Verificación |
|---|---|---|---|---|---|
| 1.1 | **Wompi prod keys en KAIU** | PRD (app.konvi.co + dashboard Wompi) | [F] ejecuta · [A] verifica | (a) app.konvi.co → Ajustes → Integraciones → Wompi → ambiente **production** → pegar `prv_prod_` + `prod_events_` (el guardado valida prefijos — S0.2). (b) Dashboard Wompi ambiente **producción** → URL de eventos: `https://konvi-api.onrender.com/api/v1/webhooks/wompi` (transitorio hasta 3.1). (c) Dashboard Wompi ambiente **sandbox** → URL de eventos: la ngrok de STG (`make -C .local print-urls`) | [A] `python3.11 scripts/check_env_data_mix.py --env-file .env.prd-backup` pasa de WARN a ✅ + link de pago de prueba real (monto mínimo) llega con `environment="prod"` y firma válida |
| 1.2 | **Anular guía UAT 86732771636** | PRD (panel Aveonline) | [F] | Panel Aveonline → buscar guía → anular (no existe vía API — verificado) | [F] visual en panel |
| 1.3 | **B4 — re-certificación E2E conversacional LIVE** | PRD | [A] corre, [F] autoriza | `coherence_scenarios.py` contra el bot live (cubierto: entrega de link Wompi tras método de pago — en local lo bloquea la ausencia de courier) | 15/15 + log en `scripts/uat/runs/` |
| 1.4 | **B6 fiscal + B3 contrato (visto bueno abogado)** | PRD (legal) | [F] | Contrato ya alineado (Aveonline único, subprocesadores sin Sentry desde S8); falta visto bueno abogado | [F] firma |

## Track 2 — STG con terceros reales (pruebas de webhooks sin tocar PRD)

| # | Ítem | Ambiente | Owner | Pasos | Verificación |
|---|---|---|---|---|---|
| 2.1 | **S2 — Meta Test App + WABA de prueba** | STG | [F] crea · [A] configura tenant | (a) developers.facebook.com → app prod → menú → **Create Test App**. (b) En la Test App: agregar producto WhatsApp → número de prueba gratuito (hasta 5 destinatarios verificados — agregar el tuyo). (c) Webhook de la Test App → `https://<ngrok-connector>/api/v1/whatsapp/webhook/<tenant_stg>` + verify token nuevo. (d) System User token para la Test App (Business Settings → System Users). (e) Pasar a [A]: App ID + WABA ID de prueba (sin secretos) | [A] registro en `environments.md` + mensaje de prueba real llega al inbox STG. **Por qué obligatorio:** 2 apps en la misma WABA = webhooks duplicados; límites/calidad son por WABA |
| 2.2 | **S5 — Resend / Telegram / Gemini STG** | STG | [F] crea keys · [A] las siembra | (a) Resend → API key `konvi-stg` con permiso **Sending access** (NUNCA Full access) ✅ **HECHO 2026-08-19 + verificado con envío real a `delivered@resend.dev` por el path de código del proyecto**. `RESEND_FROM_EMAIL`: STG = `Konvi STG <onboarding@resend.dev>` (sender compartido de pruebas — los emails de UAT NUNCA salen de `konvi.co` hacia direcciones sintéticas: los bounces dañan la reputación del dominio prod [DOC Resend]); estado objetivo con dominio propio: subdominio `stg.konvi.co` verificado en Resend (registros SPF/DKIM en DNS) → `noreply@stg.konvi.co` y reputación segregada estructural. (b) @BotFather → `/newbot` `konvi_stg_bot` → token **per-tenant** (NO existe env global de bot token — `.env.example:230`: "per-tenant en Vault, la global nunca se lee"; la única global es `TELEGRAM_WEBHOOK_SECRET`). El alta se hace por la UI del tenant STG (Ajustes → Integraciones → Telegram: token + chat_id del operador) o sembrando `notification_settings` (channel='telegram', config.bot_token en Vault) ✅ **HECHO 2026-08-20: bot `@konvi_stg_bot` + grupo `Konvi STG Operadores` (chat_id `-5381900925`) + notificación de escalación real entregada al grupo por el path del proyecto (`notify_escalation_async`)** — procedimiento canónico en `docs/integrations/telegram.md`; (c) GCP → proyecto nuevo `konvi-stg` → API key restringida a Generative Language API (cuota/billing son por proyecto, no por key) ✅ **HECHO 2026-08-20 + verificado con llamada real (`gemini-3.1-flash-lite` respondió vía `_get_genai_client` con la key del proyecto nuevo)** | [A] email real de prueba STG ✅ (Resend Logs) + bot Telegram STG responde ✅ + llamada Gemini con key del proyecto STG ✅ |
| 2.3 | **S6 — MeLi app de prueba + Aveonline sandbox** | STG | [F] | (a) MeLi DevCenter → segunda app "Konvi STG" (client_id/secret propios, redirect a ngrok) + usuarios de prueba (máx 10, expiran a 60 días de inactividad). (b) Aveonline STG ya cubierto en código: cuenta demo pública + dry-run (`bloquegenerarguia="0"`) — sin acción salvo que se quiera tracking real (exigiría cuenta separada). **Trigger: cuando el marketplace entre a operación** | [A] OAuth STG completo con usuario de prueba |
| 2.4 | **M19 — verify_token tenant dev** | STG/prod tenant dev | [F] + [A] coordinado | Runbook `credential-rotation.md` §2 paso 11: rotar `konvi-dev-direct-2026` en DB y consola Meta en la misma ventana | [A] webhook del tenant dev verifica firma post-rotación. **Cierra B2 al 100%** |
| 2.5 | **Higiene WABA de prueba — desuscribir apps de prod** | Meta dashboard | [F] + [A] | La WABA de prueba `2159052118202272` tiene 4 apps suscritas: `KAIU Chat - Test` (la correcta, STG) + `KAIU Chat` y `Konvi App` (prod) + `WA DevX Webhook Events 1P App`. Con varias apps en la misma WABA, **cada una recibe su copia del webhook** → el tráfico del número de prueba puede llegar también al connector de PRD. La desuscripción (`DELETE /{WABA_ID}/subscribed_apps`) opera sobre la app dueña del token → se hace desde el contexto de CADA app de prod (su token/dashboard). **Cuándo:** al conectar el número real de KAIU (su propia WABA), o antes si se quiere limpio ya | [A] `GET /{WABA_ID}/subscribed_apps` lista solo `KAIU Chat - Test` |
| 2.6 | **Segregación formal WABA/phone por ambiente** (verificado 2026-08-19) | Meta | [F] al conectar prod | Hechos verificados: **STG** = WABA `2159052118202272` + phone `990364080831295` (número de prueba +1 555-158-4034, Test App). **PRD** = la integración WhatsApp de KAIU hoy está `disconnected` (sin WABA/phone asignados — verificado en prod DB). **Regla que queda:** cuando KAIU conecte su número real, DEBE ser una WABA + número PROPIOS, distintos de los de STG (los límites/calidad de Meta se calculan por WABA/portfolio); jamás suscribir la Test App a la WABA de prod ni viceversa | [A] al conectar prod: verificar que WABA/phone de prod ≠ STG y que `subscribed_apps` de cada WABA lista solo su app |

## Track 3 — Infraestructura PRD profesional

| # | Ítem | Ambiente | Owner | Pasos | Verificación |
|---|---|---|---|---|---|
| 3.1 | **S3 — Dominio propio del API + Render Projects** | PRD (Render + DNS) | [F] | (a) Render → konvi-api → Settings → Custom Domains → `api.konvi.co` + CNAME en DNS (TLS automático; el subdominio onrender SIGUE funcionando → transición de webhooks sin corte). (b) Crear Project con 2 environments (staging/production) + `networking.isolation` + `permissions.protection` en production. (c) Cuando el dominio responda: migrar URLs de webhook en cada proveedor (Wompi prod, Meta, Aveonline, MeLi, Telegram) y solo entonces (opcional) `renderSubdomainPolicy: disabled` | [A] `curl https://api.konvi.co/health` → 200 + eventos Wompi llegando al dominio nuevo |
| 3.2 | **Pin Python 3.13 en Render** | PRD (Render) | [F] | Settings de cada servicio Python → Python version 3.13 (compat ya verificada en CI) | [A] health post-deploy + versión en logs |
| 3.3 | **S4.3 / #16 — Dev cloud** | nuevo proyecto Supabase Free | [F] | Día del lanzamiento: proyecto Supabase dev separado + `replay_migrations_dev.sh` + `bootstrap_dev_sandbox.py` + `KONVI_SAFE_REFS=<ref>`. NOTA: al clonar PRD→dev cloud, `pg_dump` NO copia la Vault root key → re-crear secretos per-tenant (son pocos) | [A] UAT con webhooks reales sin ngrok |
| 3.4 | **G8b — migración media inbox a bucket privado** | PRD | [A] ejecuta con autorización [F] | `scripts/admin/migrate_inbox_media_private.py` dry-run → `--apply` en prod + UAT visual del inbox | [A] dry-run sin novedades + inbox renderiza adjuntos |

## Track 4 — Operación continua (post-cierre)

| # | Ítem | Ambiente | Owner | Nota |
|---|---|---|---|---|
| 4.1 | **A1 — MFA obligatorio** | PRD | [F] decide · [A] ejecuta/verifica | Runbook `mfa-mandatory-rollout.md` (día 0 / día X con gracia; rollback documentado). Flip `MFA_MANDATORY_ENABLED=true` en Render |
| 4.2 | **Plantillas Meta por tenant** | PRD | [F] contenido · [A] submit | Cuando haya copy final de plantillas |
| 4.3 | Revisión trimestral | — | [A] | IPs MeLi (trigger: primer tenant MeLi), tokens Meta System User, rotación de secretos |

---

## Track 5 — Arquitectura de dominios modulares (visión founder 2026-08-22)

La plataforma como UN todo modular para cualquier e-commerce: los dominios (catálogo, pedidos, contactos, envíos, promociones, reclamos, comprobantes, compras, finanzas, analítica, stock) son la única fuente de verdad; la consola y el bot son canales sobre ellos; packs de vertical por tipo de tienda. Documento de arquitectura: [`architecture/modular-domains-vision.md`](architecture/modular-domains-vision.md). Fases M1-M5 (inventario de capacidades → contrato de domain services → tooling generativo del bot → packs de vertical → analítica conversacional), se insertan después de B-2. Nada toca PRD sin certificar en STG.

---

## Orden recomendado (dependencias reales)

**Decisión founder 2026-08-19 — modelo STG-first:** se trabaja y certifica TODO en STG; PRD solo recibe lo ya probado. El código fluye STG → `develop` → CI verde → `production` (ya es así); la config de terceros no se promueve (vive por ambiente) — la disciplina equivalente es configurar primero en STG, certificar, y replicar en PRD. **Consecuencia aceptada:** mientras dure la Fase A, KAIU en prod sigue con llaves sandbox (sin cobros reales) — inofensivo pre-launch.

```
FASE A — STG total (cero riesgo prod, arranca ya):
  A1. S2 Meta Test App + número de prueba → webhook al connector STG (ngrok)
  A2. S5 keys STG (Resend sending-access · bot Telegram · proyecto GCP konvi-stg)
  A3. [A] Certificación E2E en STG: webhooks reales Meta vía ngrok + email Resend STG
      + Telegram STG + suite + certify_stg + escenarios conversacionales 15/15
FASE B — Integración a PRD (solo lo certificado en A):
  B1. Wompi prod keys en KAIU + URL eventos prod (dinero real) [1.1]
  B2. Dominio api.konvi.co + migración de webhooks sin corte [3.1]
  B3. B4 live · G8b · M19 · pin Python 3.13 [1.3, 3.4, 2.4, 3.2]
  B4. A1 MFA cuando el founder decida [4.1]
  B5. dev cloud, día del lanzamiento [3.3] · S6 MeLi cuando el marketplace opere [2.3]
```

**Estado al crear este plan (2026-08-19):** suite 4405 pytest + 353 vitest + tsc 0 + ruff ≤ baseline + CI 5/5 + `certify_stg.sh` 18/18 — todo verde en develop. Cerrados hoy: S8 total (código + Render + sentry.io), B2 paso 10 (legacy Supabase 401), DB password, G23 (fallbacks legacy fuera del código), dashboard Render sin vars legacy/Sentry (verificado vía API).
