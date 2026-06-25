Confirmed: `consume/release/extend` operate on `p_reservation_id` only, no `p_tenant_id` scoping → IDOR open (requires a prod migration to fix = founder gate). I now have a fully grounded picture. Writing the roadmap.

# Roadmap de Remediación del Inbox — Ataque por Clase Sistémica

> Estado base: suite 2967, 8 commits ya mergeados esta sesión (INV-01 catálogo `variants` ✓, FSM `human_takeover` ✓, sweep `tenant_id` ✓, `/health` 503 ✓, `set_shipping_meta` merge ✓, Wompi monto/moneda ✓, dual-auth tests ✓, CART-01 ✓, `sys` import ✓). Verificado en árbol: **Ola 0 = Clase A activa = CERRADA**. Lo que sigue ataca las clases C/D/E/F/G y los residuos B, que son los de **mayor apalancamiento** (un fix de clase + su fitness function sube varios dominios).

## Principio rector

No se persiguen scores (anti-Goodhart). Se ataca la **clase** porque un fix de clase cierra N findings a la vez y, sobre todo, su **fitness function** (lint/pact/test CI) impide que la clase **reaparezca** — que es la deuda real, no el finding puntual. El score sube como *consecuencia*, no como objetivo.

## Compuertas (gates) — leyenda

- **[FOUNDER-MIGRATION]**: toca `supabase/migrations/` → DB compartida prod → **autorización EXPLÍCITA founder** antes de aplicar (memoria `feedback_supabase_migrations`: el ledger tiene drift).
- **[HOT-PATH]**: toca ingest/outbound/dispatch → **sesión dedicada** + trace de logs locales (`/home/ansible/konvi-local/logs/`) antes de declarar cerrado (`feedback_local_logs`, `feedback_no_static_uat`).
- **[CODE-ONLY]**: sin migración ni hot-path → mergeable con `validate.sh --ci` verde.

---

## Tabla de olas

| Ola | Clase atacada | Qué se hace (fix + fitness function) | Domains que sube | Esfuerzo | Riesgo | Gate | Dep |
|---|---|---|---|---|---|---|---|
| **1. Quick-wins durables** | F, B (residuo), C-trivial | Cablear reconciliación Wompi vía cron (WMP-1) · `/agentic/metrics` auth + `tenant_id` obligatorio · `patch_order` ALLOWED_TRANSITIONS (ORD-01) · Idempotency-Key determinístico bot (ORD-02, SHIP-G) | Payments 72, Observability 72, Orders 62, Shipping 68 | **S** | Bajo | CODE-ONLY (cron Render = config, no migración) | Ola 0 |
| **2. Fitness anti-Clase-A** | A (prevención) | **Extender `audit_tenant_filter.py` con un 2º linter AST**: catálogo shape + literales de estado divergentes → ratchet. **Coherence pact** ampliado: RPC return-keys ↔ callers (`out_reservation_id`). Tests contra **output real** del productor. | Todos (no sube score, **congela** la clase ya cerrada) | M | Bajo | CODE-ONLY | Ola 0 |
| **3. Seguridad multi-tenant** | IDOR + dual-auth residuo | RPCs `consume/release/extend` con `p_tenant_id` + callers (INV-IDOR) · persistencia connector usa tenant HMAC-verificado + `UNIQUE(meta_waba_id)` (WH-01) · decisión RLS GUC documentada (MTI) | Inventory 68, Webhooks 68, Multi-tenant 76 | M | **Alto** (cross-tenant blast-radius) | **[FOUNDER-MIGRATION]** (RPC + UNIQUE) | Ola 2 (pact cubre callers) |
| **4. Compliance legal (paridad agentic)** | E (código muerto compliance) | Portar gates HARD `summary-before-link` + `no-pii-pre-consent` al set `apply_invariants` agentic + **test de paridad legacy↔agentic** (INV-02) · audit canónico consent en POST/PATCH (HD-01) | Anti-hallu 68, Habeas Data 78, Prompt 68 | M | Medio (riesgo regulatorio si se omite) | CODE-ONLY | Ola 2 |
| **5. Integridad transaccional** | D (read-modify-write) | RPC `rpc_create_order_with_items` + `uniq_active_order_per_conv` (ORD-03) · RPCs `cart_set_item_quantity`/`cart_remove_item` atómicos (CART-02/03) · decremento stock atómico (oversell INV-02) | Orders 62, Cart 68, Inventory 68 | **L** | **Alto** (oversell, doble-cobro, órdenes huérfanas) | **[FOUNDER-MIGRATION]** + **[HOT-PATH]** | Ola 3 (RPC tenant-scoped) |
| **6. Durabilidad de ingestión** | F, G (idempotencia connector) | Cola durable pre-200 en connector (WH-02) · dedup `webhook_event_check_or_register` como 1er paso (WH-03) · DLQ + cap reintentos pgmq (W-01) · separar hot-path de crons | Webhooks 68, Worker 68, Orchestrator 72 | **L** | Medio (pérdida de mensajes bajo crash) | **[FOUNDER-MIGRATION]** + **[HOT-PATH]** | Ola 5 |
| **7. Observabilidad que acciona** | C, F | Estrechar `except` ancho (KeyError/NameError/TypeError nunca tragados) + métrica por degradación · logging JSON + correlation_id · circuit breaker cableado en Wompi/WhatsApp/Aveonline · tokens/costo por turn | Observability 72, Orchestrator 72, transversal | M | Bajo | **[HOT-PATH]** (toca dispatcher/worker) | Olas 3-6 |

---

## Secuencia y razón de orden (data → security → compliance → inbox → ui)

```
Ola 0 (HECHA) ─ Clase A activa cerrada
   │
Ola 1 ─ QUICK-WINS durables ──────────── [CODE-ONLY] paralelizable con Ola 2
   │   (cablear código muerto barato; cero migración; alto ROI inmediato)
   │
Ola 2 ─ FITNESS anti-Clase-A ─────────── [CODE-ONLY] habilitador de todas las siguientes
   │   (sin esto, las olas que tocan contratos pueden RE-introducir Clase A sin que CI lo note)
   │
   ├──► Ola 3 ─ SEGURIDAD multi-tenant ── [FOUNDER-MIGRATION]  ← nivel "security"
   │       (IDOR = mayor blast-radius; va antes de tocar inbox)
   │
   ├──► Ola 4 ─ COMPLIANCE agentic ────── [CODE-ONLY]          ← nivel "compliance"
   │       (paralela a Ola 3: no comparte archivos)
   │
   └──► Ola 5 ─ INTEGRIDAD transaccional ─ [FOUNDER-MIGRATION]+[HOT-PATH]  ← nivel "inbox"
           │   (depende de Ola 3: los RPC nuevos nacen tenant-scoped)
           │
           └──► Ola 6 ─ DURABILIDAD ingestión ─ [FOUNDER-MIGRATION]+[HOT-PATH]
                   │
                   └──► Ola 7 ─ OBSERVABILIDAD ─ [HOT-PATH]
                           (cierra el ciclo: la señal que habría detectado todo lo anterior)
```

**Por qué Ola 2 antes que 3-7:** las olas estructurales tocan precisamente los contratos donde nació la Clase A (catálogo, RPC returns, estado). Sin la fitness function en CI primero, un refactor de RPC puede divergir productor↔consumidor otra vez y **pasar verde** (el patrón que enmascaró los 6 originales). La fitness function es la inversión que hace el resto **seguro de ejecutar con founder+1 agente**.

**Por qué Ola 3 (security) antes que 5/6 (inbox):** respeta el orden por nivel arquitectónico del founder. Además, los RPC transaccionales de Ola 5 deben nacer ya con `p_tenant_id` — fixear IDOR después de crearlos sería refactor doble.

---

## Clasificación por naturaleza (founder constraint: quality-first)

**Quick-wins durables** (cierran finding + son irreversiblemente buenos, sin migración): Ola 1 completa, Ola 2 completa. **Empezar aquí.** Máximo ROI, mínimo riesgo, no consumen autorización founder.

**Inversiones estructurales** (cierran clases enteras, multi-día, founder debe presupuestar calidad sobre tiempo): Olas 5, 6, 7. Son las que requieren `[HOT-PATH]` con sesión dedicada y trace de logs.

**Gated-por-founder** (no avanzan sin autorización explícita de migración a prod): Olas 3, 5, 6. **Agrupar las migraciones de estas tres en lotes** para minimizar el número de ventanas de autorización/aplicación contra la DB compartida con drift.

---

## Definición de TERMINADO por ola

| Ola | DoD (todos obligatorios) |
|---|---|
| **1** | Cron de reconciliación corre y reconcilia ≥1 orden PENDING en log local · `/agentic/metrics` devuelve 401/403 sin secret · `patch_order` retorna 409 en `delivered→pending` (test) · `validate.sh --ci` verde |
| **2** | Linter AST falla con BASELINE_MAX=0 si se introduce divergencia de key de catálogo o literal de estado · coherence pact cubre return-keys de RPC usados por callers · `validate.sh --ci` ejecuta ambos · **prueba negativa**: re-introducir el bug Clase A original hace fallar CI |
| **3** | RPCs `consume/release/extend` rechazan `reservation_id` de otro tenant (test cross-tenant) · persistencia descarta + alerta si tenant HMAC ≠ tenant resuelto · `audit_tenant_filter.py` sigue en 0 gaps · decisión RLS escrita en ADR (no comentario engañoso) · **[FOUNDER]** migración aplicada y verificada en prod |
| **4** | Path agentic LIVE ejecuta ambos gates HARD · **test de paridad** legacy↔agentic verde (mismo input → misma decisión BLOCK/REWRITE) · POST/PATCH consent escriben `consent_audit_log` (test) |
| **5** | Crear orden = 1 transacción (order+items+stock) o rollback total · oversell imposible bajo test de race contra Postgres efímero · `uniq_active_order_per_conv` previene doble-orden concurrente · **trace de logs local** de una venta E2E completa sin regresión · **[FOUNDER]** migración aplicada |
| **6** | Mensaje persistido durablemente ANTES del 200 a Meta · reentrega no reabre conversación cerrada (dedup pre-side-effect) · poison-message va a DLQ tras N intentos · hot-path no se degrada con cron lento (medido en log) · **[FOUNDER]** migración aplicada |
| **7** | Ningún `except Exception` traga KeyError/NameError/TypeError en hot-path (lint o review) · cada degradación emite métrica/Sentry · logs con correlation_id rastreables cross-layer · circuit breaker abre ante fallo sostenido de Wompi/WhatsApp/Aveonline · `total_tokens` > 0 por turn |

---

## Notas de riesgo / decisión

- **Ola 2 es la de mayor ROI de calidad sostenida** y la única verdaderamente novedosa: extiende infraestructura ya probada (`audit_tenant_filter.py` ratchet + `test_coherence_pact.py`) en vez de inventar. Es la que convierte "arreglamos los 6 Clase A" en "la Clase A no puede reaparecer".
- **Olas 3/5/6 comparten gate de migración** → recomiendo presentar al founder UN plan de migraciones consolidado por lote (no goteo), reduciendo ventanas de autorización contra la DB con drift.
- **WMP-1 (reconciliación) está en Ola 1 pese a ser P0-pagos** porque el código ya existe y testeado (`wompi_client.py:730`); solo falta el caller cron — es quick-win, no inversión estructural. No esperar a Ola 5 para esto.
- **Meta Flows queda FUERA del roadmap de remediación** (decisión del anexo meta-flows: diferir; entrar por `interactive.cta_url` solo tras Ola 4, ya que un botón CTA amplifica la violación `summary-before-link` que la Ola 4 cierra). Es trabajo de nivel "ui", posterior.
- **VALIDAR en cada ola con `[HOT-PATH]`**: UAT dinámica online turn-a-turn contra DB real, nunca scenarios estáticos (`feedback_analytical_uat`, `feedback_no_static_uat`).

Archivos de infraestructura de prevención a extender (Ola 2): `/home/ansible/workspaces/konvi-platform/scripts/audit_tenant_filter.py`, `/home/ansible/workspaces/konvi-platform/tests/test_coherence_pact.py`, `/home/ansible/workspaces/konvi-platform/scripts/validate.sh` (gate `--ci`).