> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Validación del audit fullstack + Plan de trabajo a producción — 2026-07-03

**Fuente auditada:** `docs/research/fullstack-review-2026-07-03.md` (122 hallazgos).
**Método de validación:** 55 agentes adversariales (36 individuales CRITICAL+HIGH, ~18 lotes MEDIUM+LOW) verificando cada hallazgo contra el código y la DB remota reales. Nada por supuesto.

## Veredicto sobre el audit

| Métrica | Resultado |
|---|---|
| CONFIRMADOS | **116 / 122 (95.1%)** |
| PARCIALES (defecto real, impacto inflado) | 6 |
| REFUTADOS | **0** |
| Inventados / alucinados | **0** |

Existencia del defecto ~100% acertada. Severidad ~87% acertada, con sesgo a **sobreestimar** (15 casos HIGH→MEDIUM o MEDIUM→LOW). Única **subestimación**: **F85** (bypass MFA en toda /api) marcado MEDIUM → es HIGH.

**Los 6 PARCIALES (bajar prioridad):** F117 (HIGH→MEDIUM, gap de metadata) · F12 (MeLi inactivo + RLS deny-by-default lo neutraliza) · F19 · F48 · F114 · F39.

---

## Principio del plan

"Completo, sin omisión" = **cada uno de los 116 confirmados recibe una disposición** (arreglar ahora / diferir con criterio / aceptar+documentar). El esfuerzo es **proporcional al riesgo**, no plano. Protocolo:
- Migraciones a prod → **autorización explícita del founder** (por bloque de fase).
- Cada fix con **test de regresión** + `validate.sh --ci` verde antes de commit.
- Rama `develop` (= producción). Deploy manual del founder.
- Verify-before-fix: releer el código real antes de tocar (varios fixes tocan dinero/hot-path).

---

## FASE 0 — Seguridad crítica y aislamiento multi-tenant · BLOQUEANTES DE PRODUCCIÓN

Estos permiten fuga/daño cross-tenant o bypass de auth. **Nada sale a producción sin cerrarlos.**

| id | Sev real | Defecto | Fix |
|---|---|---|---|
| **F10** | CRIT | `add_member_to_tenant` SECURITY DEFINER sin REVOKE → anon/authenticated se hacen owner de cualquier tenant | Migración: REVOKE + validar `auth.uid()` membership del caller |
| **F82** | CRIT | `team/page.tsx` usa ID del form crudo → ban/borrado cross-tenant de `auth.users` | Validar target pertenece al tenant del caller (server) |
| **F11** | HIGH | pgmq helpers (enqueue/dequeue/ack) SECURITY DEFINER sin REVOKE → encolar WhatsApp saliente de otro tenant | Migración: REVOKE de los 3 |
| **F52** | HIGH | eventos template/phone-quality escriben cross-tenant (sin `.eq(tenant_id)`) | Autoridad de tenant server-side (patrón WH-01) |
| **F27** | HIGH | `POST /orders` acepta contact_id/conversation_id del body sin validar ownership → IDOR fuga cédula (Ley 1581) | Validar ownership + rechazar variation_id ajenos |
| **F83** | HIGH | cookie `mfa_recovery_session` = literal `'1'` sin firma → bypass AAL2 | Token firmado/verificado |
| **F85** | HIGH | bypass MFA en superficie /api (audit lo marcó MEDIUM) | Enforce AAL2 en middleware |
| **F30** | HIGH | `sys.path.insert` colisiona namespace `lib` api↔orchestrator | Namespacing / `__init__.py` |
| **F53** | HIGH | I/O síncrona (Supabase/Vault) en event loop del webhook Meta | `run_in_executor` / async client |
| **F17** | HIGH | webhook Telegram gateado por JWT → 401 siempre (feature muerto) | Quitar `_OFFBOARDING_GATE`, auth por secret token |
| **F13·F15·F12** | MED | RPCs SECURITY DEFINER sin REVOKE / sin `SET search_path` fijo | Migración hardening (F12 solo IaC, no explotable hoy) |

## FASE 1 — Cumplimiento Ley 1581 (Habeas Data)

Compliance roto en el canal productivo. Riesgo legal real.

| id | Defecto | Fix |
|---|---|---|
| **F2** | `conversations.contact_id` no existe → self-service F6 muerto + audit-log contact_id NULL | Resolver contact_id por `customer_phone`→contacts (arreglar mi F6) |
| **F4** | `sic_report` selecciona `document_number` inexistente → 503 siempre | Usar `nit` + resolver campos reales |
| **F116** | 3 writers escriben `consent_date` sin `consent_given_at` → export legal vacío | Escribir ambas columnas + backfill |
| **F1** | `human_takeover_reason` no existe → escalación de crisis salud mental nunca notifica | Quitar columna fantasma + persistir razón en messages |
| **F43** | `invalidate_shipping` descarta `recipient` en cada add/remove → pierde PII receptor | Preservar recipient |
| **F121·F107·F108·F125** | consent duplicado 3×, endpoints muertos, tabla rma sin uso | Consolidar + limpiar |

## FASE 2 — Integridad de dinero

| id | Defecto | Fix |
|---|---|---|
| **F42** | CRIT — reuso de link con monto congelado pre-cupón → cliente paga monto ≠ acordado | Invalidar orden/link al mutar cart tras generar link |
| **F16** | CRIT — guard de monto Wompi muerto (`_get_order_by_id` sin `total_amount`) | Seleccionar total_amount + reactivar validación |
| **F105·F46·F50·F49** | payment-link sin wrapper resiliente · total ignora discount · discount stale · POST_PAYMENT COD inalcanzable | Cablear resiliencia + recomputar descuento |

## FASE 3 — Features rotas / correctitud runtime

Cosas que hoy fallan en silencio para el operador o el bot. ~20 hallazgos: F45 (restart-loop worker), F44 (cron carritos muerto), F18 (`.select().single()` tras insert → 500), F19, F62 (pending_payment ausente en UI), F68/F139/F140/F104 (errores tragados en el frontend), F7/F5 (columnas fantasma), F32/F31 (direcciones divergentes), F17, F20/F21/F22/F23/F24/F25...

## FASE 4 — Base de datos: esquema, índices, drift

F14/F133 (índices faltantes en paths calientes) · F111/F108/F125/F123 (tablas huérfanas + consolidar 3 dedup) · F63 (vault_helper drift) · limpieza de ledger drift. **Bloque de migraciones → autorización founder.**

## FASE 5 — Código duplicado / muerto (limpieza)

F33/F35/F36 (formateadores tel/precio/carrier duplicados y drifteados) · F110/F109 (router settings sin caller, review_queue write-only) · F37 · consolidación a fuente única con pact test.

## FASE 6 — Desalineación con documentación oficial

Pendiente: re-correr los 2 validadores de docs oficiales (Next.js 14.2.35 / FastAPI 0.128.8 / Pydantic 2.12.5 / supabase-py 2.28.3 / google-genai / WhatsApp v21 / Wompi / Aveonline) — quedó fuera de esta validación (que se enfocó en los 122 hallazgos).

---

## Los 6 PARCIALES + partials de severidad → registro, no esfuerzo pleno

Se documentan y se arreglan solo el mecanismo real (no el impacto inflado): F117, F12, F19, F48, F114, F39.

## Fuera de cobertura (honestidad de alcance)

- Esta validación verificó **existencia + severidad** de los 122, no re-derivó fixes nuevos (los del audit se toman como punto de partida).
- No se auditó rendimiento bajo carga real ni pruebas de penetración activas.
- Los per-finding fix details viven en el audit fuente `fullstack-review-2026-07-03.md`.