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

**Estado 2026-08-16: CERRADA (4/4).** Evidencia en bitácora `docs/PLAN.md` §E.

1. ✅ **[A] Webhook Wompi: validación defensiva del campo `environment`.** Wompi envía `environment: "test"|"prod"` en cada evento [DOC eventos]. Hoy la segregación es implícita (el checksum solo pasa con el events_key del ambiente correcto). Implementado: si `payload.environment` viene y no corresponde con el `meta.environment` del tenant resuelto ("test"↔sandbox, "prod"↔production) → rechazo terminal (log `environment_mismatch` greppable + return; el wrapper durable marca el inbox procesado — es un rechazo deliberado, no un fallo transitorio; tras corregir las llaves, re-drive manual del inbox). Sin el campo degrada a la barrera de firma (backward compatible). Tests: cross-environment rechazado con firma válida, match procesa, sin-campo procesa (`tests/test_wompi_webhook.py`, 11 nuevos).
2. ✅ **[A] Config Wompi: validación de par llave/ambiente al guardar.** El riesgo documentado: `pub_test_` contra `production.wompi.co` es un error de configuración posible. Implementado en el path real de escritura (server action `saveWompi` de `apps/web/.../integrations/page.tsx` — no hay endpoint de API para esto): nueva lib pura `apps/web/lib/wompi-keys.ts` rechaza el guardado si el prefijo de la llave (`prv_test_`/`test_events_` vs `prv_prod_`/`prod_events_`) no coincide con el ambiente elegido, con mensaje accionable. 7 tests Vitest + tsc verdes.
3. ✅ **[A] Actualizar dossier Aveonline §12.** La investigación 2026-05-21 ("no existe sandbox") sigue siendo cierta a nivel host, pero hoy EXISTE documentado un "API Sandbox" (empresas demo 6077/25505, `avanzarEstado`, `noGenerarEnvio=1`) — agregar addendum con fecha y URLs. Registrar que el webhook es único por empresa (upsert).
4. ✅ **[A] Registrar re-verificación MeLi.** (hecho: IPs sin cambio vs snapshots; doc viva bloqueada por devsite 500 — re-verificación registrada como pendiente de tercero) El devsite de MeLi devolvía HTTP 500 global el 2026-08-16 (re-intentado y sigue caído); los hallazgos vienen de snapshots oficiales archivados. Estado preciso de A3: la revisión trimestral se re-verificó empíricamente 2026-08-03 (0 tenants MeLi en prod → sin riesgo activo; trigger de próxima revisión = primer tenant MeLi conectado, PLAN §A #9). Las 4 IPs del allowlist en código (`meli_webhook.py:80-85`: 54.88.218.97, 18.215.140.160, 18.213.114.129, 18.206.34.84, verificadas contra fuente oficial 2026-04-28) coinciden con las de los snapshots archivados → **sin cambio que aplicar hoy**. Pendiente: re-verificar contra la doc viva cuando el devsite se recupere (bloqueado por tercero, no por nosotros).

### FASE S1 — Wompi [F con verificación A] (bloquea B2 paso 6)

Diseño destino (por doc oficial): la **misma cuenta** de comercio alberga ambos ambientes; cada uno tiene su URL de eventos propia. STG usa las llaves `test` + URL STG; PRD usa las llaves `prod` + URL PRD.

1. **[F] Completar vinculación de producción** (RUT + cuenta bancaria en comercios.wompi.co) y esperar el correo de activación — depende de Wompi, fuera de nuestro control. Verificación: llaves `prod_*` visibles en "Mi cuenta → Secretos para integración técnica".
2. **[F] Registrar URL de eventos PRD** en el dashboard (ambiente producción): `https://konvi-api.onrender.com/api/v1/webhooks/wompi` (o el dominio propio cuando exista — ver S3). **[F] Registrar URL de eventos STG** (ambiente sandbox): la URL ngrok/dev-cloud del ambiente de pruebas.
3. **[F] Cargar llaves prod en el Vault del tenant PRD** (KAIU): `prv_prod_` + `prod_events_` (+ `prod_integrity_` si se usa widget) y flip `meta.environment='production'`. Verificación [A]: `check_env_data_mix.py --env-file .env.prd-backup` pasa de WARN a ✅; link de pago de prueba real (monto mínimo) → evento recibido con `environment="prod"` y firma válida.
4. **[F] Cargar llaves test en el tenant STG** y probar con tarjetas documentadas (`4242…`→APPROVED, `4111…`→DECLINED). Verificación [A]: guard STG exit 0.
5. **Nota de operación:** Wompi reintenta eventos 3 veces en 24h (30 min, 3h, 24h) si no recibe HTTP 200 — cambiar la URL de eventos tiene ventana ciega máxima de 30 min. No documentado versionado/doble entrega: el cambio es atómico por ambiente.

### FASE S2 — Meta WhatsApp [F] (puede paralelizar con S1)

**Estado 2026-08-19: CERRADA (verificación E2E live).** Test App `KAIU Chat - Test` (912826941411258) creada por el founder; WABA de prueba 2159052118202272 + número de prueba 990364080831295; webhook verificado contra el connector STG vía ngrok (verify token per-tenant); app secret + access token en el Vault STG; **E2E live: WhatsApp real desde número verificado → POST Meta 200 (HMAC OK) → bot respondió y Meta aceptó el outbound (wamid)**. IDs registrados en `environments.md` §2. Lecciones: el webhook exige el `{tenant_id}` en el path (`print-urls` corregido) y la app debe suscribirse a la WABA vía `POST /{WABA_ID}/subscribed_apps` (hecho vía API). **Pendientes menores [F]:** System User token permanente (el actual expira ~24h) y desuscribir las apps de prod de la WABA de prueba (anti-duplicados).

1. **[F] Crear Test App** hija de la app de producción (App Dashboard → menú de la app → Create Test App; hereda config, siempre en Development mode, máx 50). Alternativa aceptada: app dev independiente ya existente para el tenant sandbox.
2. **[F] WABA/número de prueba para STG** — OBLIGATORIO separar: la doc confirma que 2 apps suscritas a la misma WABA reciben webhooks duplicados y que límites/calidad se calculan por WABA/portfolio. El número de prueba gratuito permite enviar a hasta 5 destinatarios verificados (dato de snapshot 2024; la doc vigente no reafirma el número — validar en el panel).
3. **[F] Configurar webhook de la Test App** → connector STG (`{ngrok}/api/v1/whatsapp/webhook/{tenant_stg}`). Opción avanzada documentada: override de callback por WABA/número vía `POST /<WABA_ID>/subscribed_apps` — NO adoptar como mecanismo principal: templates y eventos de cuenta no se pueden desviar.
4. **[F] System User token separado para la Test App** (Business Settings → System Users → Generate token, misma mecánica que B2 paso 5). Consideración: la caducidad "60 días/nunca" solo consta en UI, no en texto oficial [NO-DOC] — calendarizar verificación trimestral del token.
5. **[A] Registrar en environments.md** los IDs de la Test App/WABA de prueba (sin secretos).
6. **Dato de gobierno [DOC]:** Graph API **v22.0 (la del proyecto) tiene soporte hasta 2027-05-20**; vigente v26.0. Sin acción inmediata; entra en la revisión trimestral.

### FASE S3 — Render + dominio propio [F] (OQ-4; desbloquea URLs canónicas de webhooks)

> **Decisión founder 2026-08-16:** STG **no dependerá de Render en absoluto** (nada de servicios staging en la nube — el plan free congela y no sirve para probar webhooks). STG = 100% local, **totalmente homologado a la topología real de PRD** (los 4 servicios corriendo con la misma separación de env vars por consumidor, health checks y wiring web→api→orchestrator→connector). La homologación completa y su certificación es tarea del agente → **fase S7**. Esta fase S3 queda solo para PRD (dominio propio + hardening de la cuenta Render).

1. **[F] Crear Project con 2 environments** (staging/production) en Render: habilita `networking.isolation` (que STG no pueda alcanzar recursos de PRD) y `permissions.protection` en production (solo admins hacen cambios destructivos). Hobby permite 2 environments por proyecto — suficiente.
2. **[F] Env Groups con scope por ambiente**: mover las vars compartidas a grupos con scope al environment correspondiente (la doc confirma que un grupo con scope NO puede linkearse fuera de su ambiente — es la barrera anti-mezcla de Render). Regla: nunca solapar keys entre grupos (precedencia entre grupos no garantizada [DOC]).
3. **[F] Custom domain** `api.konvi.com` (o el dominio definitivo): agregar en Settings → Custom Domains, DNS, verificación, TLS automático. **NO deshabilitar el subdominio onrender.com de inmediato** — la doc confirma que el servicio conserva ambos; eso permite transición de webhooks sin corte: registrar el dominio nuevo en cada proveedor, verificar, y solo entonces (opcional) `renderSubdomainPolicy: disabled`.
4. **[F] Actualizar URLs de webhook en cada proveedor** al dominio propio (Wompi prod, Meta app prod, Aveonline, MeLi, Telegram) — Render no gestiona esto; es manual por proveedor [INFERIDO confirmado: Render no documenta nada al respecto].
5. **[A] Actualizar `.env.example`** con los hosts canónicos cuando existan.
6. **Datos operativos [DOC]:** actualizar una env var ofrece "Save and deploy" (zero-downtime, gateado por health checks); `Restart service` NO recoge vars nuevas; si las instancias nuevas no pasan health checks en 15 min, el deploy se cancela solo. Plan Free (15 min spin-down, ~1 min cold start) rompería webhooks — los 4 servicios ya están en Starter (verificado 2026-08-04).

### FASE S4 — Supabase [F+A] (cierra el P0: B2 pasos 8 y 10)

1. **[F] B2 paso 8 — DB password:** reset en Database → Settings (es reset, no hay flujo con password actual [DOC]). Impacto sobre conexiones vivas NO documentado [NO-DOC] → ejecutar en ventana de bajo tráfico y actualizar `DATABASE_URL`/secrets de CI inmediatamente después.
2. **[F] B2 paso 10 — revocar legacy anon/service_role (MATA EL P0).** ✅ **HECHO 2026-08-19:** founder desactivó las legacy JWT-based keys en Settings → API Keys; verificación [A] `check_old_creds.py` → **401 en ambas** ("Legacy API keys are disabled"). Queda como referencia el procedimiento ejecutado (por si se reactivaran por error):
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
2. **Aveonline [F, decisión]:** el webhook de tracking es **único por empresa** (upsert por token [DOC]) → STG y PRD no pueden tener URLs distintas con la misma cuenta. **Decisión founder 2026-08-16:** STG usa la **cuenta demo pública homologada** (`demointegracion`/`demointegra2021`, gratis, documentada en la autenticación oficial — dossier §12.1) + el "API Sandbox" (empresas demo 6077/25505, `avanzarEstado` para simular el flujo de estados). La segregación de facturación la garantiza el dry-run (`bloquegenerarguia="0"`, doble compuerta ya en código). Si en el futuro hace falta tracking real en STG, la única vía es cuenta Aveonline separada.

---

### FASE S7 — STG 100% local, homologación total a PRD [A] (decisión founder 2026-08-16)

**Misión:** STG no depende de Render en absoluto, pero corre la MISMA topología que PRD — completo, no parcial. Implementación:

1. **Filtro de env por servicio** (`scripts/dev_env_for_service.py`): el set de variables de cada servicio local es EXACTAMENTE el de su contraparte en render.yaml. Precedencia: valor local gana · anclas de ambiente (`APP_URL`, `API_URL`, `APP_ENV`, `AVEONLINE_GENERATE_REAL_GUIDES`, …) NUNCA heredan el valor PRD (fail-closed si faltan en el env-file local) · tuning con `value:` en render.yaml se hereda (= idéntico a PRD) · `sync:false` sin valor local solo pasa si es delta documentado (Sentry off, MeLi/Telegram hasta S5/S6). Fin del "megáfono" (todos los servicios veían todo).
2. **Makefile homologado** (`.local/Makefile`, ahora TRACKEADO en git — antes `.local/` entero estaba gitignored, la orquestación local era invisible al repo): orchestrator arranca con `uvicorn server:app :8002` (= PRD; antes `python main.py` sin /health), api/connector `uvicorn main:app` (= PRD), web `next dev` (diario) / `next start` (`make start-web-prod`, = PRD). Cada servicio arranca con entorno limpio (`env -i`) + su env filtrado.
3. **Guard de paridad en CI** (`tests/test_stg_prd_parity.py`, 13 tests): snapshot del conteo de vars por servicio, precedencia del filtro, entrypoints del Makefile = render.yaml, toda key de render.yaml documentada en `.env.example`.
4. **Certificación ejecutable** (`scripts/certify_stg.sh`): filtro fail-closed ×4 · health checks en los mismos paths de render.yaml · **aislamiento probado en procesos vivos** (`/proc/<pid>/environ`: api NO tiene GEMINI_MODEL, connector NO tiene RESEND_API_KEY, web NO tiene INTERNAL_SERVICE_SECRET, orchestrator NO tiene NGROK_AUTHTOKEN) · wiring internal-secret (orchestrator 200 + api dual-auth 422) + web→api.

**Estado 2026-08-16: CERRADA — certificación live 18/18 (`bash scripts/certify_stg.sh`).** Bugs reales detectados y corregidos por esta fase:
- **Drift Sentry PRD:** el client bundle leía `NEXT_PUBLIC_SENTRY_TRACES_RATE` pero render.yaml setea `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` → el override nunca aplicaba (mismo default 0.1, sin impacto; corregido al nombre canónico F97 + contrato actualizado).
- **Quoting:** valores con espacios (`RESEND_FROM_EMAIL="Konvi <...>"`) rompían el `source` del env filtrado → shlex.quote.
- **Contrato `.env.example` completado:** PLAN_ENFORCEMENT_ENABLED, API_RATE_LIMIT_ENABLED/DISTRIBUTED, MULTIMODAL_AUDIO_ENABLED, COLOMBIA_UTC_OFFSET_HOURS, build-vars web.
- **Riesgo latente evitado por diseño:** heredar ciegamente `value:` de render.yaml habría prendido `AVEONLINE_GENERATE_REAL_GUIDES=true` en STG — por eso es ancla de ambiente con `false` explícito local.


| Guard | Qué certifica | Dónde corre |
|---|---|---|
---

### FASE S8 — Eliminación TOTAL de Sentry [A] (decisión founder 2026-08-16)

**Estado 2026-08-19: CERRADA TOTAL (agente + founder).** Certificación agente 2026-08-17: grep-cero en código/config · suite 4408 passed/0 failed · vitest 353 · tsc 0 · `next build` OK · ruff 197 ≤ baseline · `certify_stg.sh` 18/18 · CI 5/5 (run 32086032295). Parte founder 2026-08-19: env vars SENTRY_* borradas en los 4 servicios Render + org sentry.io eliminada — **verificado vía Render API (0 SENTRY_* ×4 servicios) + health live 200 ×5**. Evidencia en bitácora `docs/PLAN.md` §E.

Desviaciones del inventario (encontradas al ejecutar, verificadas contra código):
- `services/ai-orchestrator/observability.py` NO era solo Sentry: albergaba el tracing OTEL (`track_op`/`start_span`, rev.109) que usa `agentic/dispatcher.py`. El OTEL no es Sentry y se conserva → movido intacto a `services/ai-orchestrator/tracing.py` (único import actualizado).
- `_surface_email_failure` (wrapper Sentry en `lib/client_notifications.py`) era re-exportado por `routers/wompi_webhook.py` y patcheado en 4 tests de `test_wompi_webhook_money_paths.py` (no aparecían en el grep "sentry"): eliminado; los 4 tests ahora asertan la clasificación del fallo sobre los logs (assertLogs) en vez del wrapper.
- `tests/test_parity_shared_modules.py::ObservabilityParityTests` (guard M16 de los espejos observability.py ×3, tampoco decía "sentry"): guard removido con los módulos.
- `tests/test_w1_sentry_pii_scrub.py`: las clases de scrub PII de Sentry se fueron con los módulos; las de masking en origen (`_mask_phone`, vigente para logs) se conservan en `tests/test_w1_phone_masking.py`.
- `apps/web/app/dashboard/(analytics)/audit/page.tsx`: falso positivo del grep (`PiiAccessEntry`/`accessEntries` contienen la subcadena) — identificadores renombrados (`PiiAccessRecord`/`piiAccessRows`) para que el cierre grep-cero sea literal.
- `scripts/_reorg_env_f2.py`: borrado (one-off de la reorg F2 2026-08-14; operaba sobre `.env`/`.env.prod` que ya no existen tras la consolidación de ambientes).
- Docs vivos actualizados a la postura sin-Sentry (TRD, BACKEND, slo-and-dr, local-prod-symmetry, wompi, pago-wompi, 01-state, 06-contracts, 09-bot-flowchart, credential-rotation, legales ×2); `docs/observability/sentry-setup.md` archivado. Reportes/ADR/research fechados quedan como registro histórico (exentos por criterio de cierre).

**Motivo:** Sentry se adoptó como free tier; vencido el periodo de prueba deja de ser útil/cubierto. Decisión founder: **borrarlo absolutamente todo**. La observabilidad propia (métricas, alerting, error tracking) se diseña y construye en la **fase Platform Console (fase 12)** — hasta entonces la observabilidad queda en: logs estructurados (stdout, Render los retiene), endpoints `/health` + `/health/ready` + `/agentic/metrics` (ya existen, no son Sentry) y los guards de CI.

**Inventario verificado 2026-08-16 (borrado mecánico, sin suposiciones):**

| Capa | Qué borrar |
|---|---|
| Deps Python | `sentry-sdk[fastapi]==2.65.0` de los 3 `requirements.txt` (api, ai-orchestrator, connector-whatsapp) |
| Módulos Python | `services/{api,ai-orchestrator,connector-whatsapp}/observability.py` (149/326/149 líneas — son solo Sentry) |
| Call sites Python | 13 usos de `init_sentry`/`capture_exception` en services (main.py ×2, server.py, dispatcher.py, invariants/base.py, stock_reservation.py, refund_notifications.py, shipment_status_notifications.py, whatsapp_sender.py, worker.py, dependencies/auth.py, lib/client_notifications.py, routers/wompi_webhook.py) — reemplazar `capture_exception(e)` por `logger.exception(...)` donde no haya ya log |
| Deps web | `@sentry/nextjs ^10.68.0` de `apps/web/package.json` |
| Archivos web | `sentry.client.config.ts`, `sentry.server.config.ts`, `sentry.edge.config.ts`; wrapper `withSentryConfig` en `next.config` (líneas ~126-130); referencias en `instrumentation.ts`, `global-error.tsx`, `proxy.ts`, `app/api/insights/route.ts`, `app/dashboard/(sales)/claims/page.tsx`, `(settings-group)/team/page.tsx` |
| Paquete muerto | `packages/observability/` (`@commerce/observability`) — **nadie lo importa** (verificado: solo se referencia a sí mismo) → borrar el paquete completo |
| Config PRD | 19 menciones SENTRY en `render.yaml` (keys SENTRY_DSN/ENV/TRACES_SAMPLE_RATE/NEXT_PUBLIC_* ×4 servicios + SENTRY_AUTH_TOKEN/ORG/PROJECT web) |
| Contrato | Sección Sentry completa de `.env.example` (9 líneas) |
| Tests | Los que referencian comportamiento Sentry (test_config_g13*, test_a11_metrics_auth, test_internal_secret_rotation, test_m14_readiness_no_leak, agentic ×2) — actualizar asserts a la postura sin-Sentry |
| Guards propios | `scripts/dev_env_for_service.py` (_STG_DELTA_OK: quitar SENTRY_* cuando las keys salgan de render.yaml) · `scripts/_reorg_env_f2.py` (one-off histórico — evaluar borrado) |
| Dashboard [F] | Borrar las env vars SENTRY_* en los 4 servicios Render + cancelar/borrar el proyecto en sentry.io |

**Orden de ejecución:** deps+configs primero, call sites después, suite + build + CI verde, y como cierre: `grep -ri sentry services/ apps/ packages/ scripts/ tests/ render.yaml .env.example` = 0 hits (fuera de docs históricos/archive y este plan). **Certificación:** suite completa + vitest + tsc + `next build` + CI 5/5 + `bash scripts/certify_stg.sh` 18/18 (los conteos de vars por servicio en `test_stg_prd_parity.py` bajan al quitar las SENTRY_* — actualizar el snapshot en el mismo commit).

---

## 3.5 Respuestas founder (2026-08-16)

**¿Cómo se comunican los endpoints en local (webhooks de terceros)?** Sí: **ngrok**. Los túneles los levanta `make -C .local up` (`NGROK_AUTHTOKEN`/`NGROK_DOMAIN_API` para api :8001, `NGROK_AUTHTOKEN_CONNECTOR`/`NGROK_DOMAIN_CONNECTOR` para connector :8000 — vars del `.env.local`, nunca llegan al runtime de los servicios: verificado por el guard de aislamiento S7). `make -C .local print-urls` imprime las URLs exactas a registrar en cada proveedor (Wompi eventos, Meta webhook, MeLi redirect/notificaciones). Los túneles son SOLO para que terceros alcancen tu máquina; el tráfico interno web→api→orchestrator va directo por localhost. Detalle en `environment-segregation.md` §4.

**¿El API de PRD debe quedar en `*.onrender.com`?** **No.** Estado objetivo: dominio propio (`api.konvi.com` o el definitivo) — fase S3.3/S3.4. `onrender.com` es **transitorio**: la doc de Render confirma que el servicio conserva el subdominio onrender tras agregar el custom domain, lo que permite migrar los webhooks de cada proveedor sin corte; cuando todo apunte al dominio propio, el subdominio se puede deshabilitar (`renderSubdomainPolicy: disabled`). Hasta entonces, las URLs onrender registradas en los proveedores siguen siendo válidas.

---

## 4. Verificación continua (lo que queda automatizado)

| Guard | Qué certifica | Dónde corre |
|---|---|---|
| `scripts/check_env_data_mix.py` | Datos per-tenant coherentes con el ambiente (Wompi env, guías reales) | Manual pre-deploy / pre-UAT; exit 1 aborta |
| `scripts/check_no_ngrok.sh` | Ninguna URL de túnel en config de prod | CI en cada push |
| `tests/test_env_contract_guard.py` | Toda var leída por el código está en el contrato `.env.example` | CI |
| `tests/test_check_env_data_mix.py` | Lógica del guard (13 casos) | CI |
| S0.1/S0.2 (nuevos) | Cross-environment Wompi rechazado aunque la firma sea válida | CI |
| `tests/test_stg_prd_parity.py` (S7) | Paridad STG↔PRD: set de env por servicio = render.yaml, entrypoints, contrato | CI |
| `scripts/certify_stg.sh` (S7) | Homologación live: health ×5 + aislamiento /proc + wiring interno — 18 checks | Manual (con stack arriba) |

**Checklist de certificación por fase:** cada fase se marca cerrada solo con su verificación ejecutada y evidencia en la bitácora de `docs/PLAN.md` §E.

---

## 5. Dependencias entre fases y orden recomendado

```
S0 [A] ── sin dependencias (código) — ✅ CERRADA 2026-08-16
S7 [A] ── sin dependencias (STG local homologado) — ✅ CERRADA 2026-08-16 (CI 5/5 verde)
S8 [A+F] ── ✅ CERRADA TOTAL 2026-08-19 (código + dashboard Render + sentry.io; verificado Render API + health live)
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
