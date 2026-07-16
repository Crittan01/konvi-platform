# Auditoría 2026-07-16 — Plan de trabajo hacia 90+ (gate pre Platform Console)

> Generado por workflow multiagente (20 agentes: 8 tracks + 8 verificaciones adversariales + 3 sweeps + síntesis). Base: re-score **73/100** (2026-07-16) sobre `production=f3542fa0` (W1+W2 desplegados + UAT dinámico PASS).

## Resumen ejecutivo

Plan verificado hacia 90+ (gate pre Platform Console) desde el re-score 73/100 (2026-07-16). Integra los 8 tracks auditados adversarialmente (T1-T8) con TODOS los adjustments y missing_items de las reviews aplicados (cero items rechazados que excluir; sí hay correcciones materiales: taxonomía de roles owner/manager/operator en T1, semántica silent-fail de pgsec_*, xlsx muerto vs xlsx-js-style realmente expuesto, billing org-scoped Supabase, LoggingIntegration ya envía dead-letters a Sentry, aritmética de coverage T8). Estructura: 10 olas (W3-W12) de 1-2 semanas, ~91 pd, no-cost primero. W3 cierra el HIGH nuevo de W2 (errores transitorios tragados que pierden pagos permanentemente) + quick-fixes verificados. W4 construye el harness DB ejecutable (T1) — prerequisito para confiar cualquier cambio RLS posterior. W5 cierra perímetro XFF + supply-chain. W6 (gated founder ~$46-53/mes) separa dev/prod y prueba DR real — sin esto el CRITICAL dev=prod sigue abierto y 90+ es inalcanzable. W7 completa observabilidad + resync documental. W8-W12 ejecutan performance en orden estricto medición→red conductual→refactor→cache/paralelismo→gates, más deuda estructural y coverage 70%. Trayectoria conservadora calibrada con la evidencia real de que 2 olas movieron solo +2: 73→90-91 en ~19 semanas de esfuerzo neto.

## Trayectoria de score

73 (hoy) → 74 (W3, durabilidad dinero) → 76 (W4, harness DB) → 78 (W5, perímetro+supply) → 81 (W6, dev/prod+DR — cierra el CRITICAL restante) → 83 (W7, observabilidad+docs) → 84 (W8, medición+red) → 86 (W9, refactor+cache) → 88 (W10, perímetro avanzado+resiliencia) → 89 (W11, coverage 70%+SLIs) → 90-91 (W12, sello+re-score). Calibración conservadora: la evidencia real es que 2 olas (Ola0+W1+W2, ~15pd) movieron el overall solo +2; este plan asume ~+2 por ola de ~10pd porque ataca las 4 dims más bajas (performance 45, docs 55, observability 58, data-db-dr 65) donde el punto marginal es más barato, pero el re-score W12 es adversarial y puede quedar en 88-89 — de ahí la decisión founder de cierre.

**Esfuerzo total:** 90.6 pd (~18-19 semanas a 1 dev).

## Scorecard actual (22 dims; 10 re-escoreadas hoy)

| Dimensión | Score | Estado |
|---|---|---|
| payments | 89 | 🟢 |
| multitenant-isolation | 83 | 🟢 |
| security-authz | 76 | 🟡 |
| dos-ratelimit | 72 | 🟡 |
| resilience | 70 | 🟡 |
| supply-deploy | 66 | 🟡 |
| data-db-dr | 65 | 🔴 |
| observability | 58 | 🔴 |
| docs | 55 | 🔴 |
| performance | 45 | 🔴 |
| *(estables: frontend 90, invariants 81, api-gateway 81, builders 80, connector 80, fsm 79, media 78, compliance-e2e 78, worker 75, orchestrator 74, shipping-meli 73, tests 70)* | — | — |

## Plan por olas (W3–W12)

### W3 — Durabilidad de dinero cerrada + quick-fixes verificados
*Meta:* Cerrar el HIGH nuevo de W2 (contrato de durabilidad roto: flakes transitorios marcan el inbox como procesado y pierden el pago para siempre) y el residuo de gaps LOW/MEDIUM confirmados por los sweeps. Todo no-cost, sin migraciones nuevas.

**Esfuerzo:** 4.75 pd · **Score esperado:** 74 · dep: Ninguna (arranca hoy sobre f3542fa0)

- W2-F1 — Propagar errores transitorios en _get_order_id_by_link / _get_order_by_id / get_tenant_wompi_creds (distinguir 'no encontrado' de 'error de lectura'; inbox queda sin procesar y el worker re-drivea)
- W2-F2 — raise en fallo del processed-check del dedup (wompi_webhook.py:271-276) en vez de return terminal — el re-drive es idempotente
- W2-F3 — _confirm_order resumable: decrementar stock ANTES del flip a confirmed o excluir del guard terminal órdenes confirmed sin stock_movements/shipment (cierra oversell en crash-recovery)
- T3-01 — Métrica wompi_inbox_depth + wompi_inbox_dead_letters en _metrics (SIN capture_exception — LoggingIntegration ya envía el logger.error a Sentry; tags vía push_scope; test en /tests junto a test_w2_wompi_inbox_durability.py)
- GAP-PII — wompi_webhook_inbox al inventario Habeas Data: purge en offboarding/hard-delete, cleanup desacoplado del flag de reconcile, documentar retención 7/30d en docs/legal (payload crudo con PII del pagador hoy fuera del cascade)
- QF — Bundle quick-fixes: docstring MeLi XFF, masking en branch de error de whatsapp_sender (response.text), restaurar TenantPatchBrandFieldsTests (~30 líneas), test de paridad conductual de las 3 copias del scrub PII + scrub de dict keys, restaurar exc_info con masking en _run_job, limpiar 2 comentarios stale _is_outside_support_hours

### W4 — Harness DB ejecutable (T1): RLS/Vault/inbox/hook regresionables en CI
*Meta:* Convertir las garantías crown-jewel (RLS role-aware, pgsec_* Vault, claim SKIP LOCKED del inbox Wompi, custom_access_token_hook) de verificación manual a gate reproducible por PR. Prerequisito duro para confiar cualquier cambio RLS futuro.

**Esfuerzo:** 11.75 pd · **Score esperado:** 76 · **gated:** INTERVENCION HUMANA menor: founder marca db-harness como required check en branch protection (~10 min) · dep: W3 (secuencia); T1-02..08 dependen de T1-01

- T1-01 — Spike replay: supabase db reset aplica 222 migraciones en stack CI-like (resolver db start vs start -x para auth.*)
- T1-02 — Infra pytest dbharness: conftest DSN + guard anti-prod (assert host local, P0 — la VM comparte Supabase PROD), as_user con claims ANIDADOS en app_metadata, roles reales owner/manager/operator, seed con usuarios separados por tenant (UNIQUE(user_id)), marker en pyproject.toml
- T1-03 — Matriz RLS deny cross-tenant (tenant_users/tenant_integrations/notification_settings) + caso escalada member→owner + camino GUC app.current_tenant_id con test de precedencia GUC-gana-a-JWT
- T1-04 — Suite pgsec_* (5 funciones, incl. create): read/update/delete fallan en SILENCIO (assert NULL/no-op + post-condición), solo upsert/create RAISE; caso insignia: operator del tenant DUEÑO = deny (regresión del fix W1)
- T1-05 — Suite durabilidad SQL Wompi inbox: no-doble-claim concurrente (2 conexiones), lease 300s simulado, dead-letter attempts>=5, min_age, cleanup (incl. pendientes >30d), grants REVOKE + RLS deny-all anclados
- T1-06 — Hook vigente 20260704156200 end-to-end + canario anti-FORCE-RLS (controlando rolbypassrls del owner local) + documentar comportamiento real del REVOKE
- T1-06b — Hardening companion: migración REVOKE ALL ON custom_access_token_hook FROM PUBLIC + test (posible info-leak cross-tenant vía /rpc/ hoy)
- T1-07 — Etapa --db-harness en validate.sh con skip CI_MODE-aware (un _warn rompería --ci local en la VM sin docker)
- T1-08 — Job db-harness en ci.yml (setup-cli pinneado, timeout 15min, artifact de logs) + PR de sabotaje demostrando rojo

### W5 — Perímetro XFF real + supply-chain de cero a gate
*Meta:* Volver reales los rate-limiters ya desplegados (hoy evadibles rotando XFF leftmost y envenenables contra IPs de Meta), cerrar el bypass de la allowlist MeLi, y pasar de 0 auditoría JS a gate CI con los 9 vulnerables remediados + cierre de los 5 PYSEC allowlisted.

**Esfuerzo:** 8.75 pd · **Score esperado:** 78 · **gated:** INTERVENCION HUMANA: verificación XFF en prod (deploy+curl ~30 min). Decisión founder: ruta xlsx (recomendada: split read-path, $0) · dep: W4 (harness protege las superficies tocadas); T7-04 independiente de T7-03

- T4-01 — TRUSTED_CLIENT_IP_HEADER (cf-connecting-ip) + fallback hops + canary log + verificación EMPÍRICA en prod (la premisa Render es hipótesis, no doc oficial) + tests de regresión de la allowlist MeLi (hoy bypasseable) + fix docstring
- T4-05 — Barrido de superficies: rate-limit en telegram_webhook, bucket read.expensive en GETs caros, cap de Content-Length en wompi/aveonline webhooks (asimetría vs connector — amplificación en path de dinero), tabla canónica endpoint→bucket en 06-contracts.md
- T7-01 — Gate osv-scanner v2.4.0 sobre pnpm-lock.yaml en validate.sh --full + CI (veredicto por exit code, allowlist TOML con reason+fecha) + instalación del binario en la VM
- T7-02 — Remediación JS: pnpm remove xlsx (paquete MUERTO, 0 imports), pnpm update ws/postcss/js-yaml/brace-expansion/rollup, decisión sentry 8.x, y el parser REAL expuesto: split read-path de xlsx-js-style (uploads por parser parcheado, escritura de plantillas intacta) — acceptance anti-score-washing: la ruta de LECTURA de archivos subidos ya no pasa por el fork de 0.18.5
- T7-03 — dependabot.yml (pip x3 + npm + actions, weekly, groups) + pnpm minimumReleaseAge + cooldown dependabot (mitigación del vector release-recién-publicado)
- T7-04 — FastAPI 0.128.8→0.139.2 + starlette==1.3.1 pineado + bump coordinado sentry-sdk 2.18→actual (su integración parchea internals de starlette): elimina la allowlist de 5 PYSEC de pip-audit; tests ancla Content-Type; deploy escalonado connector→api→orchestrator con UAT dinámico corto

### W6 — Separación dev/prod + DR probado (T2)
*Meta:* Cerrar el CRITICAL abierto dev=prod Supabase y pasar de cero backups/DR a restore PROBADO con RTO medido. La ola de mayor impacto en data-db-dr (65) y la única con costo mensual recurrente.

**Esfuerzo:** 9.6 pd · **Score esperado:** 81 · **gated:** FOUNDER-COSTO: Supabase Pro $25/mes (P0) + Render Starter $21-28/mes + PITR $100/mes (decisión). INTERVENCION HUMANA: creación proyecto dev (~30 min) · dep: W4 (el harness usa el contenedor local; el proyecto dev desbloquea además pgTAP futuro). T2-06/07/08 dependen de T2-05

- T2-01 — Pre-flight replay 222 migraciones: bootstrap pg_cron (sin pg_net — 0 usos), clasificar 40 seeds INSERT, evaluar PRIMERO baseline vía supabase db dump (el drift del ledger puede hacer inalcanzable el replay puro)
- T2-02 — Proyecto konvi-dev en ORG Supabase SEPARADA Free (billing org-scoped: misma org costaría ~$35/mes, no $25) + extensiones + hook + paridad de esquema vía dump_schema_canonical --diff
- T2-03 — Seed dev: tenant sintético + re-provision Vault sandbox (Meta/Wompi/Aveonline) + seed_dev_project.py idempotente
- T2-04 — Cutover local a dev + guardrail env_guard anti-prod en scripts destructivos cubriendo AMBOS .env (raíz + apps/web/.env.local) y scripts/debug/
- T2-05 — Upgrade Supabase prod a Pro: backups diarios 7d visibles en <24h
- T2-06 — Runbook DR full-DB + restore REAL cronometrado (RTO medido, no declarado) + checklist de config no cubierta por backup (hook, SMTP, plantillas, NEXT_PUBLIC_* horneadas) + monitoreo periódico de éxito de backups + re-test trimestral
- T2-ESCROW — Escrow de credenciales prod fuera de la DB + runbook re-provision Vault post-restore (sin esto, un DR 'exitoso' deja WhatsApp/Wompi/Aveonline muertos — vault.secrets cifrado por-proyecto)
- T2-08 — Backup Storage buckets (consent-evidence, offboarding-archive, tenant-media — evidencia legal Ley 1581 fuera del backup de DB) a R2/S3 con lag ≤24h
- T2-DEC — Decisión documentada de alcance 'staging' (dev-local basta ahora + trigger de re-evaluación pre Platform Console)
- T2-07 — Decisión PITR $100/mes: presentar con RTO real de T2-06 (recomendación: diferir con trigger)
- T2-09 — Render Starter 3-4 servicios + retiro hack anti-hibernación + orchestrator como worker nativo

### W7 — Observabilidad accionable + resync documental (T3+T6)
*Meta:* De 'Sentry captura pero nadie se entera' a alerting proactivo end-to-end (reglas + evaluador de SLOs + dead-man), y eliminar el drift documental que hace que cada sesión razone sobre contratos que ya no existen (score docs 55, observability 58).

**Esfuerzo:** 10.75 pd · **Score esperado:** 83 · **gated:** INTERVENCION HUMANA: token Sentry + confirmar DSN en Render + email destino (~45 min) · dep: W6 (T3-04 usa protocolo de migraciones ya des-riesgado; T6-04 verifica ledger). T3-EVAL depende de T3-03/04; T6-03 de T6-01

- T3-02 — beforeSend scrub PII en los 3 configs de apps/web (paso 0: verificar inyección real del client config — condicional a SENTRY_AUTH_TOKEN; regex sin lookbehind; tests vitest existente)
- T3-03 — SLIs medibles: vista sli_turn_latency (pairing acotado por ventana, excluyendo bot-initiated/templates), RPC get_queue_health (depth + edad pgmq), SLOs propuestos en 06-contracts.md marcados como hipótesis calibrable
- T3-04 — Tabla platform_metrics append-only + flush 5min del worker (deltas) + retención 30d (protocolo seguro de migraciones)
- T3-06 — Reglas de alerta Sentry vía API con script idempotente agnóstico a topología de proyectos (regla email founder para [WOMPI_INBOX][DEAD_LETTER] y [TAKEOVER] DEAD-LETTER)
- T3-EVAL — Evaluador de SLOs (missing item): job del worker que convierte umbrales (inbox_depth>0 por >15min, cola >120s, éxito WA <99%) en logger.error→Sentry o Telegram vía notify_escalation_async + dedup F7 existente
- T3-DEADMAN — Dead-man/uptime: Sentry Cron Monitors sobre el poll cycle o monitor externo /health x4 (validar free tier en doc oficial)
- T3-07 — Cerrar /status con internal secret (confirmación founder previa: ningún monitor externo lo consume)
- T6-08 — Materializar en repo el doc canónico de la auditoría 2026-07-13 + plan de olas (hoy el roadmap solo vive en memoria de agente — prerequisito de trazabilidad de T6-05)
- T6-01 — ADR-0040 inbox durable Wompi (W2)
- T6-02 — ADR-0041 enforce_mfa_strict fail-closed
- T6-03 — Resync 06-contracts.md §12 contrato Wompi durable (depende de T6-01)
- T6-04 — HANDOFF rev.113: PRs #54-#69 (no solo #64+), 222 migraciones con estado verificado en ledger, WOMPI_INBOX_* en render.yaml + .env.example
- T6-05 — 01-state.md + 04-next-steps.md rev.113 (Ola-0 #64-65 ≠ W1 #66-68; crear 01-state-archive.md; re-score citando T6-08)
- T6-06 — Runbook Wompi post-W2: casos auto/manual/dead-letter (con raw_payload el pull por transaction_id SÍ aplica)
- T6-07 — Higiene: renumerar ADR 0023-shipping duplicado (→0042), conteos CLAUDE.md
- CONSENT — Decisión notify_consent_revoked: portar notificación al optout gate + registrar en ADR-0039 (recomendado) o eliminar dead code

### W8 — Performance fase 1: medición + red conductual (T5)
*Meta:* Regla dura del track: NINGÚN refactor sin datos ni red. Instrumentar el turno completo (hoy solo se mide LLM+tool-loop), obtener baseline real, y subir coverage del dispatcher (path productivo único, 17.5%) a ≥50% con tests offline de EFECTOS.

**Esfuerzo:** 11 pd · **Score esperado:** 84 · dep: W7 (secuencia); T5-02 de T5-01; T5-04 de T5-01+T5-03. Independiente de T2/T3 — puede solaparse si hay capacidad

- T5-01 — TurnPerf por etapa (≥8 seams) con split model_call vs tool_execution por iteración del loop + CountingSupabaseProxy (contando en .execute() del builder) + línea [AGENTIC_PERF]
- T5-02 — Baseline: 15 escenarios del harness live + analyze_agentic_perf.py + métrica queue-wait (created_at→dispatch; poll 3s + procesamiento secuencial) + DEFINIR el target de salida del track (p95 e2e percibido) — missing item integrado
- T5-03 — Red conductual offline: FakeSupabase de alta fidelidad + LLM stub + port de los 15 escenarios con assertions de efectos; dispatcher 17.5%→≥50% (esfuerzo realista 5-6pd, no 4)
- T5-04 — Golden traces de escrituras DB + outbound por escenario, con política de actualización explícita (nunca regenerar en silencio)

### W9 — Performance fase 2: strangler + cache (T5) + purga V1 (T8)
*Meta:* Descomponer _run_agentic_full (2,360 líneas) en 5 módulos por seam real con equivalencia demostrada por golden traces, eliminar el fan-out de catálogo (3 queries × hasta 3 llamadas/turno) y retirar el residuo V1 verificado.

**Esfuerzo:** 9 pd · **Score esperado:** 86 · dep: W8 dura: T5-05 exige T5-03+T5-04 verdes; T5-06 exige T5-02 (baseline) y T5-05 (TurnContext)

- T5-05 — Strangler en 4 PRs (turn_context, multimodal_stage, pre_llm_pipeline, post_llm_stage); dispatcher ≤1,200 líneas; golden traces idénticos salvo -1 query tenant_integrations documentada; sello final: harness live 15 escenarios
- T5-06 — Cache catálogo: memo por-turno CONDICIONADO (refrescar si el turno ejecutó tools que mutan stock/reservas — el invariant re-fetchea post-tools a propósito) + TTL cross-request 60-300s con kill-switch y nota de staleness de precio
- T8-01 — Purga residuo V1: fsm/resolver.py, 2 imports muertos, 4 tools test-only (~883 LOC) + tests/test_known_customer_tool.py + migrar test_address a lib/address_format.py + limpiar menciones muertas en comentarios de 5 archivos vivos (coverage post-purga ~63.7%, -0.17pt, NO ~1pt)

### W10 — Perímetro avanzado + performance cierre + resiliencia envíos
*Meta:* Token-bucket sin burst 2x + cuota per-tenant (ordenadas para no duplicar RPCs a la Supabase compartida), paralelismo intra-turno del context-load, gates anti-regresión de performance, y poller de respaldo Aveonline (hoy un webhook perdido congela el envío para siempre).

**Esfuerzo:** 10.5 pd · **Score esperado:** 88 · dep: T4-02/03 de T4-01 (W5); T5-07 de T5-05 (W9); T5-08 de T5-02+T5-06; T8-02 de T8-01

- T4-03 — RPC rate_limit_hit_v2 token-bucket + pre-filtro local 3x antes de la RPC + switch env de rollback + cleanup de la tabla nueva agendado en worker (esfuerzo realista 2pd)
- T4-02 — Cuota agregada per-tenant (API multiplier + connector pre-HMAC + webhooks post-resolución) — DESPUÉS del pre-filtro de T4-03 para no duplicar RPCs bajo flood
- T5-07 — gather + to_thread en load_turn_context (validar thread-safety del client sync en doc oficial supabase-py; acreate_client tiene 0 usos — la opción AsyncClient es patrón nuevo, no reuso); expectativa acotada: paralelismo intra-turno, el worker es secuencial
- T5-08 — Gates CI: budget de queries/turno con ratchet (patrón BASELINE_MAX) + piso de coverage del dispatcher en validate.sh
- T8-02 — Poller respaldo Aveonline (patrón wompi_void_poll): candidatos por tracking_number NOT NULL + status no-terminal (NO existe columna provider), mapping RAW_STATE_TO_INTERNAL con test de paridad webhook↔poller, port de las 3 notificaciones API-side al worker con paridad, avance monotónico idempotente; extender test_aveonline_client_parity a get_estado (missing item)

### W11 — Coverage 70% + superficie SLIs + decisiones de resiliencia
*Meta:* Subir cobertura al target J.5 con tests conductuales en las palancas de dinero (dispatcher ≥60%, adapter Aveonline ≥75%, wompi_webhook, worker), exponer SLIs al tenant, y sellar las decisiones diferidas con criterio cuantitativo.

**Esfuerzo:** 10.5 pd · **Score esperado:** 89 · **gated:** INTERVENCION HUMANA: sudo en VM para docker/podman (~30 min) · dep: T8-05 de T8-01 (W9, denominador post-purga); T3-05 de T3-03/04 (W7); T1-09 de T1-07 (W4)

- T8-05 — Coverage 63.7%→70% conductual en 4 fases (dispatcher/aveonline-adapter/wompi_webhook/worker); ratchet COVERAGE_MIN 55→68; actualizar baseline en CLAUDE.md Y validate.sh:22-24 (esfuerzo realista 6-8pd; presupuesto 7)
- T3-05 — Sección 'Rendimiento del bot' en Settings→Salud: endpoint tenant-scoped (lint AST 0 gaps) + p50/p95 24h, % éxito WA, backlog; estados vacíos honestos; paleta shades 700
- T8-03 — ADR: breaker en orchestrator DIFERIDO con criterio de activación cuantitativo + diseño fail-open comprometido + contador de fallos transitorios per-provider (especificando el puente in-process→colector) + retry del void SOLO con idempotencia verificada en doc oficial Wompi
- T1-09 — Habilitar harness local en la VM (docker/podman rootless) — cierra el ciclo de debug de 5min/push a segundos

### W12 — Sello: prompt-size condicional + UAT E2E + re-score
*Meta:* Cerrar con evidencia: aplicar la palanca de tokens SOLO si el baseline W8 demostró que model_call domina el p95, sellar con UAT dinámico completo del journey (regla del repo: nunca UAT estático), y re-score adversarial formal contra el gate 90+.

**Esfuerzo:** 4 pd · **Score esperado:** 90 · **gated:** Decisión founder si el re-score queda en 88-89: priorizar dims residuales vs abrir Platform Console · dep: Todas las anteriores; T5-09 gated por evidencia del baseline W8

- T5-09 — (CONDICIONAL a evidencia de T5-02) Reducción de tokens del prompt: catálogo selectivo + poda de history (system_prompt_chars ya persiste en agentic_shadow_log)
- UAT-SELLO — UAT dinámico E2E completo en prod: journey cupón→carrito→pago Wompi→guía→tracking + verificación bot-vs-DB turn-a-turn (feedback_analytical_uat)
- RESCORE — Re-score adversarial de las 22 dims contra f-actual + registro en 01-state.md/T6-08 doc; re-evaluar triggers diferidos (PITR, T4-04 connector distribuido, T8-04 MeLi outbox) con datos reales

## Decisiones founder (con recomendación + costo)

### Upgrade Supabase prod a plan Pro (backups diarios 7d) — T2-05, Wave W6
- **Recomendación:** APROBAR YA, incluso antes de W6. Es el gasto de mayor ROI de todo el plan: hoy no hay evidencia de NINGÚN backup — la pérdida de la DB prod (pedidos, audit logs Habeas Data, Vault) sería total e irrecuperable. 15 min de dashboard.
- **Costo:** $25/mes

### Crear proyecto konvi-dev en org Supabase SEPARADA (plan Free) — T2-02
- **Recomendación:** APROBAR con org separada obligatoria: el billing de Supabase es por organización — en la misma org que prod (Pro tras T2-05) el proyecto dev facturaría compute ~$10/mes extra. Org Free separada = $0. Acción de dashboard ~30 min (proyecto + extensiones + hook + keys). Cierra el CRITICAL dev=prod (ya hubo un soft-delete accidental).
- **Costo:** $0 (org separada; ~$35/mes total si se hiciera en la misma org)

### PITR add-on Supabase (RPO 24h → ~minutos) — T2-07
- **Recomendación:** DIFERIR con trigger registrado: re-evaluar al tener >1 tenant pagando o volumen diario de pedidos no reconstruible desde dashboards WhatsApp/Wompi, y con el RTO real medido en T2-06. Con backup diario Pro el RPO=24h es aceptable para 1 tenant.
- **Costo:** $100/mes si se aprueba (total con Pro+Render: ~$153/mes)

### Render: subir servicios prod de Free a Starter y retirar hack anti-hibernación — T2-09
- **Recomendación:** APROBAR mínimo los 3 backend (connector+api+orchestrator, ~$21/mes; web puede quedar Free). La review detectó que el anti-hibernación probablemente NO está plenamente activo (ANTI_HIBERNATION_PING_URL es sync:false y 4 servicios always-on exceden las 750h Free) → prod puede estar hibernando HOY con cold-start ~1min en webhooks Meta/Wompi. Validar precio exacto en render.com/pricing antes de aprobar. Coherente con feedback_quality_first: reduce riesgo de calidad sostenida en el path de dinero.
- **Costo:** $21-28/mes (validar precio oficial)

### Ruta de remediación del parser XLSX del importador masivo — T7-02, Wave W5
- **Recomendación:** OPCIÓN (b) split read-path: eliminar YA el paquete xlsx muerto (0 imports, cierra los 2 GHSA flaggeados, $0) y migrar SOLO la lectura de archivos subidos a un parser parcheado (sheetjs 0.20.x tarball oficial o exceljs), dejando xlsx-js-style únicamente para ESCRITURA de plantillas (sin input no confiable, y sus estilos son la razón de usarlo). La migración completa a exceljs (+1pd) queda como alternativa si prefieres cero dependencia de tarball externo. NO cerrar el item solo con 'pnpm remove xlsx': dejaría intacto el fork vulnerable que realmente parsea uploads.
- **Costo:** $0 — ~2.5 pd de esfuerzo

### Bundle de intervenciones humanas cortas distribuidas en las waves
- **Recomendación:** EJECUTAR cada una en la semana de su wave (ninguna es bloqueante hoy): (1) W4: branch protection require db-harness (~10 min); (2) W5: verificación empírica XFF en prod post-deploy (~30 min de curls); (3) W7: Auth Token Sentry + confirmar DSN poblado en Render + email de alertas (~45 min); (4) W7: confirmar que ningún monitor externo consume /status; (5) W11: sudo VM para docker/podman (~30 min). Total ~2.5h repartidas en 8 semanas.
- **Costo:** $0 — ~2.5h de tiempo founder acumulado

### notify_consent_revoked: portar al gate agentic de optout o eliminar (gap LOW desenmascarado por K-2) — Wave W7
- **Recomendación:** PORTAR la notificación al operador (email/Telegram vía notify_escalation_async existente) en el optout gate del dispatcher y registrar la decisión en ADR-0039: la revocación de consent es un evento de compliance que el operador debe ver (paridad con la conducta V1 que se perdió sin decisión documentada). Alternativa aceptable pero inferior: eliminar el dead code con nota ADR. ~0.5 pd.
- **Costo:** $0 — 0.5 pd

## Riesgos

- T1-01 puede revelar que supabase db reset NO aplica las 222 migraciones limpio (51 dependen de auth.*; drift histórico del ledger documentado en HANDOFF) — fallback: baseline vía supabase db dump del prod + migraciones futuras encima; retrasaría W4 ~2-3 días pero no invalida el harness.
- La premisa XFF de T4-01 (Render forwardea CF-Connecting-IP con la IP real) es evidencia de terceros, NO doc oficial Render — si la verificación empírica en prod la refuta, los limiters quedan best-effort anti-flood-naive y hay que escalar a otra estrategia (p.ej. fronting explícito Cloudflare); el resto del plan no depende de ello.
- Restore de vault.secrets en DR es semántica NO verificada (cifrado por-proyecto): hasta cerrar T2-ESCROW, el RTO del escenario 'pérdida de proyecto' es indefinido — un DR 'exitoso' sin credenciales deja WhatsApp/Wompi/Aveonline muertos para todos los tenants.
- Bump FastAPI/starlette 1.x (T7-04) toca 3 servicios en el path de dinero: riesgos reales son sentry-sdk 2.18 (integración parchea internals de starlette) y validación de Host header en 1.0.1 — mitigado por deploy escalonado + suite ~3.1k tests + UAT dinámico entre servicios, pero una regresión sutil en webhooks costaría un rollback.
- El refactor strangler (T5-05) opera sobre un monolito con 17.5% de coverage: si T5-03 no alcanza ≥50% con fidelidad real (FakeSupabase es más caro de lo estimado — ya ajustado a 5-6pd), la wave W9 DEBE posponerse; regla inviolable: cero refactor sin red verde + golden traces.
- Head-of-line blocking del worker (procesamiento secuencial + poll 3s) es probablemente la palanca de latencia percibida MÁS grande y solo está presupuestada su medición (W8), no su fix (concurrencia por-conversación, ~2-3pd extra post-red) — si el baseline la confirma dominante, añadir item en W10 y re-presupuestar.
- Dependencia founder-costo en W6: si Supabase Pro/Render Starter se rechazan, data-db-dr queda ~65 y el CRITICAL dev=prod parcialmente abierto — 90+ es matemáticamente inalcanzable sin esa wave (recordar feedback_quality_first: encuadrar como riesgo de calidad, no como $/ROI).
- expected_score_after son estimaciones conservadoras, no garantías: el re-score es adversarial por diseño y waves anteriores han descubierto gaps nuevos al verificar (los sweeps de HOY añadieron 1 HIGH + 5 MEDIUM); presupuestar ~10% de esfuerzo extra para follow-ups de review por wave.
- Capacidad: ~91pd netos ≈ 18-19 semanas calendario a 1 dev; W8 (performance) es paralelizable con W6/W7 si hay capacidad de review, pero comprimir waves sin gates completos (validate.sh --ci + review adversarial + UAT runtime) repite el patrón que originó los gaps W2.
- Items diferidos NO presupuestados en el total (con trigger documentado): T8-04 MeLi outbox (1.5pd, gated a tenants MeLi activos), T4-04 limiter distribuido connector (1pd, gated a numInstances>1), T3-08 relay Telegram Sentry (1pd, solo si el email de T3-06 resulta insuficiente) — suman ~3.5pd si sus triggers se activan durante el plan.

## Gaps nuevos detectados por los sweeps (regresiones / desenmascarados por K-2/Ola0/W1/W2)

- **[HIGH]** W2: el contrato de durabilidad ('retorno = desenlace terminal') se rompe con errores transitorios tragados en la correlación/credenciales — un flake DB/Vault marca el inbox como procesado y pierde el evento de pago permanentemente.
  - *evidencia:* services/api/routers/wompi_webhook.py:848-850 (_get_order_id_by_link except→None) y :868-870 (_get_order_by_id except→None) → order_id/tenant None → return terminal como ORPHAN (:214-222) o firma_invalida (:229-231); ser
- **[MEDIUM]** W2: el re-drive no puede completar side-effects interrumpidos post-confirmación — _confirm_order flip-ea status ANTES de decrementar stock; un fallo entre ambos deja orden confirmada SIN stock decrementado/notificaciones/guía, y el guard terminal hace que el re-drive lo marque como procesado.
  - *evidencia:* services/api/routers/wompi_webhook.py:876-879 (update status='confirmed') precede a :881 (_decrement_stock_on_confirm, puede lanzar — RPC reservas/orders.py:796+). Si lanza: excepción propaga (fix W2) → inbox NULL → work
- **[MEDIUM]** W2: fallo transitorio del processed-check del dedup retorna terminal ('descarta') en vez de propagar — en la ventana de crash-recovery, un segundo flake pierde silenciosamente el evento que la review clasificó como CRITICAL.
  - *evidencia:* services/api/routers/wompi_webhook.py:271-276 — si el SELECT de processed_at falla (red/DB), 'dedup_processed_check_failed → return' es un desenlace terminal para el wrapper (:135-154) → inbox marcado procesado → no hay 
- **[MEDIUM]** W2: dead-letter de eventos de DINERO es solo-log — sin métrica, sin superficie en health_metrics, sin escalación al operador, y el cleanup purga las filas dead-letter a los 30 días.
  - *evidencia:* services/ai-orchestrator/worker.py:2278-2283 (logger.error [DEAD_LETTER] ... 'requiere reconciliación MANUAL') — no incrementa self._metrics ni usa notify_escalation_async (infra ya existente, usada por health transition
- **[LOW]** W2: re-drive secuencial (hasta 20 filas × timeout 15s = 300s) dentro de _poll_cycle puede superar el umbral de heartbeat stale (120s) → /health 503 → Render reinicia el worker a mitad de ciclo cuando la API está lenta y hay backlog ≥9 filas.
  - *evidencia:* services/ai-orchestrator/worker.py:2258-2272 (httpx.AsyncClient(timeout=15) por fila, secuencial, batch p_limit=20) vs services/ai-orchestrator/server.py:66 (HEALTH_HEARTBEAT_STALE_SECONDS=120; heartbeat solo avanza al t
- **[LOW]** Ola 0: _run_job eliminó exc_info por completo — todo fallo de job del worker queda reducido a tipo + 200 chars sin traceback ni en logs locales (fuente de verdad de errores runtime), regresión de MTTR; el motivo declarado (PII a Sentry) ya quedó cubierto por el scrubber W1 para lo transmitido.
  - *evidencia:* services/ai-orchestrator/worker.py:380-388 ('Sin exc_info=True... scrubber sistémico va en W1'). El scrubber W1 llegó (observability.py:58-77 _before_send con _scrub_event) pero cubre solo eventos Sentry, y exc_info nunc
- **[LOW]** Ola 0: idempotencia de create_claim colapsa CUALQUIER reclamo nuevo del mismo (order, customer) al ticket abierto/investigating existente, sin distinguir motivo — un segundo reclamo genuinamente distinto (p.ej. 'dañado' vs 'incompleto') se traga con nota 'NO registres otro'.
  - *evidencia:* services/ai-orchestrator/agentic/tools/claims.py:159-189 — dedup por tenant_id+order_id+customer_id+status in ['open','investigating'] (claims.py:173), sin claim_type/motivo en la clave ni append del nuevo motivo al clai
- **[MEDIUM]** W2 introdujo un nuevo almacen de PII de clientes finales fuera del inventario Habeas Data: wompi_webhook_inbox persiste el payload Wompi CRUDO (nombre/email/telefono del pagador) sin tenant_id, por lo que NO lo cubre el cascade de fn_hard_delete_tenant ni el export de offboarding; ademas el cleanup 7d/30d solo corre DENTRO del job de reconciliacion (si WOMPI_INBOX_RECONCILE_ENABLED=false, retencion ilimitada) y el persist ocurre ANTES de verificar firma (payloads forjados con PII arbitraria quedan almacenados).
  - *evidencia:* services/api/routers/wompi_webhook.py:76-101 (_persist_inbox raw_payload pre-firma); supabase/migrations/20260714000000_wompi_webhook_inbox.sql:19-37 (tabla sin tenant_id) y :96-119 (cleanup 7d/30d); supabase/migrations/
- **[LOW]** K-2 desenmascaro conducta V1 no portada: al revocar consent por keyword (STOP/BAJA) el gate agentic solo hace audit log + status opted_out, sin notificar al operador; notify_consent_revoked quedo como dead code sin caller productivo (su unico caller era build_and_run_orchestration V1, y el test que anclaba la conducta se borro). Latente al baseline (0 tenants V1) pero ahora es permanente y sin decision documentada en ADR-0039.
  - *evidencia:* services/ai-orchestrator/notifications.py:253 (definicion sin callers prod — verificado con git grep en f3542fa0); services/ai-orchestrator/agentic/dispatcher.py:3770-3946 (optout gate sin notify al operador); tests/test
- **[LOW]** Docstring enganoso post-W1: _extract_request_ip del webhook MeLi afirma que el helper 'toma el hop de la DERECHA del XFF (unspoofable)', pero el default XFF_TRUSTED_HOPS_FROM_RIGHT=0 usa leftmost (spoofable) — puede inducir a un mantenedor a creer que el allowlist de origen MeLi ya es anti-spoofing cuando no lo es.
  - *evidencia:* services/api/routers/meli_webhook.py:205-206 (docstring) vs services/api/dependencies/security.py:98-110 (default 0 = leftmost historico)
- **[LOW]** Camino de log adyacente al fix W1 quedo sin masking: el branch de error de send_whatsapp_message loguea response.text completo de Meta (error_data de Meta puede ecoar el telefono del destinatario) y send_whatsapp_template guarda response.text[:200]; W1 solo enmascaro los caminos de exito/timeout. Logs Render locales no pasan por el scrubber Sentry.
  - *evidencia:* services/ai-orchestrator/whatsapp_sender.py:153-157 (body=response.text sin mask) y :516 (meta_msg = response.text[:200]); contraste con el masking agregado en :147-150 y :158-161
- **[LOW]** Cobertura viva borrada en K-2: tests/test_settings_brand_fields.py se elimino completo (importaba _is_outside_support_hours de V1), pero la mitad del archivo cubria validaciones VIVAS de TenantPatch en la API (mision/valores max_length=280, tono_comunicacion Literal) que quedaron sin test directo; test_settings_api.py solo cubre email/telefono/low_stock/nit/store_type.
  - *evidencia:* services/api/routers/settings.py:110-113 (validaciones vivas sin cobertura); commit 2ecc2df8 (borrado wholesale, 118 lineas); tests/test_settings_api.py:6-10 (no cubre brand fields)
- **[LOW]** Alcance parcial del 'scrub PII sistemico' W1: el scrubber Sentry solo redacta telefono movil COL y email; numeros de documento (cedula), direcciones y nombres — tambien PII Ley 1581 y presentes en mensajes de excepcion de los flujos de checkout — pasan sin redactar a Sentry.
  - *evidencia:* services/api/observability.py:35-37 (solo _RE_PHONE y _RE_EMAIL; sin patrones de documento/direccion) — mismo modulo replicado en services/ai-orchestrator/observability.py y services/connector-whatsapp/observability.py
- **[MEDIUM]** El rate-limit per-IP nuevo del connector (y su gemelo en Wompi webhook) se llavea con el hop IZQUIERDO del X-Forwarded-For, controlable por el cliente: un atacante lo bypassea rotando XFF y, peor, puede ENVENENAR el bucket de las IPs egress reales de Meta (publicadas) para provocar 429 a webhooks legítimos — palanca de degradación de entrega de mensajes que NO existía antes de Ola 0. La mitigación (XFF_TRUSTED_HOPS_FROM_RIGHT>0) existe pero está apagada y el env no aparece en render.yaml.
  - *evidencia:* services/connector-whatsapp/dependencies/meta.py:111-124 (_client_ip default leftmost), :491-492 (_rate_limit_hit llaveado con esa IP antes del HMAC); services/api/dependencies/security.py:104,120 (mismo default en API);
- **[LOW]** Doc-drift de seguridad en el webhook MeLi: el docstring W1 de _extract_request_ip afirma que toma 'el hop de la DERECHA del XFF (unspoofable)' pero el default activo en prod es leftmost — el allowlist de IPs MeLi (única defensa de origen, MeLi no firma) sigue siendo XFF-spoofable mientras el comentario lo presenta como cerrado, con riesgo de que la acción humana pendiente se dé por hecha.
  - *evidencia:* services/api/routers/meli_webhook.py:205-208 (docstring 'DERECHA... unspoofable') vs services/api/dependencies/security.py:104,120 (default 0 = leftmost) y render.yaml sin el env; el check de origen depende de esa IP en 
- **[LOW]** K-2 borró tests/test_settings_brand_fields.py completo porque importaba el helper V1 eliminado (_is_outside_support_hours), pero el archivo también cubría contrato API VIVO: validación TenantPatch de mision/valores (max_length=280) y tono_comunicacion (Literal de 5 valores). Hoy ningún test ancla esas validaciones (test_settings_api.py cubre email/telefono/low_stock; test_coherence_pact solo orphans de schema).
  - *evidencia:* git show 3d540f12:tests/test_settings_brand_fields.py (cubría TenantPatch brand fields + _is_outside_support_hours); código vivo en services/api/routers/settings.py:110-122; grep 'mision|tono' en tests/test_settings_api.
- **[LOW]** Tras K-2, la lógica after-hours quedó SOLO prompt-driven en V3: el único gate determinístico (_is_outside_support_hours) era V1 y fue eliminado; support_schedule/after_hours_message ahora se inyectan al prompt (business_ops_section) y el LLM decide si es fuera de horario — semántica más débil que la que el feature tenant-configurable implicaba, más 2 comentarios stale que aún referencian la función borrada.
  - *evidencia:* services/ai-orchestrator/orchestrator.py:2161,2170 (referencias stale a _is_outside_support_hours inexistente); services/ai-orchestrator/agentic/prompt/builder.py:250-259 (schedule solo como contexto de prompt); grep sin
- **[LOW]** El scrub PII W1 quedó triplicado copy-paste en los 3 servicios (misma regex/función en api, orchestrator y connector) con solo un test de EXISTENCIA como parity — misma clase de riesgo de drift que K-3 tuvo que cerrar para las 3 copias de _hash_phone. Además, _scrub_event no redacta KEYS de dicts (solo values) ni maneja sets.
  - *evidencia:* services/api/observability.py:41-54, services/ai-orchestrator/observability.py:41-54, services/connector-whatsapp/observability.py:44-56 (3 copias idénticas; dict comprehension {k: _scrub_event(v)} deja keys sin scrub); 

---

## Apéndice — Work items detallados por track (referencia de ejecución)

### T1-harness
*Estado actual:* Track T1 (harness ejecutable) parte de cero real: .github/workflows/ci.yml (117 líneas, 2 jobs ubuntu-latest) no contiene ningún bloque `services:` ni Postgres — grep confirmado; tests/ tiene 244 entradas pytest pero CERO tests con conexión a DB (grep psycopg/asyncpg/psql = 0 hits): toda la evidencia RLS/authz/RPC del re-score 73/100 es regex sobre SQL o verificación manual contra prod. Inventario verificado: supabase/migrations/ = 222 archivos; dependencias de schemas supabase-managed: auth.* en 51 archivos (64 auth.uid, 56 auth.jwt, 25 auth.users, 13 auth.role), storage.objects 33 refs, vaul

*Review adversarial:* ADJUSTED — Estrategia (a) VALIDADA: verifiqué vía WebFetch que supabase/postgres bundlea pgmq 1.4.4, pg_cron 1.6.4, vector 0.8.0 y vault 0.3.1 en PG15/17, config.toml pinnea major_version=17/puerto 54322, y el punto abierto (db start vs start para auth.*) es genuino y correctamente diferido a T1-01 — con el ag

#### T1-01 — Spike de reproducibilidad: `supabase db reset` aplica las 222 migraciones en stack local CI-like  `[P0 · 1pd]`
Es el gate empírico de toda la estrategia (a). Las docs oficiales confirman las extensiones bundleadas (https://github.com/supabase/postgres: pgmq 1.4.4, pg_cron 1.6.4, vector 0.8.0, vault 0.3.1 en PG17) pero NO especifican si `supabase db start` solo-DB provee auth.users/auth.jwt() o se requiere `supabase start` con GoTrue; 51 migraciones tocan auth.*. Resolverlo con evidencia antes de escribir suites evita construir sobre arena.

**Pasos:**
1. En un runner GH Actions efímero (workflow_dispatch temporal en branch, runner ubuntu-latest con docker) o en cualquier máquina con docker: `supabase db start` y luego `supabase db reset` sobre el repo
1. Si falla por objetos auth/storage ausentes: reintentar con `supabase start -x studio,inbucket,imgproxy,edge-runtime` (incluye GoTrue+storage-api) + `supabase db reset`; anotar cuál variante funciona
1. Registrar: número de migraciones aplicadas (debe ser 222), migraciones que fallan y por qué (extensión, schema, rol), tiempo total de `db reset`
1. Verificar post-reset via psql (puerto 54322): `SELECT extname FROM pg_extension` contiene pgmq, pg_cron, vector, supabase_vault; existen roles authenticated/anon/service_role/supabase_auth_admin; `SELECT public.custom_access_token_hook('{}'::jsonb)` no explota por objeto ausente
1. Si >0 migraciones fallan de forma irreparable: documentar en docs/adr/ la decisión de fallback (c) schema-fixture subset SOLO para las 4 suites core, con la advertencia explícita de drift; NO activar (c) sin este registro
1. Documentar resultado en .context/01-state.md (variante ganadora db start vs start, tiempo, migraciones aplicadas)

**Aceptación:**
- Log de CI o transcript reproducible que muestra `supabase db reset` completando con 222/222 migraciones aplicadas (o lista exacta de las que fallan con causa raíz)
- Query `SELECT extname FROM pg_extension` evidenciando pgmq, pg_cron, vector, supabase_vault presentes
- Decisión registrada por escrito: variante de arranque (db start vs start -x ...) y si el fallback (c) queda descartado o queda como contingencia

#### T1-02 — Infraestructura pytest del harness: marker dbharness, conftest con DSN, helpers de identidad JWT y seed multi-tenant  `[P0 · 2pd]` · dep: T1-01
Las 4 suites comparten la misma mecánica: conexión psycopg al Postgres local (127.0.0.1:54322 según config.toml:29), impersonación role-aware (`SET LOCAL ROLE authenticated` + `set_config('request.jwt.claims', ...)`) y datos semilla de 2 tenants con usuarios en roles distintos. Centralizarlo evita 4 implementaciones divergentes y hace las suites agnósticas al backend (sirven igual si algún día se usa fallback c).

**Pasos:**
1. Añadir `psycopg[binary]` a requirements de test (services/api o requirements-dev raíz, donde viva la suite pytest actual)
1. Crear tests/dbharness/conftest.py: fixture session-scoped `db_dsn` que lee env HARNESS_DB_URL (default postgresql://postgres:postgres@127.0.0.1:54322/postgres) y hace pytest.skip('harness DB no disponible') si la conexión falla — skip elegante, nunca error
1. Registrar marker `dbharness` en pytest.ini/pyproject y excluirlo del run por defecto de validate.sh (`-m 'not dbharness'`) para no romper la suite actual de ~3490 tests en máquinas sin docker
1. Helper `as_user(conn, user_id, tenant_id, role, email)`: abre transacción, `SET LOCAL ROLE authenticated`, `SELECT set_config('request.jwt.claims', json, true)` con sub/tenant_id/role/email replicando la forma exacta que emite custom_access_token_hook (leer 20260426070000 para copiar los nombres de claims reales, no inventarlos); variantes `as_anon` y `as_service_role`
1. Fixture `seed_tenants`: inserta (como postgres/service_role) tenant A y B, usuarios en auth.users (o vía supabase_auth_admin si auth.users tiene constraints de GoTrue — resolver según hallazgo T1-01), memberships en tenant_users con roles owner/admin/member, filas en tenant_integrations y notification_settings de ambos tenants; rollback/TRUNCATE al terminar para idempotencia
1. Smoke test tests/dbharness/test_smoke.py: conecta, verifica RLS habilitado en tenant_users (`SELECT relrowsecurity FROM pg_class`), verifica los 3 roles impersonables funcionan

**Aceptación:**
- `pytest tests/dbharness -m dbharness` en máquina CON stack local: smoke test PASA
- `pytest tests/ -m 'not dbharness'` en la VM actual (sin docker): suite completa actual pasa sin cambios y sin intentos de conexión
- Helper as_user demostrado: query `SELECT auth.uid(), auth.jwt()` bajo impersonación devuelve el sub y claims inyectados (test incluido)
- Ejecutar el smoke dos veces seguidas pasa (seed idempotente)

#### T1-03 — Suite matriz RLS deny cross-tenant role-aware: tenant_users, tenant_integrations, notification_settings  `[P0 · 2pd]` · dep: T1-02
Cobertura (1) del track: las 8 policies nombradas (tenant_users_{select_member,insert_owner,update_owner,delete_owner} en 20260713000000:24-57; tenant_integrations_{select_member,write_privileged} y notification_settings_{select_member,write_privileged} en 20260713020000:18-45) hoy solo tienen verificación manual contra prod. La escalada RBAC via PostgREST fue el hallazgo CRITICAL verificado del audit 2026-07-13 — esta suite es su regresión permanente.

**Pasos:**
1. tests/dbharness/test_rls_matrix.py parametrizado: (tabla, operación SELECT/INSERT/UPDATE/DELETE, rol owner/admin/member, tenant propio/ajeno) → esperado allow/deny; derivar la matriz esperada LEYENDO las policies reales de las 2 migraciones, no de memoria
1. Casos deny obligatorios: member de tenant A no SELECT filas de tenant B en las 3 tablas; member (no owner) no INSERT/UPDATE/DELETE en tenant_users de su propio tenant; rol no privilegiado no escribe tenant_integrations/notification_settings; UPDATE cross-tenant con USING-bypass (UPDATE ... SET tenant_id=B) denegado
1. Casos allow: owner gestiona tenant_users de su tenant; member SELECT su propio tenant en las 3 tablas
1. Roles especiales: anon → 0 filas en las 3 tablas; service_role → bypass total (documentando que el backend DEBE filtrar por tenant_id per ADR-0025)
1. Caso escalada RBAC: member intenta UPDATE de su propia fila tenant_users a role='owner' → deny (el vector CRITICAL del audit)
1. Aserciones de deny estrictas: para SELECT esperar 0 filas; para writes esperar excepción de policy O 0 filas afectadas — nunca aceptar éxito silencioso

**Aceptación:**
- Matriz completa ejecuta en CI: >=30 casos parametrizados, todos verdes
- Test de mutación (prueba del harness, puede ser manual documentada): DROP de una policy (p.ej. tenant_users_select_member) en el contenedor local hace fallar la suite — demuestra que el harness detecta regresiones reales
- Caso escalada member→owner en tenant_users presente y verde
- Cada caso deny asevera resultado explícito (0 filas o excepción), sin try/except genérico que trague fallos

#### T1-04 — Suite pgsec_* role-checks contra vault real (extensión supabase_vault bundleada)  `[P0 · 1.5pd]` · dep: T1-02
Cobertura (2): las 4 funciones pgsec_read/update/delete/upsert_secret (20260713010000:17-141) son la única barrera entre un member de tenant A y los secretos Meta/Wompi de tenant B. Son SECURITY DEFINER sobre vault.secrets — un refactor que rompa el check de membership expone credenciales cross-tenant. La imagen local incluye vault 0.3.1 (confirmado en https://github.com/supabase/postgres), así que se prueba contra vault REAL, no mock.

**Pasos:**
1. tests/dbharness/test_pgsec_vault.py: fixture que crea secretos via vault.create_secret con naming ownership real del repo (leer cómo derivan v_owner las funciones en 20260713010000 — el tenant se extrae del name del secreto — y replicar ese formato exacto)
1. pgsec_read_secret: member del tenant owner → devuelve decrypted_secret correcto; usuario de otro tenant → excepción tenant_ownership_violation; usuario sin membership alguna → excepción
1. pgsec_update_secret y pgsec_delete_secret: misma matriz allow/deny; verificar post-condición (secreto actualizado / fila eliminada solo en caso allow)
1. pgsec_upsert_secret: creación con name de tenant ajeno → excepción 'tenant_ownership_violation' (20260713010000:141)
1. service_role / conexiones con auth.uid() NULL → bypass intacto (el backend bot/connector depende de esto; regresión aquí rompe prod)
1. Caso id inexistente: comportamiento definido (excepción o NULL) anclado en test para detectar cambios semánticos

**Aceptación:**
- Matriz 4 funciones x {member-owner-tenant, member-otro-tenant, sin-membership, service_role} completa y verde en CI contra vault real
- Deny asevera el mensaje 'tenant_ownership_violation' (match parcial), no excepción genérica
- Test de round-trip: create → pgsec_read devuelve el plaintext exacto → pgsec_update → read devuelve el nuevo valor → pgsec_delete → read falla

#### T1-05 — Suite durabilidad Wompi inbox: concurrencia SKIP LOCKED, lease, dead-letter y cleanup  `[P0 · 2pd]` · dep: T1-02
Cobertura (3): claim_wompi_inbox_batch (20260714000000:62-88) es código de concurrencia recién escrito (branch actual w2-wompi-durability) sin un solo test; los bugs de esta clase (cron Wompi VOIDED roto, P0 del audit) ya ocurrieron. SKIP LOCKED + lease + dead-letter solo se pueden probar con conexiones concurrentes reales — imposible estáticamente.

**Pasos:**
1. tests/dbharness/test_wompi_inbox.py con psycopg y 2+ conexiones independientes (autocommit controlado)
1. No-doble-claim concurrente: conn1 BEGIN + claim batch (mantiene tx abierta), conn2 claim simultáneo → intersección de checksums vacía (FOR UPDATE SKIP LOCKED efectivo); tras COMMIT de conn1, verificar attempts incrementado exactamente 1 vez por claim
1. Lease no-re-claim: claim → segundo claim inmediato del mismo evento → 0 filas; manipular claimed_at a now()-301s via UPDATE directo (rol postgres) → re-claim SÍ devuelve el evento (evita esperar 300s reales)
1. Dead-letter: fijar attempts=5 (p_max_attempts default) → claim lo excluye; attempts=4 → incluido y attempts pasa a 5
1. min_age: evento con received_at reciente (< p_min_age_seconds) excluido; más viejo, incluido — leer el default real del parámetro en la migración y anclarlo
1. cleanup_wompi_inbox: seed de filas processed_at antigua (>7d), dead-letter antigua (>30d), processed reciente, dead-letter reciente, pendiente vigente → solo las 2 primeras borradas; retornos/counts verificados
1. Verificar orden de claim (ORDER BY de la función) si el contrato lo promete — leer 20260714000000 completo antes de asertar

**Aceptación:**
- Test de concurrencia con 2 conexiones simultáneas verdes en CI, sin sleeps > 1s (lease simulado via UPDATE de claimed_at)
- Los 5 comportamientos (no-doble-claim, lease, dead-letter, min_age, cleanup) tienen cada uno al menos 1 caso positivo y 1 negativo
- Mutación manual documentada: quitar SKIP LOCKED en el contenedor hace fallar el test de concurrencia (conn2 bloquea o doble-claim)

#### T1-06 — Suite custom_access_token_hook: inyección de rol + canario anti-FORCE-RLS  `[P0 · 1pd]` · dep: T1-02
Cobertura (4): el hook (20260426070000:22-67) es el origen de TODOS los claims tenant_id/role del Tenant Console; es SECURITY DEFINER leyendo tenant_users con GRANT exclusivo a supabase_auth_admin. El riesgo evaluado del re-score: aplicar FORCE RLS a tenant_users sin policy para el flujo del hook rompe el login entero de forma silenciosa. Necesita regresión ejecutable + canario que dispare ANTES de que alguien lo haga en una migración futura.

**Pasos:**
1. tests/dbharness/test_access_token_hook.py: seed usuario con membership role=owner en tenant A → `SELECT public.custom_access_token_hook(event)` con event jsonb realista ({user_id, claims:{}} — leer el formato exacto que consume el hook en 20260426070000) → claims de salida contienen tenant_id y role correctos
1. Usuario sin membership → verificar comportamiento fail-closed real del hook (leer el código: ¿claims sin tenant/role, o NULL?) y anclarlo como contrato
1. Usuario con membership revocada mid-session: DELETE de tenant_users → siguiente invocación del hook ya no emite el rol (la razón de ser del hook vs el trigger anterior)
1. Test de permisos: `SET ROLE authenticated; SELECT custom_access_token_hook(...)` → permission denied (REVOKE de 20260426070000:67 efectivo); `SET ROLE supabase_auth_admin` → funciona
1. CANARIO FORCE RLS: test que ejecuta `ALTER TABLE tenant_users FORCE ROW LEVEL SECURITY` en una transacción, invoca el hook como supabase_auth_admin, asevera el resultado (hoy: el hook deja de ver filas → claims vacíos), y ROLLBACK — con comentario que documenta que FORCE RLS exige policy explícita para el definer ANTES de aplicarse (insumo directo para el work item de FORCE RLS de otro track)
1. Marcar en el test la dependencia inversa: si un track futuro añade policies para supabase_auth_admin, este canario debe actualizarse (assert cambia de claims-vacíos a claims-correctos)

**Aceptación:**
- Hook probado end-to-end vía SELECT directo: rol inyectado correcto para owner/admin/member, y comportamiento sin-membership anclado
- REVOKE verificado: rol authenticated no puede ejecutar el hook
- Canario FORCE RLS presente, verde, con rollback limpio, y documentando en su docstring el prerequisito de policies antes de FORCE RLS
- Si el formato del event jsonb difiere del asumido, el test usa el formato real de la doc de Supabase auth hooks — VALIDAR EN DOCUMENTACION OFICIAL: https://supabase.com/docs/guides/auth/auth-hooks (shape del payload custom_access_token)

#### T1-07 — Integrar harness en scripts/validate.sh: etapa --db-harness con skip elegante sin docker  `[P0 · 1pd]` · dep: T1-02
validate.sh es el contrato único pre-deploy (CLAUDE.md + feedback_deploy_run_ci_not_build: correr el comando EXACTO del CI). El harness debe vivir dentro de ese contrato, pero la VM de desarrollo no tiene docker — sin skip elegante, --ci se rompería localmente y se erosionaría la disciplina de validación.

**Pasos:**
1. Añadir a scripts/validate.sh (420 líneas actuales) función run_db_harness: detecta `command -v docker` Y `command -v supabase`; si falta alguno → _warn 'db-harness SKIP (docker/supabase CLI ausente — cobertura RLS solo en CI)' y continúa con exit 0 de la etapa
1. Si están presentes: `supabase db start` (o la variante ganadora de T1-01) idempotente, `supabase db reset --no-seed` si aplica, luego `python3.11 -m pytest tests/dbharness -m dbharness -q`; fallo de tests → _err y exit 1
1. Nueva flag --db-harness que activa la etapa standalone; incluirla en el paquete --ci (que es lo que corre GitHub Actions) DESPUÉS de que T1-08 esté verde, para no romper CI antes de tiempo
1. Asegurar que el run pytest principal existente añade `-m 'not dbharness'` (coordinado con T1-02) — verificar que el conteo ~3490 tests reportado no cambia
1. Modo teardown opcional (env HARNESS_KEEP_DB=1 conserva el contenedor para debug local)
1. Actualizar el bloque 'Validación pre-deploy' de CLAUDE.md con la nueva flag y su semántica de skip

**Aceptación:**
- En la VM actual (sin docker): `bash scripts/validate.sh --ci` pasa con warn visible de skip, exit 0, y el conteo de tests principal intacto
- En máquina con docker: `bash scripts/validate.sh --db-harness` levanta stack, corre las suites dbharness y falla (exit!=0) si una suite falla — demostrado rompiendo un test a propósito
- CLAUDE.md documenta la flag; ninguna otra etapa de validate.sh cambió de comportamiento

#### T1-08 — Job db-harness en ci.yml: Supabase CLI + db reset + pytest -m dbharness como gate obligatorio de PR  `[P0 · 1pd]` · dep: T1-01,T1-02,T1-07
CI es el único entorno garantizado con docker (la VM no lo tiene) — este job ES el enforcement del track: convierte las 222 migraciones + 4 suites en un gate reproducible por PR. Sin él, todo lo anterior es opt-in local que nadie corre.

**Pasos:**
1. Nuevo job `db-harness` en .github/workflows/ci.yml (runs-on ubuntu-latest, docker preinstalado en runners GitHub-hosted): checkout, setup-python 3.11 (mismo pin del job existente ci.yml:28), instalar deps de test
1. Instalar CLI con la action oficial supabase/setup-cli@v1 pinneando version — VALIDAR EN DOCUMENTACION OFICIAL: https://github.com/supabase/setup-cli (inputs/version disponibles)
1. `supabase db start` + `supabase db reset` (variante ganadora T1-01); si reset falla → job rojo (las migraciones son parte del contrato bajo test: una migración nueva que no aplica limpio debe bloquear el PR)
1. `HARNESS_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python3.11 -m pytest tests/dbharness -m dbharness -q` — DSN/password según output real de supabase db start (ajustar con evidencia del spike)
1. timeout-minutes explícito (~15) y upload de logs del contenedor como artifact en fallo (docker logs supabase_db_*) para debuggabilidad
1. Marcar el job como required check del branch protection de main (esto es acción founder en GitHub UI → INTERVENCION HUMANA REQUERIDA: RESPONSABLE founder; PASOS Settings→Branches→main→require db-harness; INSUMOS nombre exacto del check; CRITERIO DE EXITO PR de prueba bloqueado con harness rojo)
1. Medir duración total del job en 3 corridas y registrarla en .context/01-state.md (presupuesto: <8 min; si excede, evaluar cache de imagen docker)

**Aceptación:**
- PR de prueba con las 4 suites verdes muestra job db-harness verde con 222 migraciones aplicadas visibles en log
- PR de sabotaje (romper una policy o quitar SKIP LOCKED) muestra job db-harness ROJO — evidencia adjunta al cierre del item
- Duración del job medida y documentada; branch protection actualizado por founder o marcado explícitamente como pendiente humano

#### T1-09 — Habilitar ejecución local del harness en la VM (docker o podman rootless)  `[P2 · 0.5pd]` · gated: intervencion-humana · dep: T1-07
Hoy el harness solo corre en CI (VM sin docker; which docker → not found). Poder reproducir fallos localmente reduce el ciclo de debug de ~5 min por push a segundos. NO bloquea el track: el enforcement es CI.

**Pasos:**
1. INTERVENCION HUMANA REQUERIDA — RESPONSABLE: founder/ops con sudo en la VM. PASOS: instalar docker-ce o podman (rootless preferido en OL9/UEK: `dnf install podman podman-docker`) y habilitar el socket para el usuario ansible. INSUMOS: acceso sudo a la VM. CRITERIO DE EXITO: `docker ps` (o alias podman-docker) funciona sin sudo como ansible
1. Verificar compatibilidad supabase CLI 2.90.0 con podman-docker si se elige podman — VALIDAR EN DOCUMENTACION OFICIAL: https://supabase.com/docs/guides/local-development (requisitos de container runtime del CLI); si no está soportado, instalar docker-ce
1. Correr `bash scripts/validate.sh --db-harness` end-to-end en la VM y comparar resultado con CI
1. Advertencia operativa a documentar: la VM comparte la Supabase de PROD (memoria del proyecto) — el harness usa SOLO el contenedor local en 54322; verificar que ningún test dbharness lee SUPABASE_URL/SERVICE_ROLE del entorno (grep en tests/dbharness + assert en conftest de que el DSN apunta a 127.0.0.1)

**Aceptación:**
- `bash scripts/validate.sh --db-harness` verde en la VM con el mismo resultado que CI
- conftest de dbharness rechaza (assert) cualquier DSN que no sea host local — imposible apuntar el harness a prod por accidente
- Runtime elegido y su instalación documentados en docs/HANDOFF.md

### T2-staging-dr
*Estado actual:* T2 — Aislamiento dev/staging/prod + DR. Estado verificado 2026-07-16: (a) dev local y prod comparten el MISMO proyecto Supabase — scripts/seed_tenant_zero.py lee SUPABASE_SERVICE_ROLE_KEY del .env local y escribe directo (líneas 4-27), scripts destructivos (wipe_conversation.py, purge_tenant_storage.py) operan contra esa misma DB; ya hubo un soft-delete accidental del founder. (b) DR inexistente: docs/operations/runbooks/ solo tiene 2 runbooks (auth-email, wompi-reconciliation), ninguno de restore full-DB; plan Supabase actual no verificable desde el repo (VALIDAR en dashboard) — si es Free, s

*Review adversarial:* ADJUSTED — Los 6 hallazgos y la topologia base sobreviven la refutacion: verifique en codigo real dev=prod (seed_tenant_zero.py:4-27 + cero guards en scripts/ y services/), 2 runbooks sin DR, 222 migraciones (54 no-idempotentes, 40 con INSERT — conteos reproducidos exactos), plan free x4 en render.yaml:31/125/

#### T2-01 — Pre-flight de replay: hacer las 222 migraciones aplicables desde cero en un proyecto virgen  `[P0 · 1.5pd]`
El proyecto dev nuevo (y cualquier restore DR a proyecto limpio) exige que la cadena completa de migraciones aplique sin el drift historico del ledger prod (HANDOFF.md:25-29). Hoy hay 54 migraciones sin patrones idempotentes, 40 con seeds INSERT INTO y 5 que llaman cron.schedule sin que ninguna migre CREATE EXTENSION pg_cron.

**Pasos:**
1. Crear migracion bootstrap 00000000000000_extensions.sql (o pre-script documentado) con CREATE EXTENSION IF NOT EXISTS pg_cron/pg_net y verificacion de vector+pgmq (ya cubiertas en 20260412000000 y 20260420000003/4)
1. Auditar las 5 migraciones con cron.schedule (20260502000000, 20260504000000, 20260505010000, 20260605000000, 20260704150100) y envolver en guard 'IF extension pg_cron disponible' las que no lo tengan
1. Auditar las 40 migraciones con INSERT INTO: clasificar seeds de sistema (deben replicarse) vs datos KAIU/prod (deben ser no-op en proyecto virgen); verificar que 20260426020000_vault_setup_and_migration.sql es no-op con tenant_integrations vacia (los loops son data-driven, revisado: si)
1. Grep de referencias a UUIDs/tenants hardcodeados y a storage.buckets (4 migraciones) verificando que crean el bucket en vez de asumirlo
1. Dry-run: instalar Docker en la VM y correr supabase db start + supabase db reset (replay completo local); si Docker no es viable, usar el proyecto dev desechable de T2-02 como banco de pruebas iterativo
1. Commitear fixes de idempotencia como migraciones nuevas o correcciones a archivos aun-no-aplicados (NUNCA editar migraciones ya aplicadas a prod; ver feedback_supabase_migrations)

**Aceptación:**
- supabase db reset (local Docker) o supabase db push contra proyecto virgen aplica las 222+ migraciones end-to-end con exit 0 y sin intervencion manual salvo las documentadas
- Documento corto en docs/operations/ listando los prerequisitos manuales inevitables (extensiones dashboard, auth hook) con su orden exacto
- bash scripts/validate.sh --ci sigue verde

#### T2-02 — Crear proyecto Supabase dev/staging (Free, $0) y aplicar el esquema completo + configuracion manual  `[P0 · 1pd]` · gated: intervencion-humana · dep: T2-01
Separacion fisica dev/prod es el fix del hallazgo critical #1. Plan Free basta para dev (2 proyectos activos por org, verificado supabase.com/pricing 2026-07-16) — costo $0, no gated por costo, pero exige acciones de dashboard del founder.

**Pasos:**
1. INTERVENCION HUMANA REQUERIDA — RESPONSABLE: founder. PASOS: crear proyecto 'konvi-dev' en la org Supabase (region us-east-1 o la misma de prod), habilitar extensiones pg_cron/pg_net en Dashboard→Database→Extensions, registrar el custom_access_token_hook en Auth→Hooks (mismo hook que prod, ver 20260406181239_custom_claims_trigger.sql y sucesoras), copiar publishable/secret keys. INSUMOS: cuenta Supabase org. CRITERIO DE EXITO: proyecto activo con keys entregadas al repo local (~30 min)
1. supabase link --project-ref <dev-ref> desde un checkout/worktree dedicado y supabase db push (replay validado en T2-01); iterar fixes si algo falla — el proyecto es desechable, se puede resetear
1. Aplicar plantillas de auth email (supabase/templates/) via Management API o dashboard; SMTP custom NO necesario en dev (usar builtin con rate bajo)
1. Verificar post-apply: pg_cron jobs agendados (select * from cron.job), colas pgmq creadas, buckets storage existentes (consent-evidence, offboarding-archive, tenant-media), RLS activo en tablas core
1. Correr scripts/dump_schema_canonical.py --diff apuntando al proyecto dev y comparar contra tests/fixtures/db_schema_canonical.json para probar paridad de esquema dev vs prod

**Aceptación:**
- Proyecto dev con 222+ migraciones aplicadas y ledger supabase_migrations.schema_migrations completo SIN repair
- dump_schema_canonical --diff reporta cero diferencias en tablas core vs fixture canonico
- cron.job y pgmq.list_queues() devuelven los jobs/colas esperados; los 3 buckets existen

#### T2-03 — Seed de datos no-prod + re-provision de Vault secrets per-tenant en el proyecto dev  `[P0 · 1pd]` · dep: T2-02
El proyecto dev necesita un tenant funcional (catalogo, agente, KB) con credenciales sandbox propias en Vault — las credenciales viven SOLO en vault.secrets del proyecto prod (20260426020000) y no se pueden copiar; deben re-crearse.

**Pasos:**
1. Provisionar tenant dev con scripts/admin/provision_tenant.py --tenant-name 'KAIU Dev' --owner-email <founder> apuntando el .env al proyecto dev
1. Sembrar vertical y catalogo con scripts/seed_kaiu_verticals.sql + scripts/seed_kaiu_attribute_contracts.sql + subconjunto de productos ficticios (NO copiar PII de contacts/messages prod — usar datos sinteticos)
1. Re-provisionar Vault dev: scripts/admin/seed_konvi_dev_app_secret_vault.py para Meta App dev (app_secret + access_token del numero de pruebas), y RPCs pgsec_create_secret para Wompi sandbox keys y Aveonline demo
1. Registrar integraciones en tenant_integrations del tenant dev con los *_secret_id nuevos (patron '<tenant_id>/<provider>/<credential>' de 20260527020000_aveonline_provider_setup.sql:17)
1. Escribir scripts/admin/seed_dev_project.py idempotente que orqueste todo lo anterior (re-crear dev desde cero en <30 min, prerequisito del test de restore T2-06)

**Aceptación:**
- Conversacion E2E dinamica en dev: mensaje WhatsApp al numero de pruebas → bot responde leyendo catalogo del proyecto DEV (verificar tenant_id y project ref en logs)
- Cero filas de PII real (contacts, messages, orders de prod) en el proyecto dev
- seed_dev_project.py re-ejecutable: segunda corrida termina sin error ni duplicados

#### T2-04 — Cutover del entorno local a dev + guardrails anti-prod en scripts destructivos  `[P0 · 1pd]` · dep: T2-03
Cerrar el vector del incidente original: que ningun comando local pueda tocar prod por accidente. Los 4 servicios Render NO cambian (son prod y siguen apuntando a prod via dashboard); el cambio real es .env local, ngrok y guardas de codigo.

**Pasos:**
1. Actualizar .env local: NEXT_PUBLIC_SUPABASE_URL/keys → proyecto dev; añadir SUPABASE_ENV=development y PROD_PROJECT_REF=<ref-prod> como constante de guarda
1. Añadir guardrail comun (p.ej. scripts/lib/env_guard.py) que aborta si la URL apunta al ref prod salvo flag explicito --allow-prod: aplicarlo a wipe_conversation.py, purge_tenant_storage.py, seed_tenant_zero.py, scripts/uat/* y scripts/debug destructivos
1. Re-apuntar webhooks sandbox: Meta App dev → https://<ngrok-connector>/..., Wompi sandbox → https://<ngrok-api>/api/v1/webhooks/wompi (2 cuentas ngrok existentes, reference_local_ngrok_urls); actualizar PUBLIC_WEBHOOK_URL local (.env.example:195)
1. Verificar en Render Dashboard que las env vars sync:false de los 4 servicios siguen con las keys PROD (no tocar); documentar en .env.example la nueva seccion [DEV-PROJECT]
1. Actualizar docs/HANDOFF.md y .context/01-state.md con la topologia de 2 proyectos

**Aceptación:**
- python3.11 scripts/wipe_conversation.py contra ref prod SIN --allow-prod termina con exit!=0 y mensaje claro (test automatizado del guard en tests/)
- validate.sh --ci verde con .env apuntando a dev; smoke E2E local (webhook ngrok → connector → orchestrator → respuesta) funciona contra dev
- Render prod sigue Deployed y funcional post-cutover (verificar /health de los 4 servicios)

#### T2-05 — Upgrade proyecto Supabase PROD a plan Pro ($25/mes) — backups diarios 7d  `[P0 · 0.25pd]` · gated: founder-costo
Prerequisito minimo de DR: hoy no hay evidencia de NINGUN backup. Pro incluye backups diarios con 7 dias de retencion y $10/mes de credito compute (cubre 1 Micro). Verificado en supabase.com/pricing (fetch 2026-07-16). DECISION FINAL recomendada: aprobar — es el gasto de mayor ROI de todo el track. RIESGO de no hacerlo: perdida total e irrecuperable de la DB prod (pedidos, Habeas Data audit logs, Vault).

**Pasos:**
1. INTERVENCION HUMANA REQUERIDA — RESPONSABLE: founder. PASOS: (1) verificar plan actual del proyecto prod en Dashboard→Settings→Billing; (2) upgrade a Pro; (3) confirmar en Database→Backups que el primer backup diario aparece en <24h. INSUMOS: tarjeta, $25/mes. CRITERIO DE EXITO: backup diario visible y descargable (~15 min)
1. Registrar en docs/HANDOFF.md el plan, la ventana de backup y la retencion (7 dias)
1. Activar spend cap ON (default Pro) y decidir consciente si dejarlo (protege costo, arriesga pausa de servicio al exceder limites) — anotar la decision

**Aceptación:**
- Dashboard muestra plan Pro y >=1 backup diario completado del proyecto prod
- HANDOFF.md documenta plan + retencion + decision de spend cap

#### T2-06 — Runbook DR full-DB + PRUEBA REAL de restore con RTO medido + calendario de re-test  `[P1 · 2pd]` · dep: T2-02,T2-05
Un backup sin restore probado no es DR. El proyecto dev (T2-02) es el blanco perfecto para ensayar el restore sin riesgo. Define RPO/RTO honestos: con Pro diario, RPO=24h; el RTO se mide, no se declara.

**Pasos:**
1. Escribir docs/operations/runbooks/disaster-recovery-full-db.md: escenarios (borrado logico, corrupcion, perdida de proyecto), fuente (backup diario Pro / PITR si se aprueba T2-07), pasos exactos de restore via Dashboard y via CLI, verificacion post-restore (dump_schema_canonical --diff, conteos de tablas core, smoke E2E), y re-apuntado de servicios Render si el restore es a proyecto nuevo
1. VALIDAR EN DOCUMENTACION OFICIAL (supabase.com/docs/guides/platform/backups): si el backup diario es fisico o logico, si incluye vault.secrets (critico: credenciales per-tenant) y que NO incluye Storage objects — documentar hallazgos en el runbook
1. Ejecutar la prueba: descargar backup prod del dia, restaurarlo sobre el proyecto dev (o proyecto temporal), cronometrar de inicio a smoke verde → ese es el RTO real
1. Documentar RPO/RTO oficiales resultantes (propuesta inicial: RPO 24h / RTO 4h con Pro; RPO 2min / RTO 4h si PITR) en el runbook y en .context/01-state.md
1. Calendarizar re-test trimestral (recordatorio en el runbook + tarea recurrente) — un restore que no se re-ensaya se pudre con el drift del esquema

**Aceptación:**
- Restore completo ejecutado al menos 1 vez con RTO medido y anotado en el runbook
- Runbook incluye verificacion post-restore ejecutable (comandos concretos) y el hallazgo verificado sobre vault + Storage en backups
- RPO/RTO publicados en docs y coherentes con el plan contratado

#### T2-07 — Decision founder: PITR add-on ($100/mes por 7d) — RPO 24h vs ~2min  `[P1 · 0.25pd]` · gated: founder-costo · dep: T2-05,T2-06
Con solo backup diario, un DELETE accidental a las 18:00 pierde todo el dia de pedidos/conversaciones. PITR (verificado supabase.com/pricing: add-on $100/mes por 7 dias de retencion, requiere plan pago) baja RPO a minutos. RECOMENDACION: diferir hasta tener >1 tenant pagando o volumen de pedidos diario que no se pueda reconstruir desde WhatsApp/Wompi dashboards; re-evaluar al cerrar T2-06 con datos reales. No es bloqueante de la separacion dev/prod.

**Pasos:**
1. Presentar al founder el trade-off con el RTO real medido en T2-06: costo total con PITR = $153/mes (Pro $25 + PITR $100 + Render Starter $28) vs $53/mes sin PITR
1. VALIDAR EN DOCUMENTACION OFICIAL la granularidad real de PITR (frecuencia de archivado WAL) en supabase.com/docs/guides/platform/backups antes de prometer RPO de 2 min
1. Si se aprueba: habilitar add-on en Dashboard→Add-ons, actualizar runbook DR con el flujo de restore point-in-time y re-ejecutar una prueba de restore PITR
1. Si se difiere: dejar registrado el trigger de re-evaluacion (N tenants activos o X pedidos/dia) en .context/04-next-steps.md

**Aceptación:**
- Decision registrada (aprobado/diferido con trigger) en docs + memoria de proyecto
- Si aprobado: PITR activo verificado en dashboard y runbook actualizado con prueba PITR ejecutada

#### T2-08 — Backup de Storage buckets (evidencia legal Habeas Data) — fuera del alcance del backup de DB  `[P1 · 1pd]` · dep: T2-05,T2-06
Los backups de Supabase cubren la DB; los objetos de Storage (consent-evidence de 20260510020000, offboarding-archive de 20260617000000, tenant-media de 20260704140000) contienen evidencia legal Ley 1581 que un restore de DB NO devuelve. Perderlos rompe la posicion probatoria ante la SIC.

**Pasos:**
1. VALIDAR EN DOCUMENTACION OFICIAL el alcance exacto de backups respecto a Storage (supabase.com/docs/guides/platform/backups) — si Supabase ya los cubriera en el plan contratado, cerrar este item como no-op documentado
1. Inventariar buckets y volumen actual (SELECT por bucket en storage.objects) para dimensionar
1. Implementar job de export periodico (worker existente services/ai-orchestrator/worker.py como host del cron, patron canonico fn_cleanup_webhook_secrets) que copie objetos nuevos/modificados a destino externo (opciones: bucket S3/R2 propio, o segundo proyecto Supabase; decidir por costo — R2 free tier probable $0)
1. Añadir verificacion de integridad (conteo + checksum muestral) y seccion en el runbook DR (T2-06) para restore de Storage
1. Cubrir con test la logica de seleccion incremental del export

**Aceptación:**
- Objetos de los 3 buckets replicados fuera del proyecto prod con lag <=24h
- Runbook DR incluye restore de Storage probado al menos con un objeto real
- Hallazgo oficial sobre alcance de backups documentado con URL en el runbook

#### T2-09 — Render: subir servicios prod a Starter (~$7/servicio/mes) y retirar hack anti-hibernacion  `[P2 · 0.75pd]` · gated: founder-costo · dep: T2-04
Free hiberna a los 15 min (render.com/docs/free, fetch 2026-07-16) — un webhook de Meta o Wompi que llega a servicio dormido espera ~1 min de arranque (Meta reintenta, pero es fragilidad innecesaria); 750h/mes compartidas por workspace ya son justas para 4 servicios always-on; y Free no soporta workers (el orchestrator es un web wrapper, render.yaml:282-284). Starter = 512MB/0.5CPU sin spin-down. Precio ~$7/mes por servicio segun fuentes 2026 — VALIDAR EN DOCUMENTACION OFICIAL render.com/pricing el precio exacto antes de aprobar. Costo estimado: 4x$7=$28/mes (minimo defendible: connector+api+orchestrator=$21 dejando web en Free).

**Pasos:**
1. INTERVENCION HUMANA REQUERIDA — RESPONSABLE: founder. PASOS: confirmar precio Starter en render.com/pricing y aprobar $21-28/mes. INSUMOS: tarjeta. CRITERIO DE EXITO: aprobacion registrada (~10 min)
1. Editar render.yaml: plan: starter en los 4 servicios (o 3 + web free) y convertir konvi-orchestrator de type:web wrapper a type:worker real (eliminar server.py wrapper /health o mantenerlo si el healthcheck lo exige — verificar contrato de workers en render.com/docs)
1. Retirar ANTI_HIBERNATION_* de render.yaml, .env.example y el codigo que hace self-ping; limpiar la deteccion de hibernacion en docs
1. Deploy via push a production y smoke: /health de los 4 servicios + webhook E2E real + verificar que el worker procesa colas
1. Actualizar HANDOFF.md con la nueva infra y costo

**Aceptación:**
- 4 servicios en Starter (o 3+1 justificado) Deployed y sin spin-down verificado (request tras >20 min idle responde <2s)
- Codigo anti-hibernacion eliminado del repo (grep ANTI_HIBERNATION vacio) con validate.sh --ci verde
- Orchestrator corriendo como worker nativo (o decision documentada de mantener web wrapper)

### T3-observabilidad
*Estado actual:* T3 OBSERVABILIDAD — estado real verificado 2026-07-16 (branch main @ cc0a9249). LO QUE EXISTE: (a) Sentry backend en los 3 servicios via observability.py idéntico (services/api, services/ai-orchestrator, services/connector-whatsapp): init_sentry con send_default_pii=False, before_send que filtra health/4xx y ejecuta scrub PII W1 (regex teléfono COL + email → '[phone]'/'[email]', services/api/observability.py:37-77,111-126); init confirmado en api/main.py:15, ai-orchestrator/server.py:25, connector-whatsapp/main.py:5; SENTRY_DSN declarado en render.yaml (:87,:147,:269,:486, sync:false — valor v

*Review adversarial:* ADJUSTED — Verificado contra el árbol actual (develop @ f3542fa0, incluye W2; el código citado es idéntico al main auditado). El current_state es sustancialmente exacto: confirmados con líneas exactas el scrub W1 backend (observability.py:37-77), la ausencia de beforeSend en los 3 configs de apps/web, el snaps

#### T3-01 — Alerta Sentry en dead-letter del inbox Wompi + métrica de profundidad del inbox  `[P0 · 0.5pd]`
Es el path de dinero: un webhook Wompi que agota WOMPI_INBOX_MAX_ATTEMPTS hoy muere en logger.error (worker.py:2278-2283) y nadie se entera salvo leyendo logs. capture_exception ya existe en el servicio (observability.py:140) y el claim RPC ya filtra attempts < max, así que la rama de dead-letter dispara UNA sola vez por fila — sin riesgo de tormenta de eventos. No-cost, puro código.

**Pasos:**
1. En services/ai-orchestrator/worker.py importar capture_exception (o capture_message level=error) desde observability
1. En la rama attempts >= WOMPI_INBOX_MAX_ATTEMPTS (worker.py:2278) emitir a Sentry con tags: checksum (12 chars, no-PII), attempts, tenant si está en la fila; mantener el logger.error existente
1. En _reconcile_wompi_inbox_if_due añadir count exacto de wompi_webhook_inbox con processed_at IS NULL (select head+count) y guardarlo en self._metrics['wompi_inbox_depth'] + contador acumulado 'wompi_inbox_dead_letters'
1. Test unitario en services/ai-orchestrator/tests: mock supabase + mock sentry → asserts capture llamado exactamente 1 vez cuando attempts==MAX y 0 veces cuando attempts<MAX; assert _metrics['wompi_inbox_depth'] actualizado
1. bash scripts/validate.sh --ci

**Aceptación:**
- Test verde que demuestra capture_exception/message disparado exactamente una vez al alcanzar MAX_ATTEMPTS
- metrics_snapshot() incluye wompi_inbox_depth y wompi_inbox_dead_letters
- validate.sh --ci verde sin regresiones en los ~3490 tests

#### T3-02 — beforeSend scrub PII en los 3 Sentry configs de apps/web (paridad W1 backend)  `[P0 · 1pd]`
Gap Ley 1581 verificado: sentry.client/edge/server.config.ts no tienen beforeSend; URLs con query params, breadcrumbs de fetch y mensajes de error del browser pueden arrastrar teléfono/email de clientes a Sentry. El backend ya resolvió esto en W1 con regex probadas (observability.py:37-42) — es un port a TypeScript, no diseño nuevo.

**Pasos:**
1. Crear apps/web/lib/sentry-scrub.ts: port exacto de _RE_PHONE (móvil COL +57 opcional, separadores acotados {0,3}, sin ReDoS) y _RE_EMAIL de services/api/observability.py:37-38; scrubEvent() recursivo sobre strings/objetos/arrays del evento
1. Además del scrub por regex, truncar query strings de event.request.url y de breadcrumbs http (data.url) — defensa en profundidad contra PII en params
1. Registrar beforeSend en los 3 configs y beforeBreadcrumb en client (los breadcrumbs del browser no pasan por beforeSend hasta adjuntarse; verificar comportamiento del SDK @sentry/nextjs instalado y escrubar event.breadcrumbs dentro de beforeSend como hace el backend)
1. Verificar si apps/web tiene runner de tests JS (vitest/jest); si existe, test con evento sintético conteniendo '3001234567' y 'a@b.com'; si no existe, añadir test node mínimo ejecutable en scripts/ y documentar en el PR la salida
1. bash scripts/validate.sh (incluye tsc + ESLint) y validate.sh --build para asegurar que el bundle compila

**Aceptación:**
- Los 3 configs registran beforeSend que redacta teléfono COL y email a '[phone]'/'[email]' (evidencia: test o salida de script con evento sintético)
- Query strings removidos de request.url y breadcrumbs http en el evento emitido
- tsc + ESLint + next build verdes

#### T3-03 — SLIs medibles hoy (latencia inbound→outbound, éxito envío WA, edad cola pgmq, poll_job_errors) + SLOs propuestos  `[P1 · 1.5pd]`
Los datos ya existen: timestamps en la tabla de mensajes permiten latencia E2E por turno; wa_outbound_sent/failed ya se cuentan (worker.py:330-331); enqueued_at está en el wrapper pgmq (migración 20260420000004:54). Falta definirlos como SLIs consultables y fijar targets. Sin esto no hay forma de decir si el bot 'va bien' salvo anécdota.

**Pasos:**
1. Confirmar columnas reales de la tabla de mensajes (direction/created_at) en supabase/migrations antes de escribir SQL — NO asumir esquema
1. Migración: vista sli_turn_latency (por tenant, ventana horaria: para cada mensaje outbound, delta contra el último inbound previo de la misma conversación; percentiles p50/p95 con percentile_cont)
1. RPC get_queue_health(): por cada cola pgmq (whatsapp_outbound, human_takeover_notifications) retornar depth + age_seconds del mensaje más viejo (min(enqueued_at)) usando los wrappers SECURITY DEFINER existentes como referencia de patrón (20260420000004)
1. Worker: en cada ciclo de flush (T3-04) leer get_queue_health y computar wa_send_success_rate = sent/(sent+failed) del intervalo
1. Documentar SLOs PROPUESTOS en .context/06-contracts.md (sección observabilidad): latencia turno p95 ≤ 30s / p99 ≤ 60s; éxito envío WA ≥ 99% diario; edad cola outbound ≤ 120s sostenido; poll_job_errors ≤ 5/h; wompi_inbox_depth = 0 sostenido (>0 por >15min = alerta). Marcarlos como propuesta inicial ajustable con 2 semanas de datos reales — targets NO son hecho confirmado, son hipótesis calibrable
1. Tests SQL/RPC en el suite pytest existente (patrón de tests de RPCs previos)

**Aceptación:**
- SELECT a sli_turn_latency retorna p50/p95 por tenant/hora coherentes con datos de prueba insertados
- get_queue_health retorna depth y edad del mensaje más viejo para las 2 colas
- SLOs con targets numéricos documentados en .context/06-contracts.md con racional y marca de 'propuesta inicial'
- validate.sh --ci verde

#### T3-04 — Persistencia de métricas de plataforma: tabla + flush periódico del worker + retención  `[P1 · 1.5pd]` · dep: T3-03
self._metrics (worker.py:326-354) muere en cada deploy — imposible calcular SLIs de tasa (éxito de envío, errores/h) ni ver tendencias. tenant_provider_health guarda solo el snapshot actual (upsert). Una tabla append-only barata cierra ambos gaps y alimenta la superficie de T3-05.

**Pasos:**
1. Migración: tabla platform_metrics (id, ts timestamptz default now(), metric text, value numeric, labels jsonb default '{}') con índice (metric, ts desc); RLS habilitado SIN policies para anon/authenticated (solo service_role escribe/lee) — patrón F6 de 20260704156010; seguir protocolo de feedback_supabase_migrations para el apply remoto (ledger tiene drift)
1. Worker: job _flush_platform_metrics_if_due (intervalo 5 min, registrado en _poll_cycle via _run_job): escribe DELTAS de contadores de _metrics desde el último flush + gauges (wompi_inbox_depth, queue depth/age de T3-03, heartbeat age)
1. Retención: purga >30d enganchada al cleanup throttled existente (patrón del cleanup 6h del inbox Wompi, worker.py:2238)
1. Incluir el flush en metrics_snapshot para debug y test unitario del delta (contador que no se resetea: flush N, flush N+1 → delta correcto tras restart simulado)
1. validate.sh --ci

**Aceptación:**
- Tras 2 ciclos de flush simulados, platform_metrics contiene filas con deltas correctos (test unitario con mock supabase + test de integración local si hay DB)
- Restart del worker NO produce deltas negativos ni duplicados (test)
- Purga elimina filas >30d (test)
- Migración aplicada siguiendo el protocolo seguro de migraciones remotas

#### T3-05 — Superficie mínima de SLIs en Tenant Console (Settings → Salud) + endpoint tenant-scoped  `[P2 · 2pd]` · dep: T3-03,T3-04
Ya existe la página Settings→Salud con health-grid.tsx (apps/web/app/dashboard/(settings-group)/settings/health/) leyendo tenant_provider_health. Extenderla con SLIs per-tenant (latencia de turno 24h, éxito de envío, backlog de cola) es la superficie de menor costo: cero infra nueva, respeta multi-tenant, y evita esperar al Platform Console (fase 12 bloqueada por OQ-P01). Métricas plataforma-wide quedan en /status (asegurado en T3-07) + Sentry.

**Pasos:**
1. Router en services/api: GET /api/v1/health/slis tenant-scoped — lee sli_turn_latency (T3-03) y agregados per-tenant de platform_metrics/mensajes con .eq('tenant_id', tid) (patrón canónico ADR-0025; el lint AST audit_tenant_filter.py debe pasar con 0 gaps)
1. UI: sección 'Rendimiento del bot' en la página de Salud: latencia p50/p95 24h, % éxito envío WhatsApp 24h, backlog actual; seguir feedback_ui_colors (shades 700, nunca 300-500)
1. Estados vacíos honestos: 'sin datos suficientes' cuando <N mensajes en la ventana (no inventar 100%)
1. Tests: router (auth + tenant isolation) en pytest; tsc/ESLint para UI
1. validate.sh --ci + validate.sh --build

**Aceptación:**
- Endpoint retorna solo datos del tenant autenticado (test de aislamiento cross-tenant)
- Lint AST tenant_filter en 0 gaps (BASELINE_MAX=0 se mantiene)
- Página Salud muestra los 3 SLIs con datos reales de la ventana 24h en entorno local
- validate.sh --ci + --build verdes

#### T3-06 — Reglas de alerta Sentry via API (script idempotente) — destino email founder  `[P1 · 0.5pd]` · gated: intervencion-humana · dep: T3-01
Hoy Sentry captura pero nadie es notificado proactivamente. La Issue Alert Rules API está verificada en doc oficial: POST /api/0/projects/{org}/{project}/rules/ (https://docs.sentry.io/api/alerts/create-an-issue-alert-rule-for-a-project/). Recomendación de destino: email del founder (acción nativa de Sentry, cero código, cero costo); Telegram NO es integración nativa de Sentry → relay webhook queda como T3-08. Metric Alerts (frecuencia/volumen) probablemente exigen plan pago — VALIDAR EN DOCUMENTACION OFICIAL (https://docs.sentry.io/product/alerts/) antes de diseñar sobre ellas; las issue alerts bastan para el MVP.

**Pasos:**
1. INTERVENCION HUMANA REQUERIDA — RESPONSABLE: founder. PASOS: (1) crear Auth Token en Sentry (Settings → Auth Tokens) con scope de escritura de proyecto (VALIDAR EN DOCUMENTACION OFICIAL el scope exacto: project:write vs alerts:write — https://docs.sentry.io/api/alerts/create-an-issue-alert-rule-for-a-project/); (2) confirmar org slug y los 4 project slugs (api, ai-orchestrator, connector-whatsapp, web); (3) confirmar que SENTRY_DSN está realmente poblado en Render dashboard (render.yaml lo declara sync:false — no verificable desde repo); (4) confirmar email destino de alertas. INSUMOS: acceso dashboard Sentry + Render. CRITERIO DE EXITO: token con scope correcto entregado como env var local, DSN confirmado activo en los 4 servicios
1. Script scripts/admin/setup_sentry_alerts.py idempotente (lista rules existentes, crea solo faltantes): por proyecto, regla 'nuevo issue de level>=error → email' con frequency 30 min; regla adicional para el dead-letter Wompi (T3-01) matcheando por tag/mensaje con frequency 5 min
1. Regla específica de alto valor: eventos con tag service + mensaje [WOMPI_INBOX][DEAD_LETTER] → alerta inmediata
1. Ejecutar script y verificar en dashboard que las reglas quedaron activas; disparar un error de prueba en staging/local con DSN de prod apuntando a environment de test y confirmar recepción de email
1. Documentar en docs/HANDOFF.md qué reglas existen y cómo re-ejecutar el script

**Aceptación:**
- Script idempotente: segunda ejecución no duplica reglas (verificable en salida y en dashboard)
- Email de alerta recibido en prueba controlada end-to-end
- Reglas documentadas en docs/HANDOFF.md con URL de doc oficial citada

#### T3-07 — Cerrar /status del ai-orchestrator con internal secret (paridad con /agentic/metrics)  `[P2 · 0.25pd]`
server.py:99-109 sirve metrics_snapshot completo sin auth mientras /agentic/metrics sí exige X-Internal-Service-Secret (server.py:115-122) — el guard ya existe en el archivo, es aplicarlo. Sin datos per-tenant, pero expone volumen operativo público. Con T3-04/T3-05 este endpoint gana más señal, así que cerrar antes.

**Pasos:**
1. Aplicar _require_internal_secret a /status (mantener /health público — Render lo necesita)
1. Verificar que ningún consumidor legítimo llama /status sin el header (grep en repo + scripts + docs/HANDOFF.md)
1. Ajustar/añadir tests del endpoint (401 sin header, 200 con header)
1. validate.sh --ci

**Aceptación:**
- GET /status sin header → 401; con X-Internal-Service-Secret correcto → 200 con metrics
- GET /health sigue público y funcional (test)
- Cero consumidores rotos (evidencia del grep en el PR)

#### T3-08 — Relay Sentry webhook → Telegram founder + dashboard Sentry (opcional)  `[P3 · 1pd]` · gated: intervencion-humana · dep: T3-06
El founder ya opera por Telegram (escalaciones per-tenant via notification_settings). Sentry no tiene integración nativa Telegram: requiere una Internal Integration con webhook (VALIDAR EN DOCUMENTACION OFICIAL: https://docs.sentry.io/organization/integrations/integration-platform/) apuntando a un endpoint relay propio que re-postea a la API de Telegram. Valor incremental sobre el email de T3-06 — solo si el email resulta insuficiente en la práctica. El dashboard Sentry (widgets de errores por servicio/release) se configura manualmente en UI.

**Pasos:**
1. Endpoint relay en services/api: POST /api/v1/internal/sentry-relay verificando la firma del webhook Sentry (VALIDAR EN DOCUMENTACION OFICIAL el mecanismo de firma de Internal Integrations antes de implementar) → formatea y envía a chat Telegram del founder via bot token en Vault
1. INTERVENCION HUMANA REQUERIDA — RESPONSABLE: founder. PASOS: crear Internal Integration en Sentry con webhook URL + habilitar alert-rule-action; crear/elegir bot Telegram y chat_id destino. INSUMOS: dashboard Sentry, BotFather. CRITERIO DE EXITO: alerta de prueba llega al chat Telegram
1. Actualizar reglas de T3-06 para añadir la acción de la integración
1. Dashboard Sentry manual (widgets: errores por servicio, por release, latencia de transacciones) — documentar screenshots/config en docs/HANDOFF.md
1. Tests del relay (firma inválida → 401; payload válido → POST a Telegram mockeado)

**Aceptación:**
- Alerta E2E: error de prueba → Sentry rule → webhook → mensaje en Telegram del founder
- Relay rechaza payloads sin firma válida (test)
- Dashboard documentado en docs/HANDOFF.md

### T4-antidos
*Estado actual:* Track T4 (perímetro anti-DoS, score 72) — estado real verificado 2026-07-16: (a) Los 3 webhooks de dinero/logística (wompi_webhook.py:52-58 limit=200/60s, aveonline_webhook.py:551-556, meli_webhook.py:207-208) SÍ tienen rate-limit per-IP distribuido (RPC rate_limit_hit, fail-open deliberado en Wompi para no dropear pagos); el connector WhatsApp tiene limiter in-memory sliding-window per-IP 240/60s con cota de memoria 4096 keys (meta.py:74-106); API tiene buckets canónicos write/send/MFA/offboarding (security.py:230-289) con RATE_LIMIT_DISTRIBUTED=true en prod (render.yaml:251-252). (b) PERO to

*Review adversarial:* ADJUSTED — El audit es mayormente SOUND: los 5 hallazgos son exactos contra el código, ninguno es falso ni está resuelto, y la estrategia (T4-01 fix XFF como linchpin P0 que vuelve reales todos los limiters existentes → luego cuota per-tenant → endurecimiento) es correcta y bien ordenada. Ajusto (no rechazo) p

#### T4-01 — Cerrar XFF: soporte TRUSTED_CLIENT_IP_HEADER (CF-Connecting-IP) + verificación empírica en prod + activación en render.yaml  `[P0 · 1pd]`
La verificación documental está HECHA (este audit): Cloudflare appendea al XFF entrante (doc oficial https://developers.cloudflare.com/fundamentals/reference/http-headers/), Render no lo documenta, y la evidencia empírica (arcjet/arcjet-js#3899) muestra que Render forwardea True-Client-IP y CF-Connecting-IP con la IP real (Cloudflare los setea, no son passthrough del cliente). Mantener leftmost NO es una opción 'verificada segura' — está verificada como spoofeable — y hardcodear hops=3 depende de topología interna no documentada de Render. La solución robusta es preferir el header seteado por Cloudflare, con fallback a hops y verificación empírica única. Esto convierte en reales TODOS los limiters ya desplegados (hoy evadibles rotando el leftmost) y elimina la evicción LRU maliciosa del connector.

**Pasos:**
1. Extender _client_ip en services/api/dependencies/security.py:107 y services/connector-whatsapp/dependencies/meta.py:114 (mantener duplicación deliberada — deploy units aislados): si env TRUSTED_CLIENT_IP_HEADER está seteado (ej. 'cf-connecting-ip') y el header existe, usarlo; si no, aplicar la lógica XFF actual (hops o leftmost).
1. Añadir canary log estructurado: WARN cuando el header confiable difiere del leftmost del XFF (detecta spoofing real y valida coherencia durante el soak).
1. Unit tests en ambos servicios: header presente gana; header ausente → fallback hops; hops=0 → leftmost histórico; header vacío/malformado → fallback.
1. Verificación empírica en prod (30 min): curl a https://<api>.onrender.com/health y al connector con headers spoofeados (-H 'X-Forwarded-For: 1.2.3.4' -H 'CF-Connecting-IP: 5.6.7.8' -H 'True-Client-IP: 5.6.7.8') y capturar en log temporal (o log level DEBUG existente) qué llega realmente: confirmar que CF-Connecting-IP/True-Client-IP llegan con la IP real del curl (no la spoofeada) y registrar la cadena XFF observada con su conteo de hops.
1. Setear TRUSTED_CLIENT_IP_HEADER=cf-connecting-ip en render.yaml para api, connector-whatsapp y ai-orchestrator (si aplica); dejar XFF_TRUSTED_HOPS_FROM_RIGHT=<N observado> documentado como fallback en comentario.
1. Actualizar los comentarios INTERVENCION HUMANA en security.py:98-103 y meta.py:109-110 con el resultado de la verificación (URLs citadas) — cerrar el pendiente.
1. Soak 48h post-deploy: revisar canary logs; si 0 divergencias inesperadas, cerrar.

**Aceptación:**
- curl a prod con X-Forwarded-For spoofeado queda bucketed por la IP real del emisor (verificable en log del limiter: la key contiene la IP del egress del curl, no 1.2.3.4).
- curl a prod con CF-Connecting-IP spoofeado NO logra inyectar esa IP (Cloudflare la sobreescribe) — evidencia en log.
- Unit tests verdes en ambos servicios cubriendo los 4 casos de fallback; bash scripts/validate.sh --ci verde.
- render.yaml contiene TRUSTED_CLIENT_IP_HEADER en los servicios internet-facing y el comentario INTERVENCION HUMANA de security.py:103 está reemplazado por la cita de verificación.
- 48h de canary logs sin divergencia inexplicada entre header confiable y comportamiento esperado.

#### T4-02 — Cuota agregada por tenant además de per-IP (API + connector + webhooks)  `[P1 · 1.5pd]` · dep: T4-01
Hoy el límite efectivo escala linealmente con las IPs del atacante (keys siempre incluyen IP/user — security.py:167-169) y los webhooks no tienen dimensión tenant. Un botnet modesto o un tenant comprometido satura Supabase compartida y el threadpool sin tocar ningún límite. El connector ya recibe tenant_id en el path (/webhook/{tenant_id}) → cuota per-tenant keyeable pre-HMAC a costo cero.

**Pasos:**
1. API: en build_rate_limit_dependency (security.py:143) añadir segundo check con key agregada f'{bucket}:{tenant_id}' y límite = per-IP × multiplicador (env API_RATE_LIMIT_TENANT_MULTIPLIER, default 5); ambos checks contra el mismo limiter (RPC o in-memory).
1. Connector: en el handler /webhook/{tenant_id}, segundo bucket in-memory per-tenant (límite env, default 480/60s) evaluado ANTES del lookup de secret, reusando _rate_limit_hit con key 'tenant:{tenant_id}'.
1. Webhooks API (wompi/aveonline/meli): evaluar añadir bucket per-tenant POST-resolución de tenant (segunda línea, no reemplaza el per-IP pre-parse); Wompi mantiene fail-open.
1. Elegir límites per-tenant con datos reales: revisar métricas/logs de volumen actual por tenant (KAIU) para que el techo no corte tráfico legítimo de campañas.
1. Tests: tenant que agota cuota agregada recibe 429 aunque rote IPs; tenants distintos no comparten bucket.
1. Documentar los buckets y límites en .context/06-contracts.md (sección perímetro).

**Aceptación:**
- Test de integración: 2 IPs distintas del mismo tenant comparten y agotan el bucket agregado (429 en la N+1) mientras otro tenant sigue en 200.
- Connector rechaza flood a /webhook/{tenant_X} por cuota tenant sin ejecutar lookup de secret (verificable por ausencia del log de Vault/Supabase lookup).
- Límites configurables por env y documentados en .context/06-contracts.md.
- validate.sh --ci verde.

#### T4-03 — Migrar RPC rate_limit_hit de fixed-window a token-bucket + pre-filtro local barato antes de la RPC  `[P2 · 1pd]` · dep: T4-01
Fixed-window (migración 20260425000000:38) permite burst 2x en frontera de ventana, y en modo distribuido cada request cuesta 1 RPC a la Supabase compartida — bajo flood el propio limiter amplifica carga hacia la DB (la RPC corre ANTES de rechazar). Token-bucket lazy (una fila por key: tokens + last_refill, UPSERT atómico O(1)) elimina el burst y mantiene el costo por hit; un pre-filtro in-memory coarse (ej. 3x el límite) por instancia corta floods evidentes sin tocar la DB.

**Pasos:**
1. Nueva migración: función rate_limit_hit_v2(p_key, p_limit, p_window_seconds) con token-bucket lazy-refill sobre tabla de una fila por key (tokens NUMERIC, last_refill TIMESTAMPTZ), UPSERT atómico; conservar contrato de retorno (allowed, remaining, reset_in) para compatibilidad con _distributed_hit (security.py:80-95).
1. Aplicar migración al remote siguiendo el protocolo de feedback_supabase_migrations (ledger con drift — verificar antes de aplicar).
1. Switch por env (API_RATE_LIMIT_ALGO=token_bucket|fixed_window) en _distributed_hit para rollback instantáneo sin migración.
1. Pre-filtro local: en build_rate_limit_dependency, correr _local_limiter.hit con límite 3x ANTES de la RPC; solo si pasa el filtro local se consulta el distribuido (bajo flood a una instancia, la DB no ve el exceso).
1. Tests: burst en frontera de ventana ya no duplica el cupo; pre-filtro corta antes de la RPC (mock del cliente Supabase sin llamadas).
1. Limpieza: TTL/cleanup de filas viejas del token bucket (reusar el patrón expires_at + index de rate_limit_windows).

**Aceptación:**
- Test determinístico: con límite 10/60s, 20 requests repartidas en la frontera de ventana producen exactamente 10 permitidas (antes: hasta 20).
- Bajo flood simulado (limit local 3x excedido), cero llamadas RPC a Supabase (verificable con mock/spy).
- Rollback probado: API_RATE_LIMIT_ALGO=fixed_window restaura comportamiento previo sin redeploy de migración.
- Migración aplicada al remote con el protocolo seguro y registrada en docs/HANDOFF.md.

#### T4-04 — Diseño y activación condicional de limiter distribuido en el connector (gate: scale-out)  `[P2 · 1pd]` · gated: founder-costo · dep: T4-01,T4-03
El limiter in-memory del connector (meta.py:74-106) es correcto para 1 instancia pero: (a) se resetea en cada deploy/restart (ventana de flood libre de ~1 min), (b) con numInstances>1 el límite efectivo se multiplica por N. Hoy 4 servicios free/1 instancia → NO urgente; importa en el primer upgrade de plan con autoscaling o al pasar de free (que además hace spin-down). Diseño dos-tier: mantener in-memory como primera línea (protege a la DB) y añadir segunda línea distribuida (RPC rate_limit_hit vía cliente Supabase que el connector ya tiene) activable por env CONNECTOR_RATE_LIMIT_DISTRIBUTED cuando haya >1 instancia.

**Pasos:**
1. Implementar segunda línea distribuida en meta.py: tras pasar el limiter local, si CONNECTOR_RATE_LIMIT_DISTRIBUTED=true, llamar RPC rate_limit_hit (misma semántica fail-open que Wompi: error de RPC nunca dropea un webhook Meta legítimo — Meta reintenta pero penaliza fallos).
1. Presupuesto de latencia: medir p95 del RPC desde el connector (Meta espera respuesta rápida del webhook); si p95 > presupuesto, mover el check distribuido a post-ACK (solo observabilidad + bloqueo en la SIGUIENTE request).
1. Dejar env en render.yaml comentada con instrucción de activación al escalar (value: 'false' + comentario del gate).
1. Test: con flag on, dos 'instancias' (procesos de test) comparten contador; con flag off, comportamiento actual intacto.
1. Documentar en .context/06-contracts.md el trigger operativo: activar al pasar a numInstances>1 o plan con autoscaling.

**Aceptación:**
- Con CONNECTOR_RATE_LIMIT_DISTRIBUTED=false (default) el comportamiento actual es bit-a-bit idéntico (tests de regresión del connector verdes).
- Con flag on, test multi-proceso demuestra contador compartido vía RPC y fail-open ante caída de Supabase.
- Medición de latencia del RPC documentada en el PR; decisión inline vs post-ACK justificada con el número.
- Trigger de activación documentado en .context/06-contracts.md y render.yaml.

#### T4-05 — Barrido final de superficies sin rate-limit: telegram webhook, GETs caros del API, inventario documentado  `[P2 · 1pd]` · dep: T4-01
Cierre del perímetro: telegram_webhook.py:60 es el único webhook sin limiter (auth constant-time barata mitiga, pero sin tope de intentos de brute-force del secret ni de flood post-auth); los GETs del API no llevan rate-limit (los caros — exports, printables — sí, vía RL_WRITE_DEFAULT: verificado data_subject_request.py:264,576); falta un inventario canónico que evite regresiones al añadir endpoints.

**Pasos:**
1. Añadir webhook_rate_limit_check a telegram_webhook (paridad wompi: per-IP 200/60s, ANTES de compare_digest; fail-open no necesario — Telegram reintenta).
1. Barrido sistemático: grep de todos los @router.get/@app.get en services/api sin dependencia RL + todos los route.ts de apps/web sin límite propio ni proxy al API; clasificar por costo (DB agregaciones, LLM, I/O pesado) y añadir bucket read.expensive (ej. 60/min) solo a los caros — NO rate-limitar GETs baratos (UX del console).
1. Verificar que los route handlers del web que llaman LLM directo (insights, ai/preview, ai-agents/suggest, catalog/suggest-content) tienen todos límite per-tenant (2 verificados; auditar el resto).
1. Producir tabla canónica endpoint→bucket→límite en .context/06-contracts.md (sección perímetro anti-DoS) como contrato anti-regresión.
1. Tests para los buckets nuevos.

**Aceptación:**
- telegram webhook responde 429 al exceder 200/60s per-IP (test).
- Inventario completo en .context/06-contracts.md: TODO endpoint público o autenticado-caro tiene fila con bucket y límite, o justificación explícita de exención.
- Cero superficies LLM del web sin límite per-tenant (lista verificada en el PR).
- validate.sh --ci verde.

### T5-performance
*Estado actual:* T5 Performance (score 45) auditado con evidencia 2026-07-16 sobre production=f3542fa0. El hot path por mensaje WhatsApp vive en services/ai-orchestrator/agentic/dispatcher.py (4095 líneas), con _run_agentic_full monolítico (líneas 916-3276, ~2360 líneas) y coverage real 17.5% (coverage.xml de hoy). No hay visibilidad de latencia por etapa: el único timing (dispatcher.py:2989-3002) rodea solo la llamada LLM, y es lo que persiste _persist_turn_audit como elapsed_seconds — las p50/p95 de agentic/observability.py subestiman la latencia real del turno. Fan-out DB alto y sin medir: 67 .execute estát

*Review adversarial:* ADJUSTED — Verificación línea-a-línea sobre el repo real: la gran mayoría de la evidencia es exacta (dispatcher 4095 líneas, _run_agentic_full 916-3276, 67 .execute, coverage 0.1751 en coverage.xml de hoy, 3 tests offline, 15 escenarios live-only, catálogo 3 queries × hasta 3 llamadas, tenant_integrations 2×, 

#### T5-01 — Instrumentación por etapa del turno + contador de queries por mensaje (log-first, sin migración)  `[P0 · 2pd]`
Hoy solo se mide la llamada LLM (dispatcher.py:2989-3002); sin timings de context-load/resolvers/invariants/persistencia ni conteo de queries no se puede priorizar con datos. Diseño log-first (línea estructurada AGENTIC_PERF) para NO requerir migración a agentic_shadow_log (el ledger de migraciones tiene drift y exige protocolo founder).

**Pasos:**
1. Crear agentic/perf.py: clase TurnPerf con checkpoints time.perf_counter() y stage(name) context-manager; cero dependencias, overhead <1ms
1. Insertar checkpoints en los seams ya identificados de _run_agentic_full: multimodal (936), context_load (1116-1160: catalog/history/contact/tenants), coupons (~1219), system_prompt (1301), pre_llm_resolvers (1321-2735, un sub-timing por resolver), fsm_subset (2737-2988), llm (2989-3003, ya existe), post_llm_cod (3004), invariants (3147), outbound (3186), audit (3255)
1. Crear CountingSupabaseProxy (wrapper que delega todo y cuenta .execute() por tabla+operación por turno); activable por env AGENTIC_PERF_TRACE=true; inyectarlo en dispatch_message sin tocar call-sites
1. Emitir 1 línea por turno: logger.info('[AGENTIC_PERF] conv=%s total_ms=... stages={json} query_count=N queries_by_table={json}') junto al AGENTIC_TRACE existente (dispatcher.py:3174)
1. Opcional (reuso): decorar helpers extraíbles con track_op existente (observability.py:245) para que al habilitar OTEL_EXPORTER_ENABLED los spans salgan gratis
1. Tests unitarios de TurnPerf y del proxy contador (puros, sin DB)
1. Validar con bash scripts/validate.sh --ci antes de PR

**Aceptación:**
- Un mensaje procesado en stack local emite exactamente 1 línea [AGENTIC_PERF] con ≥8 etapas nombradas y query_count>0 desglosado por tabla
- elapsed_seconds persistido en agentic_shadow_log NO cambia de semántica (sigue midiendo el LLM) — cero cambio de comportamiento observable por el cliente
- Overhead medido del instrumentado <5ms por turno (comparar 20 turnos con/sin AGENTIC_PERF_TRACE)
- validate.sh --ci verde; tenant lint 0 gaps

#### T5-02 — Baseline de latencia y fan-out con datos reales + priorización del track  `[P0 · 1pd]` · dep: T5-01
El track está anclado en 45 sin datos: no se sabe si el cuello es el LLM, el fan-out DB (bloqueante por cliente sync) o los resolvers. Este item convierte T5-01 en decisiones: qué etapa concentra p95 y qué queries son N+1 reales.

**Pasos:**
1. Correr los 15 escenarios del harness (scripts/uat/coherence_scenarios.py) en stack local con AGENTIC_PERF_TRACE=true y recolectar las líneas [AGENTIC_PERF]
1. Complementar con logs de prod en .local/logs/ (fuente de verdad runtime per memoria) si el flag se habilita en Render worker — si no, declarar baseline local-only explícitamente
1. Script scripts/perf/analyze_agentic_perf.py: parsear líneas → p50/p95/max por etapa + distribución query_count + top tablas + detección N+1 (misma tabla >3 hits/turno)
1. Producir tabla de priorización: % del p95 total por etapa; confirmar o refutar hipótesis (catálogo 3×/turno, tenant_integrations 2×, bloqueo sync)
1. Registrar baseline numérico en docs/research/ (queries/turno p50-p95, ms por etapa) como referencia del ratchet de T5-08

**Aceptación:**
- Documento con p50/p95 por etapa sobre ≥15 escenarios × sus turnos (≥60 turnos) y distribución de queries/turno
- Top-3 cuellos identificados con números (ej. 'context_load = X ms p95, Y queries'), no con hipótesis
- Verificación empírica del doble/triple fetch de catálogo y doble lectura de tenant_integrations (conteo por tabla lo muestra)

#### T5-03 — Red conductual offline del dispatcher (gate del refactor): coverage crítico 17.5% → ≥50%  `[P0 · 4pd]`
LÍMITE DURO del track: cero cambio de comportamiento sin red previa. El harness live (15 escenarios) no corre en CI; solo 3 archivos de tests offline tocan dispatch_message. Sin esto, T5-05/06/07 no pueden arrancar.

**Pasos:**
1. Construir FakeSupabase de alta fidelidad para tests (tabla→rows en memoria, soporta .eq/.in_/.single/.upsert/.update/.insert/.order/.limit) — verificar antes si ya existe un fake parcial en tests/ y extenderlo (regla reuse-over-create)
1. Stub del LLM: run_agentic_turn reemplazado por doble programable (respuesta+tool_calls por turno) — los tests conductuales NO llaman Gemini
1. Portar los 15 escenarios de coherence_scenarios.py a tests offline reutilizando las assertions puras de scripts/uat/coherence_assertions.py (ya testeadas en test_a11_coherence_assertions)
1. Cubrir explícitamente los caminos críticos del monolito: multimodal skip, no-texto, cada resolver pre-LLM (variant continuation, payment availability, shipping recipient, COD, cancel, image, consent, carrier, purchase), FSM resolve + tools subset, COD post-LLM re-mark, apply_invariants rewrite, escalación, _persist_turn_audit degrade-safe, optout/reoptin, data-rights, minor-intent
1. Asegurar aserciones sobre EFECTOS (texto outbound, estado FSM persistido, filas escritas) no sobre implementación interna — para que sobrevivan al strangler
1. Medir coverage del dispatcher con pytest --cov y fijar el número alcanzado

**Aceptación:**
- coverage.xml muestra agentic/dispatcher.py line-rate ≥0.50 (desde 0.1751)
- Los 15 escenarios de coherencia tienen equivalente offline verde en pytest sin red ni DB real
- Suite corre en <60s y queda incluida en scripts/validate.sh (CI la ejecuta en cada PR)
- Cero cambios en dispatcher.py salvo inyección de dependencias mínima si es imprescindible (documentada y con diff revisable)

#### T5-04 — Arnés de equivalencia: golden-trace de escrituras DB y outbound por escenario  `[P0 · 2pd]` · dep: T5-01,T5-03
El strangler exige demostrar semántica idéntica. Un snapshot de la secuencia de efectos (tabla, operación, filtros, payload-shape, textos outbound) por escenario detecta cualquier divergencia del refactor que las assertions de coherencia no capturen.

**Pasos:**
1. Extender el CountingSupabaseProxy de T5-01 a modo trace: registrar secuencia ordenada de (op, tabla, filtros, keys del payload) — sin valores volátiles (timestamps, uuids normalizados)
1. Grabar golden traces de los escenarios offline de T5-03 (dispatcher actual = fuente de verdad) y versionarlos en tests/agentic/golden/
1. Test de equivalencia: correr escenario → comparar trace normalizado contra golden; diff legible al fallar
1. Definir política de actualización de goldens: solo con justificación explícita en el PR (nunca regenerar en silencio)

**Aceptación:**
- ≥15 golden traces versionados y test de equivalencia verde sobre el dispatcher ACTUAL
- Mutación deliberada de prueba (ej. quitar el upsert de contacts dispatcher.py:1138) rompe el test con diff que señala la escritura faltante
- Runtime del arnés <30s

#### T5-05 — Descomposición strangler de _run_agentic_full en 5 módulos por seam real (sin cambio de semántica)  `[P1 · 6pd]` · dep: T5-03,T5-04
2360 líneas monolíticas impiden testear, cachear y paralelizar por partes. Los seams ya existen en el código (secciones ── delimitadas): la extracción es movimiento de código + firma explícita, no rediseño. Con T5-03+T5-04 como red, el riesgo queda acotado.

**Pasos:**
1. Fase 1 — agentic/turn_context.py: dataclass TurnContext (catalog, history, contact, customer_phone, coupons, tenant_prompt_ctx, tenant_meta) + load_turn_context() extrayendo dispatcher.py:1116-1310 (incluye upsert contacts y coupons); pasa TurnContext a las etapas siguientes (elimina de paso la 2ª lectura de tenant_integrations :2914 reusando la de :268 — verificar con golden trace que el conteo baja en 1 sin otro cambio)
1. Fase 2 — agentic/multimodal_stage.py: extraer 936-1115 (multimodal + no-texto) con contrato entrada/salida explícito (handled→return temprano)
1. Fase 3 — agentic/pre_llm_pipeline.py: cascada de resolvers 1321-2735 como lista ordenada de handlers con contrato uniforme (ctx → Handled(outbound, state) | Continue); el orden actual se preserva EXACTO y queda testeado como propiedad
1. Fase 4 — agentic/post_llm_stage.py: extraer 3004-3276 (COD re-mark, apply_invariants, outbound, escalación, audit)
1. Cada fase = 1 PR pequeño; tras cada una: suite T5-03 verde + golden traces T5-04 idénticos (salvo la reducción documentada de la fase 1) + validate.sh --ci
1. Meta de tamaño: dispatcher.py <1200 líneas; _run_agentic_full <300 líneas de orquestación pura

**Aceptación:**
- dispatcher.py ≤1200 líneas y _run_agentic_full ≤300 líneas (wc -l verificable)
- Golden traces T5-04 byte-idénticos post-refactor (excepción única: −1 query tenant_integrations, documentada en el PR de fase 1)
- Suite conductual T5-03 verde sin modificar aserciones de efectos
- Coverage de los módulos extraídos ≥60% cada uno
- Los 15 escenarios del harness LIVE (coherence_scenarios.py) verdes en stack local como sello final (per feedback: UAT dinámico, no estático)

#### T5-06 — Cache in-process del catálogo y config del tenant: memo por-turno + TTL cross-request 60-300s  `[P1 · 2pd]` · dep: T5-02,T5-03,T5-05
Catálogo = 3 queries × hasta 3 llamadas por turno (dispatcher:1127 + 2 invariants) en CADA mensaje; tenants y tenant_integrations también se releen siempre. Un memo por-turno es semánticamente MÁS coherente (misma verdad de stock en todo el turno) y el TTL cross-request elimina el grueso del fan-out. Riesgo de staleness acotado: stock ya se revalida transaccionalmente en add_to_cart/checkout (el catálogo del prompt no es verdad transaccional).

**Pasos:**
1. Nivel 1 (riesgo ~0): memo por-turno en TurnContext — invariants reciben el catálogo ya cargado en vez de re-fetchear (variant_availability_assertion.py:130, cart_render_coherence.py:454); elimina 2×3 queries/turno
1. Nivel 2: agentic/tenant_cache.py con TTLCache in-process (dict + monotonic, sin dependencia nueva) para get_tenant_catalog / _load_tenant_prompt_context / meta agentic; TTL env-configurable CATALOG_CACHE_TTL_S default 120 (rango 60-300)
1. Invalidación write-through: los tools del propio bot que mutan catálogo/carrito-stock (si aplica) y el flujo de reservas F4 NO usan cache — SOLO el catálogo para prompt/invariants; documentar en el módulo que stock mostrado puede tener staleness ≤TTL y que la verdad transaccional sigue en DB (principio 4 CLAUDE.md)
1. Documentar restricción multi-instancia: cache in-process válido mientras worker sea single-instance en Render (estado actual); dejar TODO explícito + env CATALOG_CACHE_TTL_S=0 como kill-switch total para el día multi-instancia
1. Tests: hit/miss/expiry/kill-switch + test conductual de que un turno usa UNA carga de catálogo
1. Verificar con T5-01: query_count por turno baja (esperado: −6 a −8 queries en turnos con invariants de catálogo)

**Aceptación:**
- Golden traces actualizados muestran 1 sola carga de catálogo por turno (3 queries) y 0 con cache caliente dentro del TTL
- [AGENTIC_PERF] evidencia reducción ≥30% de query_count p50 vs baseline T5-02 en los 15 escenarios
- Suite T5-03 verde sin cambio de textos outbound (semántica intacta)
- Kill-switch CATALOG_CACHE_TTL_S=0 restaura comportamiento pre-cache (test lo cubre)
- Nota multi-instancia visible en el módulo y en .context/04-next-steps.md

#### T5-07 — Paralelizar lecturas independientes del context-load (gather + to_thread o AsyncClient) — desbloquear el event loop  `[P2 · 3pd]` · dep: T5-02,T5-03,T5-04,T5-05
Las lecturas de context-load (catálogo, history, customer_phone, tenants, coupons) son independientes pero corren en serie Y bloquean el event loop porque el cliente Supabase es sync (worker.py:285). asyncio.gather solo, sin to_thread/AsyncClient, no paraleliza NADA — hallazgo clave que corrige el diseño ingenuo del track.

**Pasos:**
1. VALIDAR EN DOCUMENTACION OFICIAL: thread-safety del Client sync de supabase-py 2.28.3 (postgrest-py/httpx subyacente) para llamadas concurrentes vía asyncio.to_thread — https://supabase.com/docs/reference/python y repo supabase/supabase-py; si NO es thread-safe, usar un client por thread o decidir migración a acreate_client (AsyncClient ya usado en 8 archivos del servicio: notifications.py, whatsapp_sender.py, aveonline_client.py...)
1. Decisión técnica documentada (bloques DECISION FINAL/RIESGO) entre: (a) asyncio.to_thread + gather sobre client sync, (b) AsyncClient para el read-path del context-load; recomendación provisional: (a) si thread-safe, por diff mínimo
1. Implementar en load_turn_context (módulo de T5-05 fase 1): gather de las 4-5 lecturas independientes; escrituras (upsert contacts) quedan DESPUÉS, secuenciales, sin cambio de orden relativo observable
1. Verificar que el golden trace tolera reordenamiento SOLO dentro del grupo paralelo de lecturas (ajustar normalización del trace: lecturas del grupo como conjunto, escrituras siguen ordenadas)
1. Medir con T5-01: context_load_ms antes/después en los 15 escenarios

**Aceptación:**
- context_load p95 reducido ≥40% vs baseline T5-02 (lecturas en paralelo real, verificado en [AGENTIC_PERF])
- Cero cambio en escrituras: golden traces muestran mismas escrituras en el mismo orden
- Suite T5-03 + harness live verdes
- Decisión to_thread vs AsyncClient documentada con cita a doc oficial (URL) o marcada como riesgo asumido con client-por-thread

#### T5-08 — Gates de regresión de performance en validate.sh/CI: budget de queries por turno + ratchet de coverage del dispatcher  `[P2 · 1pd]` · dep: T5-02,T5-06
Sin gate, el fan-out vuelve a crecer silenciosamente (patrón ya visto: 198→0 gaps de tenant lint solo se sostuvo con ratchet BASELINE_MAX). Mismo mecanismo, aplicado a queries/turno y coverage de los módulos del dispatcher.

**Pasos:**
1. Test de budget: correr 3 escenarios representativos offline con CountingSupabaseProxy y assert query_count ≤ baseline+0 (env AGENTIC_QUERY_BUDGET, ratchet decreciente igual que BASELINE_MAX del tenant lint)
1. Añadir al validate.sh (sección coverage) chequeo de line-rate mínimo para agentic/dispatcher.py y módulos extraídos (parse de coverage.xml, mismo patrón COVERAGE_MIN)
1. Documentar budgets y su razón en .context/04-next-steps.md y en el header del test

**Aceptación:**
- PR que agregue una query no-justificada a un escenario budgeteado ROMPE CI con mensaje que nombra tabla y etapa
- validate.sh --ci falla si coverage del dispatcher cae bajo el piso fijado tras T5-03/T5-05
- Budgets versionados como env con default en el repo (no números mágicos en el test)

### T6-docs
*Estado actual:* Track T6 (DOCS/ADRs/CONTRATOS, score 55) auditado el 2026-07-16 contra production=f3542fa0. Estado verificado: (a) docs/adr/ termina en 0039-bloque-k2-retiro-v1.md → el siguiente número libre es 0040 (confirmado); NO existe ADR para W2 (inbox transaccional Wompi, commits d2207026+5907bc98, PR #69) ni para W1 enforce_mfa_strict (commit 76435109, PR #68), pese a que la metodología rev.112 exige ADR por bloque; existe además numeración duplicada 0023 (dos archivos). (b) .context/06-contracts.md §12 "Inbox Fase C — Pagos Wompi" (líneas 176-183) driftea del código: describe el flujo pre-W2 ("valida

*Review adversarial:* ADJUSTED — Los 7 hallazgos se CONFIRMAN contra f3542fa0 con evidencia exacta: 06-contracts.md §12 (líneas 176-183) describe el flujo pre-W2 mientras el código real tiene inbox pre-ACK (wompi_webhook.py:79-87), marca terminal (:135-154), dedup processed-aware (:238-289) y reconcile con lease (worker.py:409, :22

#### T6-01 — ADR-0040 — Durabilidad del webhook Wompi: inbox transaccional store-and-forward (W2)  `[P2 · 0.5pd]`
Decisión arquitectónica de dinero YA en producción (f3542fa0, PR #69) sin ADR. Sin él, una sesión futura puede 'simplificar' el re-POST cross-proceso o el dedup processed-aware sin conocer los trade-offs (Wompi NO reintenta un 200 ni permite pull por reference/link — limitación validada contra docs oficiales el 2026-06-26 en el runbook).

**Pasos:**
1. Crear docs/adr/0040-wompi-webhook-durable-inbox.md con esqueleto: ## Contexto (GAP auditoría: ACK 200 + background_tasks pierde el evento ante crash entre ACK y fin de procesamiento; pago recibido → sweeper TTL cancela la orden → dinero sin orden; citar commit d2207026), ## Decisión (inbox store-and-forward: tabla wompi_webhook_inbox checksum PK + raw_payload + processed_at NULL + attempts; _persist_inbox ANTES del 200 ACK, wompi_webhook.py:82-92; _process_wompi_event_durable marca terminal :135-154; worker job wompi_inbox_reconcile cada 3min con lease claim_wompi_inbox_batch FOR UPDATE SKIP LOCKED, worker.py:2215-2229; re-POST al endpoint para reusar firma+dedup+confirm), ## Refinamientos post-review (dedup processed-aware — descartar SOLO si processed_at IS NOT NULL, wompi_webhook.py:243-277; solo transaction.updated capturados; RPC cleanup_wompi_inbox retención 7d procesadas / 30d dead-letter, commit 5907bc98), ## Alternativas rechazadas (re-import cross-servicio de la lógica del router — acopla procesos; pull a Wompi por reference — NO existe en el API público, referenciar runbook wompi-payment-reconciliation.md), ## Consecuencias (dead-letter tras MAX_ATTEMPTS=5 requiere runbook manual; 4 env knobs WOMPI_INBOX_*), ## Referencias (migración 20260714000000, PR #69, tests test_w2_wompi_inbox_durability.py)
1. Enlazar el ADR desde .context/06-contracts.md §12 (tras T6-03) y desde 01-state.md rev.113 (T6-05)

**Aceptación:**
- docs/adr/0040-wompi-webhook-durable-inbox.md existe y cita migración 20260714000000, wompi_webhook.py y worker.py con líneas
- El ADR documenta explícitamente la alternativa rechazada 'pull por reference infactible' con referencia al runbook (validación docs oficiales 2026-06-26)
- grep -l '0040' .context/06-contracts.md devuelve match tras T6-03

#### T6-02 — ADR-0041 — enforce_mfa_strict fail-closed para operaciones crown-jewel de offboarding (W1)  `[P2 · 0.5pd]`
Decisión de política de seguridad con trade-off deliberado (outage Auth admin bloquea export/deletion para TODOS) ya en producción (commit 76435109, PR #68) sin ADR. El contraste fail-open (gate amplio) vs fail-closed (crown-jewels) es exactamente el tipo de decisión que sin ADR se revierte por accidente.

**Pasos:**
1. Crear docs/adr/0041-mfa-strict-fail-closed-crown-jewels.md con esqueleto: ## Contexto (enforce_mfa amplio es FAIL-OPEN por diseño: ante outage del Auth admin permite aal1 para no bloquear a quien no activó MFA; riesgo en operaciones irreversibles: export PII + borrado de cuenta), ## Decisión (enforce_mfa_strict FAIL-CLOSED, services/api/dependencies/auth.py:274: lookup caído → 503, JWT sin sub → 401; aal1 sin factor registrado sigue OK — no fuerza MFA a quien no lo activó), ## Refactor (_lookup_verified_mfa_cached extraído, RAISES _MfaLookupError — no decide política; _user_has_verified_mfa wrapper fail-open preserva contrato del gate amplio), ## Alcance (aplicado a /offboarding/export + /request-deletion en services/api/routers/tenant_offboarding.py; criterio para extender a futuras rutas crown-jewel), ## Trade-off aceptado (disponibilidad de 2 rutas destructivas sacrificada durante outage), ## Referencias (PR #68, test commit 2879efd0 ancla la propiedad fail-closed)
1. Referenciar el ADR desde 01-state.md rev.113 (T6-05)

**Aceptación:**
- docs/adr/0041-mfa-strict-fail-closed-crown-jewels.md existe y cita auth.py:274 + tenant_offboarding.py
- El ADR enuncia el criterio de extensión (qué convierte una ruta en crown-jewel) para decisiones futuras
- El trade-off de disponibilidad está declarado como aceptado, no omitido

#### T6-03 — Resync .context/06-contracts.md §12 — contrato Wompi durable (inbox + dedup processed-aware + lease)  `[P1 · 0.5pd]`
06-contracts.md es lectura obligatoria on-demand para quien toque API/Worker/pagos (CLAUDE.md); hoy describe el flujo pre-W2 y omite el inbox completo. Es el drift más peligroso del track: induce a razonar sobre un contrato de dinero que ya no existe.

**Pasos:**
1. Reescribir .context/06-contracts.md líneas 176-183 (§12) añadiendo el contrato W2: (1) persistencia cruda pre-ACK en wompi_webhook_inbox (checksum PK, idempotente, best-effort), (2) procesamiento marca processed_at terminal — crash deja NULL reconciliable, (3) dedup wompi_events_seen processed-aware: descartar SOLO si processed_at IS NOT NULL, (4) worker wompi_inbox_reconcile cada 3min: claim con lease (FOR UPDATE SKIP LOCKED) de filas >2min sin procesar y re-POST a /api/v1/webhooks/wompi (reusa firma+dedup+confirm), (5) dead-letter tras 5 intentos → runbook manual, (6) cleanup retención 7d/30d throttle 6h, (7) solo eventos transaction.updated se capturan en el inbox
1. Conservar lo vigente del §12 (payment_link_tool, validación total_in_cents, TTL 30min/35min sweeper) — solo cambia el bloque webhook
1. Añadir referencia al ADR-0040 y a las 4 env vars WOMPI_INBOX_* con sus defaults
1. Verificar contra código con grep antes de sellar (wompi_webhook.py:82,135,243; worker.py:409,2215; migración 20260714000000)

**Aceptación:**
- §12 menciona wompi_webhook_inbox, claim_wompi_inbox_batch, processed-aware y dead-letter (grep sobre el archivo)
- Ninguna afirmación del §12 contradice wompi_webhook.py ni worker.py en f3542fa0 (spot-check de las 7 propiedades listadas)
- §12 enlaza ADR-0040 y el runbook wompi-payment-reconciliation.md

#### T6-04 — docs/HANDOFF.md rev.113 — registrar migraciones 20260713*/20260714000000, deploy f3542fa0 y actualizar nota de reconciliación Wompi  `[P1 · 0.5pd]`
HANDOFF es la fuente operativa de infra+migraciones y hoy afirma production=0dbf1180 con 218 migraciones: cualquier operación de deploy/migración basada en él parte de un estado falso. El estado 'aplicada a prod' de las 4 migraciones nuevas NO es verificable desde el repo (el propio HANDOFF:27-29 lo dice) — hay que consultar el ledger.

**Pasos:**
1. Añadir bloque 'Actualización rev. 113 (2026-07-16)' encima de rev.112: production == develop == f3542fa0 (merge PR #69); PRs W1 #64-#68 + W2 #69 en producción
1. Actualizar conteo a 222 migraciones y registrar las 4 nuevas con propósito: 20260713000000_ola0_tenant_users_rbac_hardening (fix CRITICAL escalada RBAC PostgREST), 20260713010000_w1_vault_rpc_role_check (Vault RPCs por rol), 20260713020000_w1_rls_integrations_notifications_role (RLS role-aware), 20260714000000_wompi_webhook_inbox (tabla + RPC claim + RLS deny-all + cleanup)
1. Verificar estado APLICADA de cada una contra supabase_migrations.schema_migrations en la Supabase linked (protocolo memory feedback_supabase_migrations — el ledger tiene drift; si no hay acceso en la sesión, registrar como 'pendiente de verificación en ledger', NUNCA como aplicada)
1. Actualizar la nota 'Reconciliación Wompi' (líneas 39-42): sigue siendo cierto que el pull por reference es infactible, pero ahora existe reconcile automático propio (inbox W2) para el caso crash-post-ACK; el runbook queda para webhook-nunca-llegó y dead-letters
1. Añadir las 4 env vars WOMPI_INBOX_* al contrato de entorno (.env.example con etiqueta [RENDER-opcional], defaults del código) — coherencia con HANDOFF:102 que declara .env.example canónico

**Aceptación:**
- grep -E '20260713000000|20260713010000|20260713020000|20260714000000|f3542fa0' docs/HANDOFF.md → 5 matches con propósito y estado (aplicada-verificada o pendiente-de-verificación, nunca ambiguo)
- grep WOMPI_INBOX .env.example → 4 vars con defaults
- La nota de reconciliación distingue explícitamente los 3 casos: auto (inbox), manual (webhook nunca llegó), dead-letter

#### T6-05 — .context/01-state.md rev.113 (sesiones W1+W2 + re-score 73) y 04-next-steps.md con el plan de olas vigente  `[P1 · 1pd]` · dep: T6-01,T6-02,T6-04
Son los 2 docs de lectura OBLIGATORIA por sesión (CLAUDE.md) y están congelados en 2026-07-12: toda sesión nueva arranca ignorando W1/W2 y el roadmap de 6 olas del re-score 71→73. Es el multiplicador de trazabilidad más barato del track.

**Pasos:**
1. 01-state.md: actualizar header (última actualización 2026-07-16, production=f3542fa0) y añadir sección 'Rev. 113 (2026-07-13→16) — Olas W1+W2 hardening' con tabla: W1 = Ola-0 RBAC tenant_users (migración 20260713000000, fix CRITICAL PostgREST) + Vault RPCs por rol (PR #66) + RLS role-aware (PR #67) + scrub PII pre-Sentry + XFF trusted-hop + enforce_mfa_strict fail-closed (PR #68, ADR-0041); W2 = inbox transaccional Wompi (PR #69, migración 20260714000000, ADR-0040)
1. 01-state.md: registrar el re-score 2026-07-16 (73/100, baseline 71 del 2026-07-13) y qué CRITICAL quedó cerrado (escalada RBAC) vs abierto (dev=prod Supabase — sigue vigente, memory reference_localhost_shares_prod_supabase)
1. 04-next-steps.md: actualizar header a rev.113/f3542fa0 y añadir sección con el plan de olas vigente (olas restantes del roadmap ~195-210pd hacia 90+, gate pre Platform Console), marcando W1/W2 como CERRADAS y enlazando el documento canónico del plan si existe en docs/
1. Aplicar política de brevedad: si 01-state.md supera el presupuesto de 05-doc-policy (CLAUDE.md promete ≈290 líneas, hoy 2090), mover rev ≤110 a 01-state-archive.md en el mismo cambio — leer .context/05-doc-policy.md antes (mandato CLAUDE.md)

**Aceptación:**
- 01-state.md header dice 2026-07-16 y f3542fa0; grep 'Rev. 113' → match con W1 y W2 y referencias a ADR-0040/0041
- 04-next-steps.md refleja W1/W2 cerradas y el plan de olas restante con esfuerzos
- El CRITICAL abierto dev=prod Supabase sigue visible como pendiente (no se pierde en el resync)
- Si se archivó historial: 01-state.md quedó dentro del presupuesto de 05-doc-policy y 01-state-archive.md conserva las revisiones movidas

#### T6-06 — Actualizar runbook wompi-payment-reconciliation.md post-W2 — separar caso auto-reconciliado vs manual/dead-letter  `[P2 · 0.5pd]` · dep: T6-01
El runbook (99 líneas, validado 2026-06-26) es hoy la única guía del operador ante pagos estancados y no sabe que el worker ya auto-reconcilia el caso crash-post-ACK: un operador podría ejecutar pasos manuales redundantes o, peor, no saber consultar el inbox/dead-letter que ahora es la primera fuente de diagnóstico.

**Pasos:**
1. Añadir sección 'Diagnóstico primero: consultar wompi_webhook_inbox' al inicio del flujo: query por created_at/processed_at/attempts para clasificar el caso — (a) fila con processed_at NULL y attempts < 5 → el worker lo reintenta solo, esperar; (b) attempts >= 5 (dead-letter) → reconciliación manual con el raw_payload persistido (ya se tiene el transaction_id: NO aplica la limitación de pull); (c) sin fila en inbox → webhook nunca llegó, aplicar el runbook actual sin cambios
1. Precisar que el caso (b) es MEJOR que el histórico: el raw_payload contiene el transaction_id, así que GET /v1/transactions/{id} sí es utilizable — actualizar la sección 'Por qué NO hay cron' para acotarla al caso (c)
1. Mantener la fecha de validación de docs oficiales 2026-06-26 (la limitación del API no cambió; si se re-valida contra https://docs.wompi.co/docs/ actualizar fecha) — VALIDAR EN DOCUMENTACION OFICIAL solo si se afirma algo nuevo del API de Wompi
1. Enlazar ADR-0040 y las env vars WOMPI_INBOX_* (knobs de operación)

**Aceptación:**
- grep -i 'wompi_webhook_inbox' docs/operations/runbooks/wompi-payment-reconciliation.md → match en la sección de diagnóstico
- El runbook distingue los 3 casos (a/b/c) con criterio de query verificable
- Ninguna afirmación nueva sobre el API de Wompi sin cita a docs oficiales o marca de validación pendiente

#### T6-07 — Higiene documental: resolver colisión ADR 0023 duplicado + conteos stale en CLAUDE.md  `[P3 · 0.25pd]` · dep: T6-05
Dos ADRs comparten el número 0023 (meta-model-b y shipping-provider) — ambigüedad en referencias cruzadas ('ver ADR-0023' es hoy ambiguo, y HANDOFF.md:210 enlaza el de shipping). CLAUDE.md promete 01-state ≈290 líneas (real 2090) y 218 migraciones (real 222): el doc de arranque de toda sesión miente en 2 datos.

**Pasos:**
1. Decidir el renumerado del ADR duplicado: 0023-shipping-provider-integration-pattern.md es el candidato a mover (0023-meta-model-b está referenciado desde CLAUDE.md y memoria) — verificar TODAS las referencias entrantes con grep -rn '0023-shipping' docs/ .context/ services/ antes de renombrar; actualizar HANDOFF.md:210 y cualquier otra; dejar nota de redirect en el ADR viejo NO es necesario si se corrigen todas las referencias (verificar con grep post-cambio = 0 refs rotas)
1. CLAUDE.md: actualizar '218 SQLs' → 222 (o mejor: eliminar el número exacto y decir '200+ — leer solo con tarea de migración' para no re-driftear), y la línea de 01-state.md al conteo real post-T6-05
1. Verificar que scripts/validate.sh o CI no dependan de nombres de archivo ADR (grep -rn 'adr/0023' scripts/ .github/)

**Aceptación:**
- ls docs/adr/ no muestra números duplicados
- grep -rn '0023-shipping' en repo → 0 referencias al path viejo
- CLAUDE.md no contiene conteos que contradigan el repo (spot-check migraciones y líneas de 01-state)

### T7-supply
*Estado actual:* T7 SUPPLY-CHAIN (score 66) — estado real verificado 2026-07-16. LADO PYTHON: pip-audit es gate real en validate.sh:313-339 (--full/--ci, veredicto por exit code, reparado Ola 0) con allowlist de 5 PYSEC de starlette (validate.sh:323). Los 3 requirements.txt tienen directos 100% pineados con == (fastapi==0.128.8, starlette transitivo 0.49.3 instalado), pero los transitivos NO están pineados ni hay hash-checking → el build de Render (render.yaml:127,168,292 `pip install -r requirements.txt`) no es reproducible y pip-audit audita la resolución del momento, no lo desplegado. Verificado vía OSV API

*Review adversarial:* ADJUSTED — Verificacion adversarial con evidencia primaria: (1) codigo/config del repo — validate.sh:313-339 gate pip-audit real con allowlist de los 5 PYSEC exactos, requirements.txt de los 3 servicios 100% pineados sin starlette (instalado 0.49.3 flotante), render.yaml:127/168/292 sin hashes, cero dependabot

#### T7-01 — Gate de auditoría JS con osv-scanner (pnpm audit roto upstream) en validate.sh --full + CI, con allowlist estilo pip-audit  `[P0 · 1pd]`
Hoy hay 0 auditoría JS y 9 paquetes vulnerables en pnpm-lock.yaml. `pnpm audit` NO es opción: npm retiró los endpoints (410 verificado en vivo; pnpm/pnpm#13033 abierto). osv-scanner v2.4.0 soporta pnpm-lock.yaml oficialmente (google.github.io/osv-scanner/supported-languages-and-lockfiles/ — verificado) y tiene allowlist declarativa por vuln con justificación, equivalente al patrón _PA_IGNORE de pip-audit pero en archivo versionado.

**Pasos:**
1. Crear osv-scanner.toml en raíz con [[IgnoredVulns]] (id + reason + fecha de revisión) SOLO para lo no remediable de inmediato (los 2 GHSA de xlsx hasta T7-02); VALIDAR EN DOCUMENTACION OFICIAL el schema exacto en https://google.github.io/osv-scanner/configuration/
1. Añadir sección 8b a scripts/validate.sh dentro de `if $FULL` (patrón de líneas 313-339): si `command -v osv-scanner`, ejecutar `osv-scanner scan --lockfile pnpm-lock.yaml` y veredicto por EXIT CODE (lección Ola 0: nunca grep de texto ni `|| true`); si no está instalado → _warn con comando de instalación (mismo trato que pip-audit ausente en línea 338)
1. En .github/workflows/ci.yml añadir paso que instala osv-scanner PINEADO a versión exacta (binario release v2.4.0 con checksum, o action oficial google/osv-scanner con tag fijo) ANTES de `bash scripts/validate.sh --ci`, para que el gate corra en CI (en local queda opt-in como pip-audit)
1. Documentar en el TOML la política: toda entrada de allowlist exige reason + issue/fecha de re-evaluación; vuln nueva sin entrada = CI rojo
1. Correr `bash scripts/validate.sh --full` y confirmar que el gate detecta los 9 vulnerables actuales (rojo esperado antes de T7-02) y que con la allowlist mínima el veredicto es el diseñado

**Aceptación:**
- `bash scripts/validate.sh --full` en la VM ejecuta osv-scanner sobre pnpm-lock.yaml y el veredicto sale del exit code (demostrable: inyectar dep vulnerable dummy en una rama → gate falla; revertir → gate pasa)
- CI (validate.sh --ci) falla si aparece una vuln JS nueva no allowlisted — verificado con el mismo experimento en PR de prueba
- osv-scanner.toml versionado con reason por cada ignore; cero ignores sin justificación
- pip-audit sigue verde (sin regresión en sección 8)

#### T7-02 — Remediar los 9 paquetes JS vulnerables: updates/overrides + decisión sobre xlsx (sin fix en npm)  `[P1 · 1.5pd]` · gated: founder-costo · dep: T7-01
ws@8.20.0 (HIGH DoS) llega por @supabase/realtime-js a código prod; xlsx@0.18.5 tiene 2 HIGH sin fix en el registry npm y parsea archivos subidos por usuarios en mass-importer.tsx (prototype pollution sobre input no confiable). Dejarlos allowlisted permanentemente sería score-washing; el gate de T7-01 solo vale si la allowlist tiende a cero.

**Pasos:**
1. `pnpm update -r` dirigido para transitivos con fix dentro de rango: ws→≥8.21.0, postcss→≥8.5.10, js-yaml→≥4.2.0, brace-expansion→≥5.0.6, rollup→≥3.30.0; verificar con re-scan OSV que desaparecen
1. Para uuid@9.0.1 y @opentelemetry/core@1.30.1 (vía @sentry/nextjs 8.55.2): intentar bump de @sentry/nextjs a línea actual (8.x→9/10 es major: revisar migration guide oficial docs.sentry.io ANTES — VALIDAR EN DOCUMENTACION OFICIAL); si el major no cabe en el sprint, pnpm.overrides en package.json raíz para uuid≥11.1.1 sólo si @sentry/webpack-plugin lo tolera (es build-time), y allowlist temporal con fecha para @opentelemetry/core
1. xlsx: DECISION FINAL propuesta = migrar a la distribución oficial SheetJS `https://cdn.sheetjs.com/xlsx-0.20.x/xlsx-0.20.x.tgz` (mismo API, cierra ambos GHSA) — VALIDAR EN DOCUMENTACION OFICIAL https://docs.sheetjs.com/docs/getting-started/installation/frameworks (verificar versión vigente y compatibilidad pnpm con tarball URL); alternativa si el founder prefiere no depender de tarball externo: reemplazo por exceljs en mass-importer.tsx + import-template.ts (~0.5pd extra). Evaluar también xlsx-js-style@1.2.0 (fork con el mismo código base potencialmente vulnerable, hoy NO flaggeado por OSV — revisar si hereda el parser afectado)
1. Actualizar tests: apps/web/app/dashboard/(products)/catalog/_lib/import-template.test.ts debe pasar con la lib nueva; smoke manual del importador masivo (subir xlsx real de plantilla)
1. Vaciar de osv-scanner.toml todo ignore remediado; correr `bash scripts/validate.sh --ci` completo

**Aceptación:**
- Re-scan OSV del lockfile (mismo método querybatch o osv-scanner) = 0 vulnerabilidades HIGH; MODERATE restantes ≤2 y todas con reason+fecha en osv-scanner.toml
- Importador masivo de catálogo funciona end-to-end con archivo real (parse + preview + import) tras el cambio de lib
- `pnpm --filter web build` y `pnpm --filter web test` verdes
- pnpm-lock.yaml sin xlsx@0.18.5

#### T7-03 — Crear .github/dependabot.yml: pip (3 servicios) + npm/pnpm (workspace) + github-actions, semanal y agrupado  `[P1 · 0.5pd]`
Cero automatización de updates hoy; la deuda se acumula en silencio (sentry 8.55, eslint 8 EOL, 9 vulns JS). Dependabot nativo > renovate para este repo: sin app externa, soporta pnpm, pip y actions, y `groups` reduce el ruido a ~3 PRs/semana que el CI (validate.sh --ci) valida solo.

**Pasos:**
1. Escribir .github/dependabot.yml version 2 con: (a) package-ecosystem npm, directory '/', schedule weekly, groups {npm-minor-patch: update-types [minor,patch]}, majors como PR individual; (b) package-ecosystem pip con directories ['/services/api','/services/ai-orchestrator','/services/connector-whatsapp'], weekly, un grupo pip-all para minor/patch; (c) package-ecosystem github-actions, directory '/', weekly, un grupo — VALIDAR EN DOCUMENTACION OFICIAL https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file (sintaxis vigente de `groups` y de la clave `directories` multi-path, y soporte pnpm 10)
1. open-pull-requests-limit conservador (5 npm / 3 pip / 2 actions) para no inundar; labels 'deps' para trazabilidad
1. Merge a main y verificar en pestaña Insights→Dependency graph→Dependabot que los 3 ecosistemas quedan activos y corre el primer scan
1. Documentar en .context/04-next-steps.md la rutina semanal: revisar PRs agrupados, CI verde = mergeable; majors requieren revisión manual

**Aceptación:**
- GitHub muestra los 3 ecosistemas activos en Dependabot sin errores de parseo del yml (check en /network/updates)
- Primer lote de PRs agrupados creado y validado por ci.yml (validate.sh --ci corre en cada PR — comportamiento ya existente)
- Los PRs de pip aparecen para los 3 services/*/requirements.txt (o requirements.in post T7-05)

#### T7-04 — Bump FastAPI 0.128.8 → 0.139.2 + pin explícito starlette==1.3.1: cierra los 5 PYSEC y elimina la allowlist de pip-audit  `[P1 · 2pd]` · dep: T7-03
Los 5 advisories allowlisted (validate.sh:323) están parcheados solo en starlette 1.x (OSV: 1.0.1/1.1.0/1.3.0/1.3.1) y FastAPI soporta Starlette 1.0+ desde 0.133.0 (release notes oficiales, PR #14987; verificado en PyPI: 0.133+ ya no capa '<1.0.0'). El repo casi no toca starlette directo (solo run_in_threadpool, estable en 1.x) y no usa nada removido en 1.0.0rc1 (TemplateResponse legacy, FileResponse method, ORJSONResponse) — riesgo acotado y verificado por grep.

**Pasos:**
1. En los 3 requirements.txt: fastapi==0.139.2 y AÑADIR pin explícito starlette==1.3.1 (deja de flotar el transitivo de seguridad); uvicorn 0.39.0 revisar compat en changelog oficial uvicorn (VALIDAR EN DOCUMENTACION OFICIAL)
1. RIESGO 1 — FastAPI 0.132.0 activa strict_content_type por defecto (rechaza JSON sin Content-Type válido): auditar los 3 servicios; webhooks Meta y Wompi envían application/json (confirmar con test de firma existente), pero cualquier caller interno/curl sin header pasará a 415 — añadir test explícito por servicio que postea el webhook real con y sin Content-Type y fija el comportamiento esperado
1. RIESGO 2 — starlette 1.0.1 introduce validación de Host header (el fix de PYSEC-2026-161): verificar que healthchecks de Render y el proxy no envían Host malformado — smoke en un servicio primero (connector-whatsapp, el de menor blast radius)
1. RIESGO 3 — FastAPI 0.137.0 refactor interno de APIRouter/include_router: la suite completa (~3490 tests pytest) es el gate; correr `bash scripts/validate.sh --ci` local ANTES de PR (regla feedback_deploy_run_ci_not_build)
1. Quitar _PA_IGNORE de validate.sh:323 (allowlist a vacío) y actualizar el comentario de las líneas 320-322; pip-audit debe quedar verde SIN ignores
1. Deploy escalonado en Render: connector-whatsapp → api → ai-orchestrator, con UAT dinámico corto del flujo webhook→bot→pago entre cada uno (memoria: no UAT estático)

**Aceptación:**
- `pip-audit -r services/*/requirements.txt` verde SIN ningún --ignore-vuln (allowlist eliminada de validate.sh — diff visible en línea 323)
- `bash scripts/validate.sh --ci` completo verde local con fastapi==0.139.2 + starlette==1.3.1
- Test nuevo de Content-Type en webhook Meta (connector) y webhook Wompi (api) pasando y anclando el comportamiento 415/200
- Smoke prod post-deploy: mensaje WhatsApp entrante procesado end-to-end y webhook Wompi de pago aceptado (evidencia en logs .local/logs/ o Render)

#### T7-05 — Lock reproducible Python con hashes (uv pip compile) + Render --require-hashes  `[P2 · 1.5pd]` · dep: T7-04
Directos pineados pero transitivos flotando = el deploy de Render puede instalar versiones distintas a las auditadas por pip-audit en CI (audita resolución del momento, no lo desplegado). Hash-checking cierra además el vector de sustitución de paquete en el registry. uv ya está instalado en la VM (/home/ansible/.local/bin/uv) — costo de tooling cero. Se hace DESPUÉS del bump T7-04 para no compilar el lock dos veces.

**Pasos:**
1. Renombrar cada services/*/requirements.txt → requirements.in (fuente de directos, se mantiene el formato actual con ==)
1. Generar por servicio: `uv pip compile requirements.in -o requirements.txt --generate-hashes --python-version 3.11` — VALIDAR EN DOCUMENTACION OFICIAL https://docs.astral.sh/uv/pip/compile/ el flag vigente para resolución independiente de plataforma (--universal) dado que se compila en la VM y se instala en Render linux; los 3 runtime.txt ya fijan 3.11 (verificado)
1. render.yaml: buildCommand pasa a `pip install --require-hashes -r requirements.txt` en los 3 servicios python (líneas 127, 168, 292) — Render acepta buildCommand arbitrario, sin cambio de plataforma; RIESGO: si pip necesita instalar un paquete no listado (setuptools implícito) fallará el build → probar primero en un deploy manual de connector-whatsapp
1. Apuntar pip-audit de validate.sh y dependabot (T7-03) al artefacto correcto: pip-audit sobre requirements.txt lockeado (ahora sí audita EXACTAMENTE lo desplegado); dependabot pip sobre requirements.in con job/documentación para regenerar el lock en cada PR de deps
1. Añadir a validate.sh --full un check de drift: `uv pip compile --check` o recompilar y diff — lock desactualizado respecto a .in = warn (fail en --ci)
1. Documentar el flujo en .context/03-rules.md: tocar deps = editar .in + regenerar lock, nunca editar el lock a mano

**Aceptación:**
- Los 3 requirements.txt contienen TODOS los transitivos con --hash=sha256 (starlette aparece pineado explícito en el lock)
- Deploy real en Render de los 3 servicios verde con --require-hashes (evidencia: build logs)
- pip-audit en validate.sh corre contra el lock y sigue verde; test de drift: editar un .in sin recompilar → validate.sh --ci falla
- Build reproducible: recompilar el lock en la VM produce diff vacío

#### T7-06 — Pinear GitHub Actions por SHA de commit + mantenimiento vía dependabot  `[P2 · 0.5pd]` · dep: T7-03
ci.yml usa tags mutables (@v4/@v5, líneas 25-108): un tag re-apuntado en una action comprometida ejecuta código arbitrario en un runner con acceso al repo. Pin por SHA es la mitigación estándar (GitHub security hardening) y dependabot (T7-03, ecosistema github-actions) mantiene los SHAs actualizados con PRs, así que el costo de mantenimiento post-pin es ~0.

**Pasos:**
1. Para cada uses: de ci.yml (checkout@v4, setup-python@v5, pnpm/action-setup@v4, setup-node@v4, upload-artifact@v4) resolver el SHA del tag vigente (`gh api repos/{owner}/{repo}/git/ref/tags/vX`) y reemplazar por `uses: owner/action@<sha40> # vX.Y.Z`
1. VALIDAR EN DOCUMENTACION OFICIAL https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions (sección pinning) que dependabot actualiza SHAs comentados con versión (comportamiento documentado)
1. PR con solo el cambio de pins; CI del propio PR es el test
1. Opcional mismo PR: `permissions: contents: read` a nivel workflow si no está declarado (least privilege del GITHUB_TOKEN)

**Aceptación:**
- ci.yml sin ningún uses: por tag mutable — todos @SHA40 con comentario de versión
- CI verde en el PR de pins
- Dependabot genera PRs de actualización de actions contra los SHAs (verificable tras primer ciclo semanal)

### T8-estructural
*Estado actual:* Track T8 (deuda estructural W5 + resiliencia) auditado 2026-07-16 sobre production=f3542fa0. (1) K-2/ADR-0039 fue limpio en el core: 0 referencias vivas a build_and_run_orchestration, checkout_form, state_renderers o AGENTIC_SHADOW en services/ (grep verificado); orchestrator.py bajó a 2,623 LOC y render.yaml no tiene flags muertos. PERO queda residuo V1 no retirado: fsm/resolver.py (114 LOC, 0 callers de producción, solo tests/test_fsm_resolver.py), 2 imports muertos en orchestrator.py:1525-1526, y 4 tools test-only (~883 LOC: tools/dispatcher.py, inbound_dispatcher.py, known_customer_tool.py

*Review adversarial:* ADJUSTED — Los 5 hallazgos son REALES y verificados contra el código con precisión inusual: LOC exactos (114+120+145+213+405=883; orchestrator 2,623), imports muertos confirmados en orchestrator.py:1525-1526 con 0 usos posteriores (determine_transactional_state/resolve_display_state tienen 0 callers de producc

#### T8-01 — Purga del residuo V1 post K-2: fsm/resolver muerto, imports muertos y 4 tools test-only (~1,000 LOC)  `[P2 · 1pd]`
K-2 (ADR-0039) retiró el pipeline V1 pero quedó residuo verificado sin callers de producción: fsm/resolver.py (114 LOC, solo test), imports muertos en orchestrator.py:1525-1526, y tools/dispatcher.py + inbound_dispatcher.py + known_customer_tool.py + order_status_tool.py (883 LOC, solo tests; equivalentes agentic vivos en agentic/tools/contact.py y orders.py). Es superficie de confusión y mantenimiento sin valor. fsm/address.py y fsm/states.py se CONSERVAN (vivos vía orchestrator.py:1600-1601).

**Pasos:**
1. Repetir la prueba dangling-ref del método K-2: grep import-aware de cada símbolo de fsm/resolver.py y de los 4 tools sobre services/ (excluyendo tests) — confirmar 0 referencias vivas
1. Eliminar orchestrator.py:1525-1526 (imports _fsm_resolver y _fsm_has_real_address_data) y ajustar fsm/__init__.py para dejar de re-exportar resolver
1. Borrar services/ai-orchestrator/fsm/resolver.py + tests/test_fsm_resolver.py; borrar tools/{dispatcher,inbound_dispatcher,known_customer_tool,order_status_tool}.py + sus tests dedicados (test_tool_dispatcher.py, test_inbound_dispatcher.py, test_order_status_tracking.py; en test_address_building_type_matrix.py migrar el import de known_customer_tool._format_address al equivalente agentic o inline)
1. Actualizar scripts/agentic_cutover.py:27,135 eliminando la opción --shadow-only y las menciones a AGENTIC_SHADOW_ENABLED (flag retirado en K-2)
1. Verificar con python3.11 -c 'import orchestrator; import agentic.dispatcher' (compile check, precedente K-2 paso 3) + bash scripts/validate.sh --ci
1. Registrar la línea de cobertura ANTES y DESPUÉS (borrar código muerto cubierto baja el % ~1pt — dejar el número real anotado para que T8-05 mida contra el denominador nuevo)

**Aceptación:**
- grep -rn 'fsm.resolver|tools.dispatcher|tools.inbound_dispatcher|tools.known_customer_tool|tools.order_status_tool' services/ (sin __pycache__) devuelve 0 líneas
- import + compile de orchestrator y agentic.dispatcher pasan
- validate.sh --ci verde (suite completa, tenant lint 0 gaps, TypeScript, ESLint)
- Cobertura post-purga registrada en el PR (esperado ~62.9%, denominador ~22.7k stmts)

#### T8-02 — Poller de respaldo Aveonline: job _poll_aveonline_shipment_states_if_due análogo al poller Wompi  `[P2 · 2pd]` · dep: T8-01
El webhook webhookEstadosGuias es hoy la ÚNICA fuente de avance shipments→orders (aveonline_webhook.py); un webhook perdido/atrasado congela el estado del envío indefinidamente y el cliente pregunta '¿dónde está mi pedido?' contra datos stale. El cliente YA tiene get_estado (aveonline_client.py:1138) documentado como respaldo pero con 0 callers. El patrón exacto ya existe: _poll_wompi_pending_voids_if_due (worker.py:2024) con gate enabled + interval + lookback + limit 50 + exemption de tenant lint para cron cross-tenant.

**Pasos:**
1. Añadir job _poll_aveonline_shipment_states_if_due al _poll_cycle (worker.py:390-413) con flag AVEONLINE_STATE_POLL_ENABLED, intervalo default 30min y lookback configurable (default 72h)
1. Query candidatos: shipments con status NOT IN ('delivered','returned','cancelled') (espejo de TERMINAL_STATUSES de aveonline_webhook.py:96), carrier de Aveonline, updated_at más viejo que un umbral de staleness (default 12h) y dentro del lookback; limit 50; comentario tenant_filter:exempt:cron_cross_tenant (patrón worker.py:2056)
1. Por candidato: instanciar el cliente Aveonline per-tenant (creds Vault), llamar get_estado(tracking_number); mapear el raw con el MISMO mapping canónico del webhook — extraer _map_raw_status + RAW_STATUS_MAP de aveonline_webhook.py a un módulo compartible o duplicar con test de paridad (precedente documentado: integrations/wompi_client.py:1-9 duplica por sys.path separado API/orchestrator; el test de paridad es obligatorio)
1. Aplicar la MISMA semántica de avance del webhook: persistir shipment_tracking_events (RPC fn_record_shipment_tracking_event, aveonline_webhook.py:220), avance monotónico de orders.status (rank aveonline_webhook.py:105) y notificaciones existentes — reusar, no reimplementar
1. Fallos de get_estado por guía: log warning y continuar (un tenant caído no bloquea el ciclo; mismo aislamiento que _run_job worker.py:374)
1. Tests: candidatos elegibles/no elegibles, paridad de mapping webhook↔poller, monotonicidad (no regresa delivered), idempotencia (poll repetido no duplica eventos ni notificaciones), fallo parcial no aborta el batch

**Aceptación:**
- worker.py lista el job nuevo en _poll_cycle con gate por flag y default habilitado
- Test de paridad de mapping raw→canónico entre webhook y poller pasa (mismo fixture de estados Aveonline)
- Simulación en tests: shipment in_transit con webhook perdido y estado real ENTREGADA en get_estado → shipments.status=delivered + orders.status avanza monotónicamente + evento tracking persistido exactamente 1 vez en polls repetidos
- validate.sh --ci verde; tenant lint 0 gaps (exemption del cron justificada)

#### T8-03 — DECISION: NO cablear CircuitBreaker en los clientes del orchestrator ahora — documentar criterio de activación + contador observable de fallos transitorios per-provider  `[P3 · 1pd]` · dep: T8-01
Veredicto franco riesgo-vs-valor: con 1 tenant activo el breaker protege contra un modo de fallo (provider caído + alto volumen concurrente) que hoy no existe, y su costo de error sí existe: un breaker mal calibrado en quote/generate_guide (checkout) o en void (dinero) bloquea plata. Las mitigaciones reales ya están: taxonomía Transient/Permanent con degradación graceful (legacy_adapters/aveonline.py:257), refresh JWT con retry (aveonline_client.py:24-31), y el void Wompi tiene doble backup (poller worker.py:2024 + reconcile worker.py:409). Además circuit.py:23 advierte que es in-memory single-process — en la API multi-worker ni siquiera es correcto sin Redis. Lo que SÍ falta para decidir CON DATOS en el futuro es la señal: hoy nadie cuenta fallos transitorios por provider.

**Pasos:**
1. Añadir sección a ADR (nueva nota en docs/adr/, referenciando ADR-0033 money integrity) con la decisión: breaker en orchestrator DIFERIDO; criterio de activación explícito (≥N tenants activos O ≥X llamadas/día a un provider O primer incidente de provider-down que cause degradación en cascada)
1. Especificar en el ADR el diseño comprometido para cuando se active: breaker per-provider (key='aveonline'|'wompi') reusando lib/integration_client/circuit.py (el worker orchestrator ES single-process → in-memory válido ahí), con semántica FAIL-OPEN para paths de dinero: breaker OPEN ⇒ log ERROR + métrica + INTENTAR la llamada igual (advisory), NUNCA short-circuit de void/quote/guide
1. Instrumentar YA la señal barata: contador de fallos transitorios/permanentes per-provider en health_metrics.py (ya existe _collect_health_metrics_if_due en worker.py:413) — incrementar en los except de AveonlineTransientError y en void HTTP>=500
1. Añadir el retry mínimo que falta sin breaker: void_transaction_sync (integrations/wompi_client.py:86) con 1 reintento en timeout/5xx (el POST void es idempotente del lado Wompi para la misma txn — VALIDAR EN DOCUMENTACION OFICIAL: https://docs.wompi.co anulaciones/void antes de mergear; si no es verificable, dejar sin retry y que el poller backup absorba, que ya lo hace)

**Aceptación:**
- ADR mergeado con decisión, criterio de activación cuantitativo y diseño fail-open comprometido
- Métrica de fallos per-provider visible en health_metrics (test unitario del incremento)
- Retry del void: o mergeado con cita de doc oficial Wompi sobre idempotencia del void, o explícitamente descartado en el ADR con el poller como mitigación (ambos aceptables — lo inaceptable es retry sin verificar idempotencia)
- validate.sh --ci verde

#### T8-04 — MeLi stock sync retry/outbox — diferido y gated a la habilitación real de MeLi (ADR-0037)  `[P3 · 1.5pd]` · gated: founder-costo · dep: T8-03
Gap real (sync_meli_stock es fire-and-forget con 'falla silenciosa', marketplace.py:129-135; orders.py:784-790 traga errores → una venta WhatsApp con sync fallido deja stock stale en MeLi = oversell cross-canal), pero con 0 tenants MeLi activos el blast radius actual es CERO y ADR-0037:63-66 ya lo agenda como roadmap gated. Hacerlo ahora sería inventario sin cliente. Se diseña para ejecutarlo cuando el gate se abra.

**Pasos:**
1. (Al abrirse el gate) Crear outbox: tabla meli_sync_outbox (tenant_id, variation_id, target_qty, attempts, next_retry_at, status) — el sync escribe la fila ANTES del PUT y la marca done tras éxito
1. Reemplazar los fire-and-forget de orders.py:784-790 y marketplace.py por enqueue al outbox + intento inline (fast path); en fallo, la fila queda pending
1. Job de worker con backoff exponencial (reusar RetryPolicy de lib/integration_client/retry.py como referencia de taxonomía) + cap de attempts + alerta a operador al agotar
1. Colapsar filas por variation_id (solo el target_qty más reciente importa — no re-aplicar valores viejos)
1. Tests: fallo de PUT → fila pending → retry exitoso aplica el qty MÁS RECIENTE; token inválido no quema attempts (espera reconexión status='connected')

**Aceptación:**
- Una venta con MeLi caído converge el stock en MeLi al recuperarse el provider sin intervención manual (test de integración)
- 0 aplicaciones fuera de orden (qty viejo nunca pisa qty nuevo) — test dedicado
- validate.sh --ci verde + migración aplicada per protocolo feedback_supabase_migrations

#### T8-05 — Cobertura conductual 63.9%→70%: dispatcher agentic, adapter Aveonline de dinero, wompi_webhook y worker  `[P2 · 6pd]` · dep: T8-01
El baseline CLAUDE.md (58.9%) está desactualizado — coverage.xml del 2026-07-16 da 63.9% (15,066/23,590). Para 70% faltan ~1,540 líneas post-purga T8-01. Las palancas honestas son conductuales, no de relleno: agentic/dispatcher.py está al 17.5% (999 missed) siendo EL ÚNICO path productivo post K-2, y agentic/legacy_adapters/aveonline.py al 4.6% (124 missed) siendo el path vivo de guías/carrier — dinero real casi sin tests. wompi_webhook.py (342 missed) es el otro path de dinero. Priorizo módulos por (líneas ganables × criticidad), no por facilidad.

**Pasos:**
1. Fase 1 — dispatcher (objetivo +600-700 líneas): harness de turno con supabase fake + LLM stub (ya existe patrón en tests/agentic/) cubriendo: gate human_takeover/closed, degraded+escalation del tenant no-agentic (route K-2, dispatcher.py:305), gate de menor autodeclarado (dispatcher.py:670), consent flow (_log_consent_event en 3863/4032), persistencia de turn audit, y las ramas de error/fallback del composer (dispatcher.py:871)
1. Fase 2 — legacy_adapters/aveonline.py (objetivo +100): tests del adapter con cliente Aveonline mockeado: éxito quote/guide, AveonlineTransientError→degradación (línea 257), AveonlineAuthError→refresh, respuesta malformada
1. Fase 3 — wompi_webhook.py (objetivo +200): fixtures de eventos transaction.updated (APPROVED/DECLINED/VOIDED/ERROR) contra firma events_key válida/ inválida, dedup, y el path COD (línea 1098)
1. Fase 4 — worker.py (objetivo +250): tests por job usando el patrón _run_job aislado: sweep_stale, release_pending_payment, wompi_void_poll (candidatos elegibles/no), takeover_sla — más el job nuevo de T8-02 que ya trae los suyos
1. Tras cada fase: coverage run + report; al cruzar 70% estable, subir el ratchet COVERAGE_MIN de 55→68 en validate.sh:25 (margen 2pts anti-flaky) y corregir el baseline en CLAUDE.md (58.9%→real)
1. Regla de honestidad: prohibido subir el número con tests que asserten mocks de sí mismos; cada test nuevo debe fijar un comportamiento observable (outbound enviado, fila mutada, evento persistido, excepción tipada)

**Aceptación:**
- coverage report --skip-empty ≥70.0% sobre el denominador post-T8-01 (~22.7k stmts) en 2 corridas consecutivas de validate.sh --ci
- agentic/dispatcher.py ≥60% y agentic/legacy_adapters/aveonline.py ≥75% individuales (las 2 palancas críticas, no solo el agregado)
- COVERAGE_MIN=68 en validate.sh y CI verde con el ratchet nuevo
- CLAUDE.md baseline actualizado al valor real medido
