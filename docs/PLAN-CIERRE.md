# PLAN DE CIERRE CONTROLADO — lo que falta, por ambiente

> Estado: VIGENTE · Reordenado 2026-08-24 (directiva founder: la plataforma primero — dominios/consola/infra — y el BLOQUE BOT AL FINAL, inclusive su GUI/API/métricas; ver §Orden de ejecución). Creado 2026-08-19.
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

**Estado al 2026-08-27 (prep del agente ejecutada con evidencia medida — detalle y decisiones en PLAN.md §E):**
- **3.4 ✅ CERRADO** — G8b aplicado en PRD: 1 objeto legado migrado a `tenant-inbox-media` + mensaje re-apuntado a `inbox-media://` + URL pública vieja cerrada (400) + signed URL 200 (la ruta de render del chat).
- **3.2 ✅ CERRADO** — `PYTHON_VERSION=3.13.15` pineado en los 3 servicios Python (fully-qualified, doc oficial Render) tras verificar compat con gate CI nuevo `py-compat-313` (suite completa bajo CPython 3.13.15 verde). Preparación honesta: la afirmación previa "compat ya verificada en CI" era falsa — ningún job corría 3.13.
- **3.1(a) ✅ CERRADO** — AMBOS dominios live 2026-08-27: `api.konvi.co/health` 200 (verified,
  TLS emitido) + `app.konvi.co/login` 200 (el founder agregó el CNAME extra por su cuenta; ya
  estaba registrado en konvi-web). Blip de ~segundos en el dominio custom durante el switchover
  de UN redeploy (recuperado solo; onrender intacto) — registrado para futuras ventanas.
  **Fase 2 (webhooks al dominio) EJECUTADA parcial:** mapeo real contra código — los 5 webhooks
  NO-Meta viven en konvi-api; solo Meta vive en el connector. `PUBLIC_WEBHOOK_URL` y
  `NEXT_PUBLIC_WEBHOOK_HOST` → `https://api.konvi.co` (render.yaml + Render API) + redeploys
  live. Por proveedor: Telegram — sin tenant prod (futuros registros ya salen por el dominio) ·
  **Aveonline — ✅ MIGRADO DE VERDAD 2026-08-28 14:00 UTC** (tras el fix RS256 en PRD:
  `POST …/custom-webhook` → 201 Created + `mechanism=custom-webhook aveonline_ok=True` en
  log + token oficial de Aveonline en DB + endpoint 401-live; el intento de 08-27 a.m. era
  el fail-silent del bug — corregido aquí) ·
  Wompi/Resend — registrar en sus dashboards con las URLs del dominio cuando activen esos
  pendientes [F] · MeLi — S6 · **Meta — queda en `konvi-connector.onrender.com`** ·
  **`connector.konvi.co` mapeado como pendiente** (activación: CNAME [F] + custom domain/vars
  [A] + Meta console por WABA [F]; costo medido: 3er dominio = $0.25/mes sobre las 2 incluidas
  del Hobby ya usadas por api+app; orchestrator NO necesita dominio — superficie HTTP solo
  interna, verificado contra `server.py`). Detalle: `docs/deployment/domains-and-subdomains.md`.
- **3.1(b)** — Project "Konvi" ya existía con 1 environment "Production". `protected`: la REST API NO lo permite (PATCH silencioso no-op / 403-405; doc oficial: solo workspace Admin desde el Dashboard) → **paso [F] de 4 clicks**: Dashboard → proyecto Konvi → menú ••• del environment Production → All settings → Permissions → Edit → **Protected** → Save (https://render.com/docs/projects). `networking.isolation`: **decisión documentada = diferir** — la doc oficial lo define como bloqueo de tráfico de red PRIVADA entre environments (no corta webhooks públicos), y sin un segundo environment en Render es un no-op; reevaluar si algún día existe staging en Render (hoy STG = local podman). **`protected` REEVALUADO 2026-08-28 = DIFERIR** (medido por el founder en el Dashboard: activarlo exige plan Pro) — con workspace de UN solo miembro (founder = único admin) no protege contra nadie adicional y contra el propio admin no aplica: es control de gobierno multi-miembro, no de seguridad. **Trigger para activarla: el primer colaborador con acceso al workspace de Render** (ahí sí paga: evita que un operador nuevo borre prod por accidente). La pregunta Pro sigue sus propios criterios en `docs/deployment/render-upgrade-path.md` (cold starts en webhooks, worker nativo, SLA) — NUNCA por este toggle.
- **3.3 [F] irreducible** — crear proyecto Supabase Free para dev cloud: https://supabase.com/dashboard → New project (región cercana, free tier) → entregar al agente: project ref, URL, publishable+secret keys y DB password. Con eso [A] ejecuta `scripts/db/replay_migrations_dev.sh` + `bootstrap_dev_sandbox.py` con `KONVI_SAFE_REFS=<ref>` + re-crea los secretos del Vault del dev (pg_dump no copia la Vault root key).

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

La plataforma como UN todo modular para cualquier e-commerce: los dominios (catálogo, pedidos, contactos, envíos, promociones, reclamos, comprobantes, compras, finanzas, analítica, stock) son la única fuente de verdad; la consola y el bot son canales sobre ellos; packs de vertical por tipo de tienda. Documento de arquitectura: [`architecture/modular-domains-vision.md`](architecture/modular-domains-vision.md). Fases M1-M5 (inventario de capacidades → contrato de domain services → tooling generativo del bot → packs de vertical → analítica conversacional). **Por el REORDEN founder 2026-08-24 (PLAN-CIERRE §Orden): los dominios van PRIMERO y el bloque bot AL FINAL — M3 (tools del bot generadas del contrato) es exactamente la razón.** Nada toca PRD sin certificar en STG.

---

## Track 9 — Seguridad DB: RLS/grants hardening (directiva founder 2026-08-22; hallazgos verificados por muestreo contra DB live 2026-08-22)

> **✅ CERRADO EN STG 2026-08-22** — 4 migraciones (`20260822120000` C1 · `20260822120100` A1-A9 · `20260822120200` M1-M14 · `20260822120300` bajos+causa raíz) + 113 tests dbharness de ataque nuevos (cada exploit verificado ANTES — fallaba — y DESPUÉS — pasa) + guard CI (`scripts/check_secdef_grants.py` en validate.sh §4.7 + barrido vivo `test_track9_secdef_hygiene.py`). Ajustes de alcance contra el pre-planteo (todo verificado en DB real, detalle y evidencia en bitácora PLAN.md §E): "9 funciones sin search_path" → eran **4** SECDEF · A7 resuelto con **vista `payments_safe`** (payments owner-only + página de pedido migra a la vista — la alternativa del plan que no rompe consola) · M14-storage sin acción (tenant-media vacío y en uso legítimo por catálogo) · causa raíz cerrada con **event trigger** `track9_revoke_public_on_new_function` (se demostró empíricamente que `ALTER DEFAULT PRIVILEGES` NO quita el built-in PUBLIC EXECUTE de funciones nuevas). Hallazgo de entorno: **el Postgres 17.6 del build local crashea (signal 11) al denegar EXECUTE de función** — los tests de grants verifican por catálogo, no por ejecución (patrón ya vigente en el repo). Migraciones pendientes de aplicar a PRD en el descongelamiento (§Orden paso 9).

Hallazgos de auditoría RLS/grants (el muestreo confirmó el patrón: funciones SECURITY DEFINER con EXECUTE a `authenticated`). Patrón de fix: REVOKE PUBLIC/anon/authenticated + GRANT solo `service_role` (o guarda de membresía/rol), **cada fix con su test dbharness que simula el ataque** (la red ya existe en tests/dbharness). Orden por severidad:

**Crítico:**
- C1 — `dequeue_human_takeover_notifications` / `ack_human_takeover_notification`: PII cross-tenant + DoS de escalaciones humanas → REVOKE a service_role (el caller es el worker).

**Altos:**
- A1 — `rpc_meli_*_refresh_lease` (×3): robo de lease + marcar integración MeLi de otro tenant en error → REVOKE a service_role.
- A2 — `upsert_aveonline_jwt`: escritura cross-tenant de credenciales del carrier → REVOKE a service_role (verificar que el worker lo usa con service_role).
- A3 — `fn_record_shipment_tracking_event`: manipulación de estados de envío + forenses falsos → REVOKE authenticated (webhooks usan service_role).
- A4 — `consume_tenant_capability`: DoS de cuotas cross-tenant → REVOKE o guarda `app_current_tenant()`.
- A5 — claims: UPDATE/DELETE por operator sobre dinero del cliente → policies RESTRICTIVE (update solo owner/manager; delete nadie).
- A6 — order_cancellations: "append-only" declarado pero mutable → RESTRICTIVE UPDATE/DELETE false.
- A7 — payments: lectura financiera/PII sin gate de rol → owner-only (o vista proyectada sin raw_webhook).
- A8 — api_security_events mutable → patrón append-only (REVOKE + trigger + service_role).
- A9 — miembros `status='inactive'` conservan acceso (pgsec_*, ai_agents, storage policies, etc.) → añadir `status='active'` a todos los gates basados en tenant_users o migrar a `app_current_role()`.

**Medios (M1-M14):** integration_oauth_states, idempotency_keys, wompi_events_seen, tenant_usage_*, escritura sin rol en configs críticas (tenant_shipping_provider_config con real_guides_enabled!, tenant_cancellation_policy, rma, marketplace_listings, shipments, order_tracking), notification_settings.config con bot_token legible, messages/conversations/contacts sin lockdown, conversation_notes sin WITH CHECK, outbound_idempotency_* sin search_path/revoke, retención de pii_access_log rota por trigger incondicional, get_aveonline_credentials sin gate de rol, reversion_procede oráculo cross-tenant, storage legacy tenant-media público (ampliar purge hard-delete).

**Bajos:** rol stale desde JWT claim → `app_current_role()` fresco; RESTRICTIVE que no cubre DELETE; user_dismissed_alerts sin WITH CHECK; bot_source_log mutable; 9 funciones sin SET search_path; mfa_recovery_codes; overloads legacy por dropear; grants ALL+TRUNCATE residuales en tablas de auditoría.

**Guard para no repetir la ola (mi adición):** lint en CI que falle si una migración crea función SECURITY DEFINER sin REVOKE explícito de PUBLIC/anon o sin SET search_path — la causa raíz sistémica.

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

> **✅ IMPLEMENTADO dentro de B-3 (2026-08-23)** — corpus adversarial en `coherence_scenarios.py` (10 escenarios `t8_*`: grosero, corchar/descuento inventado, prompt injection, PII ajena, lenguaje roto, estrés/urgencia, cambio abrupto, multi-intención, arrepentimiento mid-checkout, "ya pagué" falso) con assertions de comportamiento correcto verificadas contra DB (no cede plata — `check_no_discount_without_coupon`; no confirma pago falso — `check_no_fake_payment_confirmation`; escala de verdad — `check_real_escalation` sobre `human_takeover` en DB). La deuda encontrada quedó codificada como xfails auditables (H1-H8) para el bloque bot.

Cuando B-1/B-2 dejen el bot versátil: batería de conversaciones DIFÍCILES en STG — cliente grosero/de mal humor, el que intenta "corchar" (descuentos inventados, "ya pagué" falso, prompt injection, pedir datos de otro cliente), lenguaje coloquial extremo/escritura rota, estrés/urgencia, cambios de tema abruptos, multi-intención en un mensaje, arrepentimientos a mitad de checkout. Cada caso: assertions de comportamiento correcto (no cede plata, no pierde la calma, no alucina, escala cuando debe). Vive dentro del harness serio (B-3) como corpus adversarial.

## Nota Platform Console (transversal a todo)

Todo lo que se construye ahora se diseña pensando en la futura **Platform Console (Fase 12)**: las métricas del bot (`/agentic/metrics`), la observabilidad mínima (B-4), los domain services (Track 5) y las capacidades de proveedores (Track 6) son la API que la consola plataforma consumirá — decisiones de diseño deben dejar ese punto de extensión abierto (nada de lógica cross-tenant hardcoded en canales).

---

## Orden de ejecución vigente (consolidado 2026-08-24 — REORDEN founder: la plataforma primero, el BOT AL FINAL)

**Reglas vigentes:** STG-first — nada pasa a PRD sin certificar en STG y sin visto bueno founder. Todo con evidencia, cero suposiciones. PRD descongelado 2026-08-22; el smoke de dinero real sigue aplazado al cierre (la certificación de dinero la hace el harness turno a turno en STG).

**Por qué el BOT va al final (directiva founder 2026-08-24):** el bot es el mayor CONSUMIDOR de las superficies de dominio (inventario, reclamos, órdenes, pagos, catálogo, endpoints de API). Re-ingenierizar su núcleo mientras esas superficies se mueven (dominios modulares, consola, API) es construir sobre blanco en movimiento: cada cambio de contrato rompe los supuestos del bot. La propia visión Track 5 ya lo declara: las tools del bot se GENERAN del contrato de dominios (M3) — el bot correcto solo se construye sobre contratos estables. **Lo que hace seguro este reorden: B-3 (cerrado 2026-08-23/24) deja la red de seguridad — harness serio con assertions de outcome en DB + corpus adversarial Track 8 + CI nocturno + corpus dorado + LLM-judge — que certifica en cada noche que el bot ACTUAL sigue verde mientras la plataforma evoluciona debajo.**

**Matiz sobre el harness (objeción founder 2026-08-24: "el harness mide al bot — ¿no es tema bot?"):** sí, y tiene DOS capas con destinos distintos que NO hay que confundir:
1. **Framework (desacoplado del bot)** — runner, `TurnCtx`, assertions de outcome contra DB, aislamiento fail-closed, CI nocturno, LLM-judge, métricas SQL. Mide verdad en DB + texto observable; no depende del núcleo interno del bot. **Persiste intacta a través de B-2** y es además el instrumento de aceptación DEL bloque bot (B-2 es migración strangler que preserva comportamiento — sin esta red, esa migración va a ciegas).
2. **Capa de escenarios (acoplada al bot actual)** — los 28 escenarios codifican el comportamiento observable de HOY. Cuando B-2/M3 cambien el núcleo y las tools se generen del contrato de dominios, ESTA capa se revisa/reescrive donde aplique. Es deuda conocida y barata: los xfails H1-H8 ya son la cola de comportamiento a corregir, y el runner obliga a retirarlos (XPASS).

Conclusión documentada: el harness NO va al bloque bot porque la fase plataforma sin él deja al bot sin certificación continua (el riesgo exacto del reorden). Lo que SÍ va al bloque bot es la revisión de la capa de escenarios — registrado como parte del paso 7 (B-2).

**CERRADOS (base sobre la que se para este plan):** S8 · B2 paso 10 (P0 muerto) · G23 · Fase A STG (Meta/Resend/Telegram/Gemini) · Track 9 (seguridad DB, aplicado a PRD) · Track 6 (alineación docs oficiales 6/6) · B-1 (calidad conversacional) · B-3 (harness serio + Track 8) · descongelamiento PRD (deploy `eec5534f`).

```
AHORA — la plataforma primero:
  1. Track 5 (M1-M5) — Dominios modulares [A]: inventario de capacidades por
     dominio → contrato de domain services (pilotos: pedidos + reclamos) →
     tooling generativo → packs de vertical → analítica conversacional.
     Es la fuente de verdad que el bot consumirá — por eso va primero.
  2. Track 7 — UX/UI de clase mundial [A]: consola del tenant completa y
     pulida contra Kaiu DS (login, módulos, inbox, móvil).
  3. Track 3 — Infra PRD profesional [F/A]: dominio api.konvi.co + Render
     Projects (3.1) · pin Python 3.13 (3.2) · dev cloud (3.3) · G8b media
     privada (3.4).
  4. Track 1+2 remanentes [F]: Wompi prod keys (1.1) · anular guía UAT (1.2)
     · B6/B3 legal (1.4) · S6 MeLi (2.3) · M19 verify_token (2.4) · WABA
     hygiene (2.5) · smoke dinero real PRD (al cierre, con todo certificado).
  5. Track 4 — Operación continua: A1 MFA (cuando [F] decida) · plantillas
     Meta por tenant · revisión trimestral.

AL FINAL — BLOQUE BOT (TODO el bot, inclusive su GUI, API y métricas):
  6. Entrada: inventario de inclusiones parche del bot → formulación
     arquitectónica (validación pedida por founder 2026-08-23; los agentes
     explore cayeron por cuota — los briefs quedan en
     .audit/findings/2026-08-23-patch-inventory-brief.md como primer paso).
  7. B-2 — Re-ingeniería del núcleo del dispatcher (state handlers por estado
     FSM + TurnContext único + TurnFinalizer único; strangler por fases, Fase 0
     sin riesgo primero) SOBRE los contratos de dominio ya estables. Resuelve
     la deuda conversacional H1-H8 (codificada como xfails del harness — el
     runner obliga a retirar cada xfail cuando el comportamiento se corrija).
  8. B-4 — Observabilidad/métricas del bot post-Sentry: cron /agentic/metrics
     + alertas Telegram + decisión canary (AGENTIC_STATE_ROUTING_ENABLED /
     AGENTIC_TOOL_VALIDATED_ENABLED se vuelven default solo con la telemetría
     acumulada en agentic_shadow_log — medir con
     scripts/uat/agentic_quality_metrics.py).
  9. Bot GUI/API/métricas en la consola del tenant (inbox, controles,
     evidencia) — con Track 7 ya cerrado y la Platform Console como destino
     (Fase 12 sigue fuera de alcance — OQ-P01).
```

**Completado la semana del 2026-08-17→24 (base certificada):** S8 total · B2 paso 10 · G23 · Fase A STG · Track 9 (STG + PRD) · Track 6 (6/6) · B-1 · B-3 (harness serio + Track 8 + E2E real de verificación + fix arquitectónico de cortesía en el embudo OutputValidator) · suite 4.707 pytest + 316 dbharness + 363 vitest · certify_stg 18/18 · CI 5/5.
