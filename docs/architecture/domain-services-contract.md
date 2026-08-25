# Track 5 · M2 — Contrato de Domain Services (propuesta de diseño)

> **Estado: APROBADO por founder 2026-08-25 (4/4 decisiones §8 en la opción recomendada) — M2 en ejecución.**
> Origen: visión [`modular-domains-vision.md`](modular-domains-vision.md) §4 fase M2, sobre el
> inventario verificado [`domain-capabilities-inventory.md`](domain-capabilities-inventory.md) (M1,
> 2026-08-24, evidencia `archivo:línea` por afirmación — abreviado abajo como **M1 §x.y**).
> Pilotos: **pedidos + reclamos**. Reglas que gobiernan este diseño: STG-first · el bot queda
> **congelado** hasta el bloque bot (dispatcher/prompts/resolvers/invariants no se tocan; el harness
> B-3 certifica cada noche que sigue verde) · FIX ARQUITECTÓNICO, no parche · cero suposiciones.

---

## 1. Qué problema resuelve (síntesis del inventario)

1. **La misma capacidad existe N veces con semántica divergente**: cancelación de pedido ×2 (consola
   "a medias" vs bot pipeline legal completo — M1 §3.3), creación de reclamo ×2 (vocabulario cerrado
   vs texto libre, dedup solo en el bot — M1 §3.8), cotización de envío ×2 (con/sin COD — M1 §3.6),
   restock al cancelar ×3 (M1 §3.2), "ingreso reconocido" ×5 (M1 §3.11).
2. **Compartir código hoy = copiarlo** (M1 §H1): cliente Aveonline ×2 idénticos, sys.path hack para
   cupones, duplicaciones "a conciencia". Cada fix se aplica a mano N veces.
3. **La consola bypassea el API en lecturas** (M1 §H2) y el bot lee DB directo en 3+ puntos: no hay
   contrato, hay drift garantizado (ya medido: vocabulario de estados extinto vivo en el bot).
4. **El destino exige UN camino**: la consola y el bot (y la Platform Console futura) consumen las
   mismas capacidades de dominio definidas UNA vez; en M3 las tools del bot se **generan** del
   contrato. Sin contrato estable, M3 y B-2 no tienen sobre qué construir.

## 2. Restricciones de diseño (verificadas, no negociables)

- **R1 — Despliegue**: `services/api` y `services/ai-orchestrator` tienen rootDirs separados en
  Render; no pueden importarse entre sí (M1 §H1). El repo completo SÍ está disponible en build.
- **R2 — La verdad transaccional ya vive en Postgres** (M1 §H4): RPCs con guards de idempotencia
  (stock, receipts, cupones, reversión). No se reimplementan; los servicios **delegan** en ellas.
- **R3 — Seguridad heredada**: dual-auth (JWT operador / `X-Internal-Service-Secret`+`X-Tenant-Id`),
  RBAC, MFA AAL2 en money-movement humano, rate-limit, `audit_log`/`pii_access_log`, RLS última
  barrera (Track 9). El contrato las vuelve **declarativas por operación**, no implícitas por router.
- **R4 — Bot congelado**: durante la fase plataforma el bot sigue con sus implementaciones actuales.
  El contrato se adopta primero en API+consola; la adopción por el bot es trabajo de B-2/M3 con el
  harness B-3 como instrumento de aceptación. La coexistencia temporal es **explícita y acotada por
  tests de paridad** (§6.3), no silenciosa.
- **R5 — Platform Console (Fase 12, fuera de alcance) como punto de extensión**: nada de lógica
  cross-tenant hardcoded; el actor y el tenant son parámetros siempre (PLAN-CIERRE §Nota PC).

## 3. Decisiones de diseño propuestas

### D1 — Packaging: paquete compartido `packages/shared-py/` + delegación SQL + REST

Tres mecanismos, cada uno donde es fuerte:

1. **`packages/shared-py/konvi_domain/`** — librería Python única con los servicios de dominio
   (lógica de negocio, validaciones, orquestación de RPCs/DB, eventos). Instalada por `services/api`
   y `services/ai-orchestrator` como dependencia editable del mismo repo
   (`pip install -e packages/shared-py` en buildCommand/Makefile — el repo completo está en build,
   R1). **Mata la copia física y el sys.path hack** (la deuda ya estaba declarada:
   `orch/lib/coupons.py:7-9` pide exactamente `packages/shared-py/`).
2. **SQL/RPC** — lo que debe ser atómico, idempotente o multi-escritor sigue bajando a Postgres
   (patrón probado ADR-0040; M1 §H4). Candidatos nuevos identificados: ajuste de stock con ledger,
   recepción de OC. No es parte de los pilotos salvo delegación en los existentes.
3. **REST del API = proyección HTTP del servicio** — el router se vuelve adaptador delgado
   (auth→actor, HTTP→DTO, errores tipados→status) sobre `konvi_domain`. Es la puerta para consola,
   canales futuros y Platform Console. El bot YA consume 3 endpoints así (M1 §H4) — precedente real.

Descartado: bot-consumo-por-HTTP para todo (latencia por turno y rompe el patrón in-process del
catálogo/carrito); compartir por git-submodule/copia en CI (perpetúa H1).

### D2 — El contrato: `DomainCapability` declarativa por dominio

Cada dominio publica un módulo `contract.py` en el paquete compartido que declara, por operación:

```text
Operation:
  name            # verbo de dominio: orders.cancel, claims.transition
  description     # texto canónico — en M3 alimenta la descripción de la tool LLM generada
  audience        # customer | operator | owner  (M5: primera audiencia owner-facing)
  input_model     # pydantic — única validación de forma
  output_model    # pydantic — DTO de dominio, nunca la fila cruda de DB
  preconditions   # validaciones declaradas (dinero, estado, titularidad, tenant)
  rbac            # matriz actor→permitido (aplicada UNA vez en el servicio, no por capa)
  idempotency     # estrategia: key explícito | key derivado | unique-natural | read-only
  events          # DomainEvent[] que emite (§D6) — escritura exige ≥1 evento
  errors          # catálogo de DomainError tipados (§D7)
  customer_facing # si el bot puede exponerla al cliente final (M3 filtra tools por esto)
```

El servicio (`service.py`) implementa las operaciones; el contrato es importable sin efectos
colaterales (M3 lo lee para generar schemas de tools; la Platform Console para descubrir capacidades).

### D3 — `Actor` de primer ciudadano

```text
Actor(channel: console|bot|worker|api_public,
      role:    owner|manager|operator|customer|system,
      tenant_id: UUID, user_id?: UUID, contact_id?: UUID)
```

Resuelve el drift de RBAC medido en M1: claims create = owner/manager/operator por consola pero
"cliente autenticado por `contact_id`" por bot (§3.8); cancelación owner/manager por consola pero
cliente con confirmación en 2 turnos por bot (§3.3); compras/finanzas owner-only replicado en 3
capas (§3.9). La matriz vive declarada en la operación; los adaptadores solo construyen el `Actor`.

### D4 — Contexto tenant explícito

Los servicios reciben `tenant_id` explícito (nunca derivado de JWT fuera del borde HTTP). Las RPCs
que hoy derivan tenant de `auth.jwt()` (métricas — M1 §H5) se migran, **cuando su dominio entre en
el backlog**, al patrón GUC `app.current_tenant_id` ya usado por workers (Track 9). No es trabajo
de los pilotos (pedidos/reclamos ya operan con tenant explícito).

### D5 — Idempotencia obligatoria y declarada

Toda operación de escritura declara su estrategia (D2). Patrones ya probados en el repo que el
contrato adopta como canon: key explícito `Idempotency-Key` + `idempotency_keys`
(`dependencies/idempotency.py`) · key derivado determinístico (`ordc:{conv}:{cart_hash}`,
`plink:{order}:b{bucket}` — M1 §3.3) · unique-natural con adopt-winner (índice anti doble-cobro +
23505) · unique por entidad (`UNIQUE(tenant_id, order_id)` en receipts; `UNIQUE(claim_id)` en
reversión) · movement único `(order_id, variation_id, reason)` en stock.

### D6 — Eventos de dominio (sin infraestructura nueva)

`DomainEvent(name, payload, occurred_at)` tipado por dominio. En M2 el bus es el existente, mapeado:
`cart_events` (16 tipos canónicos, `cart/events.py:40-66`) · `audit_log` (`write_audit_event`) ·
`messages` (`claim_audit`) · notificaciones WA/email/Telegram ya cableadas. **No se crea bus nuevo**;
se nombra y declara lo que ya se emite, y se hace obligatorio: escritura sin evento = contrato
inválido (verificable por test estructural, §7).

### D7 — Errores tipados

`DomainError` con `code` estable: `VALIDATION | FORBIDDEN | NOT_FOUND | CONFLICT | PRECONDITION |
UPSTREAM | TENANT_MISMATCH`. El adaptador REST los mapea a 4xx/5xx; en M3 el generador de tools los
mapea a texto seguro para el cliente (nunca stack ni SQL). Sustituye el mosaico actual de
`HTTPException` con detalle libre.

### D8 — Lecturas también son contrato

Los read-models faltantes se construyen como operaciones del servicio (M1 §H2): `orders.list`,
`orders.list_by_contact`, `claims.list_by_contact`, `contacts.get/list`, `coupons.list`… La consola
migra sus lecturas a REST **dominio a dominio, empezando por los pilotos**; los dominios no
tocados siguen con PostgREST/RLS hasta su turno (pragmático: RLS ya los protege; el drift crítico
está en las escrituras).

## 4. Piloto 1 — `OrdersService` (pedidos)

### 4.1 Operaciones

| Operación | De dónde se extrae | Novedad |
|---|---|---|
| `orders.create(input, actor) → OrderResult` | `orders.py:143-410` (total recomputado, guard de redención, adopt-winner, índice anti doble-cobro) | Ninguna de semántica — es el buen precedente; se mueve intacta al servicio |
| `orders.get(order_id, actor) → OrderDetail` | `orders.py:413` + reads del bot (`order_status_tool.py:241`, `agentic/tools/orders.py:87`, `cancel_intent_resolver.py:103`) | UN read de detalle para los 4 consumidores |
| `orders.list(filter, page, actor) → Page[OrderSummary]` | — | **NUEVO** `GET /api/v1/orders/` (hueco M1 §H2); consola migra su listado |
| `orders.list_by_contact(contact_id, actor) → [OrderSummary]` | `GetRecentOrdersTool` (`agentic/tools/orders.py:87-98`) | Cubre bot (M3) y consola (historial del contacto) |
| `orders.transition(order_id, to, actor) → Order` | `orders.py:442-534` + máquina `orders.py:60-74` + efectos stock | Transición declara efectos (decrement/restore) como parte del contrato |
| `orders.cancel(order_id, reason, actor, items?) → CancellationResult` | **`lib/order_cancellation.py:241-440` (pipeline completo)** | La consola deja de cancelar "a medias": mismo pipeline legal (void Wompi, cancel guía, restock, `order_cancellations`, notificaciones) para ambos canales; el flip del router queda como caso delegado |
| `payments.get_or_create_link(order_id, actor) → PaymentLink` | `orders.py:540-752` + política espejo del bot | **Colapsa la duplicación TTL/criterio** (M1 §3.3): una sola política, TTL único de config |
| `payments.confirm(event) → ConfirmationResult` | `wompi_webhook.py:345-783` (referencia; NO se mueve en el piloto) | Documenta la frontera webhook→servicio |

### 4.2 Validaciones declaradas (canon del contrato)

- Dinero: total recomputado server-side desde ítems − descuento + envío; mínimo Wompi $1.500 en
  `get_or_create_link` (hoy validado ×2 — M1 §3.3); guard monto/moneda en confirmación.
- Estado: máquina forward-only con rank, terminal no reabrible (`orders.py:60-74`).
- RBAC (D3): create = owner/manager/operator + bot(customer vía carrito); cancel = owner/manager
  (consola, MFA AAL2) y customer (bot, confirmación en 2 turnos B6 — la política per-tenant
  `tenant_cancellation_policy` decide elegibilidad); payment-link = owner/manager + bot.
- Idempotencia: create = `Idempotency-Key` + unique-natural anti doble-cobro + adopt-winner;
  link = key derivado `plink:{order}:b{bucket}` + reuso por TTL; cancel = dedup por
  `order_cancellations` + restock idempotente (`rpc_stock_restore` reason `cancellation_refund`).
- Eventos: `order.created` · `order.status_changed` · `order.cancelled` · `payment.link_created`
  (mapeados a `cart_events` + `audit_log` + notificaciones WA/email/Telegram existentes).

### 4.3 Qué NO toca el piloto

El flujo del bot sigue usando sus implementaciones actuales (R4). El servicio se adopta en
API+consola. La convergencia del bot al contrato es M3/B-2, con harness como aceptación.

## 5. Piloto 2 — `ClaimsService` (reclamos)

### 5.1 Operaciones

| Operación | De dónde se extrae | Novedad |
|---|---|---|
| `claims.create(order_id, reason, reason_detail?, requested_amount?, actor) → Claim` | `claims.py:201-237` (API) + `agentic/tools/claims.py:104-297` (bot) | **UN writer**: vocabulario cerrado `reason` + `reason_detail` libre opcional (resuelve el drift API-cerrado vs bot-libre — M1 §3.8); dedup idempotente (hoy solo el bot); titularidad por actor: `customer` exige `order.contact_id == actor.contact_id`, staff solo tenant; eventos: `audit_log` + Telegram operador + `messages.claim_audit` (unión de los efectos actuales de ambos writers) |
| `claims.get(claim_id \| ticket_number, actor) → ClaimDetail` | `claims.py:240-256` + tool `:303-374` | Scoping por actor: customer solo los suyos |
| `claims.list(filter, page, actor) → Page[ClaimSummary]` | `claims.py:178-198` | Consola migra su lectura directa |
| `claims.list_by_contact(contact_id, actor) → [ClaimSummary]` | — | **NUEVO** — hueco del bot: hoy sin `ticket_number` no hay consulta (M1 §3.8) |
| `claims.transition(claim_id, to, notes?, refunded_amount?, actor) → Claim` | `claims.py:315-442` (FSM completa) | FSM formalizada en el contrato: `VALID/TERMINAL/REOPENABLE`, **`refunded` final**, `refunded_amount` write-once que sella KPI net-revenue; reopen solo owner; evento `claim.status_changed` → WhatsApp outcome F-5 |
| `claims.register_reversion(claim_id, causal, actor) → ReversionConstancia` | `claims.py:524-573` → RPC `rpc_registrar_reversion` | Delega en SQL (frontera ya SECURITY DEFINER); causales cerradas |
| `claims.register_reversion_movement(claim_id, tipo, actor)` | `claims.py:586-621` → RPC | Idem; detecta doble pago |

### 5.2 Enums compartidos (mata el drift vivo)

`ClaimStatus = {open, investigating, resolved, refunded, rejected, cancelled}` definido UNA vez en
el paquete compartido. El `status_human` del bot con vocabulario extinto (`in_progress`, `closed` —
M1 §3.8) se corrige cuando el bot adopte el contrato en M3; mientras tanto el enum del contrato es
la única referencia que los tests de paridad defienden.

### 5.3 Fuera de alcance del piloto

RMA/devoluciones formales (tabla muerta — decisión de producto aparte, M1 §H6) · entidad
`data_subject_requests` · unificación del pipeline de retracto (`order_cancellations`) con claims
(se documenta como dominio paralelo; la cancelación unificada del piloto pedidos es el primer paso).

## 6. Plan de migración (strangler, sin big bang)

### 6.1 Fases

1. **M2.0 — Cimientos del paquete**: `packages/shared-py/konvi_domain/` (Actor, DomainError,
   DomainEvent, base de contrato, cliente supabase compartido con tenant explícito) + wiring de
   instalación en los 2 servicios (requirements/buildCommand/Makefile) + CI. Sin cambio de
   comportamiento. **Primera extracción sin riesgo: `api/lib/coupons.py` → paquete** (ya es el
   servicio de-facto; sustituye el sys.path hack — prueba el packaging con el caso más fácil).
   **✅ CERRADO 2026-08-25** (con ajuste de alcance documentado: el cliente supabase compartido y
   la base del contrato aterrizan con su primer consumidor real — M2.1 — en vez de construirse
   especulativamente; bitácora PLAN.md §E).
2. **M2.1 — OrdersService lecturas + create**: `orders.create/get/list/list_by_contact` en el
   servicio; router como adaptador; `GET /orders/` nuevo; consola orders migra listado a REST.
   **✅ CERRADO 2026-08-25** — incluye la máquina de estados como alias único del paquete y tests
   de paridad canal↔canal (REST↔servicio in-process) + verificación live en STG (list/create/get/
   idempotencia). El efecto de stock al confirmar se inyecta (`on_confirm_stock`) porque sigue
   acoplado a `sync_meli_stock` hasta InventoryService (backlog M1 #3).
3. **M2.2 — Cancelación unificada**: pipeline completo en el servicio; `POST /orders/{id}/cancel`
   (o PATCH con política completa) para la consola; **el bot sigue con el suyo (R4)** — duplicación
   time-boxed y defendida por test de paridad de outcome (mismo estado DB final para el mismo input).
   **✅ CERRADO 2026-08-25** — implementación real: pipeline extraído intacto a
   `konvi_domain.orders.cancellation` con **puertos inyectados** (`CancellationPorts`:
   void_credentials/void_payment/cancel_shipping_guide/on_stock_restored) · consola cancela vía
   PATCH (sin endpoint nuevo — una sola superficie) · regla de canal: la triage bloquea solo a
   `customer` (staff procede registrando la señal en la auditoría) · puertos API en
   `lib/order_cancel_ports.py` (Wompi void + Aveonline cancel + WhatsApp cliente + Telegram
   operador) · **paridad de outcome bot↔paquete certificada** (`test_cancellation_outcome_parity.py`
   — 11 escenarios, misma huella DB) · fix destapado por la certificación live: el actor de consola
   debe ser `operator` (enum `order_cancellation_actor` — "owner" rompe el insert 22P02) · hook
   `on_stock_restored` preserva el sync MeLi que la consola ya tenía.
4. **M2.3 — Payment link colapsado**: `payments.get_or_create_link` único (política + TTL de config
   única); test de paridad anti-drift TTL.
   **✅ CERRADO 2026-08-25** — implementación real: política reuso/TTL extraída intacta a
   `konvi_domain.orders.payments` (TTL fail-safe de env · `find_reusable_payment_link` con el
   criterio exacto · `validate_link_amount` con round-no-int y mínimo $1.500 ·
   `get_or_create_payment_link` async con el orden de pasos heredado) · **puertos inyectados**
   (`PaymentLinkPorts`: wompi_credentials/create_link — lazy import en call time para preservar el
   patrón de patch de los tests del endpoint) · puertos API en `lib/order_payment_ports.py`
   (max_attempts=2 = presupuesto de latencia del canal, F105) · router = adaptador (idempotency +
   dual-auth/RBAC/MFA/rate-limit/audit intactos; DomainError→HTTP con `http_status` opcional nuevo
   en `DomainError` — el "Wompi no configurada" 503 no cabía en el mapeo UPSTREAM→500) · shim
   `integrations/wompi_client` re-exporta el TTL (wompi_webhook sigue cableado) ·
   `_payment_link_expires_at` del router muere (vive en el paquete) · **paridad de política
   bot↔paquete con alarma** (`test_payment_link_policy_parity.py`: TTL env-limpio + decisión de
   reuso en 4 escenarios + mismos filtros de query) · el bot conserva su espejo congelado (B-2/M3).
5. **M2.4 — ClaimsService completo**: §5.1 + endpoints + consola claims migra; enums compartidos.
6. **Cierre M2**: tests de paridad canal↔canal, test estructural del contrato, docs (§9).

### 6.2 Orden y riesgo

M2.0 primero porque prueba el packaging sin tocar comportamiento (coupons ya es librería pura).
Cancelación (M2.2) es el mayor cambio semántico: la consola **gana** void automático, cancel de guía
y audit SIC que hoy no tiene — requiere certificación STG turno a turno con el harness
(`money_full_flow` + escenarios de cancelación) antes de considerarse verde.

### 6.3 Coexistencia temporal bot ↔ contrato (R4) con red de seguridad

- El bot NO se toca (dispatcher/prompts/resolvers/invariants — diff cero exigido en esos paths).
- Donde el bot conserva su implementación (cancelación, link TTL, claims create), se añaden **tests
  de paridad** que fallan si las dos semánticas divergen del contrato — la duplicación deja de ser
  silenciosa y queda con alarma.
- El harness B-3 nocturno certifica que el bot actual sigue verde en cada paso (29 escenarios;
  xfails H1-H8/H10/H11 son deuda conocida del bot, no de este trabajo).
- En B-2/M3 el bot adopta el contrato (tools generadas), las copias internas se retiran junto con
  el código muerto verificado (M1 §4) y los tests de paridad se convierten en tests del contrato.

## 7. Criterios de aceptación de M2 (verificables)

1. **Una sola implementación por operación**: en los dominios piloto, ninguna lógica de dominio en
   routers (SQL inline de dominio = 0 en `orders.py`/`claims.py` tras el piloto — son adaptadores);
   el paquete compartido es la única fuente.
2. **Paridad canal↔canal**: para `create/transition/cancel` de pedidos y `create/transition` de
   reclamos, tests que ejecutan la operación vía REST (consola) y vía servicio in-process y
   verifican **mismo estado DB final y mismos eventos** (patrón de assertions del harness B-3).
3. **Drift medido eliminado**: TTL/política de link única (paridad TTL) · vocabulario `ClaimStatus`
   único · restock al cancelar con UNA implementación en la capa servicio (las 3 copias delegan) ·
   cancelación desde consola = pipeline completo (void + audit + cancel guía verificables en STG).
4. **Test estructural del contrato**: toda operación de escritura registrada declara `rbac` no
   vacío + estrategia `idempotency` + ≥1 `event`; todo DTO es pydantic; el contrato se importa sin
   efectos colaterales.
5. **Cero regresión certificada**: suite pytest + dbharness (316) + vitest + ruff ≤ baseline +
   `certify_stg.sh` 18/18 + `validate.sh --ci` + harness B-3 completo verde (con los mismos xfails
   conocidos, ninguno nuevo) + E2E `money_full_flow` turno a turno en STG tras M2.2.
6. **Bot intacto**: diff cero en `agentic/dispatcher.py`, `agentic/prompt/**`,
   `agentic/*resolver*.py`, `agentic/invariants/**` durante todo M2.
7. **Seguridad heredada verificada**: dbharness de ataque sigue verde (Track 9); los nuevos
   endpoints heredan dual-auth/RBAC/MFA/rate-limit por adaptador, con tests.

## 8. Decisiones founder (2026-08-25 — 4/4 aprobadas en la opción recomendada)

1. **Packaging (D1) → APROBADO `packages/shared-py/`** instalado editable en build. Mata la copia
   física y el sys.path hack de raíz; el bot la consumirá in-process en M3. (Alternativa descartada:
   bot-consumo-por-HTTP para todo — latencia por turno y no mata las copias in-process.)
2. **Cancelación consola (§4.1) → APROBADO pipeline legal completo**: la consola gana void Wompi
   automático + cancel de guía Aveonline + audit `order_cancellations` (misma semántica del bot),
   protegida con el MFA AAL2 ya existente.
3. **Reason de reclamos (§5.1) → APROBADO vocabulario cerrado + `reason_detail` libre opcional**:
   recupera analítica por causal y preserva la expresividad del bot.
4. **Lecturas consola (D8) → APROBADO migrar a REST dominio a dominio**, pilotos primero (pedidos y
   reclamos, donde faltan endpoints como `GET /orders/`); el resto al llegar su turno en el backlog.

## 9. Relación con las fases siguientes

- **M3 (tooling generativo del bot)**: lee los `contract.py` (D2) y genera schema+descripción de
  tools; `customer_facing` y `audience` filtran el subset por estado FSM. Sin M2 estable, M3 no
  tiene fuente — es la razón estructural del REORDEN founder (PLAN-CIERRE §Orden).
- **M4 (packs de vertical)**: los packs referencian capacidades del contrato (p.ej. políticas de
  envío/devolución por vertical) — requiere los enums y eventos de D2/D6.
- **M5 (analítica conversacional)**: primer consumidor `audience=owner`; requiere D4 (contexto
  tenant GUC) en las RPCs de métricas — backlog #11 del inventario.
- **Platform Console (Fase 12, fuera de alcance)**: consumirá los mismos `contract.py` vía REST;
  D3/D4 garantizan que nada de lógica cross-tenant quede hardcoded (R5).
- **B-2 (bloque bot)**: adopta los servicios y retira las copias internas; los tests de paridad de
  §6.3 se convierten en tests del contrato; el harness B-3 es el instrumento de aceptación.
