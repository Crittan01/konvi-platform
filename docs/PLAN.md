# PLAN — Plan maestro y backlog priorizado pre-producción

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop (certificación final: gate `--ci` 24 OK / 0 ERROR, coverage TOTAL 69.4%)

**Qué es este documento:** la fuente de verdad de "qué falta para producción y qué sigue". Se alimenta de la [auditoría consolidada 2026-08-02](../.audit/findings/2026-08-02-consolidated-audit.md) (IDs B/A/M con evidencia `archivo:línea`) y de los pendientes verificados de [`.context/04-next-steps.md`](../.context/04-next-steps.md). El producto que este plan lleva a producción está descrito en [`product/PRD.md`](product/PRD.md).

**Convención de IDs:** B1-B6 = bloqueantes de producción, A1-A13 = hallazgos ALTOS, M1-M20 = MEDIOS (el informe consolidado define 13 ALTOS; no existen A14-A20). Algunos pendientes de `.context` usan IDs propios (F1-F8, H7/H8, G-7, BLOQUE K/L) — se citan entre comillas para no colisionar con los IDs de la auditoría (p. ej. el "B4 anti-hibernation" de `.context` NO es el bloqueante B4).

**Escala de esfuerzo:** S < 1 día · M = 1-3 días · L > 3 días (estimación de ingeniería, no compromiso).

---

## A. Checklist Go-Live

Criterio de salida: **todas las filas en estado "Hecho" con su evidencia archivada**. Owner "Founder" = intervención humana fuera del repo; "Agente" = ejecutable en código/infra desde este repo.

| # | Ítem | Estado (verificado 2026-08-02) | Owner | Evidencia requerida |
|---|---|---|---|---|
| 1 | **B1 — Flip `AVEONLINE_GENERATE_REAL_GUIDES` a true** (founder-gate) | ☐ Pendiente. `false` en los 2 servicios (`render.yaml:226-227` konvi-api, `render.yaml:349-350` konvi-orchestrator) → toda guía es simulada, nada se despacha | Founder (flip) + Agente (UAT) | UAT previa de guía real con `POST /api/v1/integrations/aveonline/guide-dry-run` (`services/api/routers/integrations.py:591`, owner-only, `simulate=False` factura) + guía real verificada en Aveonline + flip `AVEONLINE_GENERATE_REAL_GUIDES=true` en `render.yaml:226` (konvi-api) y `render.yaml:349` (konvi-orchestrator) / dashboard Render de ambos servicios |
| 2 | **B2 — Rotación de credenciales (H7)** (founder-gate) | ☐ Pendiente. Secretos productivos en historia git desde 2026-04-06 (commit `be739a4`), sin evidencia de rotación (detalle operativo en `.context/04-next-steps.md` §"H7 — rotación de credenciales"). No verificable desde el repo | Founder | Confirmación fechada de rotación de: Supabase service_role key, anon key, DB password, Meta App Secret, Wompi keys. H8 (`git filter-repo`) queda opcional (P3) |
| 3 | **B3 — Contrato legal tenant vs operador logístico real** (founder-gate) | ◐ **En curso.** Doc corregido 2026-08-02: `docs/legal/contract-template-tenant.md` (líneas contexto, 6.4 y 8) ya declara **Aveonline único** como operador logístico/subprocesador, alineado con su anexo (`docs/legal/subprocessors.md:21`; Envia fue eliminado del runtime en rev. 109). **Pendiente:** visto bueno de abogado antes de firma con tenants | Agente (redacción ✅) + Founder (abogado) | Contrato corregido (eliminado Envia de las 3 líneas) + visto bueno de abogado (solapa con acción 4 de B6) |
| 4 | **B4 — Re-certificación E2E conversacional** (founder-gate la parte live) | ◐ **Automatizado local VERDE 2026-08-02; la re-certificación contra bot LIVE queda founder-gate.** Local sin servicios: `pytest tests/agentic/` → 654 passed / 10 skipped; `pytest tests/test_a11_coherence_assertions.py` → 13 passed (núcleo puro de assertions del harness); gate `--ci` 24 OK. El harness `coherence_scenarios.py` (15 escenarios, `--list` OK) **requiere stack live** (connector :8000 + orchestrator + DB): sin stack falla con `Connection refused` (verificado hoy) y además sigue desincronizado del gate de método de pago ("BLOQUE K/L", P2). Últimos runs live archivados en `scripts/uat/runs/` datan de mayo-2026; 5 fixes de bot de agosto (#209-#213) sin re-certificación live | Founder (run live) + Agente (sync K/L) | `python3.11 scripts/uat/coherence_scenarios.py` → 15/15 escenarios verde con bot LIVE (staging/prod, previo sync "BLOQUE K/L") + `python3.11 -m pytest tests/test_a11_coherence_assertions.py` verde + log archivado en `scripts/uat/runs/` |
| 5 | **B5 — Cobertura de paths de dinero** | ✅ **Cerrado 2026-08-02.** `.coverage` del gate `--ci`: `wompi_webhook` 90.2%, `meli_webhook` 87.0%, `order_cancellation` 90.0%, `aveonline_client` 94.7% (medición previa: 53.7/37.7/36.6/45.7). Tests nuevos: `tests/test_wompi_webhook_money_paths.py`, `test_meli_webhook_processing.py`, `test_order_cancellation_pipeline.py`, `test_aveonline_client_money.py`, `test_uat20260720_money_path_integrity.py`. TOTAL 69.4% → gate sube a `COVERAGE_MIN=60` (M18) | Agente | Nuevo `.coverage` con meta por módulo alcanzada (≥80% en los 4 módulos de dinero ✓) + CI verde (gate `--ci` 24 OK / 0 ERROR ✓) |
| 6 | **B6 — Fase 0 fiscal founder** (founder-gate) | ☐ Pendiente. Declarada "ventana crítica 2-4 sem" el 2026-05-30 (ADR-0022, constraints y triggers SAS en `.context/04-next-steps.md` §"Fase 0 fiscal"); externa al repo | Founder | 6 acciones: contador SaaS contratado · facturación electrónica DIAN activa · pólizas E&O ≥$500M + Cyber ≥$500M · abogado revisó contrato tipo · nombre comercio Wompi = "KONVI" · autodiagnóstico exclusión IVA cloud |
| 7 | **Flip `MFA_MANDATORY_ENABLED`** (A1) | ☐ Pendiente. `false` en prod (`render.yaml:208-209`); write-roles operan sin MFA obligatorio. Rollout ya diseñado: setear `MFA_MANDATORY_START` a la fecha del flip (`render.yaml:212`) → notificar usuarios → `ENABLED=true` (gracia 14 días, `MFA_MANDATORY_GRACE_DAYS`) | Founder | Variable en `true` en Render + usuarios owner/manager enrolados (página `/dashboard/settings/security` ya existe) |
| 8 | **Verificación canario `cf-connecting-ip`** (A2, T4-01) | ☐ Pendiente verificación empírica. `TRUSTED_CLIENT_IP_HEADER=cf-connecting-ip` (`render.yaml:161-162,303-304`); si Render/CF no sobrescribiera el header, allowlist MeLi y rate-limit serían spoofeables (`security.py:108-142`) | Agente | Prueba canario en prod: activar `XFF_CANARY=1` (log `[XFF_CANARY] trusted_header/xff/client_host/resolved` por request, `security.py:139-144`) y enviar request con header `cf-connecting-ip` spoofeado → `resolved` debe ser la IP real del cliente; evidencia en log + cierre formal de T4-01 |
| 9 | **Revisión trimestral IPs MeLi** (A3) | ☐ **Vencida** (estaba declarada para 2026-07-28; el ritual trimestral quedó registrado en §D de este PLAN) | Agente | Diff de IPs oficiales de notificaciones MeLi vs `_MELI_DEFAULT_NOTIFICATION_IPS` (`services/api/routers/meli_webhook.py:80`); PR menor si cambiaron + fecha registrada en §D |
| 10 | **Tenants legacy con `active_provider='envia'`** (M12) | ☐ Pendiente verificación. El `DEFAULT 'envia'` persiste en migraciones viejas (`supabase/migrations/20260527020000_aveonline_provider_setup.sql:23`) aunque Envia salió del runtime | Agente | Query live (`supabase db query --linked`): 0 filas con `active_provider='envia'`, o migración correctiva aplicada |
| 11 | **Plantillas Meta (HSM) por tenant** | ☐ Pendiente (founder-gate) | Founder | Plantillas aprobadas en Meta Business Manager de cada tenant productivo; UI ya existe en `/dashboard/integrations/whatsapp?tab=plantillas` |
| 12 | **Wompi production keys** | ☐ Pendiente (founder-gate; aplica cuando un tenant pase a operativo) | Founder | Keys de producción en Render + 1 transacción real verificada con reconciliación 3 capas |
| 13 | **Aviso de privacidad publicado** | ☐ Pendiente (founder-gate) | Founder | Versión canónica del aviso publicada por tenant (template ya existe en `settings/legal`) |
| 14 | **Dirección de notificación judicial de KAIU** | ☐ Pendiente. Único campo legal que le falta al comprobante (ADR-0040) | Founder | Campo diligenciado en datos del tenant + comprobante v2 emitido con el campo |
| 15 | **SMTP propio (IH-SMTP)** | ☐ Pendiente. Hoy Resend con dominio del operador; bloquea F7-email (recovery dual-channel) | Founder | Dominio propio verificado en Resend (DNS) + `RESEND_FROM_EMAIL` actualizado |

---

## B. Backlog técnico priorizado

Los ítems del checklist (A1, A2, A3, M12) no se duplican aquí. Esfuerzo y dependencias son estimaciones; el "qué" y la evidencia vienen del informe de auditoría.

### P0 — Antes o inmediatamente después del go-live

| ID | Qué | Por qué importa | Esfuerzo | Dependencias |
|---|---|---|---|---|
| ✅ A4 | Guardrails del bot **fail-open** ante excepciones DB — **CERRADO 2026-08-02:** fail-closed para guardrails de dinero vía `FAIL_CLOSED_INVARIANTS` (`agentic/invariants/base.py:43`): un invariant de dinero que lanza escala a humano y el texto NO pasa (`base.py:124`; test `tests/agentic/test_a4_invariant_fail_closed.py`) | Las 3 capas anti-alucinación son promesa central del producto | M | — |
| ✅ A5 | Cascada LLM peor caso ~5 min vs heartbeat Render 120s — **CERRADO 2026-08-02:** presupuesto total por turno `LLM_CASCADE_DEADLINE_SECONDS=100` (< heartbeat 120s) en `llm_invoke.py`; aplicado en `agentic/agent.py:597` (test `tests/agentic/test_a5_cascade_deadline.py`) | Mensajes duplicados al cliente final = experiencia rota y riesgo anti-spam Meta | M-L | — |
| ✅ A6 | Rescate Claude **muerto** — **CERRADO 2026-08-02:** `llm_claude_rescue.py` eliminado de `services/api/lib/` y `services/ai-orchestrator/`; `anthropic` ausente de requirements y `render.yaml` (test `tests/agentic/test_a6_claude_rescue_removed.py`). **Ojo:** `llm_cascade.py` (orchestrator + copia byte-equal en `services/api/lib/`, paridad blindada por `tests/agentic/test_llm_cascade_parity.py`) **conserva el tier Claude opcional** del cascade: sin `ANTHROPIC_API_KEY` el tier se omite en runtime; borrarlo rompería la paridad byte-a-byte de la copia | Código muerto que simulaba una red de seguridad inexistente | S | — |
| A7 | Doc canónica stale: `09-bot-flowchart.md` describe arquitectura V1 retirada; AGENTS.md 2 majors atrás; `01-state`/`04-next-steps` ~50% contenido muerto. **Parcialmente cerrado 2026-08-02 vía A13 + reescritura de `04-next-steps`** — queda pendiente la verificación final de `01-state` y AGENTS.md | Los agentes operan con mapas falsos del sistema; este PRD/PLAN corrige la capa de producto | M | Ninguna (este PLAN ya descontó lo verificado) |
| ✅ A10 | Polling backup de tracking Aveonline ausente — **CERRADO 2026-08-02:** job `_aveonline_status_poll` en `services/ai-orchestrator/worker.py:3334+` (intervalo 1h, candidatas = guías reales >6h sin update vía webhook, batch 25) con `AVEONLINE_STATUS_POLL_ENABLED/INTERVAL_SECONDS/STALE_HOURS/BATCH` en `render.yaml:503-509` y `.env.example:200-203` | Envíos congelados sin alerta = reclamos y retracciones | M | — |
| ✅ A12 | `X-Tenant-Id` autodeclarado sin verificar en dual-auth — **CERRADO 2026-08-02 (audit trail):** cada llamada internal-secret deja fila en `api_security_events` (`internal_auth.py` `_audit_internal_call` → `observability.record_api_security_event`): tenant declarado, path, método, outcome, user-agent; secret válido sin `X-Tenant-Id` → 400 logueado. La verificación criptográfica estricta del tenant queda amarrada al refactor A0.2c (transición anotada en `render.yaml`) | Quien obtenga el secret actuaba como cualquier tenant sin dejar rastro; ahora deja rastro forense | M-L | Refactor A0.2c para la verificación estricta |
| ✅ A13 | Docs canónicas de runtime desactualizadas — **CERRADO 2026-08-02:** `.context/09-bot-flowchart.md` reescrito (path agentic único, verificado contra código @ `5fdad396`), `.context/06-contracts.md` corregido (§16 deduplicada; Envia solo como nota histórica rev.109), `.context/07-schema-canonical.md` regenerado | Misma raíz que A7, en los contratos runtime | S-M | A7 |

### P1 — Primeras 4 semanas post-go-live

| ID | Qué | Por qué importa | Esfuerzo | Dependencias |
|---|---|---|---|---|
| ✅ M1 | Badge `human_takeover` invisible en móvil — **CERRADO 2026-08-02:** badge en `apps/web/app/dashboard/bottom-nav.tsx` (mismo dato que el sidebar desktop — conversaciones en `human_takeover` sin archivar; aria-label con conteo) | El operador móvil no ve que un cliente espera humano | S | — |
| M2 | Registrar las 9 rutas reales en el tree L1 (`/promotions`, `/receipts`, `/categories`, `/settings/security\|health\|legal\|retention\|account-closure` + visor legal) | Drift entre L1 y navegación real (verificado: las 8 páginas SÍ están en el sidebar); bloquea futuras decisiones de módulos | S | Decisión formal de producto (regla L1) |
| M4 | Runbook de reconciliación Wompi para webhook totalmente perdido (hoy manual, limitación del proveedor) | Dinero: sin runbook, la recuperación depende de memoria del founder | S | Ninguna |
| ✅ M5 | Error boundaries por ruta + tests de componente UI — **CERRADO 2026-08-02:** 7 `error.tsx` (`app/`, `dashboard/`, inbox, orders, shipping, catalog, metrics) + tests de componente Vitest `components/ui/motion.test.tsx` y `components/command-palette.test.tsx` (suite Vitest: 320 passed) | Una excepción de render tumbaba la pantalla entera | M-L | — |
| M6 | `fn_apply_retention` sin rama `audit_log` (política insertable con FALSE) | Si alguien la habilita, la retención de auditoría no se aplica y nadie se entera (cumplimiento) | S-M | Ninguna |
| M7 | "A6.3" RLS GUC middleware + "A6.4" Vault RPC ownership sin implementar | El aislamiento hoy depende de lint + filtros de aplicación, no de la sesión DB | L | Diseño de sesión DB por request |
| ✅ M8 | Doble default de modelo Gemini divergente — **CERRADO 2026-08-02:** default unificado: `orchestrator.py` toma `DEFAULT_PRIMARY_MODEL` de `llm_invoke.py` (una sola fuente de verdad; test `tests/agentic/test_m8_orchestrator_model_default.py`) | Comportamiento distinto según el path de invocación | S | — |
| M9 | 171-229 archivos de tests con paths absolutos `/home/ansible`; CI depende de symlink shim | Suite no portable; cualquier contribuyente externo no puede correrla | M | Ninguna |
| ✅ M10 | Post-venta fuera de ventana 24h: promesa de canal rota — **CERRADO 2026-08-02:** el bot ya no promete confirmación solo "por este chat" (`orchestrator.py:1048`, `payment_link_tool.py:459`): el comprobante va SIEMPRE por correo + por WhatsApp si la CSW sigue abierta (error 131047; test `tests/agentic/test_m10_orchestrator_channel_promise.py`) | Promesa rota al cliente en tracking/cambios tardíos | M | — |
| ✅ M11 | Flag `agentic_enabled` fail-closed ante error transitorio — **CERRADO 2026-08-02:** `_get_agentic_meta` con 1 retry + stale-ok del último valor cacheado (`agentic/dispatcher.py:81-133`); solo degrada a fail-closed si NUNCA se leyó valor (test `tests/agentic/test_m11_agentic_enabled_fail_closed.py`) | Un glitch de DB desactivaba el bot para todos los clientes a la vez | S-M | — |
| M13 | 2 ADRs con número 0023 duplicado; ADRs 0018/0019/0028 con Estado falso ("PROPUESTO" estando implementados) | Trazabilidad de decisiones rota | S | Ninguna |
| ✅ M14 | `/health/ready` devolvía `detail=str(exc)[:200]` sin auth — **CERRADO 2026-08-02:** detalle genérico hacia afuera ("dependencia no disponible"); error completo a logs + Sentry (`main.py:332-365`) | Fuga de detalle interno a Internet | S | — |
| ✅ M15 | Gaps de rate-limit en writes sensibles — **CERRADO 2026-08-02:** `RL_WRITE_DEFAULT` aplicado a los 12 endpoints del gap: expenses POST + `/{id}/reverse`, product_attribute_definitions (3), settings/maintenance/idempotency-cleanup, integrations/aveonline/* (6: webhook configure/rotate/delete + carriers put/delete/seed) | Superficie de abuso autenticada sin freno | M | — |

### P2 — Primer trimestre post-go-live

| ID | Qué | Por qué importa | Esfuerzo | Dependencias |
|---|---|---|---|---|
| M16 | Cliente Aveonline duplicado espejo (`services/api` + `services/ai-orchestrator`, 1176 líneas ×2) | Todo fix de shipping hay que aplicarlo dos veces; drift garantizado | L | Extracción a paquete compartido o consumo vía API interna (solapa A12) |
| M17 | Telegram: `setWebhook` manual por tenant; MeLi: refresh de tokens lazy (token >6 meses sin uso expira) | Operación manual por tenant no escala; tokens MeLi mueren en silencio | M | Automatización o runbook + alerta en `tenant_provider_health` |
| ◐ M18 | Gate de cobertura vs comentarios que decían 70 — **CERRADO PARCIAL 2026-08-02:** `COVERAGE_MIN` default sube de 55 a **60** en `scripts/validate.sh` (TOTAL medido por el gate `--ci` hoy: 69.4%) y comentarios alineados (`validate.sh`, `pyproject.toml:87`). **Target 70 sigue abierto** — subir el gate al cerrar la deuda de cobertura restante | El gate mentía; solapa con B5 | S | B5 ✅ (hecho) |
| M19 | `verify_token` dev en claro + UUIDs de tenant hardcodeados en migración backfill — **SIGUE PENDIENTE (verificado 2026-08-02):** `'konvi-dev-direct-2026'` persiste en `supabase/migrations/20260622_whatsapp_model_b_backfill_konvi_dev.sql:11` | Higiene de secretos/identificadores en repo | S-M | B2 |
| M20 | `services/worker`, `services/cron`, `connector-shopify`, `connector-mercadolibre` son placeholders (solo README) | Ruido estructural; decidir mantener documentados o eliminar | S | Decisión de producto (Shopify = fase 13) |
| "G-7 self-service" | Reversión de pago self-service del bot (0 hits en `agentic/`): hoy la radica el operador desde Reclamos — human-in-the-loop, legalmente más sólido | Solo si producto decide automatizarla; requiere tool nuevo + `tools_subset` por estado FSM | M | Decisión de producto (diseño actual es deliberado) |
| "F2" | Tokenización completa de `document_number` con Vault (hoy hash + last4 aditivo, rev. 96) | PII fuerte (cédula) con seudonimización mejorada | M | "A6.4" (M7) |
| "F3" | Migración de `audit_log` legacy a `consent_audit_log` (deduplicar) | Doble fuente de auditoría de consentimientos | S-M | Ninguna |
| "BLOQUE K/L" | Higiene de tests: harness `coherence_scenarios.py` desincronizado del gate de método de pago (turnos no responden contraentrega/online) — **bloquea la parte live de B4** | La red de regresión conversacional (B4) queda coja si no se sincroniza | M | B4 |
| "F7-email" | Recovery dual-channel por email | Recuperación de cuentas sin depender de un solo canal | S | SMTP propio (checklist #15) |
| "F7-full" | Cart abandonment proactivo (hoy F7-lite reactivo) | Recuperación de carritos = revenue del tenant | M | Plantilla Meta aprobada (checklist #11) |
| "F8" | Multimodal imagen (reusa base `meta_media.py` del audio) | Catálogo conversacional por foto | M | Ninguna |
| Custom Access Token Hook | Claims custom vía hook de Supabase Auth (feature beta) | RBAC más limpio en JWT | M | Supabase GA del feature |

> **Nota ADR-0003 (F1-F7):** la tabla de follow-ups de `.context/04-next-steps.md` quedó limpiada 2026-08-02 (fila "ADR-0003 follow-ups F1, F4, F5, F6, F7" en su tabla §Verificado-resuelto). Verificado en código 2026-08-02: F1 (SAR printable HTML, `data_subject_request.py:407`), F4 (UI retención), F5 (reporte SIC, `sic_report.py`), F6 (detector rectificación, `orchestrator.py:326`) y F7 (click-wrap legal, `settings/legal`) **ya están implementados**. Solo quedan F2 y F3 (arriba).

### P3 — Oportunista / condicionado

| ID | Qué | Por qué importa | Esfuerzo | Dependencias |
|---|---|---|---|---|
| H8 | `git filter-repo` para purgar `.env` de TODA la historia git | Higiene profunda; innecesario si B2 rotó todo (secretos viejos inutilizables) | L | B2 hecho + coordinación de clones (destructivo, reescribe hashes) |
| "B4-infra" | Anti-hibernation ping (Render Free) | Evitar cold starts si se mantiene plan Free | S | Decisión de plan Render (ver `docs/deployment/render-upgrade-path.md`) |
| "C3" | DR/backup de Supabase | Continuidad del negocio | M | Plan de Supabase que lo soporte |
| Tenant environments | Entornos dev/staging/prod por tenant para UAT sin data real | Escala de UAT multi-tenant | L | Trigger definido: 5+ tenants productivos o Platform Console |

---

## C. Roadmap post-go-live

| Iniciativa | Trigger / gate | Estado |
|---|---|---|
| **Konvi Studio** (Camino D — editor de personalización, react-konva, ~6-8 sem de dev) | **Gate comercial duro**: Lucams valida demanda con flow manual (Instagram + WhatsApp + Wompi link directo + diseño a mano) hasta **>30 órdenes/mes**. NO arrancar antes (contexto en `.context/04-next-steps.md` §"Konvi Studio") | Gated, sin código |
| **COD / contraentrega (H.2.4)** | Pausado formalmente 2026-05-07. Trigger de reanudación: KAIU completa KYC Ecart Pay Colombia + Prueba 3 en producción + ejecutivo confirma formato DANE Servientrega (V.4) + Coordinadora. Certificado: 4 carriers COD viables; no existe webhook COD dedicado (evidencia en `.context/04-next-steps.md` §"COD H.2.4") | Pausado formal |
| **Shopify / tienda custom (Fase 13)** | Futuro lejano; `services/connector-shopify` es placeholder | No iniciada |
| **Platform Console (Fase 12)** | Bloqueada por **OQ-P01** (¿misma app o app separada?) sin resolver — [`risks/open-questions.md`](risks/open-questions.md). Todas las vistas cross-tenant se difieren aquí | Bloqueada |

---

## D. Rituales operativos

| Ritual | Frecuencia | Próxima ejecución | Qué se verifica |
|---|---|---|---|
| Revisión de IPs de notificaciones MeLi | Trimestral | **YA — vencida 2026-07-28** (checklist #9) | Diff IPs oficiales vs `_MELI_DEFAULT_NOTIFICATION_IPS` en `meli_webhook.py`; PR menor si cambiaron |
| Re-certificación E2E conversacional | Cada release que toque bot (FSM, tools, invariants, prompt) | Con el próximo cambio de bot | `coherence_scenarios.py` 15/15 + `test_a11_coherence_assertions.py` verde; log en `scripts/uat/runs/` |
| Rotación de secretos | Trimestral y tras cualquier incidente | Tras cerrar B2 (primera rotación documentada) | Supabase keys, DB password, Meta App Secret, Wompi keys, `INTERNAL_SERVICE_SECRET`, `RESEND_API_KEY` |
| Revisión de este PLAN | Semanal | Próxima sesión de trabajo | Checklist §A al día, P0/P1 re-priorizados, estados verificados contra código (no contra memoria) |
