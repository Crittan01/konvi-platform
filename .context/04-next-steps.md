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

### Track 5 — estado de ejecución al 2026-08-25 (M2.0/M2.1/M2.2/M2.3/M2.4 ✅ — **M2 COMPLETO** — ver PLAN.md §E)

Cerrados y certificados (suite 4826 + dbharness 316 + certify_stg 18/18 + validate --ci 25/25 + CI 5/5
+ harness B-3 money_full_flow/s11/s19 verdes + live STG): **M2.0** (paquete `konvi_domain` + cupones como
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
checkout_url, 1 fila payments, orden pending_payment) · **M2.4** (`konvi_domain.claims` — las 7 ops
del piloto: UN writer create (reason cerrado + `reason_detail` libre opcional + dedup heredada del
bot + titularidad por actor + unión de eventos audit/claim_audit/Telegram-puerto) · get (id|ticket,
scoping customer fail-closed) · list con embeds + reason_detail (consola migra su listado a REST,
decisión #4) · list_by_contact NUEVO (hueco M1 §3.8) · transition (FSM formalizada: refunded FINAL,
refunded_amount write-once sellando KPI, reapertura solo owner) · reversión delegada en RPCs (R2)
con `_MOTIVO_HTTP` → `DomainError.http_status` · migración `20260825180000` (ledger 269) · router =
adaptador puro JWT-only (RBAC asimétrico G-4 intacto; dedup → 200 `deduplicated:true`) · F-5 movida
a `lib/claim_ports.py` · `CLAIMS_CONTRACT` 7/7 implemented · 38 tests nuevos (33 unit + 5 paridad
bot↔paquete alarmada — el `status_human` extinto del bot queda como deuda M3 registrada) · live STG
vía REST con JWT real — `scratch/m24_live_verify.py` — : create+dedup+claim_audit+F-5 encolado+
refunded write-once+reversión end-to-end RV-000003 · bot intacto: diff cero en `agentic/**`).

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
- **Restore track9 + migración NUEVA = ledger viejo (M2.4)**: el filtro del dump
  (`scratch/track9_filter_dump.py`) NO excluye `supabase_migrations.schema_migrations` → tras el
  replay+restore, la columna nueva está aplicada pero su versión falta en el ledger (el dump la
  traía de antes). Fix canónico: `supabase migration repair --local --status applied <version>` —
  o tomar el dump DESPUÉS de aplicar la migración al vivo. Verificar siempre
  `max(version)` del ledger vs el archivo nuevo tras un restore.
- **Fixture `db_schema_canonical.json` se regenera LOCAL cuando hay columnas pendientes de deploy
  (M2.4)**: `scripts/dump_schema_canonical.py` consulta `--linked` (PRD) — las migraciones aún no
  desplegadas no existen ahí y el pacto de coherencia (`test_coherence_pact.py`) las marcaría
  huérfanas. Regenerar contra la DB local con el mismo template SQL (`_format_sql(CORE_TABLES)`)
  vía podman psql + `json.dump(indent=2, sort_keys=True)` — quedó más fiel al código bajo test
  (ganó las 7 columnas de las 6 migraciones pendientes + `reason_detail`).
- **Verificación visual live con navegador real (T7.2)**: hay chromium para Playwright cacheado en
  `~/.cache/ms-playwright` (chromium-1234) pero el paquete NO está instalado — crear venv aislado
  (`python3.11 -m venv scratch/venv-visual && pip install playwright psycopg[binary]`; el venv está
  gitignored y calza con el browser cacheado, cero descarga). Patrón de sonda en
  `scratch/t7_02_visual_verify.py`: login dev-owner → `?conv=<id>` → MutationObserver registra el
  `style` inline al MONTAR cada burbuja (entrada animada = `opacity: 0` presente) + inserts/updates
  SQL directos para disparar realtime. Tres trampas resueltas: (1) **usar `localhost`, NO
  `127.0.0.1`** — Next 16 dev bloquea `/_next/*` desde orígenes no listados en `allowedDevOrigins`
  (solo la IP LAN está) → la página carga pero NUNCA hidrata (forms hacen submit nativo GET);
  (2) `add_init_script` corre antes de parsear el documento (`document.body` null → instalar el
  observer en DOMContentLoaded); (3) tap pre-hidratación en móvil no dispara onClick de React —
  esperar networkidle + ~1.5s o una señal post-tap (`?conv=` en URL).
- **Reduced-motion + SSR = hydration mismatch (fix DS, T7.2)**: framer-motion `useReducedMotion()`
  lee la media query REAL en la primera pintura cliente, pero el SSR no puede conocerla → las
  ramas con estilo de entrada (opacity:0/translateY) no coinciden y React loguea mismatch para
  usuarios con reduce (chromium headless con `reduced_motion='reduce'` lo expone). Fix en el
  wrapper: `useReducedMotionDS` (motion.tsx) — false en SSR/hidratación, valor real tras montar.
- **`variants={undefined}` bajo reduced-motion CONGELA el contenido (bug T7.3)**: quitar las
  variantes post-hidratación no resetea los valores en vuelo → StaggerItem quedaba en
  `opacity:0` para siempre (listas invisibles para usuarios reduce desde 894b7357). Patrón
  correcto: variante reduced con los MISMOS valores finales + `transition: {duration: 0}`
  (snap instantáneo). Y al verificar viajes layout/layoutId con una sonda: framer-motion usa
  **`translate3d(x, y, 0)`** (no `translateX/Y`) — el detector debe cubrir ambos.
- **`whileTap` emite `tabindex="0"` en SSR (bug T7.4)**: framer-motion hace focusable cualquier
  elemento con gesto tap → el atributo SÍ es SSR-visible y diverge bajo reduced-motion
  (mismatch hydration). Pressable también necesita el gate `useReducedMotionDS`. Regla general:
  para saber si un wrapper diverge en SSR no basta mirar `initial` — pensar en ATRIBUTOS
  (tabindex) además de estilos.
- **Sonda de dinero real (T7.4)**: el loop completo orden REST (auth interna `X-Internal-Service-
  Secret`) → `payment-link` (Wompi sandbox real) → `scripts/uat/_send_wompi_webhook.py APPROVED
  --tenant-id=d0000000-...` (corre con `python3.11` del sistema, NO con el venv de la sonda —
  necesita `supabase` y lee la events_key del Vault) → realtime → toast. El webhook apunta a la
  ÚLTIMA fila `payments` del tenant: crear la orden del escenario justo antes de dispararlo.
  Ojo: `unit_price` de la REST es en PESOS y Wompi exige mínimo $1.500.
- **Live-verify de dinero CONTAMINA el dbharness si no se limpia (T7.4, bug auto-infligido)**:
  `tests/dbharness/test_order_receipts.py` cuenta GLOBALMENTE `order_receipts` y asume la tabla
  prístina — cada orden confirmada por la sonda emite un comprobante que SOBREVIVE a la
  cancelación (voided_at, la fila queda). Regla: toda sonda que confirme pedidos DEBE borrar sus
  filas al final (`order_receipts` + `payments` + `order_items` + `orders`; ver
  `cleanup_orders` en `scratch/t7_04_visual_verify.py`). Síntoma: `assert 8 == 1` en
  `test_y_ademas_rls_lo_bloquearia_igual`.

### M2.4 ✅ CERRADO (2026-08-25) — M2 COMPLETO — brief ejecutado

El brief detallado que vivía aquí (ClaimsService: 7 ops, 10 constraints verificadas, protocolo de
migración `reason_detail`, estrategia de paridad) quedó ejecutado tal cual. Ajustes contra el brief
(verificados en ejecución, documentados en la bitácora): (1) `get_claim` usa `maybe_single` en ambos
paths (el test fdoc lo exige: llamada directa al endpoint con chain mockeada — `limit(1)` no
configurado devolvía MagicMock truthy y tragaba el 404); (2) `ClaimPage` no aterrizó — el endpoint
heredado devuelve lista plana y no había consumidor del DTO (YAGNI documentado); (3) la dedup del
writer quedó DEFENSIVA (try/except → se crea) no solo por el patrón del bot: el fake de
`test_claim_create_rbac.py` no implementa `in_` y sin defensiva rompe — verificado. Bitácora
completa: PLAN.md §E (2026-08-25, M2.4).

### Resto del Track 5 (vista rápida)

- **M1-M2 ✅ cerrados (2026-08-24/25 — pilotos pedidos+reclamos completos)**. Quedan: **M3**
  (tooling generativo del bot desde los `contract.py` — dentro del BLOQUE BOT, al final del §Orden),
  M4 (packs de vertical, con founder), M5 (analítica conversacional owner — requiere contexto tenant
  explícito en RPCs de métricas, M1 §H5). Backlog completo de 11 domain services: inventario M1 §4.
- **Con M2 cerrado, el §Orden sigue** (`docs/PLAN-CIERRE.md` §Orden paso 2): **Track 7** (UX/UI consola
  de clase mundial contra Kaiu DS — login animado, módulos pulidos, micro-interacciones con
  framer-motion ya instalado, móvil de primera; `docs/ux/UX-UI.md`) → **Track 3** (infra PRD:
  dominio `api.konvi.co` + Render Projects, pin Python 3.13, dev cloud, G8b media privada) →
  remanentes Track 1/2 [F] (Wompi prod keys, anular guía UAT, legal B6/B3, MeLi S6, M19, WABA
  hygiene, smoke dinero real al cierre) → **Track 4** ops (A1 MFA cuando founder decida) →
  **AL FINAL el BLOQUE BOT** (inventario parche → B-2 dispatcher sobre contratos estables →
  B-4 observabilidad/métricas → bot GUI/API en consola).

### Track 7 — brief de implementación (gap analysis verificado contra `develop` 2026-08-25)

> Derivado con auditoría completa de la consola contra `docs/ux/UX-UI.md` (Kaiu DS).
> **Directiva founder 2026-08-25 (ampliación):** el tratamiento del login NO es una
> referencia aislada — es el **lenguaje de diseño diferencial que debe impregnar TODO
> el front**: logout, cambio de contraseña, módulos y submódulos. La meta no es solo
> "llamativo": es que sea **diferencial frente a cualquier desarrollo genérico**.
> La firma (Kaiu Organic Differential — solo tokens Kaiu, reduced-motion siempre):
> canvas con grano + aurora ambiental (nada de fondos planos en momentos de marca) ·
> brand tile degradado primary→amber + glow como marca de la casa · coreografía de
> entrada (stagger/reveal) en cada superficie · motion físico con propósito
> (layout/pill/celebraciones) · estados con diseño en TODO módulo.
> **Hallazgo central:** gran parte de la Spec WOW §4 YA está implementada (commit
> `894b7357`, 2026-08-02: wrappers `ui/motion.tsx` + command palette ⌘K + drawers vaul
> + carrusel embla + StaggerList en inbox/orders + EmptyState en 14 módulos + 7 error
> boundaries + badge takeover en bottom-nav). **NO rehacer eso.** El trabajo restante,
> ordenado por impacto para ojos de founder:

- **T7.1 — Login memorable animado** ✅ 2026-08-25 (con T7.10 — bitácora PLAN.md §E).
  Estado previo: estático total, logo MOCK (SVG genérico). Ejecutado: escena compartida
  `components/auth/auth-scene.tsx` (grano inline sin terceros + aurora estática + brand
  tile degradado + glow + coreografía stagger/reveal vía wrappers DS) aplicada a las 4
  páginas auth; el mock murió (wordmark K en tile degradado).
- **T7.2 — Motion del chat del inbox** ✅ 2026-08-25 (bitácora PLAN.md §E).
  Ejecutado: `BubbleIn`+`AnimatePresence` (wrappers DS) en `chat-panel.tsx` —
  slide-up 200ms SOLO en burbujas nuevas; hook `useAnimatableMessageIds` (id +
  created_at >= max visto) + `loadedConvId` en `use-messages` (guard de stale
  paint al cambiar de conversación). Verificado live con navegador real
  (`scratch/t7_02_visual_verify.py`): carga sin cascada, dedupe UPDATE sin
  re-mount, reduced-motion fade-only, móvil 390px, ambos temas, 0 errores
  consola. Efecto colateral (fix arquitectónico DS): `useReducedMotionDS`
  hidratación-seguro mata el mismatch SSR/CSR pre-existente de T7.1.
- **T7.3 — Física de navegación y pedidos** ✅ 2026-08-25 (bitácora PLAN.md §E).
  Ejecutado: `NavPill` (layoutId, pill que viaja entre destinos del bottom-nav,
  aria-current y badge intactos) + `LayoutItem` (reubicación suave de cards de
  `orders-manager.tsx` al filtrar — wrapper de TODA card, StaggerItem queda
  dentro para la entrada). Verificado live (`scratch/t7_03_visual_verify.py`):
  viaje con 56 mutaciones translate en cards / 16 en la pill, estático en
  reduced-motion, aria-current viaja, ambos temas. **Bug real cazado por la
  sonda (fix DS):** `StaggerItem` con `variants={undefined}` bajo reduced-motion
  NUNCA reseteaba los valores en vuelo → las listas con StaggerList quedaban
  congeladas en `opacity:0` (invisibles) para usuarios reduced-motion desde
  894b7357. Fix: `itemVariantsReduced` (mismos valores finales, duration 0).
- **T7.4 — Micro-celebraciones de dinero** ✅ 2026-08-25 (bitácora PLAN.md §E).
  Ejecutado: `CelebrationCheck` (DS, pop spring una vez / estático en reduced) +
  `money-celebration.tsx` (detección de transición vía payload UPDATE —
  `orders` tiene REPLICA IDENTITY FULL, `old.status` viaja — + dedupe por
  orden+estado + toast sonner con monto count-up) en home (canal orders
  existente) y detalle de pedido (isla `OrderStatusLive` NUEVA: celebra y
  refresca sin F5 — antes el detalle quedaba estático). Verificado live con
  dinero sandbox real (`scratch/t7_04_visual_verify.py`: orden REST + link
  Wompi sandbox + webhook firmado APPROVED → `confirmed`): toast único con
  monto exacto en home y detalle, badge flips sin F5, reduced estático.
  **Bug DS cazado:** Pressable con `whileTap` emite `tabindex="0"` en SSR →
  mismatch bajo reduced-motion; ahora también usa `useReducedMotionDS`.
- **T7.5 — Topbar con identidad de página** ✅ 2026-08-25 (bitácora PLAN.md §E).
- **T7.6 — Barrido de estados** ✅ 2026-08-25 (bitácora PLAN.md §E). Ejecutado:
  `components/route-error.tsx` NUEVO (superficie única anti-falso-0: retry +
  inicio + digest) + **23 `error.tsx` por ruta** (17 nuevos + 6 migrados;
  integrations cubre providers, settings cubre subrutas) · **barrido EmptyState**
  (~20 sitios en 13 archivos; excluidos a propósito: micro-notas de dropdown
  y la alerta ámbar de proveedores — documentado en UX-UI §6.3) · **skeletons**
  → `ui/skeleton` (14 `loading.tsx` + 4 componentes inbox: conversaciones,
  contexto, notas, imagen). Tests nuevos (3): route-error. Verificado live
  (`scratch/t7_06_visual_verify.py`): 27 rutas renderizan sin errores de
  consola/hidratación + empties en ambos temas + móvil.
- **T7.7 — Virtualización donde paga**: `audit/page.tsx` (miles de filas);
  `conversation-list.tsx` solo si el cursor no basta. Si nada lo justifica → decisión
  documentada y dep `@tanstack/react-virtual` eliminada (no dejar dep muerta).
- **T7.8 — Cobertura de render del DS**: vitest para empty-state, carousel, drawer,
  responsive-dialog, confirm-dialog, skeleton (hoy 5 tests .tsx sobre 27 primitivos).
- **T7.9 (opcional, al final)**: gesto swipe catálogo móvil + carrusel KPI en más módulos.
- **T7.10 — Logout con despedida de marca** ✅ 2026-08-25 (con T7.1 — bitácora PLAN.md §E).
- **T7.11 — Settings/Security con la firma** (directiva): cambio de contraseña, MFA TOTP,
  recovery codes — mismo lenguaje de superficie (cabecera de módulo con identidad,
  revelado stagger, cards con diseño) dentro del canvas dashboard.
- **T7.12 — Cabeceras de módulo con identidad** (directiva "módulos y submódulos"):
  patrón de header de página (título + contexto + micro-motion de entrada) aplicado
  transversal a los 37 `page.tsx` — hoy cada módulo encabeza a su manera; la firma
  exige UN patrón (hermano de lo que T7.5 hace en la topbar móvil).
- **También**: BUG-105-02 del tracker (inbox "no refresca sin F5") — probablemente obsoleto
  (Realtime+polling ya viven en `inbox-manager.tsx:152,180`): verificar live y cerrar entrada.

**Reglas Kaiu inviolables (§4.1):** todo motion pasa por `@/components/ui/motion`
(prohibido `motion` crudo) · solo tokens semánticos (la excepción documentada del login
es la única) · dark probado en cada superficie nueva · 150-300ms · reduced-motion siempre.
**Barra por T7.x:** vitest + tsc + lint → suite completa → `validate.sh --ci` (web
detenido) → verificación visual live STG en AMBOS temas + viewport móvil + reduced-motion
emulado → commits temáticos + CI 5/5 + bitácora PLAN.md §E + UX-UI.md §6/§1.9 al día
(el inventario dice 20 componentes y son 27). **NO tocar backend ni bot** (directiva —
el bloque bot va al final del §Orden).

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
