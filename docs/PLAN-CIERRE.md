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

## Track 6 — Alineación total con docs oficiales de TODAS las tecnologías embebidas (directiva founder 2026-08-22)

No solo conformidad: **explotación máxima de cada plataforma según su documentación oficial vigente** (fetch live, cero suposiciones), evolucionando lo actual con mirada al futuro. Patrón de trabajo = el aplicado a Aveonline 2026-08-22 (matriz acción × doc × código, verificación live, dossier actualizado).

| Tecnología | Qué se revisa/evoluciona (ejemplos ya detectados) |
|---|---|
| **Wompi** (docs.wompi.co/docs/colombia/…) | Hoy usamos 2 de 4 llaves (prv + events, pagos por link). Registrar las 4 por tenant (**pub + integrity**) para habilitar el futuro checkout embebido/widget en una tienda online propia (Konvi Studio / custom store Fase 13) — el guard de prefijos S0.2 ya soporta validarlas. Revisar: widget-checkout-web, tokens de aceptación, presignado, reintentos de eventos, ambientes. |
| **Aveonline** | Hecho 2026-08-22 (conformidad + webhook oficial + mapping estados). Evolución: recogida programada (`generarRecogida2` — gap REC-1 registrado), sandbox oficial `avanzarEstado` para UAT de estados, catálogo homologado `tiposEstadosEnvios` cuando el token v2 esté disponible. |
| **Meta WhatsApp** | Webhook fields que hoy no consumimos, versión de API (v22 soportada hasta 2027-05-20; plan de bump), templates por tenant, calidad/messaging limits por WABA, flows interactivos (listas/botones nativos) si la doc los soporta para nuestro caso. |
| **Supabase** | Realtime (publicaciones, Authorization), Vault, branching/local, signing keys — maximizar lo que ya pagamos. |
| **Gemini** | Context caching (ahorro real de tokens por turno — gap identificado en la auditoría), structured output, grounding, rate limits por tier. |
| **Resend** | Webhooks de eventos de email (entregado/rebotado/queja) por ambiente con signing svix — alimenta analítica y reputación. |
| **Telegram** | Comandos operativos ya viven; revisar capacidades no usadas (botones inline para acciones de operador, etc.). |
| **MeLi** | Cuando el marketplace opere (S6): docs de ítems, preguntas, ventas, usuarios de prueba. |

**Salida por tecnología:** matriz capacidad × doc × estado actual → qué se adopta ahora vs qué queda diseñado para el futuro (con el punto de extensión ya preparado, p.ej. las 4 llaves Wompi en el modelo de datos).

## Track 7 — UX/UI de clase mundial (directiva founder 2026-08-22)

Mejorar ABSOLUTAMENTE la experiencia: no solo corregir bugs visuales sino elevar el estándar — login animado y memorable, módulos completos y pulidos, micro-interacciones con propósito (framer-motion ya instalado), estados vacíos/errores/cargas con diseño, móvil de primera. Referencia de sistema de diseño: `docs/ux/UX-UI.md` (Kaiu DS). Se mide contra lo que un founder esperaría de un producto SaaS top, no contra "funciona".

## Track 8 — Bot a presión (adversarial conversation suite) (directiva founder 2026-08-22)

Cuando B-1/B-2 dejen el bot versátil: batería de conversaciones DIFÍCILES en STG — cliente grosero/de mal humor, el que intenta "corchar" (descuentos inventados, "ya pagué" falso, prompt injection, pedir datos de otro cliente), lenguaje coloquial extremo/escritura rota, estrés/urgencia, cambios de tema abruptos, multi-intención en un mensaje, arrepentimientos a mitad de checkout. Cada caso: assertions de comportamiento correcto (no cede plata, no pierde la calma, no alucina, escala cuando debe). Vive dentro del harness serio (B-3) como corpus adversarial.

## Nota Platform Console (transversal a todo)

Todo lo que se construye ahora se diseña pensando en la futura **Platform Console (Fase 12)**: las métricas del bot (`/agentic/metrics`), la observabilidad mínima (B-4), los domain services (Track 5) y las capacidades de proveedores (Track 6) son la API que la consola plataforma consumirá — decisiones de diseño deben dejar ese punto de extensión abierto (nada de lógica cross-tenant hardcoded en canales).

---

## Orden de ejecución vigente (consolidado 2026-08-22 — integra Fase A/B, auditoría del bot, conformidad de proveedores y la visión de dominios)

**Reglas vigentes:** STG-first — nada pasa a PRD sin certificar en STG y sin visto bueno founder (PRD está CONGELADO desde 2026-08-21 hasta cerrar los bloques de ajuste). Todo con evidencia, cero suposiciones.

```
HOY → en curso:
  1. Track 6 — Alineación total con docs oficiales de TODAS las          [A]
     tecnologías (Wompi 4 llaves + widget futuro, Meta, Supabase, Gemini
     context caching, Resend webhooks, Telegram, MeLi). Aveonline ya
     cerrado 2026-08-22. Matriz capacidad×doc×código por tecnología.
  2. B-1 — Calidad conversacional (la queja original del founder):    [A]
     resumen rodante de conversación (amnesia estructural), routing de modelo
     por estado (lite→flash en transaccional), contradicción de longitud,
     few-shots + manejo de objeciones, gate de pago NO destructivo (F5),
     resolvers de afirmación/preguntas mid-flow (F4/F6), instrucción de cupón
     (F3), convivencia bot↔operador y salida de human_takeover (F7/F8).
  3. B-2 — Re-ingeniería del núcleo del dispatcher (state handlers por    [A]
     estado FSM, TurnContext único, TurnFinalizer único; strangler por fases,
     Fase 0 sin riesgo primero: matar V2 eager, resolver estado ANTES de
     mutaciones, borrar estados/reglas muertos).
  4. B-3 — Harness de evaluación serio: assertions de outcome en DB       [A]
     obligatorias, fail por respuesta stale, CI nocturno; corpus dorado
     (conversaciones reales anonimizadas) + LLM-judge + métricas SQL.
     INCLUYE Track 8: corpus adversarial (cliente grosero, "corchar",
     lenguaje roto, estrés, multi-intención, arrepentimientos).
  5. B-4 — Observabilidad mínima post-Sentry: cron /agentic/metrics +     [A]
     alertas Telegram (error rate, p95, tokens/día), señal Gemini caído,
     uptime externo /health. Diseñado como base de la futura Platform Console.
  6. Track 7 — UX/UI de clase mundial (login animado, módulos             [A]
     completos y pulidos, micro-interacciones framer-motion, estados
     vacíos/errores/cargas con diseño, móvil primero — contra Kaiu DS).

DESPUÉS (visión de plataforma — Track 5):
  7. M1-M5 — Dominios modulares (ver docs/architecture/modular-domains-vision.md):
     inventario de capacidades por dominio → contrato de domain services
     (pilotos: pedidos + reclamos) → tools del bot generadas del contrato →
     packs de vertical (belleza/moda/tecnología/juguetería) → analítica
     conversacional para el owner. Todo deja el punto de extensión para
     la futura Platform Console (Fase 12).

DESCONGELAR PRD (cuando 1-2 cierren en STG, mínimo):
  8. Migraciones pendientes a prod por protocolo: B-0 ×3 (20260821120000,
     …120100, …120200) + 20260822020000 (RPC idagente). Antes: SELECT de
     duplicados legacy para el pre-paso del índice B1.
  9. Deploy develop→production + verificación Render ×4 + health ×5.
 10. Smoke delgado PRD: pago real mínimo (link prod) + confirmación.
 11. Founder ops: B2 dominio api.konvi.co · M19 verify_token · desuscribir
     apps prod de la WABA de prueba (2.5) · anular guía UAT 86732771636 ·
     pin Python 3.13 · A1 MFA (cuando decida).
```

**Completado esta semana (base sobre la que se para este plan):** S8 total · B2 paso 10 (P0 muerto) · G23 · Fase A STG (Meta/Resend/Telegram/Gemini E2E) · deploy prod 2026-08-21 · auditoría profunda del bot (6 frentes, evidencia en `.audit/findings/2026-08-21-bot-deep-audit.md`) · B-0 fixes críticos de dinero/verdad · E2E bot STG certificado turno a turno · conformidad Aveonline contra doc oficial (verificada live contra cuenta demo).

**Estado al crear este plan (2026-08-19):** suite 4405 pytest + 353 vitest + tsc 0 + ruff ≤ baseline + CI 5/5 + `certify_stg.sh` 18/18 — todo verde en develop. Cerrados hoy: S8 total (código + Render + sentry.io), B2 paso 10 (legacy Supabase 401), DB password, G23 (fallbacks legacy fuera del código), dashboard Render sin vars legacy/Sentry (verificado vía API).
