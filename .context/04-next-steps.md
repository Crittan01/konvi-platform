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

### Track 5 — estado de ejecución al 2026-08-25 (M2.0/M2.1/M2.2 ✅ — ver PLAN.md §E)

Cerrados y certificados (suite 4767 + dbharness 316 + certify_stg 18/18 + validate --ci 25/25 + CI 5/5
+ harness B-3 money_full_flow/s11 verdes + live STG): **M2.0** (paquete `konvi_domain` + cupones como
única fuente + wiring Render/CI/nightly + `make -C .local deps`) · **M2.1** (`konvi_domain.orders`:
create/get/list/list_by_contact + `GET /api/v1/orders/` nuevo + consola orders sobre REST + FSM como
alias único + `ORDERS_CONTRACT` 8 ops/4 implementadas) · **M2.2** (`konvi_domain.orders.cancellation`
con puertos inyectados + consola cancela vía PATCH con pipeline legal completo + paridad de outcome
bot↔paquete ×11 + fix enum `order_cancellation_actor`: actor consola = `operator`).

### M2.3 — brief de implementación (payment link colapsado) — LEER ANTES DE ESCRIBIR

> El prompt de continuación listo para abrir la sesión de M2.3 vive en
> `.context/handoff-prompt-m23.md` (apunta de vuelta a este brief).

**Scope:** operación `payments.get_or_create_link` del contrato (§4.1) — UNA política de reuso/TTL
(mata el espejo `orders.py` ↔ `payment_link_tool.py` medido en M1 §3.3). El bot NO se toca (su
espejo se retira en B-2/M3); la duplicación queda con alarma de paridad.

**Archivos a crear/tocar:**
- CREAR `packages/shared-py/src/konvi_domain/orders/payments.py`: `DEFAULT_PAYMENT_LINK_TTL_MINUTES=30`
  + `payment_link_ttl_minutes()` (lee `WOMPI_PAYMENT_LINK_TTL_MINUTES` del env EN CADA LLAMADA,
  fail-safe al default — la lógica hoy en `services/api/integrations/wompi_client.py:61-85`) +
  `payment_link_expires_at(created_at)` (hoy `orders.py:80`) + `find_reusable_payment_link()`
  (la query de reuso) + `MIN_WOMPI_AMOUNT_CENTS=150000` + `validate_link_amount()` +
  `get_or_create_payment_link()` (async, con puertos) + `PaymentLinkPorts` + `PaymentLinkOutcome`.
- `services/api/integrations/wompi_client.py`: quitar la def local del TTL → re-export del paquete
  (shim, mismo patrón que coupons M2.0). OJO: `wompi_webhook.py:29` sigue importando de aquí.
- CREAR `services/api/lib/order_payment_ports.py`: `build_api_payment_ports(supabase)` — OJO: los
  puertos deben hacer **lazy import** de `integrations.wompi_client` EN CALL TIME (ver constraint 1).
- `services/api/routers/orders.py::create_payment_link` → delega al servicio (idempotency + auth
  quedan en el router).
- `packages/.../orders/contract.py`: `payments.get_or_create_link` → `implemented=True` +
  `tests/test_domain_contract_structural.py` SERVICE_MODULES añade `"konvi_domain.orders.payments"`.
- CREAR `tests/test_payment_link_policy_parity.py` (paridad con el espejo del bot — ver abajo).

**Constraints de compatibilidad DESCUBIERTAS (no re-derivar):**
1. **Tests existentes pachean el módulo**: `test_payment_link_reuse.py` / `test_wompi_payment_link_endpoint.py`
   hacen `patch.object(wompi_client_module, "get_tenant_wompi_creds")` y `...create_payment_link_with_resilience`.
   Funcionan porque el router los importa LAZY dentro de la función (`orders.py:583-584`). El puerto
   del API debe preservar ese patrón (import lazy en call time) o esos tests rompen.
2. **`test_payment_link_ttl.py`**: importa `DEFAULT_PAYMENT_LINK_TTL_MINUTES` + `payment_link_ttl_minutes`
   desde `integrations.wompi_client` (el re-export los mantiene vivos; el env se lee en call time).
   SUS WIRING TESTS usan `inspect.getsource(orders.create_payment_link)` y exigen el string
   `payment_link_ttl_minutes()` en él → **hay que actualizarlos deliberadamente**: la fuente única
   ahora es el paquete; reescribir como (a) identidad `wompi_client.payment_link_ttl_minutes is
   konvi_domain...payment_link_ttl_minutes`, (b) `wompi_webhook._maybe_offer_payment_retry` sigue
   usándolo (source check se mantiene), (c) alarma TTL bot↔paquete: `tools/payment_link_tool.py:
   WOMPI_LINK_TTL_MINUTES == payment_link_ttl_minutes()` con env limpio (hoy ambos 30; el env NO está
   seteado en render.yaml ni .env.local — drift real si alguien lo setea).
3. **Criterio de reuso EXACTO** (espejo `orders.py:640-658` ↔ `payment_link_tool.py:117-140`):
   `payments.select("checkout_url, wompi_link_id, status, created_at, amount_in_cents")
   .eq(tenant_id).eq(order_id).eq(status,"pending").gte(created_at, cutoff).order(created_at desc)
   .limit(1)`; reusar SOLO si `checkout_url` no vacío; si el lookup FALLA → degradar a crear
   (log warning, disponibilidad). El test de reuse existente aserta la cadena de filtros sobre el
   mock (`probes["payments_select"].eq.assert_any_call(...)`) — la query del servicio debe ser idéntica.
4. **Dinero**: `amount_in_cents = int(round(total_amount * 100))` (round, NO int() — BLOQUE A,
   subcobro de 1 cent). Mínimo `$1.500` (150000 cents) → 422 con detalle EXACTO
   `f"Monto mínimo Wompi es $1.500 COP. Monto actual: ${total_amount:,.0f}"`. La rama de REUSO
   salta el guard (hoy y siempre).
5. **Orden de pasos heredado** (preservar): creds (503 si sin private_key) → order lookup (embed
   `contacts(name, phone, email, document_type, document_number)`; 404 "Pedido no encontrado") →
   status check pending|pending_payment (409 con mensaje exacto) → reuso (200, sin Wompi ni insert
   ni update) → amount guard → crear link (name `f"Pedido #{short_id} — {contact_name}"[:100]`,
   description `notes or f"Pedido #{short_id}"`, expires_at `now+TTL` formato `"%Y-%m-%dT%H:%M:%S.000Z"`,
   `max_attempts=2`) → insert payments (`provider="wompi"`, `status="pending"`, `wompi_status="ACTIVE"`,
   `currency="COP"`) → flip orden a `pending_payment` si no lo está → 200.
6. **`DomainError` necesita `http_status` opcional**: el caso "Wompi no configurada" es **503** y el
   mapeo actual `_DOMAIN_ERROR_HTTP` no lo cubre (UPSTREAM→500). Añadir campo `http_status` a
   `konvi_domain/errors.py` y que `_domain_error_to_http` del router lo honre cuando venga.
7. **Idempotency queda en el router** (begin/finalize/abort con `payload_fingerprint({"order_id":...,
   "route":"payment-link"})`); finalize con **status 200 en AMBAS ramas** (reuse y create).
8. MFA/RBAC del endpoint NO cambian: `require_write_internal_or_user` + `enforce_mfa_internal_or_user`
   (NO-OP bot / AAL2 operador) + `RL_WRITE_DEFAULT` + `@audit_log(action="payment_link_created")`.
9. **`_payment_link_expires_at` del router muere** → vive en el paquete (regla: `created_at + TTL`,
   formato idéntico, `''` si no parseable — degradación espejo del bot).

**Paridad con el espejo del bot (`tests/test_payment_link_policy_parity.py`):**
- TTL: `WOMPI_LINK_TTL_MINUTES` (bot) == `payment_link_ttl_minutes()` (paquete) con env limpio.
- Reuse: mismas filas staged → la decisión `active_link` del bot (`_find_pending_order`) == el
  resultado del paquete (`find_reusable_payment_link`) — con link vigente / expirado / sin
  checkout_url / sin filas. Reusar el fake stateful `_Sb` de `test_order_cancellation_pipeline.py`
  o el `_make_supabase_mock` de `test_payment_link_reuse.py`.
- La query de payments del paquete produce los mismos filtros (eq tenant/order/status + gte
  created_at) que la del bot.

**Certificación M2.3 (misma barra que M2.1/M2.2):** tests focales → suite completa → dbharness 316 →
harness B-3 `money_full_flow` + `s11_cancela_preconfirmacion` (el bot consume este path) → live STG
(reuso de link vigente vía REST: crear orden + link, re-llamar, verificar mismo checkout_url sin fila
nueva en payments) → `validate --ci` **con el web DETENIDO** (`make -C .local stop-web` — ver lección
validator.ts abajo) → commits temáticos + push + CI 5/5 + bitácora PLAN.md §E + 01-state.

### Lecciones de entorno/proceso de esta sesión (aplican a TODO el trabajo restante)

- **`validate --ci` con el web dev server parado o asentado**: `next dev` reescribe
  `apps/web/.next/dev/types/validator.ts` (incluido por tsconfig, default Next 16) y puede quedar
  entrecortado mid-write tras un restart → tsc falla con TS1128 fantasma. Protocolo: `make -C .local
  stop-web` + `rm -rf apps/web/.next/dev` antes de validate; CI es inmune (clone fresco sin `.next`).
- **xdist**: parámetros de `subTest` deben ser primitivos (execnet no serializa `PosixPath` → usar
  `str()`). La suite corre serial localmente pero xdist en validate/CI — un test puede pasar serial y
  fallar en xdist.
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

### M2.4 y resto del Track 5 (vista rápida)

- **M2.4 — ClaimsService** (diseño §5 del contrato): UN writer (`reason` cerrado + `reason_detail`
  libre — decisión founder #3), dedup idempotente, titularidad por actor, FSM formalizada
  (`refunded` final, write-once), reversión delega a RPCs SQL existentes, enums compartidos (mata el
  vocabulario extinto del bot cuando lo adopte). Misma barra de certificación + paridad bot↔paquete.
- Después: **M3** (tooling generativo del bot desde los `contract.py` — dentro del BLOQUE BOT),
  M4 (packs de vertical, con founder), M5 (analítica conversacional owner — requiere contexto tenant
  explícito en RPCs de métricas, M1 §H5). Backlog completo de 11 domain services: inventario M1 §4.

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
