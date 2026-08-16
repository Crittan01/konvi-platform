# Plan de trabajo — Segregación TOTAL de ambientes (código + plataformas)

**Estado: VIGENTE · Investigación verificada contra documentación oficial 2026-08-16 (6 frentes, ~70 URLs oficiales citadas al final).**
**Relación con otros docs:** el DISEÑO (qué separa cada ambiente en el código) está en [`environment-segregation.md`](environment-segregation.md); el ESTADO operativo de los ambientes está en [`environments.md`](environments.md). **ESTE documento es el PLAN DE TRABAJO**: qué hay que configurar en el dashboard de cada plataforma, en qué orden, quién lo ejecuta y cómo se verifica — sin suposiciones.

> Origen: decisión founder 2026-08-16 — "la parte de Wompi no se ha hecho pensando en la segregación total; hay que validar no solo el código sino las tecnologías integradas (Render, Resend, Supabase…), con documentación real y vigente, sin suposición".

---

## 0. Principio rector (qué significa "segregación total")

La segregación de ambientes NO se logra solo en el repo. Se logra en **tres capas**, y las tres deben cerrarse:

1. **Código** — ya verificado (environment-segregation.md): routing per-tenant, guards, sin URLs de túnel en prod.
2. **Datos** — ya parcialmente cerrado: `scripts/check_env_data_mix.py` (fail-closed STG, WARN PRD).
3. **PLATAFORMAS EXTERNAS** — alcance de este plan: cada proveedor tiene su propio mecanismo de ambientes (o no tiene ninguno), y hay que configurarlo deliberadamente. **Esto es lo que faltaba mapear.**

Regla de oro (sin cambios): STG nunca escribe en PRD. PRD solo recibe código vía `git push origin develop:production` y migraciones por protocolo seguro.

---

## 1. Matriz de plataformas — qué ofrece cada una (verificado, no supuesto)

| Plataforma | Mecanismo de ambientes que OFRECE | Webhook por ambiente | Riesgo residual si no se configura |
|---|---|---|---|
| **Wompi** | 2 ambientes reales (sandbox/prod) bajo UNA cuenta; 4 llaves por ambiente (`pub/prv/events/integrity` × `test`/`prod`) | **Sí — URL de eventos distinta por ambiente; la doc lo EXIGE** para evitar mezcla | Misma cuenta alberga secretos prod y test; 1 sola URL por ambiente; prod requiere activación por Wompi (RUT + cuenta bancaria) |
| **Meta WhatsApp** | NO hay ambientes nativos. Piezas: App mode Dev/Live, **Test Apps** (hijas, máx 50), número de prueba (5 destinatarios verificados) | 1 callback URL por App; override por WABA/número vía API (pero templates/cuenta NO se pueden desviar) | 2 apps sobre la misma WABA = webhooks DUPLICADOS; límites/calidad son a nivel WABA/portfolio → STG y PRD exigen **WABA + número distintos** |
| **Mercado Libre** | NO hay sandbox. Apps múltiples por cuenta + **usuarios de prueba en producción** (máx 10, expiran a 60 días de inactividad) | Sí — callback URL + tópicos **por aplicación** | Webhooks sin firma: única defensa = allowlist de 4 IPs fijas (revisión trimestral vencida 2026-07-28 — gap A3) |
| **Aveonline** | NO hay host sandbox. Sí hay "API Sandbox" documentado (2026): empresas demo 6077/25505 sobre infra PROD, simulación de estados (`avanzarEstado`), `noGenerarEnvio=1`, `bloquegenerarguia="0"` dry-run | NO por ambiente — **un solo webhook por empresa** (upsert por token) | Segregación total exige **cuenta Aveonline separada** para STG; el sandbox demo es compartido entre todos los integradores |
| **Resend** | NO hay test mode. Keys múltiples con permisos (`sending_access`), dominios/subdominios múltiples, test addresses `@resend.dev` | Sí — webhook por endpoint con signing secret svix propio | Sin aislación real: una key `full_access` de STG puede tocar dominios de PRD → mitigar con `sending_access` |
| **Telegram** | **Nativa y gratis**: un bot por ambiente vía @BotFather (la doc lo recomienda) | Sí — `setWebhook` por bot con `secret_token` verificable | Un bot = un solo webhook → bots separados es OBLIGATORIO, no opcional |
| **Gemini** | NO hay sandbox. Rate limits y billing son **por proyecto GCP, no por API key** | N/A | 2 keys en el mismo proyecto NO segregan cuota ni gasto → STG exige **proyecto GCP separado**. Free tier entrena con tus datos → prohibido con datos de clientes |
| **Supabase** | **Patrón oficial: proyectos separados** (staging + prod). Branching existe (pago, data-less). CLI local gratis | N/A | Legacy `anon`/`service_role` **YA NO ROTAN** — la vía es publishable/secret + JWT signing keys (pasos exactos en §3.4). Free se pausa a 7 días de inactividad |
| **Render** | Projects/Environments (aislamiento de red + protección), Env Groups con scope por ambiente, Preview Envs (Pro+). Modelo 1 servicio = 1 rama | N/A (los webhooks se registran en cada proveedor) | Aislamiento es lógico y opt-in (default `disabled`); sin scope, un env group puede linkearse a cualquier servicio → mezcla |

**Conclusión de la investigación:** solo Wompi, Telegram y Supabase ofrecen segregación estructural real. Meta, MeLi, Resend y Gemini exigen **recursos duplicados por ambiente** (app/bot/proyecto/dominio separados). Aveonline no ofrece nada a nivel cuenta: la segregación STG es el dry-run (`bloquegenerarguia="0"`) ya implementado en código, y la total exige cuenta separada.

---

## 2. Estado actual de Konvi (verificado contra código 2026-08-16)

| Plataforma | Estado STG | Estado PRD | Brecha |
|---|---|---|---|
| Wompi | Sin integración en la DB sintética (verificado con guard) | KAIU `connected` en **sandbox** (WARN del guard) | Sin llaves prod; URL de eventos no registrada pensando en segregación |
| Meta | Tenant sandbox con app dev | App prod del tenant | Sin Test App / WABA de prueba formal para STG |
| Aveonline | Dry-run por doble compuerta (código) | Guías reales activas (B1 cerrado) | Webhook único por empresa — misma URL para ambos |
| MeLi | Sin app de prueba | App de plataforma configurada | Falta app STG + usuarios de prueba |
| Resend | Sin key → simula | Key prod rotada (B2 paso 4 ✅) | Sin key STG `sending_access` |
| Telegram | — | Bot prod | Sin bot de prueba |
| Gemini | Key dev (auth key restringida ✅) | Key prod rotada (B2 paso 3 ✅) | Mismo proyecto GCP comparte cuota (a evaluar) |
| Supabase | Local podman OSS ✅ | Cloud con keys nuevas (B2 paso 2 ✅) | Legacy aún VIVAS (B2 paso 10 pendiente — mata P0) |
| Render | — | 4 servicios Starter, rama `production` | Sin Projects/Environments ni network isolation; sin dominio propio |

---

## 3. Plan de trabajo por fases

Convención: **[A]** = ejecuta el agente (código/tests/docs) · **[F]** = founder HITL (dashboard externo) · **[A+F]** = mixto. Cada paso lleva su verificación. Dependencias explícitas.

### FASE S0 — Endurecimiento de código derivado de la investigación [A] (sin dependencias)

1. **[A] Webhook Wompi: validación defensiva del campo `environment`.** Wompi envía `environment: "test"|"prod"` en cada evento [DOC eventos]. Hoy la segregación es implícita (el checksum solo pasa con el events_key del ambiente correcto). Agregar: rechazar (log + 400, sin marcar inbox procesado) si `payload.environment` no corresponde con el `meta.environment` del tenant resuelto ("test"↔sandbox, "prod"↔production). Defensa en profundidad contra mala configuración de llaves. Tests: evento cross-environment rechazado aunque la firma sea válida.
2. **[A] Config Wompi: validación de par llave/ambiente al guardar.** El riesgo documentado: `pub_test_` contra `production.wompi.co` es un error de configuración posible. Al escribir `tenant_integrations` Wompi (endpoint de configuración), rechazar si el prefijo de la llave (`pub_test_`/`prv_test_` vs `pub_prod_`/`prv_prod_`) no coincide con `meta.environment`. Tests de ambos cruces.
3. **[A] Actualizar dossier Aveonline §12.** La investigación 2026-05-21 ("no existe sandbox") sigue siendo cierta a nivel host, pero hoy EXISTE documentado un "API Sandbox" (empresas demo 6077/25505, `avanzarEstado`, `noGenerarEnvio=1`) — agregar addendum con fecha y URLs. Registrar que el webhook es único por empresa (upsert).
4. **[A] Registrar re-verificación MeLi.** El devsite de MeLi devolvía HTTP 500 global el 2026-08-16; los hallazgos vienen de snapshots oficiales archivados. Tarea: re-verificar cuando se recupere + ejecutar la revisión trimestral de IPs de notificaciones (gap A3, vencida 2026-07-28): las 4 IPs documentadas hoy son 54.88.218.97, 18.215.140.160, 18.213.114.129, 18.206.34.84.

### FASE S1 — Wompi [F con verificación A] (bloquea B2 paso 6)

Diseño destino (por doc oficial): la **misma cuenta** de comercio alberga ambos ambientes; cada uno tiene su URL de eventos propia. STG usa las llaves `test` + URL STG; PRD usa las llaves `prod` + URL PRD.

1. **[F] Completar vinculación de producción** (RUT + cuenta bancaria en comercios.wompi.co) y esperar el correo de activación — depende de Wompi, fuera de nuestro control. Verificación: llaves `prod_*` visibles en "Mi cuenta → Secretos para integración técnica".
2. **[F] Registrar URL de eventos PRD** en el dashboard (ambiente producción): `https://konvi-api.onrender.com/api/v1/webhooks/wompi` (o el dominio propio cuando exista — ver S3). **[F] Registrar URL de eventos STG** (ambiente sandbox): la URL ngrok/dev-cloud del ambiente de pruebas.
3. **[F] Cargar llaves prod en el Vault del tenant PRD** (KAIU): `prv_prod_` + `prod_events_` (+ `prod_integrity_` si se usa widget) y flip `meta.environment='production'`. Verificación [A]: `check_env_data_mix.py --env-file .env.prd-backup` pasa de WARN a ✅; link de pago de prueba real (monto mínimo) → evento recibido con `environment="prod"` y firma válida.
4. **[F] Cargar llaves test en el tenant STG** y probar con tarjetas documentadas (`4242…`→APPROVED, `4111…`→DECLINED). Verificación [A]: guard STG exit 0.
5. **Nota de operación:** Wompi reintenta eventos 3 veces en 24h (30 min, 3h, 24h) si no recibe HTTP 200 — cambiar la URL de eventos tiene ventana ciega máxima de 30 min. No documentado versionado/doble entrega: el cambio es atómico por ambiente.

### FASE S2 — Meta WhatsApp [F] (puede paralelizar con S1)

1. **[F] Crear Test App** hija de la app de producción (App Dashboard → menú de la app → Create Test App; hereda config, siempre en Development mode, máx 50). Alternativa aceptada: app dev independiente ya existente para el tenant sandbox.
2. **[F] WABA/número de prueba para STG** — OBLIGATORIO separar: la doc confirma que 2 apps suscritas a la misma WABA reciben webhooks duplicados y que límites/calidad se calculan por WABA/portfolio. El número de prueba gratuito permite enviar a hasta 5 destinatarios verificados (dato de snapshot 2024; la doc vigente no reafirma el número — validar en el panel).
3. **[F] Configurar webhook de la Test App** → connector STG (`{ngrok}/api/v1/whatsapp/webhook/{tenant_stg}`). Opción avanzada documentada: override de callback por WABA/número vía `POST /<WABA_ID>/subscribed_apps` — NO adoptar como mecanismo principal: templates y eventos de cuenta no se pueden desviar.
4. **[F] System User token separado para la Test App** (Business Settings → System Users → Generate token, misma mecánica que B2 paso 5). Consideración: la caducidad "60 días/nunca" solo consta en UI, no en texto oficial [NO-DOC] — calendarizar verificación trimestral del token.
5. **[A] Registrar en environments.md** los IDs de la Test App/WABA de prueba (sin secretos).
6. **Dato de gobierno [DOC]:** Graph API **v22.0 (la del proyecto) tiene soporte hasta 2027-05-20**; vigente v26.0. Sin acción inmediata; entra en la revisión trimestral.

### FASE S3 — Render + dominio propio [F] (OQ-4; desbloquea URLs canónicas de webhooks)

1. **[F] Crear Project con 2 environments** (staging/production) en Render: habilita `networking.isolation` (que STG no pueda alcanzar recursos de PRD) y `permissions.protection` en production (solo admins hacen cambios destructivos). Hobby permite 2 environments por proyecto — suficiente.
2. **[F] Env Groups con scope por ambiente**: mover las vars compartidas a grupos con scope al environment correspondiente (la doc confirma que un grupo con scope NO puede linkearse fuera de su ambiente — es la barrera anti-mezcla de Render). Regla: nunca solapar keys entre grupos (precedencia entre grupos no garantizada [DOC]).
3. **[F] Custom domain** `api.konvi.com` (o el dominio definitivo): agregar en Settings → Custom Domains, DNS, verificación, TLS automático. **NO deshabilitar el subdominio onrender.com de inmediato** — la doc confirma que el servicio conserva ambos; eso permite transición de webhooks sin corte: registrar el dominio nuevo en cada proveedor, verificar, y solo entonces (opcional) `renderSubdomainPolicy: disabled`.
4. **[F] Actualizar URLs de webhook en cada proveedor** al dominio propio (Wompi prod, Meta app prod, Aveonline, MeLi, Telegram) — Render no gestiona esto; es manual por proveedor [INFERIDO confirmado: Render no documenta nada al respecto].
5. **[A] Actualizar `.env.example`** con los hosts canónicos cuando existan.
6. **Datos operativos [DOC]:** actualizar una env var ofrece "Save and deploy" (zero-downtime, gateado por health checks); `Restart service` NO recoge vars nuevas; si las instancias nuevas no pasan health checks en 15 min, el deploy se cancela solo. Plan Free (15 min spin-down, ~1 min cold start) rompería webhooks — los 4 servicios ya están en Starter (verificado 2026-08-04).

### FASE S4 — Supabase [F+A] (cierra el P0: B2 pasos 8 y 10)

1. **[F] B2 paso 8 — DB password:** reset en Database → Settings (es reset, no hay flujo con password actual [DOC]). Impacto sobre conexiones vivas NO documentado [NO-DOC] → ejecutar en ventana de bajo tráfico y actualizar `DATABASE_URL`/secrets de CI inmediatamente después.
2. **[F] B2 paso 10 — revocar legacy anon/service_role (MATA EL P0).** Pasos exactos verificados en doc oficial:
   a. Settings → API Keys: revisar indicadores **"last used"** de `anon` y `service_role` (confirmar que el tráfico ya usa publishable/secret — B2 paso 2 ya migró el runtime).
   b. **Desactivar** `anon` y `service_role` (mismo panel). Son **reactivables** si algo se rompe [DOC] → la ventana de riesgo es reversible.
   c. Verificación [A]: `.audit/check_old_creds.py` debe pasar de HTTP 200 a **401** leyendo `tenants` con las keys viejas (esa es la evidencia que mata el P0).
   d. (Opcional, cierre total) Revocación del legacy JWT secret: Settings → JWT Keys → "Migrate JWT secret" → "Rotate keys" → esperar expiración de tokens (expiry + 15 min) → Revoke sobre "Previously used". Requiere (b) hecho primero [DOC].
   e. **No aplica a Konvi:** Edge Functions verifican JWT solo con legacy keys [DOC] — verificado que el repo NO usa Edge Functions (`supabase/functions` no existe); sin acción.
3. **[F] Dev cloud (PLAN §A #16, día del lanzamiento):** patrón oficial = proyecto separado (no Branching — es data-less y de pago). Mitigación documentada a la pausa Free (7 días de inactividad): actividad periódica o restauración manual (hasta 1 año).
4. **[F] Al clonar PRD→dev cloud:** `pg_dump` manual NO copia la Vault root key → secretos ilegibles [DOC]. Procedimiento: copiar root key vía Management API `GET/PUT /v1/projects/{ref}/pgsodium`, o re-crear los secretos per-tenant (recomendado: son pocos y rotados).
5. **[A]** Actualizar el runbook `credential-rotation.md` §Supabase con los pasos 2a-d exactos (hoy dice "revocar" sin el detalle de signing keys).

### FASE S5 — Resend / Telegram / Gemini [F] (ligeras, paralelizables)

1. **Resend [F]:** crear API key STG con permiso `sending_access` (nunca `full_access` — la doc confirma que full_access de STG podría tocar dominios de PRD). Dominios: cuando exista dominio propio, subdominio por ambiente (`stg.konvi.com` vs `konvi.com`) para segmentar reputación [DOC]. Tests de eventos con `delivered@resend.dev` / `bounced@resend.dev`. Si se adoptan webhooks de email: un endpoint por ambiente, signing secret svix propio por endpoint.
2. **Telegram [F]:** `/newbot` en @BotFather para STG (la doc oficial lo recomienda explícitamente). `setWebhook` con `url` del STG + `secret_token` propio + `drop_pending_updates=true` al cutover. El código ya verifica `X-Telegram-Bot-Api-Secret-Token`. Un bot = un webhook → separación obligatoria, ya diseñada.
3. **Gemini [F]:** crear **proyecto GCP separado** para STG (rate limits y billing son por proyecto, no por key [DOC] — dos keys en el mismo proyecto no segregan nada). Key STG: auth key (restringida a Generative Language API por default [DOC]). **PRD jamás en free tier**: el free tier puede usar prompts/respuestas para mejorar productos Google [DOC] → con datos de clientes es inviable. Migración forzosa a auth keys: sept-2026 — ya cumplido en B2 pasos 3 (ambas son auth keys).

### FASE S6 — MeLi / Aveonline [F] (cuando el marketplace entre a operación)

1. **MeLi [F]:** crear segunda aplicación en DevCenter ("Konvi STG") con su `client_id/secret`, redirect URI al ambiente STG y callback de notificaciones propio. Crear usuarios de prueba (`POST /users/test_user`, máx 10; **expiran a los 60 días de inactividad** → calendarizar recreación o uso mensual). Regla de la doc: los ítems de prueba se titulan "Item de Prueba - Por favor, NO OFERTAR"; usuarios test solo operan entre usuarios test. Defensa en código (ya existente): allowlist de las 4 IPs de notificación — pendiente la revisión trimestral (S0.4).
2. **Aveonline [F, decisión]:** el webhook de tracking es **único por empresa** (upsert por token [DOC]) → STG y PRD no pueden tener URLs distintas con la misma cuenta. Opciones: (a) **cuenta Aveonline separada para STG** (segregación total; costo: otra vinculación), o (b) aceptar que STG no recibe tracking real y usa el "API Sandbox" documentado (empresas demo 6077/25505, `avanzarEstado` para simular el flujo de estados). Recomendación: (b) mientras el volumen no lo justifique, (a) antes del lanzamiento con múltiples tenants.

---

## 4. Verificación continua (lo que queda automatizado)

| Guard | Qué certifica | Dónde corre |
|---|---|---|
| `scripts/check_env_data_mix.py` | Datos per-tenant coherentes con el ambiente (Wompi env, guías reales) | Manual pre-deploy / pre-UAT; exit 1 aborta |
| `scripts/check_no_ngrok.sh` | Ninguna URL de túnel en config de prod | CI en cada push |
| `tests/test_env_contract_guard.py` | Toda var leída por el código está en el contrato `.env.example` | CI |
| `tests/test_check_env_data_mix.py` | Lógica del guard (13 casos) | CI |
| S0.1/S0.2 (nuevos) | Cross-environment Wompi rechazado aunque la firma sea válida | CI |

**Checklist de certificación por fase:** cada fase se marca cerrada solo con su verificación ejecutada y evidencia en la bitácora de `docs/PLAN.md` §E.

---

## 5. Dependencias entre fases y orden recomendado

```
S0 [A] ── sin dependencias (código, inmediato)
S4.2 [F] B2 paso 10 (legacy Supabase) ── mata el P0, MÁXIMA PRIORIDAD founder
S1 [F] Wompi ── depende de activación de Wompi (tiempo externo); desbloquea cobros reales
S2 [F] Meta ── paralelo a S1
S3 [F] Render/dominio ── independiente; cuando cierre, actualizar URLs en S1/S2 (transición sin corte)
S5 [F] ── paralelo, bajo riesgo
S6 [F] ── cuando marketplace opere
S4.3 [F] dev cloud ── día del lanzamiento (PLAN §A #16)
```

---

## 6. Fuentes oficiales (verificadas 2026-08-16)

**Wompi:** docs.wompi.co/docs/colombia/ambientes-y-llaves/ · /eventos/ · /datos-de-prueba-en-sandbox/ · /widget-checkout-web/ · /tokens-de-aceptacion/ · soporte.wompi.co (vinculación)
**Meta:** developers.facebook.com/documentation/development/build-and-test/app-modes · /test-apps · /business-messaging/whatsapp/webhooks/overview · /webhooks/override/ · /webhooks/create-webhook-endpoint · /access-tokens/ · /permissions/ · /messaging-limits/ · docs/graph-api/guides/versioning · /changelog (v22.0 → 2027-05-20)
**MeLi:** developers.mercadolibre.cl/es_ar/realiza-pruebas · /productos-recibe-notificaciones · /crea-una-aplicacion-en-mercado-libre-es · /gestiona-tus-aplicaciones · /gestionar-ips-de-una-aplicacion (vía snapshots oficiales Wayback — devsite HTTP 500 el 2026-08-16, re-verificar)
**Aveonline:** integraciones.aveonline.co/docs/sandbox/sandbox-introduccion · /sandbox-avanzarEstado · /sandbox-obtenerEstadoAuth · /nacional/autenticacion/ · /nacional/generacionGuia/ · /webhookPersonalizadoApi · /webhookEstadosGuias
**Resend:** resend.com/docs/api-reference/api-keys/create-api-key · /dashboard/domains/introduction · /knowledge-base/what-email-addresses-to-use-for-testing · /dashboard/webhooks/introduction · /dashboard/webhooks/verify-webhooks-requests
**Telegram:** core.telegram.org/bots/features · /bots/api#setwebhook · /bots/faq
**Gemini:** ai.google.dev/gemini-api/docs/api-key · /rate-limits · /billing
**Supabase:** supabase.com/docs/guides/api/api-keys · /auth/signing-keys · /troubleshooting/rotating-anon-service-and-jwt-secrets-1Jq6yd · /deployment/managing-environments · /deployment/branching · /local-development · /reference/cli/supabase-start · /database/vault · /platform/free-project-pausing · /database/postgres/row-level-security
**Render:** render.com/docs/projects · /configure-environment-variables · /blueprint-spec · /custom-domains · /deploys · /health-checks · /free · /preview-environments · articles/best-practices-for-implementing-git-based-deployment-in-production-environments
