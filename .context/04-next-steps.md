# Próximos Pasos

> **Verificado contra repo**: 2026-08-02 @ `5fdad396` (develop).

**El backlog de verdad es [`docs/PLAN.md`](../docs/PLAN.md)** — checklist go-live, backlog
P0/P1/P2/P3, roadmap post-go-live y rituales operativos, alimentado por la
[auditoría consolidada 2026-08-02](../.audit/findings/2026-08-02-consolidated-audit.md)
(IDs B/A/M con evidencia `archivo:línea`). Este archivo solo conserva (1) lo que PLAN.md no
cubre o necesita contexto extra y (2) el registro de lo verificado-resuelto en la limpieza
de hoy. **No duplicar aquí ítems que ya están en PLAN.md.**

---

## Verificado-resuelto 2026-08-02 (antes listado aquí como pendiente)

| Ítem | Evidencia |
|---|---|
| Gate gemini-3.x + Next 15 (incl. sus pasos IH) | Desplegado: producción a la par de develop; `GEMINI_MODEL=gemini-3.1-flash-lite` en `render.yaml` |
| P0 Sem 6 — re-uso framework común para HSM | Obsoleto: HSM templates ya implementado end-to-end |
| F2 WhatsApp HSM templates (F2.1–F2.6) | Implementado: schema `whatsapp_templates`, webhook `message_template_status_update`, `send_template`, UI en `/dashboard/integrations/whatsapp?tab=plantillas`. Solo queda F2.7 (abajo) |
| Rev. 74 cutover V2 (Fases D/E) | Plan **cancelado** en rev. 75: V2 eliminado; path único = orchestrator agentic |
| Model B Phase 7 (founder) | Connector Model B live en prod; WhatsApp funciona en ambos tenants |
| A6.2.7 aislamiento multi-tenant | 0 gaps en 248 archivos, ratchet CI (`scripts/audit_tenant_filter.py`) |
| A7 RBAC ai_agents / marketplace | Cerrado (owner-only en server actions) |
| ADR-0003 follow-ups F1, F4, F5, F6, F7 | Implementados en código: SAR printable (`data_subject_request.py:407`), UI retención, reporte SIC (`sic_report.py`), detector rectificación, click-wrap legal (`settings/legal`). Quedan solo F2/F3 → PLAN P2 |
| G-7 / G-8 legal | PRs #195/#197 mergeados |
| Comprobante ADR-0040 | En prod (#180-#186), `/dashboard/receipts` |
| M3 AI Agents router | Resuelto |
| Migraciones bloques 2026-04 "pendientes de aplicar" | Todas aplicadas: ledger 251 repo = prod, cero drift |
| Envia Fase 2 (labels/pickup/webhooks/DANE dinámico) | Muerto: Envia eliminado del runtime en rev. 109 |

---

## Lo que PLAN.md no cubre (o necesita contexto extra)

### Track 5 M2 — decisiones founder TOMADAS (2026-08-25, 4/4 recomendadas)

Las 4 preguntas del diseño del contrato ([`domain-services-contract.md`](../docs/architecture/domain-services-contract.md) §8)
quedaron resueltas: **(1)** packaging `packages/shared-py/` editable en build · **(2)** cancelación
desde consola con pipeline legal completo (void Wompi + cancel guía + audit) tras MFA AAL2 ·
**(3)** reason de reclamos = vocabulario cerrado + `reason_detail` libre opcional · **(4)** lecturas
consola → REST dominio a dominio (pilotos primero). M2 en ejecución: M2.0 (paquete + extracción
cupones) → M2.1-M2.4 (pilotos pedidos + reclamos) con la barra de certificación vigente.

### Track 5 — estado de ejecución al 2026-08-25 (M2.0/M2.1/M2.2/M2.3 ✅ — ver PLAN.md §E)

Cerrados y certificados (suite 4776 + dbharness 316 + certify_stg 18/18 + validate --ci 25/25 + CI 5/5
+ harness B-3 money_full_flow/s11 verdes + live STG): **M2.0** (paquete `konvi_domain` + cupones como
única fuente + wiring Render/CI/nightly + `make -C .local deps`) · **M2.1** (`konvi_domain.orders`:
create/get/list/list_by_contact + `GET /api/v1/orders/` nuevo + consola orders sobre REST + FSM como
alias único + `ORDERS_CONTRACT` 8 ops/4 implementadas) · **M2.2** (`konvi_domain.orders.cancellation`
con puertos inyectados + consola cancela vía PATCH con pipeline legal completo + paridad de outcome
bot↔paquete ×11 + fix enum `order_cancellation_actor`: actor consola = `operator`) · **M2.3**
(`konvi_domain.orders.payments` — política reuso/TTL del payment link colapsada (mata el espejo
router↔bot M1 §3.3): TTL único fail-safe + reuso exacto + round-no-int + mínimo $1.500 · puertos
`PaymentLinkPorts` con lazy import en call time · `DomainError.http_status` opcional (el 503 de
"Wompi no configurada" no cabía en UPSTREAM→500) · router = adaptador puro · shim
`integrations/wompi_client` re-exporta el TTL · paridad de política bot↔paquete alarmada
(`test_payment_link_policy_parity.py`) · verificación live STG del reuso vía REST: mismo
checkout_url, 1 fila payments, orden pending_payment).

### M2.3 ✅ CERRADO (2026-08-25) — brief ejecutado

El brief detallado que vivía aquí quedó ejecutado tal cual (constraints 1-9 verificados contra el
código). Único ajuste de alcance durante la ejecución: la factory de mocks compartida se movió a
`tests/helpers/supabase_mocks.py` (de `test_payment_link_reuse.py`) — ver la lección xdist nueva
abajo. Bitácora completa: PLAN.md §E (2026-08-25, M2.3).

> El prompt de continuación (durable — vale para cualquier sesión del plan) vive en
> `.context/handoff-prompt.md` (apunta de vuelta a estos briefs).

### Lecciones de entorno/proceso de esta sesión (aplican a TODO el trabajo restante)

- **`validate --ci` con el web dev server parado o asentado**: `next dev` reescribe
  `apps/web/.next/dev/types/validator.ts` (incluido por tsconfig, default Next 16) y puede quedar
  entrecortado mid-write tras un restart → tsc falla con TS1128 fantasma. Protocolo: `make -C .local
  stop-web` + `rm -rf apps/web/.next/dev` antes de validate; CI es inmune (clone fresco sin `.next`).
- **xdist**: parámetros de `subTest` deben ser primitivos (execnet no serializa `PosixPath` → usar
  `str()`). La suite corre serial localmente pero xdist en validate/CI — un test puede pasar serial y
  fallar en xdist.
- **xdist / colisión `integrations.*` (M2.3)**: el paquete `integrations` existe en `services/api`
  Y `services/ai-orchestrator` → compite por el MISMO slot de `sys.modules`. Varios test files se
  defienden con `_purge_foreign_integrations(...)` a nivel módulo (colección), que BORRA la copia
  "ajena" — pero eso HUERFANA los bindings ya hechos por otros módulos (patch.object parchea el
  objeto huérfano y los lazy imports re-importan la otra copia). Regla: **las factories/mocks
  compartidos entre tests viven en `tests/helpers/` (módulos SIN side effects de colección), no en
  test modules con `sys.path.insert`** — un import test→test puede adelantar la colección de ese
  módulo a antes de una purga y romper la suite entera bajo xdist (4 tests de
  `test_payment_link_reuse.py` caían solo en la distribución xdist, verdes en serial).
- **`grep -c ... || echo 0` duplica el conteo** cuando no hay matches (imprime "0" Y sale 1) → usar
  `|| true` (quirk heredado en validate.sh §ruff; ya corregido en el check del paquete).
- **Enums DB**: valores de actor/estado que vienen de enums Postgres (`order_cancellation_actor`, etc.)
  — verificarlos contra la migración, y OJO con try/except que tragan errores de escritura (el bug
  del enum daba 200 sin escribir). La certificación live STG es la que los destapa.
- **Stack local**: si Kong/auth caen (`podman ps`), `make -C .local db` auto-recupera; si los 4
  servicios caen, `make -C .local up` (con preflight DB). Tras cambios de código, REINICIAR el
  servicio afectado (`make -C .local stop-api start-api`) antes de certificar live — el proceso
  corriendo tiene el código viejo.
- **Paquete `konvi_domain`**: `make -C .local deps` tras clonar/actualizar (editable, user site);
  el `_check` del Makefile lo exige. Render: buildCommand `pip install -e ../../packages/shared-py`
  (pip resuelve `-e` relativo al CWD, NO al requirements.txt — verificado empíricamente 2026-08-25).

### M2.4 — brief de implementación (ClaimsService) — LEER ANTES DE ESCRIBIR

> Derivado y verificado contra código vivo 2026-08-25 (sesión M2.3). Diseño: contrato §5
> (`docs/architecture/domain-services-contract.md`) + drift medido M1 §3.8. Decisiones founder:
> #3 (reason cerrado + `reason_detail` libre opcional) y #4 (lecturas consola → REST).

**Scope:** 7 operaciones del piloto reclamos → nuevo subpaquete `konvi_domain/claims/`
(espejo de `orders/`): UN writer create (reason cerrado + reason_detail + dedup + titularidad
por actor + unión de eventos), get/list/list_by_contact, transition (FSM formalizada),
register_reversion + register_reversion_movement (delegan RPCs SQL existentes — R2). El bot
NO se toca (sus writers congelados se adoptan en B-2/M3); la duplicación queda con alarma de
paridad. Consola migra su LISTADO a REST (decisión #4 — las mutaciones YA van por REST vía
`claims/actions.ts`).

**Archivos a crear/tocar:**
- CREAR migración `supabase/migrations/20260825HHMMSS_claims_reason_detail.sql`:
  `ALTER TABLE public.claims ADD COLUMN IF NOT EXISTS reason_detail TEXT;` (nullable, sin
  backfill). **PROTOCOLO OBLIGATORIO (reglas vigentes):** backup secretos ANTES
  (`scratch/track9_backup_secrets.py` — leer `decrypted_secret`, NO `secret`) → aplicar/replay →
  `bash scripts/schema_drift_check.sh --update` (regenera baseline — lección CI 2026-08-03) →
  restaurar STG (`track9_restore_stg.sh` + `track9_restore_stg.py`) → destruir el backup →
  dbharness. Ledger pasa 268→269 repo (queda pendiente de PRD como las 6 anteriores).
- CREAR `packages/shared-py/src/konvi_domain/claims/__init__.py` + `models.py` +
  `service.py` + `reversion.py` + `contract.py` (`CLAIMS_CONTRACT`).
- `models.py`: **enums canónicos únicos** — `CLAIM_STATUSES`/`CLAIM_TERMINAL_STATUSES`/
  `CLAIM_REOPENABLE_STATUSES` (hoy `claims.py:47,51,58` del router; el set del bot
  `agentic/tools/claims.py:52` queda defendido por alarma de paridad) + `CLAIM_REASONS`
  (`claims.py:66`, espejo de REASON_MAP de la UI `claims-manager.tsx:61-67`) +
  `CAUSALES_REVERSION`/`VIAS_REVERSION` (`claims.py:460-470`) + DTOs
  (`ClaimCreateInput/ClaimCreateResult(created: bool)`, `ClaimTransitionInput`, `ClaimPage`).
- `service.py`: `create_claim` (UN writer) · `get_claim` · `list_claims` (con embeds) ·
  `list_claims_by_contact` (NUEVO — hueco M1 §3.8; service-only, sin endpoint REST, igual que
  `orders.list_by_contact` en M2.1) · `transition_claim` (absorbe patch Y /resolve — ver
  constraint 4) · `ClaimPorts` (puertos de notificación — ver constraint 3).
- `reversion.py`: `register_reversion` / `register_reversion_movement` / `read_reversion` —
  wrappers delgados sobre `rpc_registrar_reversion` / `rpc_registrar_movimiento_reversion`
  (params EXACTOS del router `claims.py:551-565,611-616`) + mapeo `motivo` → DomainError con
  `http_status` (la tabla `_MOTIVO_HTTP` `claims.py:475-493` migra al servicio).
- `services/api/routers/claims.py`: los 8 endpoints quedan adaptadores (deps JWT + RBAC +
  audit decorator + rate-limit INTACTOS — constraint 1) que delegan al servicio. `VALID_STATUSES`
  etc. quedan como alias del paquete (patrón FSM de M2.1).
- CREAR `services/api/lib/claim_ports.py`: `build_api_claim_ports(supabase)` — Telegram operador
  (`lib/operator_alerts.notify_operator_telegram`, firma verificada `:76`) + WhatsApp cliente F-5
  (la lógica de `_notify_client_claim_outcome` se MUEVE aquí — ver constraint 3).
- Consola: `claims/page.tsx` migra el listado a REST (patrón M2.1 de orders/page.tsx:91-93 —
  `fetch(CORE_API_URL…, Bearer, cache:'no-store')`, timeout 15s) — requiere el endpoint con
  embeds (constraint 2). `claims/actions.ts` pasa `reason_detail` cuando el dialog lo capture
  (campo opcional en el dialog "Nuevo Reclamo" — textarea libre, Kaiu DS).
- `tests/test_domain_contract_structural.py`: `CONTRACTS += [CLAIMS_CONTRACT]` y
  `SERVICE_MODULES["claims"] = ("konvi_domain.claims.service", "konvi_domain.claims.reversion")`.
- CREAR `tests/test_konvi_domain_claims.py` (unit) + `tests/test_claims_policy_parity.py`
  (paridad bot↔paquete — ver abajo).

**Constraints de compatibilidad DESCUBIERTAS (no re-derivar):**
1. **RBAC/audit asimétricos — NO cambian**: create es owner/manager/**operator** SIN
   `require_write_role` (G-4, `claims.py:209-216`; el test `test_claim_create_rbac.py` lo
   defiende); patch/resolve/reversion SÍ llevan `require_write_role` (owner/manager). Auth =
   JWT-only (`get_current_tenant` — NO dual-auth; el bot escribe directo a DB y sigue así
   congelado). Los `@audit_log` (created/updated/status_changed + payment_reversion created/
   updated) se quedan en el router.
2. **`GET /claims/` no tiene consumidores hoy** (verificado: consola lee directo; actions.ts solo
   POST/PATCH/reversion) → seguro extenderlo con embeds PostgREST
   `orders(id, total_amount, payment_method), contacts(id, name, phone)` (lo que page.tsx:32-41
   necesita) + `reason_detail`. Filtros heredados: status (validado 422), customer_id, order_id,
   limit ≤200, order created_at desc.
3. **F-5 es puerto, no servicio directo**: `test_claim_customer_notification.py` llama
   `claims._notify_client_claim_outcome` DIRECTO y pachea
   `routers.wompi_webhook._enqueue_whatsapp_outbound` → la lógica se mueve a
   `lib/claim_ports.py` (misma lógica: solo resolved/rejected + order.conversation_id + textos
   exactos `:293-304` + lazy import + best-effort) y el test se ACTUALIZA deliberadamente al
   puerto. El servicio dispara el puerto SOLO en transición real a outcome (reglas `:344-348,438-441`).
4. **FSM exacta heredada** (`_refund_ledger_fields` `:124-159` + guards `:344-389` +
   `/resolve` `:415-441`): transición a `refunded` exige `refunded_amount` (422) y sella
   `refunded_at`; `refunded` es FINAL (409 por patch Y por /resolve); corrección de monto sin
   cambio de status solo si refunded con monto NULL (422/409); reopen terminal→no-terminal solo
   owner (403) y solo desde rejected/cancelled (409); mismo-status no-op permitido (notify se
   salta); "Sin campos a actualizar" → 422. `test_claim_refund_capture.py` (8 tests vía
   TestClient con fake que devuelve `store` para CUALQUIER tabla) exige la MISMA secuencia:
   fetch (select id,status,refunded_amount,refunded_at + maybe_single) → update → res.data[0].
5. **Dedup del UN writer (gana la consola)**: la query del bot (`agentic/tools/claims.py:163-176`)
   — claims abiertos (`in_ status [open, investigating]`) por (tenant_id, order_id, customer_id)
   limit 1; lookup defensivo (falla → None, se crea). Si existe → NO insertar: retornar el
   existente. Contrato HTTP nuevo (decisión de diseño documentada): el servicio retorna
   `ClaimCreateResult(claim, created=False)` → el adaptador responde **200 + body del claim
   existente + `"deduplicated": true`** (201 si creó — patrón adopt-winner de orders.create).
   La consola (actions.ts) acepta ambos (toast "Reclamo registrado" / ya existía).
6. **Titularidad por actor**: `customer` (bot, M3) exige `order.contact_id == actor.contact_id`
   (query scoped tenant+contact, `claims.py:133-141` del tool); staff consola solo tenant
   (`_ensure_order_belongs_to_tenant` `:162-173` del router — 404 "Pedido no encontrado para este
   tenant"). `customer_id` del claim = body.customer_id o order.contact_id (heredado).
7. **Unión de eventos en create** (§5.1): `audit_log` (decorator, router) + `messages.claim_audit`
   (servicio, directo — payload del bot `:232-248`) + Telegram operador (puerto). OJO:
   `messages.conversation_id` es **NOT NULL** (migración 20260406181237:14) → el claim_audit del
   canal consola usa el `conversation_id` de la ORDEN si existe; si no hay (pedido MeLi/manual),
   se OMITE el mensaje (queda el audit_log) — documentar en el servicio. El texto Telegram del
   operador replica el del bot (`:260-266`: "Nuevo reclamo #ticket\nPedido: …\nMotivo: …" +
   monto opcional).
8. **Reason cerrado + detail**: el servicio valida `reason ∈ CLAIM_REASONS` (422 con el mensaje
   heredado `:101-106`) y persiste `reason_detail` (trim, max 500 — mismo límite que el free-text
   del bot) solo si viene. El bot congelado sigue escribiendo free-text en `reason` (sin CHECK en
   DB — deliberado `:60-66`); el enum del paquete es la referencia que la paridad defiende.
9. **Reversión = delegación RPC**: NO reimplementar (R2). `_leer_reversion` (`:624-639`) → 404
   "Este reclamo no tiene una solicitud de reversión radicada". Causal inválida → 422 con el
   mensaje que enumera las 5 (`:544-549`); vía inválida → 422 (`:604-608`); motivo de la RPC →
   `_MOTIVO_HTTP` (404/409/422) — usar `DomainError.http_status` (M2.3) para el mapeo.
   `test_claim_reversion_api.py` (13 tests) aserta params RPC exactos y traducción de motivos.
10. **Ticket number**: lo computa el trigger DB (`set_claim_ticket_number`, 20260417000003) —
    el servicio NO lo calcula; lo lee del insert response (`res.data[0]`).

**Paridad con el espejo del bot (`tests/test_claims_policy_parity.py`):**
- **Alarma de enums**: `_VALID_STATUSES` del bot == `CLAIM_STATUSES` del paquete (frozenset).
  Drift vivo conocido (NO se arregla aquí — es deuda del bot para M3): el `status_human` del tool
  (`:358-364`) usa el set extinto {in_progress, closed} — registrarlo como comentario del test.
- **create**: mismo estado staged (fake `_Sb` con eq/in/limit — extenderlo con `in_` ya lo tiene)
  → bot `CreateClaimTool.execute` vs paquete `create_claim(actor=customer)`: misma decisión de
  dedup (existente → sin insert, mismo claim devuelto), mismas claves del insert compartidas
  (tenant_id/order_id/customer_id/status=open/requested_amount), claim_audit insertado en ambos,
  notificación operador disparada en ambos (bot: `notify_escalation_async` severity=info; paquete:
  puerto). La DIFERENCIA deliberada se aserta explícita: bot escribe free-text en `reason`;
  paquete escribe `reason` cerrado + `reason_detail`.
- **get**: mismo claim staged → bot `GetClaimStatusTool` por ticket (scoped customer) == paquete
  `get_claim`/by-ticket con actor customer (mismas filas visibles; customer ajeno → no encuentra).

**Certificación M2.4 (misma barra M2.1-M2.3 + protocolo de migración):** tests focales → suite
completa xdist → dbharness 316 (tras replay + restore track9 + baseline regenerado) → harness B-3
`s19_reclamo` (el bot crea reclamos — su path NO cambia, certifica que sigue verde) +
`money_full_flow` → live STG (crear reclamo vía REST con reason_detail, dedup 200 sin duplicar,
transition a investigating + resolved con WhatsApp F-5 encolado, refunded con monto write-once,
reversión RPC end-to-end; listado consola por REST renderiza) → `validate --ci` con web DETENIDO →
commits temáticos + push + CI 5/5 + bitácora PLAN.md §E + 01-state.

### Resto del Track 5 (vista rápida)

- Después: **M3** (tooling generativo del bot desde los `contract.py` — dentro del BLOQUE BOT),
  M4 (packs de vertical, con founder), M5 (analítica conversacional owner — requiere contexto tenant
  explícito en RPCs de métricas, M1 §H5). Backlog completo de 11 domain services: inventario M1 §4.
- **Cerrado Track 5, el §Orden sigue** (`docs/PLAN-CIERRE.md` §Orden): **Track 7** (UX/UI consola
  de clase mundial contra Kaiu DS — login animado, módulos pulidos, micro-interacciones con
  framer-motion ya instalado, móvil de primera; `docs/ux/UX-UI.md`) → **Track 3** (infra PRD:
  dominio `api.konvi.co` + Render Projects, pin Python 3.13, dev cloud, G8b media privada) →
  remanentes Track 1/2 [F] (Wompi prod keys, anular guía UAT, legal B6/B3, MeLi S6, M19, WABA
  hygiene, smoke dinero real al cierre) → **Track 4** ops (A1 MFA cuando founder decida) →
  **AL FINAL el BLOQUE BOT** (inventario parche → B-2 dispatcher sobre contratos estables →
  B-4 observabilidad/métricas → bot GUI/API en consola).

### F2.7 — UAT HSM con 2 tenants piloto (único remanente de F2)

Onboarding manual de 2 de los 6 tenants que requieren proactivos fuera de la CSW de 24h
(~2 días). Dependencia: plantillas aprobadas en el Meta Business Manager de cada tenant
(PLAN.md checklist #11, founder-gate).

### H7 — rotación de credenciales (founder) — detalle operativo

PLAN B2 lo lista; el detalle: rotar service_role key, anon key, DB password, Meta App
Secret y Wompi keys del proyecto Supabase `***SUPABASE_PROJECT_REF_REDACTED***`. Razón: el commit
histórico `be739a4` (2026-04-06) tenía un `.env` con plaintext de estos secretos; `488c6c6`
lo removió del tracking, pero la historia git permanece pushed a GitHub. H8
(`git filter-repo`) queda opcional — PLAN P3.

### Fase 0 fiscal — hard constraints y triggers SAS (contexto de PLAN B6)

PLAN B6 lista las 7 acciones founder. Aquí quedan solo los constraints de fondo (ADR-0022):

1. **Correo Wompi inmutable** — pensar bien el correo definitivo.
2. **UNA cuenta Wompi = UN nombre comercial** — el cliente final ve "KONVI" en el extracto.
3. **Wompi NO marketplace** — Konvi NO recibe pagos para terceros (sería intermediación financiera regulada SFC).
4. **Persona natural = patrimonio personal ilimitado** — mitigar Capa 1 (contratos) + Capa 2 (seguros) obligatorias.
5. **Facturación electrónica DIAN desde el primer peso**.
6. **RST 2027** — ventana cierra 28-feb-2027.

Triggers SAS (cualquiera activa migración persona natural → SAS): ingresos founder
≥ $10M COP/mes × 3 meses · tenant enterprise exige sociedad · capital externo ·
ingresos consolidados cruzan 3.500 UVT · vertical propia >$5M/mes sostenida.

### Konvi Studio — contexto del gate (PLAN §C)

Gate comercial duro: Lucams (tenant piloto de productos personalizables) valida demanda
con flow manual (Instagram + WhatsApp + Wompi link + diseño a mano) hasta **>30 órdenes/mes**.
NO arrancar antes. Si se dispara: editor canvas (react-konva), preview 3D, design assistant,
3 buckets storage per-tenant, `cart_items.custom_design` — estimado ~6-8 semanas.

### COD H.2.4 — evidencia certificada de la pausa (PLAN §C)

Pausado formalmente 2026-05-07. Certificado: 4 carriers COD viables en Colombia
(servientrega, tcc, fedex, dhl); no existe webhook COD dedicado del carrier. Bloqueantes
de reanudación: KYC Ecart Pay Colombia + prueba real en producción + confirmación de
formato DANE Servientrega (V.4) + habilitación Coordinadora.

### Backlog menor no cubierto por PLAN (sin re-verificar 2026-08-02 — verificar antes de ejecutar)

- **MeLi**: tracking de `order_tracking` en detalle de pedido; paginación completa de listings; Q&A + topics de mensajes (auto-reply post-venta).
- **Plataforma**: multi-agente per-tenant (I.5) · Storefront base (I.1) · Channel Registry Messenger/Instagram (I.3) · Onboarding Wizard (MA-4) · billing aggregator (MA-5) · logs forensics append-only (MA-8).
- **Cupones**: tipos de descuento extendidos (`percent_on_total`, `percent_on_shipping`) — trigger: 2-3 tenants pidiéndolo (extiende ADR-0015).
- **Tiering**: decisión comercial de límites/exclusividades por plan + política grace/overage (IH founder).
- **Higiene**: retirar fallback legacy `NEXT_PUBLIC_API_URL` del código server-side.
- **Bot/Habeas Data** (rev. 102): flujo representante legal para menores · i18n bot no-CO · upload evidencia física canal `in_person` · reporte SIC enriquecido.
- **Inbox**: visual de carrito + pedidos recientes del contacto (F-Inbox-1) · persistir `shipping_carrier` en la orden (F-Order-1).

### ADRs activos (leer antes de tocar LLM / Meta / Habeas Data)

- [ADR-0001](../docs/adr/0001-llm-tier-strategy.md) — cascada LLM + triggers concretos (§7) para revisitar scaling.
- [ADR-0002](../docs/adr/0002-meta-business-policy-compliance.md) — detectores pre-LLM (healthcare, drugs, sensitive payment).
- [ADR-0003](../docs/adr/0003-habeas-data-compliance-strategy.md) — cumplimiento Habeas Data end-to-end (D1-D7).
- Índice completo: [`docs/adr/README.md`](../docs/adr/README.md).

---

## Histórico

Este archivo ya no lleva log de sesiones. El detalle de cierres anteriores a 2026-08-02
vive en `.context/01-state.md` y en `docs/_archive/`.
