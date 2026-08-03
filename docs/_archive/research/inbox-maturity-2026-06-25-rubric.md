> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


I have full clarity on the existing pact mechanism (Pydantic write-model fields ⊆ DB columns, fixture from live schema). I now have everything needed to design a falsifiable rubric. Writing the final answer.

# Rúbrica de Scoring Falsable — Inbox Ecosystem Konvi

> Convierte el "70/100 subjetivo" en una métrica **falsable**: cada nivel se define por criterios binarios verificables, cada dominio tiene un target con su gap-closer estructural anclado a un finding del `per-domain.json`, y cada dimensión declara cómo se mide (automatizable vs re-auditoría). Anti-Goodhart: el score se compone de gates de evidencia, no de un número que se pueda "subir" sin cerrar el finding subyacente.

---

## 0. Modelo de score: por dimensión, no global plano

El "score de dominio" (62–78 hoy) deja de ser una opinión y pasa a ser una **función de 6 sub-scores dimensionales** (0–100 cada uno), donde la dimensión que más pesa es la que el finding más severo del dominio toca. Esto evita el promedio plano que enmascara un crítico tras cinco lows.

**Dimensiones (las 6 categorías ya usadas en el `per-domain.json`, fusionando `scalability` en resilience y `completeness` en maintainability para no inflar):**

| Dim | Qué mide | Señal canónica de fallo en el audit |
|---|---|---|
| **correctness** | El productor y el consumidor comparten contrato; el path declarado es el path ejecutado | Clase A (literal `human_handoff`, `variants`, `out_reservation_id`); Clase E (código muerto) |
| **security_multitenant** | Toda ruta cross-tenant filtra explícitamente + dual-auth cubierto por test | IDOR RPC stock; connector ignora tenant HMAC; `/agentic/metrics` sin auth; Clase B latente |
| **data_integrity** | Mutaciones atómicas, idempotencia determinística, sin lost-update | Clase D (read-modify-write); Clase G (idempotencia decorativa); CART-01 |
| **resilience** | Degradación con señal, no fail-open silencioso; health real | Clase C (except ancho fail-open); Clase F (/health 200 con worker muerto) |
| **completeness/compliance** | Garantías documentadas están cableadas y corren en el path LIVE | gates HARD solo en legacy; reconciliación Wompi sin caller |
| **maintainability** | Contrato único compartido; sin duplicación inline; observabilidad accionable | duplicación V2↔V3; `sys.path.insert` cross-service; logs sin correlation_id |

**Score de dominio = min(dimensiones con finding ≥ high) ponderado, NO promedio.** Regla anti-Goodhart: **un finding `critical` abierto capea el dominio a ≤ 68**; un `high` de `security_multitenant` o `compliance` abierto lo capea a ≤ 75. Así "subir el score" exige cerrar el finding que lo capea, no acumular lows resueltos.

---

## 1. Qué significa CADA nivel (criterios objetivos verificables)

Los anclajes (60/75/90/95) se definen como **gates acumulativos**: para alcanzar un nivel hay que cumplir TODOS los criterios de ese nivel y los inferiores. Cada criterio es binario y tiene una fuente de evidencia.

### Nivel 60 — "Funciona en el happy path, frágil bajo trigger"
Es el piso de un dominio que **tiene un crítico activo o un fail-open sistémico**. Criterios (todos deben cumplirse para *no* caer por debajo de 60):
- C-60.1 `correctness`: no hay un finding `critical/correctness` que rompa el path LIVE en runtime con probabilidad ≈1 (ej. INV-01 catálogo, ORCH-01 sweep). **Evidencia:** ausencia de finding crítico abierto en el dominio + test que falla con el bug presente.
- C-60.2 `security`: ninguna ruta cross-tenant escribe/lee sin filtro explícito. **Evidencia:** `audit_tenant_filter.py` = 0 gaps NEW (ya enforced, BASELINE_MAX=0).
- C-60.3 `data_integrity`: ninguna mutación financiera (orders, payments, stock) corre sin idempotencia *alguna*. **Evidencia:** grep de Idempotency-Key + UNIQUE en la tabla.

> Un dominio < 60 significa: hay un finding `critical` abierto cuyo trigger es ≈1 (no condicionado). Hoy: **Orders (62)** está aquí por acumulación de 3 `high/data_integrity` sin atomicidad.

### Nivel 75 — "Correcto y seguro bajo trigger común; gaps son de robustez/observabilidad"
Es el target operativo por defecto del repo para producción multi-tenant. Añade sobre 60:
- C-75.1 `correctness`: **0 findings Clase A abiertos** en el dominio. Productor↔consumidor comparten contrato verificado por test contra **output real del productor** (no fixture con shape inventado). **Evidencia automatizable:** test de contrato/pact (extender `test_coherence_pact.py` a contratos de runtime: catálogo, FSM literal, retorno RPC).
- C-75.2 `resilience`: ningún `except Exception` ancho degrada hacia el camino *menos seguro* sin emitir métrica/alerta. KeyError/NameError/TypeError NO se tragan. **Evidencia:** lint AST nuevo `audit_broad_except.py` (ver §3) + grep de `except Exception: return None|False|''` en hot-paths.
- C-75.3 `security`: el path dual-auth internal-secret está **cubierto por ≥1 test de integración**. **Evidencia:** `grep -r 'X-Internal-Service-Secret' tests/` > 0 (hoy = 0 → ningún dominio con ruta S2S supera C-75.3 todavía).
- C-75.4 `completeness`: ningún gate de compliance/reconciliación documentado corre solo en path muerto/legacy. **Evidencia:** test de paridad legacy↔agentic + grep de callers del building block.

### Nivel 90 — "Garantías estructurales por construcción; la clase de bug es imposible, no solo ausente"
Eleva de "no tiene el bug" a "no puede tener el bug":
- C-90.1 `correctness`: la entidad cross-boundary del dominio tiene **un único tipo/contrato compartido** (no dos definiciones que se mantienen en sync manualmente). **Evidencia:** un solo símbolo importado por productor y consumidor + test que falla si divergen las keys.
- C-90.2 `data_integrity`: **toda** mutación del dominio pasa por RPC `SECURITY DEFINER + FOR UPDATE + bump version` o CAS con retry. Idempotency-Key **determinística por intent** (nunca `uuid4()`). **Evidencia:** grep 0 de read-modify-write en Python sobre tablas del dominio + grep 0 de `uuid4()` en keys de idempotencia.
- C-90.3 `resilience`: health refleja liveness real (503 si worker muerto); circuit breaker cableado en clientes outbound del hot-path. **Evidencia:** test que mata el worker y asserta 503; grep de breaker en wompi/whatsapp/aveonline clients.
- C-90.4 `maintainability`: logging JSON con correlation_id propagado cross-layer; métricas por turn (tokens/costo) pobladas. **Evidencia:** assert `correlation_id` presente en log de un turno e2e; `total_tokens > 0`.

### Nivel 95 — "Auditado adversarialmente; regresión imposible de pasar a CI"
El nivel que cierra el meta-patrón (el bug pasó CI porque el test mockeaba la forma rota):
- C-95.1: existe un **guardrail en `validate.sh --ci`** (lint AST o pact) que **falla** si la clase de bug del dominio reaparece. No basta con haber arreglado la instancia. **Evidencia:** el guardrail está en el ratchet y un commit que reintroduce el bug hace fallar CI (verificable con mutation test).
- C-95.2: ≥1 test de **race real contra Postgres efímero** para mutaciones concurrentes del dominio (donde aplique oversell/lost-update). **Evidencia:** test de integración con stock=1 + N reservas concurrentes.
- C-95.3: re-auditoría adversarial humana firma que no hay finding `medium+` abierto **y** que los tests no comparten el error del código (coherence pact verificado).

> **95 es el techo realista** para este repo y equipo (founder + agente). 100 implicaría observabilidad distribuida multi-réplica + chaos engineering, fuera de scope. Pedir 100 sería Goodhart.

---

## 2. Target y gap-closer por dominio (actual → target → gap-closer estructural)

Target = nivel realista dado el equipo y la dependencia arquitectónica (no "todo a 95"). El gap-closer es el cambio **estructural** que cierra la clase, anclado al finding-id del `per-domain.json`. Esfuerzo del audit: S/M/L.

| # | Dominio (`_key`) | Actual | Target | Dim que capea | Gap-closer estructural (finding-id → cambio) | Esf |
|---|---|---|---|---|---|---|
| 1 | Anti-hallucination (`anti-hallucination`) | 68 | **90** | correctness | **INV-01/02**: helper canónico único de shape de catálogo compartido por `get_tenant_catalog`+`_render_catalog_block`+`AddToCartTool`+invariant; test contra **output real** de `get_tenant_catalog`. **INV-03**: portar gates HARD (`summary-before-link`, `no-pii-pre-consent`) a `apply_invariants` agentic + test paridad. | S+M |
| 2 | Prompt & LLM (`prompt-llm`) | 68 | **85** | correctness | **PLLM-01**: mismo fix de contrato único (§1). **PLLM-02**: decidir+documentar router (integrar o borrar código muerto). **PLLM-04**: poblar `total_tokens` desde `usage_metadata`. | S+M |
| 3 | FSM (`fsm-state`) | 68 | **90** | correctness | **FSM-1/2**: literal `human_takeover` desde constante compartida + fixture corregido (test falla con el bug). **FSM-3**: pasar `order=`/`payment=` + **test de reachability por estado**. **FSM-5**: except estrecho → toolset conservador si `_resolved_state is None`, NO abrir todo. | S+M |
| 4 | Cart-as-SoT (`cart-sot`) | 68 | **88** | data_integrity | **CART-01**: merge preservador por campo (cierra crítico). **CART-03/06**: RPCs `cart_set_item_quantity`/`cart_remove_item` + shipping_meta atómico (`FOR UPDATE`+version). **CART-04**: filtrar cart por `conversation_id` (cierra cross-binding intra-tenant). | S+M+L |
| 5 | Inventory/Catalog (`inventory-catalog`) | 68 | **90** | security/data_integrity | **INV-02**: `p_tenant_id` en RPCs `consume/release/extend` (cierra IDOR). **INV-03**: decremento por UPDATE atómico (cierra oversell). **INV-01(inv)**: reusar `lib/stock_reservation.reserve()` (`out_reservation_id`). **INV-09**: test de race Postgres efímero. | M+L |
| 6 | Shipping (`shipping-aveonline`) | 68 | **82** | data_integrity/correctness | **SHIP-01/02**: propagar `cod_enabled` real + `declaredValueCop` del cart al quote. **SHIP-03 (BUG-D)**: re-confirmar destino cuando proviene de fallback `contact.address`. **SHIP-04**: billable weight en función única compartida. | S+M |
| 7 | Webhooks/Connector (`webhooks-connector`) | 68 | **88** | security_multitenant | **WH-01**: persistencia usa el `tenant_id` HMAC-verificado como autoridad + `UNIQUE(meta_waba_id)` (cierra crítico cross-tenant). **WH-02**: `webhook_event_check_or_register` como primer paso (dedup pre-side-effect). **WH-03**: cola durable pre-200. | M+L |
| 8 | Worker/queues (`worker-async`) | 68 | **85** | resilience/correctness | **W-01**: `import sys` (NameError latente). **W-02/06**: DLQ + cap `read_ct` en colas pgmq. **W-03**: claim atómico `sent_at IS NULL RETURNING` antes de enviar (cierra doble-envío). **W-05**: separar hot-path de crons. | S+M |
| 9 | Orchestrator core (`orchestration-hotpath`) | 72 | **88** | resilience/data_integrity | **ORCH-01**: `tenant_id` al select del sweep + except estrecho + test que falla con el bug. **ORCH-02**: `/health` → 503 si worker muerto + watchdog. **ORCH-03**: `outbound_intent (conversation_id, inbound_message_id)` UNIQUE pre-POST (cierra doble-envío). **ORCH-04/07**: fail-closed en flag agentic y opt-out. | S+M |
| 10 | Payments/Wompi (`payments-wompi`) | 72 | **90** | data_integrity/resilience | **WMP-1**: validar monto/moneda antes de `_confirm_order` (cierra crítico). **WMP-2**: `UNIQUE(tenant_id, wompi_txn_id)` + upsert. **WMP-3**: **cron de reconciliación que invoque `get_transaction_with_resilience`** (cierra P0 webhook-no-entregado). | S+M |
| 11 | Observability (`observability-resilience`) | 72 | **85** | resilience | **OBS-01**: auth + `tenant_id` obligatorio en `/agentic/metrics`. **OBS-02**: circuit breaker cableado en Wompi/WhatsApp/Aveonline. **OBS-03**: logging JSON + correlation_id. **OBS-04**: `/ready` con dependency check. | M+L |
| 12 | Multi-tenant/S2S auth (`multitenant-auth`) | 76 | **90** | security_multitenant | **MTI-02**: tests de integración dual-auth internal-secret (cierra punto ciego Clase B — el guardrail que faltaba). **MTI-01**: decidir+documentar estrategia RLS GUC (activar de verdad o corregir comentario `auth.py:17`). | M |
| 13 | Contacts/Habeas Data (`contacts-habeas`) | 78 | **90** | compliance | **HD-01**: anonimizar `document_type/number` en revocación POST. **HD-02**: escribir `consent_audit_log` en POST/PATCH (audit canónico consistente). **HD-03**: enrutar TODA mutación consent por `_compute_consent_update`. **HD-05**: métrica/alerta en fallo de audit insert. | S+M |
| 14 | Orders lifecycle (`orders-lifecycle`) | **62** | **85** | data_integrity | **ORD-03**: `rpc_create_order_with_items` transaccional (cierra órdenes huérfanas). **ORD-02**: `ALLOWED_TRANSITIONS` + CHECK/trigger DB. **ORD-01**: Idempotency-Key determinística `order-create:{conv}:{cart}`. **ORD-04**: `uniq_active_order_per_conv` parcial. | M+L |

**Promedio actual 70 → promedio target ≈ 87.5.** Ningún dominio target a 95: el 95 exige re-auditoría adversarial + mutation testing por dominio, que solo se justifica para Payments/Multi-tenant tras cerrar el resto. Los targets respetan el orden por nivel arquitectónico (data→security→compliance→inbox), no por número de finding.

---

## 3. Cómo se MIDE el score de forma repetible

Tres tiers de medición. **El objetivo: que ≥70% de los criterios sean máquina-verificables** y se integren al ratchet de `validate.sh --ci`, dejando la re-auditoría humana solo para lo semántico.

### Tier 1 — Automatizable HOY (extiende infraestructura ya probada, NO inventa)

| Criterio | Mecanismo | Cómo se integra al gate |
|---|---|---|
| C-60.2 filtro tenant | `scripts/audit_tenant_filter.py` (ya en CI) | ratchet `BASELINE_MAX=0` (ya enforced) |
| C-75.1 contrato productor↔consumidor (Clase A) | **Extender `tests/test_coherence_pact.py`** de Pydantic↔DB a **contratos de runtime**: keys de catálogo, literal FSM↔CHECK constraint, columnas de retorno de RPC. Patrón ya existe (subset-check contra fixture canónico). | nuevo test en suite; falla si las keys del productor no son superset de las leídas por el consumidor |
| C-75.2 except ancho fail-open | **Nuevo lint AST `scripts/audit_broad_except.py`** (mismo molde que `audit_tenant_filter.py`): detecta `except Exception` cuyo handler retorna default inseguro (`return None/False/''`) en hot-paths, o que captura sin re-raise un KeyError/NameError. Ratchet decreciente desde baseline medido (71 en dispatcher, 50 en worker). | ratchet `BASELINE_BROAD_EXCEPT` en `validate.sh --ci` |
| C-75.3 dual-auth test | `grep -rc 'X-Internal-Service-Secret' tests/` > 0 + test 2xx con header / 401 sin él | assert en suite (hoy = 0) |
| C-90.2 idempotencia determinística | grep `uuid4()` en construcción de Idempotency-Key = 0; grep read-modify-write Python sobre tablas financieras = 0 | lint AST extendido |
| C-90.3 health real | test que pone `_worker_status['running']=False` y asserta 503 | test unitario |
| C-90.4 observabilidad | assert `total_tokens > 0` y `correlation_id` en log de turno e2e | test e2e |
| C-95.1 guardrail anti-regresión | **mutation check**: un commit que reintroduce el bug debe hacer fallar `validate.sh --ci`. Verificable inyectando el bug en un branch desechable. | manual por dominio al certificar |

> Punto clave anti-Goodhart: el coherence pact y los lint AST miden **la propiedad estructural** (las keys coinciden, no hay fail-open), no un número de tests verdes. Un test que mockea la forma rota **no** sube estos gates porque el pact valida contra el output real del productor.

### Tier 2 — Semi-automatizable (medición en runtime, requiere infra de logs)
- Tasa de `MUST_LIST_CATALOG_FIRST` por tenant (confirma blast-radius INV-01) — métrica estructurada, no test.
- `% turnos simples` para decidir router LLM (PLLM-02) — requiere instrumentar `usage_metadata`.
- Estos alimentan el score pero se miden con logs locales (`feedback_local_logs.md`), no en CI.

### Tier 3 — Requiere re-auditoría humana adversarial (no automatizable)
- C-95.3: que los tests **no comparten el error del código** (el meta-patrón que dejó pasar 6 Clase A). Un humano lee el test y verifica que el fixture refleja producción. Automatizable *parcialmente* vía coherence pact, pero el juicio "este mock es realista" es semántico.
- Findings en zona gris ADR-0024 (invariants regex sobre prosa) — INV-07: no se reescriben, se instrumenta FP/FN y se muestrea manualmente.
- Decisiones arquitectónicas (RLS GUC activar vs documentar — MTI-01) — requieren firma, no test.

### Protocolo de re-scoring (repetible)
1. `bash scripts/validate.sh --ci` → produce el vector de gates Tier 1 (pass/fail por criterio).
2. Por dominio: `score = nivel más alto cuyos criterios acumulados pasan`, capeado por la regla anti-Goodhart (`critical` abierto ≤68, `high/security|compliance` ≤75).
3. Tier 2: anexar métricas de runtime como evidencia (no modifican el gate, contextualizan).
4. Tier 3: re-auditoría adversarial firma el salto a 90→95 (no se puede auto-otorgar).
5. El delta de score entre dos commits es **falsable**: si alguien afirma "subí Orders de 62 a 85", debe exhibir el `rpc_create_order_with_items` mergeado + el test transaccional verde + el `uniq_active_order_per_conv` en migración + el guardrail que falla si se revierte. Sin esa evidencia, la afirmación es falsa por definición.

---

## Notas de cierre (riesgo / decisión)

**DECISIÓN FINAL.** El score deja de ser opinión cuando: (a) cada nivel = conjunto de criterios binarios; (b) cada criterio tiene fuente de evidencia (lint/pact/test/firma); (c) el promedio se reemplaza por `min` ponderado capeado por severidad, de modo que cerrar lows no compense un crítico abierto.

**RIESGO Goodhart mitigado por diseño.** El score no se puede subir sin cerrar el finding: los gates miden propiedades estructurales (contrato único, atomicidad, fail-closed), no "tests verdes". Un test que mockea la forma rota no mueve la aguja porque el coherence pact valida contra el output real del productor — exactamente el meta-patrón que dejó pasar las 6 Clase A.

**INTERVENCION HUMANA REQUERIDA.** El salto 90→95 por dominio NO es automatizable: requiere re-auditoría adversarial firmada (Tier 3). Las migraciones de los gap-closers que tocan DB compartida prod (`uniq_active_order_per_conv`, `UNIQUE(tenant_id, wompi_txn_id)`, `p_tenant_id` en RPCs, `UNIQUE(tenant_id, meta_message_id)`) requieren **autorización explícita del founder** antes de aplicar.

**Construir primero (mayor ROI de medición):** `audit_broad_except.py` (Clase C, 9 dominios) y la extensión de `test_coherence_pact.py` a contratos de runtime (Clase A, 6 dominios). Esos dos guardrails convierten las dos clases más extendidas en **regresiones imposibles de mergear**, que es la diferencia operativa entre "score 70 subjetivo" y "score falsable".

Archivos clave referenciados (absolutos):
- `/home/ansible/workspaces/konvi-platform/scripts/audit_tenant_filter.py` (molde del lint AST a replicar)
- `/home/ansible/workspaces/konvi-platform/tests/test_coherence_pact.py` (molde del pact a extender a runtime)
- `/home/ansible/workspaces/konvi-platform/scripts/validate.sh` (ratchet `BASELINE_MAX`/`COVERAGE_MIN`/`BASELINE_RUFF_ERRORS` donde se enganchan los nuevos gates)
- `/home/ansible/workspaces/konvi-platform/docs/research/inbox-audit-2026-06-25-per-domain.json` (fuente de finding-ids por dominio)
- `/home/ansible/workspaces/konvi-platform/docs/research/inbox-audit-2026-06-25-target-arch.md` (gap-closers estructurales por subsistema)