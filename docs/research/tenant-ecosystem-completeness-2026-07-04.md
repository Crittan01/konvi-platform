# Mapa de Completitud del Ecosistema Tenant — Fase 0 · 2026-07-04

> Generado por workflow multi-agente `tenant-completeness-audit` (run `wf_8d34d5b5-b1d`): 23 auditores (uno por módulo) × 8 dimensiones DoD v2 → refutación adversarial de cada gap critical/high (147 confirmados / 3 refutados) → crítico de puntos ciegos. Evidencia `file:line` en cada gap, verificada a HEAD (`develop`, post-deploy audit 2026-07-03).
> **Lente: COMPLETITUD + UX** (¿está terminado y pulido para cualquier tenant?), NO bug-hunt — los bugs del audit 2026-07-03 ya fueron remediados y desplegados.

**Objetivo founder:** _"Antes de crear el Platform Console, todo el ecosistema tenant debe estar cerrado con el objetivo 100% cumplido, un full stack completo UX/UI, cada módulo y submódulo."_

## DoD v2 — la vara del 100% (aprobada por founder)

8 dimensiones: **funcional** (end-to-end, sin features a medias) · **full-stack** (DB↔API↔UI sin drift) · **UX/UI** (todos los estados, responsive, a11y, design system, copy es-CO) · **tenant+resiliencia** (scoping, rate-limit, errores surfaceados, RBAC) · **tests/UAT** · **performance** (paginación, sin N+1, budgets) · **observabilidad** (logs, audit trail, Sentry-ready) · **operador** (empty states instructivos, primer uso). Sin i18n (es-CO only, decisión YAGNI). Dark mode = decisión de producto, no gap.

## Resumen ejecutivo

- **Completitud promedio del ecosistema: 63%** (rango 50–85%). Ningún módulo está al 100%; ninguno está roto — es distancia de *terminación y pulido*, no de correctitud.
- **Gaps activos: 661** → 11 critical · 138 high (147 confirmados por verificación adversarial; 3 refutados y descartados) · 295 medium · 217 low.
- **Esfuerzo:** 451 S (<½d) · 186 M (½–2d) · 24 L (2–5d) · **0 XL** — no hay monstruos: el cierre es volumen de items pequeños, no reescrituras.
- **Dimensiones sistémicamente débiles (patrón transversal):** `tests_uat` (promedio ~44%) y `performance` en superficies analíticas (fetch-all sin ventana). `design_system` (54%) multiplica gaps de UX en todos los módulos.
- **Lo más maduro:** bot_engine (85%) — el core conversacional es la fortaleza del producto. **Lo más lejos:** finance (50%), metrics (52%), design_system (54%), tenant_onboarding (55%).

## Matriz de completitud — módulo × dimensión (%)

| Módulo | Total | Funcional | Full-stack | UX/UI | Tenant+Resil | Tests/UAT | Perf | Observab | Operador | Gaps C/H conf. |
|---|---|---|---|---|---|---|---|---|---|---|
| Finanzas (P&L, OPEX) | **50%** | 55 | 70 | 50 | 55 | 15 | 38 | 55 | 45 | 10 |
| Analítica · Métricas | **52%** | 55 | 70 | 55 | 65 | 10 | 30 | 35 | 60 | 9 |
| Design system + theming (transversal) | **54%** | 55 | 60 | 45 | 78 | 10 | 85 | 72 | 62 | 5 |
| Onboarding de tenant (provisión→operando) | **55%** | 58 | 55 | 55 | 68 | 45 | 85 | 70 | 40 | 8 |
| Ventas · Reclamos | **57%** | 55 | 62 | 48 | 80 | 55 | 62 | 68 | 45 | 5 |
| Canales · Mercado Libre | **58%** | 48 | 58 | 58 | 85 | 58 | 68 | 70 | 62 | 7 |
| Compras (órdenes a proveedores) | **58%** | 68 | 62 | 52 | 82 | 22 | 50 | 74 | 58 | 4 |
| IA · Base de Conocimiento | **58%** | 55 | 48 | 55 | 65 | 45 | 80 | 70 | 65 | 10 |
| Analítica · Auditoría | **58%** | 58 | 55 | 58 | 72 | 42 | 75 | 55 | 48 | 3 |
| Ventas · Despachos (Aveonline) | **60%** | 62 | 58 | 55 | 78 | 45 | 70 | 62 | 58 | 5 |
| Configuración · Integraciones | **61%** | 62 | 55 | 58 | 70 | 45 | 85 | 55 | 72 | 10 |
| Dashboard (home operativo) | **62%** | 78 | 68 | 66 | 72 | 20 | 52 | 55 | 58 | 6 |
| WhatsApp Templates (HSM) | **62%** | 55 | 62 | 65 | 82 | 58 | 80 | 68 | 52 | 8 |
| Inbox conversacional | **65%** | 66 | 72 | 64 | 70 | 52 | 58 | 80 | 64 | 8 |
| Configuración · General+Legal+Retención | **65%** | 62 | 55 | 70 | 62 | 60 | 90 | 58 | 68 | 6 |
| Configuración · Usuarios y Acceso | **66%** | 82 | 70 | 60 | 76 | 20 | 80 | 40 | 75 | 9 |
| Auth (login→sesión completa) | **66%** | 72 | 78 | 58 | 75 | 40 | 88 | 62 | 65 | 5 |
| Ventas · Pedidos | **68%** | 68 | 74 | 62 | 85 | 70 | 62 | 80 | 60 | 5 |
| Productos · Catálogo+Inventario unificado | **68%** | 66 | 73 | 62 | 70 | 65 | 60 | 72 | 76 | 7 |
| IA · Agentes IA | **68%** | 66 | 60 | 72 | 80 | 55 | 72 | 55 | 85 | 6 |
| Ventas · Contactos (CRM + Habeas Data) | **72%** | 72 | 70 | 72 | 82 | 65 | 55 | 85 | 78 | 4 |
| Configuración · Seguridad/MFA | **74%** | 88 | 84 | 68 | 76 | 45 | 95 | 62 | 78 | 4 |
| Bot conversacional (orchestrator) | **85%** | 86 | 78 | 90 | 90 | 84 | 85 | 92 | 75 | 3 |

---

## Detalle por módulo

### Finanzas (P&L, OPEX) — 50%

_MVP funcional con escritura auditada, pero la cifra central (Ingresos) cuenta pedidos NO pagados, el fetch es full-table sin límite (números se truncan silenciosamente al crecer), los errores de guardado se tragan mostrando "Guardado", y la UI viola paleta/tema — un tenant no puede confiar aún en sus números sin explicación externa._

**Gaps critical/high (10):**

- ✅ `[critical·S·funcional]` **Ingresos Netos incluye pedidos no pagados (pending/pending_payment) pese a que la card dice 'De pedidos pagados'**
  - apps/web/app/dashboard/finance/_components/finance-dashboard.tsx:63-64 solo excluye status==='cancelled'; los estados reales son pending|pending_payment|confirmed|processing|shipped|delivered|cancelled (services/api/routers/orders.py:48). Carritos abandonados en pending inflan revenue y margen. Copy contradictoria en finance-dashboard.tsx:107 ('De pedidos pagados').
- ✅ `[high·M·funcional]` **Sin editar ni anular gastos: un typo en monto queda para siempre y distorsiona el P&L**
  - services/api/routers/expenses.py:5 declara 'Solo existe creación (no edición/borrado de gastos)'; el router solo tiene POST (expenses.py:29). La UI no tiene columna de acciones (expenses-manager.tsx:88-125). No hay flujo de corrección auditado.
- ✅ `[high·S·ux_ui]` **Violación masiva de la regla de paleta: texto/borders con shades 400-500 fluorescentes en todos los KPIs y el formulario**
  - finance-dashboard.tsx:103 (text-blue-500), 106-107 (text-blue-500), 116-119 (text-amber-500), 126-129 (text-red-500), 133-141 (text-green-500/text-red-500, border-b-green-500/red-500); expenses-manager.tsx:50 (border-red-500/30), 66 (text-red-500 + border-red-500/30), 117 (text-red-500). Regla founder: texto/borders con 700, nunca 300-500.
- ✅ `[high·S·ux_ui]` **Gráfico con colores hardcodeados de tema oscuro sobre design system claro (Kaiu Cream): grid casi negro, tooltip negro #111**
  - finance-dashboard.tsx:156 (stroke='#2a2a2a'), 157 (tick fill '#888'), 160 (contentStyle backgroundColor '#111', border '#333'). El tema global es claro (apps/web/app/globals.css:18 --background #F8F5F1) — el tooltip se ve como pegado de otra app.
- ✅ `[high·M·tenant_resiliencia]` **addExpense traga todos los fallos y el operador SIEMPRE ve 'Guardado' aunque el gasto no se creó (403, 500, timeout, sin token)**
  - apps/web/app/dashboard/finance/actions.ts:11,20,24 retornos silenciosos; línea 30-40 fetch sin verificar res.ok; línea 42 catch { /* non-fatal */ }; components/ui/submit-button.tsx:31-37 muestra savedText al terminar pending sin conocer el resultado. No hay patrón ActionResult.
- ✅ `[high·M·tests_uat]` **Router expenses sin tests: RBAC 403 de operator, audit_log insertado, categoría inválida, expense_date default — todo sin red de regresión**
  - tests/test_coherence_pact.py:141-143 es la única referencia a ExpenseCreate (subset de schema); grep 'expense' en tests/ no encuentra ningún test funcional del endpoint (comparar con tests/test_coupons_router.py, test_settings_api.py que sí testean sus routers).
- ✅ `[high·M·tests_uat]` **Lógica de cálculo P&L (revenue/COGS/OPEX/margen + filtros de tiempo) sin ningún test — es exactamente donde vive el bug crítico de estados**
  - finance-dashboard.tsx:29-76 toda la lógica de negocio está inline en el componente sin extraer a lib testeable; apps/web solo tiene 4 archivos .test.* (mfa-recovery-cookie, marketplace-badges, attribute-contract, category-tree) — ninguno de finance.
- ✅ `[high·M·performance]` **Full-table fetch de orders + order_items + expenses de todo el histórico sin .limit() ni ventana: con >1000 pedidos PostgREST trunca y el P&L queda silenciosamente incorrecto**
  - page.tsx:25-28 select de orders con join order_items sin filtro temporal ni límite; page.tsx:33-37 igual para expenses; el filtro temporal es 100% client-side (finance-dashboard.tsx:48-56) aunque el default es 'Mes Actual'. Métricas sí acota server-side (metrics/page.tsx:69 .gte('created_at', since)). Falta RPC de agregación o ventana por searchParams.
- ✅ `[high·S·observabilidad]` **addExpense falla en silencio total: catch vacío sin console.error/Sentry y sin propagar — cero señal en producción**
  - apps/web/app/dashboard/finance/actions.ts:42 'catch { /* non-fatal */ }' sin logging; tampoco loguean los early-returns de validación/token (líneas 11, 20, 24). Comparar con services/api/routers/expenses.py:53 que sí loguea con tenant.
- ✅ `[high·S·operador]` **COGS=$0 silencioso cuando el tenant no ha cargado costos en Catálogo: el margen sale 100% inflado sin advertencia ni CTA hacia donde se corrige**
  - finance-dashboard.tsx:66-67 el comentario reconoce 'Si unit_cost es 0, históricamente no teníamos costo. Lo manejamos como COGS 0' pero la UI no muestra ningún banner/aviso cuando X% de items tienen unit_cost=0, ni enlaza a /dashboard/catalog donde vive cost_price.

**Medium/low:** 16 medium · 7 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Definición canónica de 'ingreso' para Finanzas: ¿qué estados de pedido cuentan como venta (confirmed+, delivered, COD cobrado)? Hoy Finanzas cuenta todo excepto cancelled y Métricas solo delivered — deben converger en UNA definición de negocio
- ⚖️ ¿Los gastos son inmutables tipo libro contable (entonces cerrar el bypass RLS de UPDATE/DELETE y ofrecer 'gasto de reversa') o editables con audit trail? Hoy la inmutabilidad es solo omisión de UI/API
- ⚖️ Alinear matriz de permisos 2026-07-02: ¿la ESCRITURA de gastos es owner-only (como la página) o owner+manager (como hoy permiten action y API)?
- ⚖️ Profundidad del P&L prometido: ¿basta snapshot por período o el módulo debe incluir tendencia mensual, desglose OPEX por categoría y export CSV para el contador? Define si los gaps funcional #3-5 son alcance o backlog
- ⚖️ ¿Gastos recurrentes (nómina, suscripciones) se re-registran a mano cada mes o se automatizan/recuerdan? Hoy es 100% manual sin recordatorio, lo que degrada la fidelidad del OPEX con el tiempo

**Código muerto detectado:**
- 🪦 apps/web/app/dashboard/finance/page.tsx:20 — canWrite = role==='owner'||role==='manager' es siempre true: la línea 16 ya redirigió a todo no-owner; la rama canWrite=false de ExpensesManager (expenses-manager.tsx:42) es inalcanzable
- 🪦 apps/web/app/dashboard/finance/page.tsx:22 — const meta re-deriva tenant_id de app_metadata cuando tenantId ya vino de getCachedTenantMeta (línea 14); doble fuente para el mismo dato
- 🪦 apps/web/app/dashboard/finance/page.tsx:27 — campos id y unit_price de order_items se fetchean pero FinanceOrder (finance-dashboard.tsx:10-15) nunca los consume

**Ya sólido (no re-trabajar):** Escritura de gastos vía Core API con @audit_log(entity_type='expense', action='created') + require_write_role server-side (services/api/routers/expenses.py:29-37) — la traza forense contable existe y fue un fix deliberado (F2.2) · Guard de acceso en 3 capas coherentes para lectura: sidebar roles:['owner'] (sidebar-client.tsx:88) + redirect server-side para no-owner (finance/page.tsx:16) + RLS por tenant · Integridad COGS end-to-end verificada: cost_price de la variante se snapshotea a order_items.unit_cost al crear la orden (services/api/routers/orders.py:248), y los pedidos del bot pasan por el mismo Core API (payment_link_tool.py:671-673) — no hay path que deje unit_cost sin poblar por diseño · Scoping multi-tenant correcto en todas las queries del módulo: .eq('tenant_id', …) explícito en web (page.tsx:28,36) y API (expenses.py:41), conforme ADR-0025

### Analítica · Métricas — 52%

_Demo-completo pero no production-done: KPIs se truncan silenciosamente a 1000 filas (rompe "datos correctos a escala"), ventanas temporales inconsistentes entre KPIs, charts diseñados para dark theme en un app claro, y cero tests del módulo._

**Gaps critical/high (9):**

- ✅ `[critical·L·funcional]` **KPIs incorrectos a escala: fetch de filas crudas sin limit/count, PostgREST trunca a 1000 filas silenciosamente**
  - apps/web/app/dashboard/(analytics)/metrics/page.tsx:66-74 — las 7 queries (messages, conversations, orders, order_items, contacts, products, claims) traen filas completas para contar/sumar en JS sin .limit() ni count:'exact'; supabase/config.toml:18 max_rows=1000. Un tenant con >1000 mensajes/30d (trivial en WhatsApp commerce) ve 'Mensajes: 1000' e ingresos parciales sin ningún aviso. Mismo patrón en app/api/insights/route.ts:189-193 (el LLM analiza datos truncados). El propósito canónico del módulo es 'KPIs de negocio con datos correctos a escala' — esto lo bloquea.
- ✅ `[critical·L·performance]` **Todo el módulo cuenta y suma en JS sobre filas crudas: 7 full-fetches por render, payloads sin acotar, y agregaciones (revenue, byStatus, itemTotals, msgsPerDay) que deberían ser SQL**
  - page.tsx:66-74 (fetch) + 84-141 (agregación en JS); period='all' usa since=epoch (page.tsx:62-64) → trae la historia completa del tenant en cada visita. order_items (page.tsx:70) es full-table siempre. Solución natural: count:'exact' head:true para conteos + RPC/vista con GROUP BY para revenue/top-productos. (Mismo gap raíz que el critical de funcional — el truncamiento a 1000 es el síntoma, esto es la causa.)
- ✅ `[high·S·funcional]` **Ventanas temporales inconsistentes: conversaciones y contactos son all-time bajo un header que dice 'Últimos 30 días'**
  - page.tsx:68 (conversations sin .gte('created_at', since)) y page.tsx:71 (contacts selecciona solo id, imposible filtrar); page.tsx:94-96 calcula conversionRate = pedidos-del-período / conversaciones-all-time → la tasa cae artificialmente con el tiempo. Mismo mismatch en app/api/insights/route.ts:192+204 (conversion_rate para el LLM).
- ✅ `[high·S·funcional]` **'Top 5 productos vendidos' ignora el filtro de período e incluye ítems de pedidos cancelados**
  - page.tsx:70 — order_items sin .gte('created_at', since) ni join a orders.status; page.tsx:107-114 suma todo el historial. Con period=7 la tabla muestra ventas de toda la vida, incluyendo cancelados (revenue inflado). order_items tiene created_at (supabase/migrations/20260409220000_fase9_schema_core.sql:51), el filtro es directo.
- ✅ `[high·M·ux_ui]` **Violación masiva de la regla de paleta: 28 usos de Tailwind shades 300-500 en texto/borders sobre fondo claro crema**
  - page.tsx:12-18 (STATUS_COLORS con text-yellow-400/text-blue-400/etc + borders 500/30), page.tsx:174-203 (KPI cards text-blue-400, text-emerald-400, text-violet-400, text-red-400), page.tsx:279-281 (medallas top-productos text-yellow-400/slate-400/orange-400), page.tsx:299-325 (sección reclamos text-red-400/amber-400/emerald-400/green-400); components/ai-insight-panel.tsx:28-30 (PRIORITY_STYLES 400s) y 104-107,150-152. El tema del app es claro (globals.css:18 --background #F8F5F1 crema) → 400s son fluorescentes/ilegibles. Regla founder: usar 700.
- ✅ `[high·S·ux_ui]` **Charts estilizados para dark theme en app claro: grid blanco invisible y paleta de pie con hexes 400 fluorescentes**
  - metrics-charts.tsx:28 — CartesianGrid stroke='rgba(255,255,255,0.06)' (blanco al 6% sobre crema = invisible); metrics-charts.tsx:11 — COLORS=['#a3e635','#facc15','#60a5fa','#f472b6','#34d399','#f87171'] (lime/yellow/blue/pink/emerald/red-400, todas prohibidas por la regla de paleta y de bajo contraste en claro).
- ✅ `[high·S·tenant_resiliencia]` **Errores de query silenciados: si cualquier query Supabase falla, el módulo muestra KPIs en 0 como si fueran datos reales, sin ningún aviso al operador**
  - page.tsx:76-82 — los 7 resultados se consumen como (res.data ?? []) sin revisar res.error jamás; un fallo RLS/red/timeout renderiza 'Pedidos: 0, $0 en ventas' indistinguible de un negocio sin ventas. Viola el patrón de errores surfaceados.
- ✅ `[high·S·tenant_resiliencia]` **/api/insights sin rate limit ni cooldown: cada clic (y cada 'Regenerar') es una llamada Gemini facturable, spameable por cualquier owner/manager**
  - app/api/insights/route.ts:210-289 — POST sin ningún control de frecuencia; el patrón in-memory por tenant ya existe en el repo en app/api/ai/preview/route.ts:14-31 (20/hora + respuesta 429 con minutos restantes) y no se aplicó aquí. ai-insight-panel.tsx:136 expone botón Regenerar sin throttle.
- ✅ `[high·M·tests_uat]` **Ningún test de la lógica de agregación de KPIs ni del route /api/insights (auth, RBAC, módulo inválido, parse de Gemini, truncamiento)**
  - Búsqueda exhaustiva: apps/web/**/*.test.* = 4 archivos, ninguno del módulo; tests/ (pytest) no contiene tests del web route. La lógica de negocio (conversionRate, openClaims, itemTotals, ventanas temporales) vive inline en el server component page.tsx:84-141 sin extraer a funciones testeables — los 3 bugs de ventana temporal de este audit habrían sido atrapados por tests unitarios triviales.

**Medium/low:** 11 medium · 6 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Semántica de 'ventas': definir si el KPI '$X en ventas' debe incluir pedidos pending/pending_payment (hoy solo excluye cancelled, page.tsx:90-91) o solo pedidos con pago confirmado — impacta cómo el comerciante lee su negocio
- ⚖️ Política de consumo IA de insights: cuota por tenant/plan, cooldown de regeneración y si se persiste el último análisis — hoy es ilimitado, efímero y sin accounting
- ⚖️ Destino del insight 'inventory': exponerlo en /dashboard/catalog (el fetcher ya existe) o eliminar la rama muerta del route
- ⚖️ Cierre del drift D3 (render.yaml:81): mover la superficie Gemini del web al servicio api, decisión ya anotada como planeada pero sin ejecutar — /api/insights y /api/ai/preview duplican invocación REST cruda a Gemini desde Next.js
- ⚖️ Timezone canónica de negocio: fijar America/Bogota para todas las agregaciones temporales del console (afecta Métricas, Auditoría, Finanzas) en vez de heredar la TZ del servidor

**Código muerto detectado:**
- 🪦 app/api/insights/route.ts:23-50 + 137-156 — módulo 'inventory' completo (prompt + fetcher) sin ningún caller en UI: AiInsightPanel solo se monta con module=orders|contacts|metrics; /dashboard/catalog no lo renderiza
- 🪦 apps/web/app/dashboard/(analytics)/metrics/metrics-charts.tsx:24 — rama 'Sin datos.' de MessagesBarChart inalcanzable: page.tsx:122 siempre construye barData con 7 elementos
- 🪦 app/api/insights/route.ts:191 — columna total_amount seleccionada en el fetcher de metrics pero nunca agregada al payload (el LLM nunca ve revenue)

**Ya sólido (no re-trabajar):** Aislamiento multi-tenant ejemplar: las 7 queries de página y todos los fetchers de /api/insights llevan .eq('tenant_id', ...) explícito sobre cliente de sesión con RLS (patrón canónico ADR-0025) — verificado contra schema real, sin columnas fantasma · RBAC en triple capa coherente: sidebar (sidebar-client.tsx:104 roles owner/manager), guard server-side con redirect en la página (page.tsx:55-56) y 403 en el route (insights/route.ts:219-220) · AiInsightPanel con máquina de estados completa (idle/loading/error/done), human-in-the-loop a demanda, retry, timeout 30s (route.ts:249) y expectativa de costo comunicada al usuario — patrón AI-assist bien aterrizado · loading.tsx dedicado con skeleton que refleja el layout real de la página

### Design system + theming (transversal) — 54%

_Base shadcn/Radix sólida con tema Kaiu coherente, pero el DS cubre una minoría del vocabulario UI real (tablas/selects/chips/confirms hand-rolleados), la regla de paleta 300-500 está violada 465 veces y codificada en tailwind.config, Inter nunca se carga en runtime, y hay 0 tests de primitivos._

**Gaps critical/high (5):**

- ✅ `[high·L·funcional]` **Cobertura de primitivos insuficiente: la app hand-rollea tablas, selects, checkboxes, tooltips y skeletons**
  - apps/web/components/ui/ contiene solo 12 archivos (sin table/checkbox/switch/tooltip/dropdown-menu/toast/skeleton/alert). Consumo real: 9 archivos con <table> crudo (p.ej. app/dashboard/(products)/catalog/_components/catalog-table.tsx), 22 archivos con <select> nativo vs 4 con ui/select, 8 archivos con type="checkbox" nativo (p.ej. app/dashboard/(settings-group)/settings/payment-methods-form.tsx), 88 tooltips vía title= (p.ej. app/dashboard/inbox/_components/conversation-list.tsx:104), skeletons ad-hoc con animate-pulse en 16 archivos
- ✅ `[high·S·fullstack]` **Inter declarada pero jamás cargada: la tipografía del DS no existe en runtime**
  - apps/web/app/globals.css:7 declara --font-inter: 'Inter' y tailwind.config.ts:23 la mapea a font-sans, pero app/layout.tsx:14-18 no importa next/font, no hay archivos de fuente en public/ ni <link> a fuentes — grep 'next/font' en app/ → 0 resultados. Todo el producto cae al fallback system-ui y se ve distinto por OS
- ✅ `[high·L·ux_ui]` **Regla de paleta violada 465 veces en 66 archivos: text/border con shades 300-500 sobre canvas crema**
  - grep (text|border)-*-(300|400|500) en app/+components/ → 465 ocurrencias / 66 archivos. Casos en flujo principal sobre fondo claro: app/dashboard/(settings-group)/team/page.tsx:40-62 (text-amber-400/text-blue-400/text-slate-400 en chips de rol), app/login/page.tsx:88-92, app/forgot-password/forgot-password-form.tsx:44-48, components/ai-insight-panel.tsx:27-31 (componente compartido por 4 módulos), components/ui/submit-button.tsx:45 (text-emerald-400 en primitive core)
- ✅ `[high·S·ux_ui]` **tailwind.config codifica la violación: redefine emerald/amber 300-500 con '+brillo, +saturación' global**
  - apps/web/tailwind.config.ts:26-39 — comentario literal 'Emerald y Amber más claros/vibrantes que los defaults… Afecta globalmente todos los usos'. amber-400 pasa a #fcd53a, que sobre el canvas crema #F8F5F1 rinde ~1.4:1 de contraste (ilegible); contradice frontalmente la regla del founder
- ✅ `[high·M·tests_uat]` **0 tests de components/ui/** y el harness excluye la carpeta: testing de componentes imposible tal como está configurado**
  - apps/web/vitest.config.ts:7-10 — include: ['app/**/*.test.{ts,tsx}', 'lib/**/*.test.{ts,tsx}'] (components/ fuera del patrón) + environment: 'node'; package.json sin @testing-library/* ni jsdom. Solo existen 3 tests co-locados de lógica pura (lib/mfa-recovery-cookie.test.ts, catalog/_lib/*)

**Medium/low:** 11 medium · 7 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Dark mode / theming: NO existe hoy (darkMode:["class"] configurado sin bloque .dark, sin toggle, 5 variantes dark: inertes). Decidir: implementar tema oscuro real o remover la config y variantes para que el código no mienta.
- ⚖️ Alcance de la regla de paleta 300-500: definir si aplica también sobre fondos oscuros (sidebar/topbar/chips translúcidos bg-*-500/10). Sin criterio binario, el sweep de las 465 ocurrencias no puede ejecutarse de forma determinística ni lint-earse (candidato a regla ESLint tipo tenant-filter).
- ⚖️ Patrón de feedback global: adoptar toast (p.ej. sonner) como canal único de éxito/error de mutaciones vs mantener mensajes inline por pantalla. Hoy conviven 3 patrones (inline, SubmitButton, confirm() nativo).
- ⚖️ Formalizar el DS como contrato: hoy la adopción decae por ausencia de catálogo (Badge 1 uso, Select 4 vs 22 raw, Accordion 0). Decidir si se documentan variantes/tokens mínimos y se completan primitivos faltantes (Table, Checkbox, Tooltip, DropdownMenu, Skeleton) o se acepta hand-rolling permanente.
- ⚖️ Tipografía oficial: confirmar si Inter es la fuente del producto (y cargarla vía next/font con subset latino) o formalizar system-ui como decisión y limpiar --font-inter.

**Código muerto detectado:**
- 🪦 apps/web/components/ui/accordion.tsx — 0 imports en toda la app
- 🪦 apps/web/components/ui/badge.tsx:20-24 — variantes success y warning con 0 usos (grep variant="success"|"warning" → 0)
- 🪦 apps/web/app/globals.css:50 — token --sidebar-bg definido y nunca referenciado (sidebar-gradient usa literales)
- 🪦 apps/web/app/globals.css:137-159 — .animate-fade-in y .animate-slide-up + sus keyframes: 0 usos en tsx
- 🪦 apps/web/tailwind.config.ts:5 — darkMode: ["class"] inerte + 5 variantes dark: nunca activables (mass-importer.tsx:315,328; context-panel.tsx:206-207; ai-agents/page.tsx:343)
- 🪦 apps/web/tests/marketplace-badges.test.mjs — huérfano: ni vitest ni validate.sh ni CI lo ejecutan
- 🪦 apps/web/tailwind.config.ts:14-20 — config container (center/padding/2xl) sin usos de la clase container en el dashboard

**Ya sólido (no re-trabajar):** Arquitectura de tokens limpia y coherente: HSL CSS vars (globals.css:6-51) mapeadas 1:1 en tailwind.config.ts:40-73 con rationale documentado del tema 'Kaiu Organic' — foreground #224438 sobre crema #F8F5F1 es contraste AAA real · Primitivos Radix con a11y baseline correcta: focus-visible ring-2 ring-ring consistente en Button/Input/Textarea/Select/Tabs/Dialog/Sheet, estados disabled uniformes, portales y animaciones data-[state] bien hechas · Shell responsive real: sidebar con drawer móvil completo (hamburger + overlay + cierre al navegar, sidebar-client.tsx:216-267) con aria-labels en es-CO ('Abrir menú'/'Cerrar menú') · SubmitButton con micro-UX pending/saved vía useFormStatus adoptado en 11 pantallas — patrón de botón de guardado unificado (solo le falta el canal de error)

### Onboarding de tenant (provisión→operando) — 55%

_La maquinaria de provisión (script + RPC + endpoint F3 + connector Model B) es sólida, pero el camino del tenant nuevo se rompe en la puerta principal: el form WhatsApp del hub omite app_secret/verify_token (conexión que nunca recibirá mensajes), las URLs de webhook mostradas son incorrectas, y toda la documentación de onboarding describe el modelo Meta descartado — proceso aún artesanal, no cerrado._

**Gaps critical/high (8):**

- ✅ `[critical·M·funcional]` **Hub 'Conectar WhatsApp' usa form legacy de 3 campos — conexión inservible bajo Model B**
  - apps/web/app/dashboard/(settings-group)/integrations/_components/integrations-manager.tsx:431-449 (form solo waba_id + phone_number_id + access_token) + page.tsx:284-337 (saveWhatsApp marca status='connected' sin app_secret ni verify_token). El connector exige verify_token per-tenant para el handshake de Meta (services/connector-whatsapp/routers/webhook.py:39-52) y app_secret para HMAC (línea 77). El form correcto de 6 campos (whatsapp-credentials-form.tsx) solo es alcanzable vía 'Gestionar panel completo' que aparece ÚNICAMENTE en la rama connected (integrations-manager.tsx:373-384). Un tenant nuevo queda 'Conectado' pero el bot jamás recibe mensajes.
- ✅ `[critical·M·operador]` **La única guía de onboarding WhatsApp para tenants describe el modelo superseded (Modelo A) — no existe guía Model B**
  - docs/onboarding/whatsapp-tenant-setup.md:75-88 (Paso 3: 'Conectar Konvi App a tu Business Portfolio', App ID 819229210624423) y :116-124 (form de 3 campos) contradicen ADR-0023 (docs/adr/0023...md:37-44: cada tenant crea SU PROPIA Meta App con 6 credenciales + webhook per-tenant). Un tenant que siga la guía autoriza la app equivocada y jamás llega al form F3. No existe la guía Model B (crear Meta App propia, BV + App Review propios ~2-5 semanas, configurar webhook /webhook/{tenant_id}).
- ✅ `[high·M·funcional]` **Submit de plantillas HSM a Meta es solo-script-admin; la UI instruye al operador a correr Python**
  - apps/web/.../whatsapp/_components/whatsapp-templates.tsx:233-234 ('submitealo a Meta vía script submit_template_to_meta.py') y :347 ('El submit a Meta para review es manual'). El script es scripts/admin/submit_template_to_meta.py (requiere SUPABASE_SERVICE_ROLE_KEY — un operador tenant no puede ejecutarlo).
- ✅ `[high·S·fullstack]` **URL de webhook Wompi del panel apunta a ruta inexistente (y contradice al hub)**
  - wompi-setup.tsx:97 muestra 'https://api.konvi.co/api/v1/wompi/webhook' pero la ruta real es /api/v1/webhooks/wompi (services/api/main.py:173 prefix '/api/v1/webhooks' + routers/wompi_webhook.py:39 '/wompi'). El hub muestra la correcta 'https://konvi-api.onrender.com/api/v1/webhooks/wompi' (integrations-manager.tsx:773). Tenant que copie la del panel → confirmaciones de pago 404 para siempre.
- ✅ `[high·S·fullstack]` **URL de webhook Telegram del panel apunta a ruta inexistente**
  - telegram-setup.tsx:71 muestra '/api/v1/telegram/webhook'; la ruta real es /api/v1/integrations/telegram/webhook (services/api/main.py:181 prefix '/api/v1/integrations' + routers/telegram_webhook.py:40).
- ✅ `[high·M·ux_ui]` **60 violaciones de paleta (texto/borders con shades 300-500) en el hub de integraciones**
  - grep en apps/web/.../integrations/: 60 hits en integrations-manager.tsx (ej. :215 text-green-400, :242-244 text-red-400, :254-257 text-emerald-400, :265-267 text-red-300/90, :352 emerald-400, :615-618 text-amber-400, :832-836 emerald-400), aveonline-setup.tsx:326,370 (text-amber-300) y disconnect-button.tsx. Regla founder: texto/borders con 700, nunca 300-500 fluorescentes.
- ✅ `[high·M·tests_uat]` **provision_tenant (script y RPC) sin ningún test**
  - grep 'provision' en tests/ y apps/web/__tests__ = 0 hits. El único flujo que crea tenants en producción no tiene red de regresión (ni del RPC vía mock, ni del _resolve_owner, ni del dry-run).
- ✅ `[high·M·operador]` **Runbook interno de onboarding esquelético y desactualizado — el 'proceso cerrado' no está documentado en ningún lado**
  - docs/operations/onboarding-tenants.md (última actualización 2026-04-21, 25 líneas): describe crear filas a mano; no menciona provision_tenant.py, el RPC, credenciales WhatsApp/Wompi/Aveonline, carga de catálogo, plantillas, ni criterios de verificación. docs/onboarding/H1-H5-checklist.md:91-203 también describe trámites del modelo Tech Provider cancelado (transferir Konvi App, App Review de Konvi).

**Medium/low:** 13 medium · 9 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ ADR-0023 Phase 7 (founder, ~5h en Meta dashboards: regenerar tokens + actualizar webhooks Konvi App y KAIU Chat + smoke E2E) sigue PENDING — bloquea producción real de ambos tenants y de cualquier tenant nuevo.
- ⚖️ Definir host público canónico de webhooks (OQ-4 ADR-0023): ¿api.konvi.co apunta al connector o al API? ¿subdominios separados (wa.konvi.co / api.konvi.co)? Hasta decidirlo, las URLs mostradas en la UI no pueden corregirse de forma definitiva.
- ⚖️ Decidir el destino del form WhatsApp legacy de 3 campos del hub: eliminarlo y enrutar al form F3 de 6 campos, o reemplazarlo in-place. Hoy coexisten dos paths de conexión con capacidades distintas.
- ⚖️ Decidir si el submit de plantillas HSM a Meta será self-service en UI (endpoint owner-gated) o permanece admin-script — hoy la UI promete algo que solo el founder puede ejecutar.
- ⚖️ DPA de custodia del App Secret tenant→Konvi (OQ-1 ADR-0023, legal externo) sin template — requisito antes de onboardear el primer tenant externo real.
- ⚖️ Definir la política de entrega de credenciales del owner (password temporal impresa vs magic-link/reset de Supabase) y si se fuerza cambio en primer login.

**Código muerto detectado:**
- 🪦 scripts/seed_tenant_zero.py — seed legacy con credenciales hardcodeadas (admin@commerce.local / SuperSecurePassword123!), superseded por provision_tenant.py; solo referenciado en docs/research/ecosystem-master-plan-2026-07-01.md.
- 🪦 docs/setup/meta_whatsapp_manual_setup.md — instruye setear META_APP_SECRET/META_VERIFY_TOKEN globales en .env, eliminados del runtime por ADR-0023 (criterio de éxito #3: 0 hits de META_APP_SECRET en el connector).
- 🪦 wompi-setup.tsx:57-84 — SetupFields 'Public key' e 'Integrity key' que ningún flujo de escritura alimenta (siempre '—').
- 🪦 whatsapp-setup.tsx:96-103 — botón 'Copiar' sin onClick (UI muerta).
- 🪦 docs/onboarding/H1-H5-checklist.md secciones H2-H4 — trámites del modelo Tech Provider cancelado por ADR-0023 (transferir Konvi App, App Review de Konvi para servir tenants).

**Ya sólido (no re-trabajar):** RPC provision_tenant transaccional y bien blindado: SECURITY DEFINER + REVOKE PUBLIC/anon/authenticated + GRANT solo service_role, valida inputs, plan_code con FK real a billing_plans (supabase/migrations/20260702190000_f3_provision_tenant.sql). · Script admin con dry-run, reuso de usuario auth existente, password temporal random y mensaje claro de siguiente paso (scripts/admin/provision_tenant.py). · Endpoint F3 /whatsapp/credentials impecable en su capa: RBAC owner/manager, rate-limit, @audit_log, Vault idempotente (update-in-place de secret_id, cero secretos huérfanos), shape EXACTO que el connector lee (services/api/routers/integrations.py:91-147) + 3 tests. · Connector Model B per-tenant completo: verify_token + HMAC por tenant, caches TTL, métricas /health/metrics, 10 tests HMAC (ADR-0023 Phases 1-6+8 cerradas).

### Ventas · Reclamos — 57%

_El ticket básico funciona end-to-end (bot + consola) con aislamiento multi-tenant sólido, pero el módulo cumple 1 de sus 3 promesas (tickets sí; devoluciones/disputas sin superficie), es inusable en móvil, tiene drift RBAC operator UI↔API y su madurez de primer uso es baja._

**Gaps critical/high (5):**

- ✅ `[high·S·funcional]` **La búsqueda no encuentra por número de ticket — el identificador que el bot da al cliente**
  - apps/web/app/dashboard/(sales)/claims/_components/claims-manager.tsx:86-89 filtra solo por order.id y nombre/teléfono; el bot instruye comunicar el ticket # al cliente (services/ai-orchestrator/agentic/tools/claims.py:226-228), así que el flujo 'cliente cita su ticket → operador lo busca' falla.
- ✅ `[high·M·funcional]` **Estados terminales irreversibles y sin confirmación previa**
  - claims-manager.tsx:242 oculta todas las acciones cuando status∈{refunded,rejected}; los botones Reembolsar/Rechazar (:251-262) ejecutan al primer click sin diálogo de confirmación. Un misclick deja el ticket bloqueado sin camino de reapertura en UI (el API sí aceptaría PATCH status).
- ✅ `[high·S·fullstack]` **RBAC drift: operator ve 'Nuevo Reclamo' pero el API le responde 403**
  - apps/web/app/dashboard/(sales)/claims/page.tsx:13 canWrite=['owner','manager','operator'], pero services/api/routers/claims.py:137 usa require_write_role con WRITE_ROLES={'owner','manager'} (services/api/dependencies/auth.py:56,178). El propio docstring del router (claims.py:8) dice '[owner, manager, operator]'. Un operator (justo el rol de soporte) llena el formulario y recibe 403.
- ✅ `[high·M·ux_ui]` **Detalle de reclamo inaccesible en móvil — tap en card no muestra nada**
  - claims-manager.tsx:217 `lg:col-span-2 hidden lg:flex`: bajo el breakpoint lg el panel de detalle no se renderiza y no existe Sheet/Drawer alternativo; seleccionar una card (:191) solo cambia el ring. Ver motivo, notas o resolver desde el teléfono es imposible.
- ✅ `[high·M·operador]` **'Reembolsar' no mueve dinero y nada se lo dice al operador**
  - claims-manager.tsx:251-255 botón 'Reembolsar' + :266-270 badge 'Reembolso efectuado'; la tabla claims es tracking-only ('Sin afectación directa a cash flow', supabase/migrations/20260413150000_claims.sql:2) y no existe integración ni guía hacia el refund manual en Wompi. El operador puede creer que el cliente ya recibió su dinero.

**Medium/low:** 16 medium · 8 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ rma_requests / retracto Art. 47: la tabla completa (lifecycle 9 estados, deadlines legales, inspección) sigue sin un solo writer ni reader — decidir entre (a) construir la gestión de devoluciones dentro de Reclamos (writers bot + UI operador) o (b) eliminar la tabla y formalizar que el retracto se opera vía escalación Telegram + proceso manual. Hoy es esquema muerto que sugiere una capacidad que no existe.
- ⚖️ Semántica de 'Reembolsar': ¿queda como marca contable manual (tracking-only, con copy que lo aclare y checklist Wompi) o debe encadenarse con el flujo de refund Wompi (registro de txn_id, evidencia)? El copy actual 'Reembolso efectuado' afirma algo que el sistema no hizo.
- ⚖️ RBAC canónico de creación de reclamos: el docstring del router y la UI dicen que operator puede crear; WRITE_ROLES dice que no. Decidir si operator (rol de soporte de primera línea) crea tickets — y alinear API o UI en consecuencia.
- ⚖️ ¿Las cancelaciones/retractos escalados (order_cancellations.escalated_to_operator=true) se muestran dentro de Reclamos como cola de trabajo del operador, o Telegram queda como único canal? El código del dispatcher promete 'visibilidad operador en panel' que ningún panel cumple.

**Código muerto detectado:**
- 🪦 services/api/routers/claims.py:107-127 — GET /api/v1/claims/ (list_claims) sin ningún consumidor: la web lee Supabase directo en RSC y el bot va directo a DB
- 🪦 services/api/routers/claims.py:163-179 — GET /api/v1/claims/{id} sin consumidores
- 🪦 services/api/routers/claims.py:215-238 — POST /{id}/resolve sin consumidores (la UI usa PATCH y nunca envía 'resolved')
- 🪦 services/api/routers/claims.py:50-59 — COMMON_REASONS: no valida nada y la UI usa keys distintas; documentación muerta que además contradice al frontend
- 🪦 supabase/migrations/20260606000000_cancellation_and_retracto.sql — tabla rma_requests + enum rma_status_enum: cero productores y cero lectores en todo el repo (única referencia: lista de borrado en services/api/lib/tenant_offboarding.py:77)

**Ya sólido (no re-trabajar):** Vocabulario de status unificado en 4 capas (API VALID_STATUSES, tool bot, UI STATUS_MAP, CHECK constraint DB) con test de pacto que lo protege: tests/test_a3_a4_nivel5.py:54-87 + migración 20260624010000_claims_status_check.sql · Escrituras SIEMPRE vía API con RBAC + rate-limit (RL_WRITE_DEFAULT) + @audit_log en POST/PATCH/resolve — cierre real del drift D1 (services/api/routers/claims.py:130-131,182-183,215-216) · Aislamiento multi-tenant en profundidad: .eq tenant_id en RSC (page.tsx:25,32), validación order-pertenece-al-tenant en el router (claims.py:91-102), RLS app_current_tenant() (migración 20260416000000), exenciones de lint justificadas inline · ticket_number secuencial per-tenant con trigger DB + backfill (migración 20260417000003) — referencia legible que el bot comunica al cliente

### Canales · Mercado Libre — 58%

_Listings/vinculación es sólido y seguro, pero la pata "órdenes MeLi" está rota a HEAD (guards maybe_single omitidos), el sync de precio prometido es incompleto y falta pulido UX (sin loading, paleta 300-500, cap 100 items "próximamente")._

**Gaps critical/high (7):**

- ✅ `[critical·S·funcional]` **Ingesta de órdenes MeLi rota para órdenes nuevas: maybe_single() sin guard None**
  - services/api/routers/meli_webhook.py:518-522 — `existing = ...maybe_single().execute()` seguido de `if existing.data:`. El commit 54e87218 (F-doc) verificó contra el source de postgrest 2.28.3 que maybe_single() retorna None (el objeto completo) en 0 filas; con orden nueva (caso principal) existing=None → AttributeError → la orden nunca se crea. Mismo patrón sin guard en _process_shipment (línea 604-608) y en el lookup de order_tracking (649-664: el primer insert de tracking siempre cae al except de línea 671 → tracking nunca se persiste). El guard correcto SÍ existe en la línea 356 del mismo archivo.
- ✅ `[high·S·funcional]` **Importar con 'Sin categoría' seleccionada explícitamente rompe el import**
  - apps/web/app/dashboard/(channels)/marketplace/_components/marketplace-manager.tsx:587 ofrece `<SelectItem value="_none">Sin categoría</SelectItem>` pero handleImport (línea 179) pasa `selectedCategoryId || undefined` sin mapear '_none' → llega "_none" a marketplace.py:660-670 que hace .eq("id", "_none") sobre columna UUID → error postgrest no manejado → 500. Solo funciona si el usuario nunca toca el dropdown.
- ✅ `[high·M·funcional]` **Sync de precio prometido sin camino propio: cambio de precio en catálogo nunca se propaga a MeLi**
  - .context/00-product.md:45 promete 'sync catálogo/stock/precio'. services/api/routers/products.py:556-560 solo dispara sync_meli_stock `if "stock_quantity" in data` (cambio de precio solo, no sincroniza). En la UI el botón Sync solo aparece con stock desincronizado (marketplace-manager.tsx:354 `item.is_linked && stockOutOfSync`) y la tabla nunca compara precio catálogo vs precio MeLi → drift de precio invisible e infixeable desde la consola. meli_client.update_item_price (línea 576) existe y nadie lo llama.
- ✅ `[high·M·funcional]` **Paginación de listings incompleta: cap duro de 100 items con promesa 'próximamente' en producción**
  - services/api/routers/marketplace.py:194 `get_user_items(user_id, access_token, limit=100, offset=0)` hardcoded (el cliente soporta offset, meli_client.py:431-438). marketplace-manager.tsx:437-441 muestra 'La paginación completa estará disponible próximamente.' Un seller con >100 publicaciones no puede ver ni vincular el resto; la búsqueda es client-side sobre los 100 cargados.
- ✅ `[high·M·fullstack]` **Órdenes MeLi sin columna channel/source: correlación por string en notes**
  - supabase/migrations/20260409220000_fase9_schema_core.sql:25-36 — orders no tiene columna source/channel. meli_webhook.py:511 codifica `notes = f"MeLi order #{id} · vendedor: {nickname}"` y los lookups dependen de match exacto (línea 517 .eq("notes", notes)) y LIKE prefix (línea 603). Si el operador edita las notas desde Pedidos, los updates de status/shipment crean duplicados o se pierden; en Pedidos la orden MeLi es indistinguible de una manual.
- ✅ `[high·S·ux_ui]` **Sin loading.tsx: navegación bloqueada hasta 12s sin feedback (todas las rutas hermanas lo tienen)**
  - apps/web/app/dashboard/(channels)/marketplace/ solo contiene page.tsx, actions.ts y _components/ (verificado con find); orders, contacts, catalog, knowledge-base, ai-agents, metrics, settings, integrations y team SÍ tienen loading.tsx. page.tsx:63 usa AbortSignal.timeout(12000) en el fetch server-side a MeLi → hasta 12s de pantalla congelada al entrar.
- ✅ `[high·M·tests_uat]` **_process_order/_process_shipment sin ningún test: el crash maybe_single habría sido cazado**
  - grep de '_process_order|_process_shipment' en tests/ retorna vacío. El flujo más crítico del módulo (creación de orden + decremento stock + tracking) no tiene red de regresión; test_meli_webhook_origin.py y test_meli_webhook_alert_and_dedup.py solo cubren perímetro (IP/dedup).

**Medium/low:** 14 medium · 9 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Paginación >100 publicaciones: decidir entre offset server-side con pager en UI vs sincronizar listings a DB local (cambia la arquitectura del módulo: hoy es 100% live contra MeLi API)
- ⚖️ Columna channel/source en orders (y badge 'MeLi' en Pedidos): decisión de modelo de datos que afecta Pedidos, webhook y reportería — hoy la correlación es por texto en notes
- ⚖️ Política de sync de precio: ¿push automático a MeLi al cambiar precio en catálogo (riesgo de sobrescribir promos gestionadas en MeLi) o solo manual con indicador de drift?
- ⚖️ Restitución de stock ante cancelación de orden MeLi: ¿automática (riesgo con devoluciones parciales/reclamos) o tarea manual del operador?
- ⚖️ Import/vinculación masiva para onboarding: ¿vale la inversión L ahora o el onboarding admin-controlado actual (provision_tenant) lo absorbe operativamente?

**Código muerto detectado:**
- 🪦 services/api/integrations/meli_client.py:576 update_item_price — definido, cero callers en el repo
- 🪦 marketplace-manager.tsx:39,45 — campos meli_variation_id y synced_at del tipo MeliItem: la API nunca los envía y la UI nunca los renderiza
- 🪦 apps/web/lib/marketplace-badges.js:1 — status 'error' en ATTENTION_STATUSES: ningún writer de marketplace_listings.status lo escribe jamás
- 🪦 services/api/routers/meli_webhook.py:624 — rama `elif not existing.data` inalcanzable: con 0 filas existing es None y la línea 608 crashea antes
- 🪦 services/api/routers/meli_webhook.py:56-69 — _normalize_phone_e164 wrapper DEPRECATED con TODO de renombre pendiente (deuda declarada rev. 104)

**Ya sólido (no re-trabajar):** Perímetro del webhook robusto y testeado: allowlist de IPs oficiales MeLi con override por env, rate-limit 200/min por IP, dedup distribuido vía RPC meli_webhook_seen con fallback local, y alerta proactiva por umbral de rechazos (meli_webhook.py:80-234 + 3 archivos de tests) · Aislamiento multi-tenant consistente: .eq('tenant_id') en todas las queries, exemptions AST justificadas por comentario, rollbacks del import con tenant filter, y test_tenant_scoping.py cubre el lookup del sync · RBAC completo en ambas capas: require_write_role en las 5 mutaciones + canWrite en UI, con test dedicado (test_rbac_marketplace_agents.py) · Habeas Data en contactos MeLi maduro: consent_source/notice_version/evidence + consent_audit_log append-only, con phone canónico unificado (meli_webhook.py:381-491, test_rev103_meli_contact_import.py)

### Compras (órdenes a proveedores) — 58%

_El flujo núcleo (proveedor → OC → recibir → stock+WAC) opera end-to-end con seguridad multi-tenant sólida, pero el módulo es un MVP sin pulir: proveedores solo-alta, cero tests de comportamiento, paleta prohibida en el flujo principal, sin filtros/paginación/índices y drift de schema latente que bloqueará borrados de variantes._

**Gaps critical/high (4):**

- ✅ `[high·M·funcional]` **Proveedores solo-alta: no existe editar ni eliminar/desactivar**
  - services/api/routers/purchases.py:111-147 (solo GET/POST suppliers, sin PATCH/DELETE) + apps/web/app/dashboard/purchases/_components/suppliers-manager.tsx:82-106 (cards sin acción de edición). Un typo en email/teléfono/lead_time es permanente; un proveedor extinto queda para siempre en el selector de OCs (purchase-orders-manager.tsx:109).
- ✅ `[high·S·fullstack]` **FK ON DELETE SET NULL sobre columnas NOT NULL: borrar una variante comprada romperá el DELETE en Catálogo**
  - supabase/migrations/20260413000001_finance_polish.sql:14-22 cambia purchase_order_items.variation_id a ON DELETE SET NULL, pero la columna sigue NOT NULL (tests/fixtures/db_schema_canonical.json: variation_id nullable=NO; igual purchase_orders.supplier_id líneas 4-12). El hard-delete de variante existe (services/api/routers/products.py:623-655): al borrar una variante referenciada por cualquier PO histórica, PostgreSQL intentará SET NULL sobre NOT NULL → violación de constraint → el borrado en Catálogo falla con 500. La intención de preservar histórico quedó a medias.
- ✅ `[high·S·ux_ui]` **Paleta prohibida (shades 300-500) en texto/borders por todo el flujo principal**
  - purchase-orders-manager.tsx:149 text-red-400 (trash), :185-187 text-green-500/text-red-500/text-blue-500 (badges de estado), :207 text-red-500 + border-red-500/20 (botón Cancelar Orden), :168 border-amber-500/20 (banner sin proveedores). Regla founder: texto/borders nunca 300-500, usar 700.
- ✅ `[high·M·tests_uat]` **Cero tests de comportamiento del router: WAC, receive idempotente, cancel guard, RBAC**
  - grep de _compute_wac/purchase_restock/receive_purchase en tests/ solo devuelve tests/test_coherence_pact.py:156-170, que valida únicamente que los campos Pydantic existan como columnas. La fórmula WAC (purchases.py:100-106) y la transición idempotente (purchases.py:292-298) — que mutan stock y costo real del tenant — no tienen ni un caso de prueba.

**Medium/low:** 22 medium · 12 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Visibilidad RBAC de Compras: ¿owner-only (como dice el sidebar, sidebar-client.tsx:85 — coherente con que expone costos) o owner+manager (como permiten API y página)? Hoy las capas se contradicen y un manager opera por URL directa sin entrada de menú.
- ⚖️ Recepción parcial e 'in_transit': el CHECK de DB ya contempla ambos, pero API/UI son todo-o-nada. Decidir si el ciclo de vida se expande (draft→ordered→in_transit→received parcial) o si se poda el schema para que DB refleje el producto real.
- ⚖️ Gestión de proveedores: ¿se habilita editar/desactivar (soft-delete preservando histórico)? Requiere primero resolver la contradicción FK SET NULL vs NOT NULL de purchase_orders.supplier_id.
- ⚖️ Los 3 endpoints GET del router purchases: ¿se mantienen como contrato para consumo futuro (orchestrator/reporting) o se elimina la superficie no consumida? Mantenerlos sin tests ni consumidor es deuda silenciosa.
- ⚖️ Numeración humana de OCs (consecutivo OC-001 per tenant) para que el operador pueda citarla al proveedor — hoy solo hay prefijo de UUID.

**Código muerto detectado:**
- 🪦 services/api/routers/purchases.py:111-125 — GET /suppliers sin ningún consumidor (la UI lee suppliers directo vía RSC Supabase en page.tsx:24-28)
- 🪦 services/api/routers/purchases.py:152-171 — GET / (listado de OCs con filtros status/supplier_id) sin consumidor
- 🪦 services/api/routers/purchases.py:217-240 — GET /{po_id} (detalle con items) sin consumidor: no hay vista de detalle en la UI
- 🪦 apps/web/app/dashboard/purchases/_components/purchases-client.tsx:10-11,18-23 — props tenantId y role declarados en el tipo y pasados desde page.tsx:73-74 pero descartados en el destructuring
- 🪦 apps/web/app/dashboard/purchases/_components/purchase-orders-manager.tsx:179 — fallback 'Proveedor Eliminado' para un estado inalcanzable (no existe delete de supplier y el FK SET NULL violaría el NOT NULL)
- 🪦 supabase/migrations/20260413000000_purchases_and_finance.sql:33 — estados 'draft' e 'in_transit' del CHECK de purchase_orders inalcanzables desde API y UI (DEFAULT 'draft' nunca usado: el API siempre inserta 'ordered')
- 🪦 apps/web/app/dashboard/purchases/page.tsx:38,53 — columnas price y stock_quantity seleccionadas y nunca consumidas por los tipos del cliente

**Ya sólido (no re-trabajar):** Aislamiento multi-tenant impecable: cada query del router filtra .eq('tenant_id') y valida ownership de supplier y variations ANTES de crear (purchases.py:68-97,185-186); RLS + WITH CHECK aplicado (20260702120000_f0_rls_with_check.sql:30-34) · WAC determinístico server-side con saneo de stock negativo y guard de división por cero (purchases.py:100-106); total de la OC calculado en servidor contra manipulación del cliente (purchases.py:188) · Idempotencia real de transiciones: UPDATE condicionado a status='ordered' evita doble recibo y doble cancelación (purchases.py:253-259,292-298) · RBAC (require_write_role) + rate-limit (RL_WRITE_DEFAULT) + audit_log en las 4 mutaciones (purchases.py:128-129,174-175,243-244,269-270); drift D2 cerrado — writes van por el API, no directo a Supabase desde RSC (actions.ts:12-14)

### IA · Base de Conocimiento — 58%

_Núcleo RAG/CRUD sólido y bien aislado por tenant, pero NO cerrado: editar un doc recategoriza o pierde cambios en silencio (categorías legacy en la UI), el botón "Preparar para IA" indexa con un modelo de embedding retirado e incompatible con el que usa el bot, y ningún error de mutación llega al operador._

**Gaps critical/high (10):**

- ✅ `[critical·S·funcional]` **Editar un documento pierde cambios o lo recategoriza a FAQ en silencio (categorías legacy en doc-card)**
  - apps/web/app/dashboard/(ai)/knowledge-base/doc-card.tsx:20-26 usa valores 'politica','producto','general' (taxonomía pre-rev.68) mientras el API valida {faq,negocio,politicas,productos,envios,pagos} (services/api/routers/knowledge_base.py:43) y la DB tiene CHECK constraint (migración 20260429000001:41-43). Efecto doble: (a) seleccionar 'Políticas'/'Productos'/'General' envía valor inválido → PATCH 422 → updateDocument solo hace console.error y redirect (page.tsx:183-184) → el operador pierde TODA la edición sin feedback; (b) al editar un doc con categoría 'politicas'/'productos'/'envios'/'pagos', el <select defaultValue> no matchea ninguna option → el browser selecciona la primera ('faq') → guardar título recategoriza el doc a FAQ sin que el usuario lo pida.
- ✅ `[critical·S·fullstack]` **Drift de modelo de embedding: apps/web indexa con gemini-embedding-001 (retirado 2026-07-14) mientras el bot consulta con gemini-embedding-2**
  - apps/web/app/api/ai/index-pending/route.ts:11-12,19 y apps/web/app/api/ai/preview/route.ts:10 hardcodean 'gemini-embedding-001', mientras services/ai-orchestrator/llm_embed.py:52-57 y render.yaml:210-211,328-329 fijan gemini-embedding-2 para api/orchestrator. El propio llm_embed.py:49-51 advierte 'CRÍTICO — CAMBIAR EL MODELO EXIGE RE-EMBEBER... vectores viejos incompatibles → RAG roto'. Efecto: docs indexados vía el botón 'Preparar para IA' (index-pending-banner.tsx:19) quedan en espacio vectorial incompatible con las queries del bot → similarity basura silenciosa; y tras el retiro del modelo (2026-07-14, a 10 días) el botón falla con 404. El swap Fase 6 olvidó estas 2 rutas web (render.yaml:81-83 ni siquiera lista index-pending en la deuda D3).
- ✅ `[high·M·funcional]` **'Eliminar' es soft-delete: el cap de 30 docs nunca se libera y el doc 'eliminado' reaparece como Inactivo**
  - services/api/routers/knowledge_base.py:240-250 (DELETE = is_active=false + embedding NULL, la fila persiste) + :124-131 (cap cuenta TODAS las filas sin filtrar is_active). page.tsx:344 dice 'Elimina alguno para agregar nuevos' pero eliminar no reduce totalCount (page.tsx:139 cuenta allDocs.length). Además la página lista docs inactivos (page.tsx:110-116 sin filtro is_active) → el doc 'Eliminado' reaparece como card 'Inactivo' con botón 'Activar'. A los 30 docs el módulo queda bloqueado permanentemente.
- ✅ `[high·S·funcional]` **Plantillas starter dejan vacías las categorías 'envios' y 'pagos' — contradice el sistema de markers anti-alucinación**
  - apps/web/app/dashboard/(ai)/knowledge-base/starter-templates.ts:18 ('Métodos de pago aceptados' → category:'faq'), :31 ('Tiempos de entrega' → category:'faq'); 5 de 9 plantillas van a 'faq' y NINGUNA usa 'envios' ni 'pagos'. Tras cargar las 9, el form sigue mostrando '⚠️ vacía' (new-doc-form.tsx:56-59) y el bot inyecta marker 'sin información configurada' para consultas de pagos/envíos (services/ai-orchestrator/tools/kb_tool.py:191-193) aunque la info SÍ existe en FAQ — señales contradictorias al LLM y al operador.
- ✅ `[high·S·fullstack]` **Enum de categorías legacy también en templates-section: badges muestran slug crudo y className 'undefined'**
  - apps/web/app/dashboard/(ai)/knowledge-base/templates-section.tsx:8-18 (CATEGORY_COLORS/LABELS con keys 'politica','producto','general') vs starter-templates.ts que usa 'politicas','productos' → en :110-111 CATEGORY_COLORS[t.category] es undefined (clase literal 'undefined') y el label cae al slug crudo 'politicas'/'productos' en las cards de plantillas de devoluciones, garantía y cuidado.
- ✅ `[high·S·ux_ui]` **Regla de paleta del founder violada en los 7 componentes: 27+ usos de text/border con shades 300-500**
  - grep sobre el módulo: page.tsx:262,266,273,342 (text-amber-400, text-emerald-400, text-green-400, border-green-500/30, border-amber-500/30); doc-card.tsx:29-33,100,132 (text-blue-400/purple-400/green-400/orange-400, text-emerald-400/500); templates-section.tsx:9-12; index-pending-banner.tsx:31-50 (text-amber-400 x5); embed-retry-button.tsx:25; new-doc-form.tsx:57,70,106 (text-amber-500, text-red-500); kb-migration-banner.tsx:65-66. La regla exige shade 700 para texto/borders.
- ✅ `[high·M·ux_ui]` **Botones muestran éxito ('Eliminado', 'Guardado', 'Activado') aunque el backend haya rechazado la operación**
  - Las 6 server actions solo hacen console.error y siguen (page.tsx:166,183,197,212,221,243) → SubmitButton muestra savedText de éxito (doc-card.tsx:75,131,143,154) tras un 422/403/409/502. Un operator (403) ve 'Eliminado' y nada cambió; un 409 de cap al cargar plantillas no muestra nada (loadSelectedTemplates hace break silencioso, page.tsx:242-245).
- ✅ `[high·M·tenant_resiliencia]` **Cero surfacing de errores: las 6 server actions tragan 409/422/403/502 con console.error**
  - page.tsx:166,183,197,200,212,221,243 — ninguna action retorna estado al cliente ni usa el patrón ActionResult; el 409 del cap (knowledge_base.py:131-135), el 422 de categoría y el 502 de reindex (knowledge_base.py:275-279) mueren en logs del server. El operador no puede distinguir éxito de fallo.
- ✅ `[high·M·tests_uat]` **0 tests de endpoints para services/api/routers/knowledge_base.py**
  - grep en tests/ solo halla test_coherence_pact.py:174-179 (subset de campos Pydantic vs schema) — no existe ningún test TestClient del CRUD: cap 409 (knowledge_base.py:131), 422 de categoría (:66-71), RBAC 403, reindex 502 (:275-279), semántica soft-delete (:240-250), fallback embedding NULL (:146-147).
- ✅ `[high·M·operador]` **El ciclo de vida del documento es ilegible para el operador: Eliminar ≡ Desactivar**
  - doc-card.tsx:138-158 ofrece 'Desactivar' y 'Eliminar' como acciones distintas pero ambas dejan el doc visible como 'Inactivo' con botón 'Activar' (backend knowledge_base.py:240-250 + page.tsx sin filtro is_active); un operador nuevo no puede predecir qué hace cada botón ni recuperar cupo del límite.

**Medium/low:** 11 medium · 8 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Semántica de 'Eliminar': decidir entre hard-delete real o que el cap de 30 cuente solo docs activos — hoy el cupo es un ratchet irreversible y la UI promete lo contrario ('Elimina alguno para agregar nuevos')
- ⚖️ Cierre real del drift D3: mover /api/ai/index-pending (y /api/ai/preview, /api/insights) al servicio api y retirar GEMINI_API_KEY del web — render.yaml:81-83 lo reconoce como deuda pero el comentario ni siquiera lista index-pending
- ⚖️ Recategorizar/ampliar las plantillas starter para cubrir las 6 categorías rev.68 (hoy 'envios' y 'pagos' quedan vacías incluso cargando todas) — requiere curaduría de contenido, no solo código
- ⚖️ Visibilidad del módulo para rol operator: la página implementa modo lectura (canWrite) pero el sidebar lo oculta a operators (sidebar-client.tsx:93-95) — decidir si es read-only visible o exclusivo owner/manager y alinear ambas capas
- ⚖️ Nombre visible del módulo: el árbol canónico L1 y el sidebar dicen 'Base de Conocimiento'; el h1 de la página dice 'Knowledge Base' — decidir y unificar (es-CO manda según el producto)

**Código muerto detectado:**
- 🪦 services/api/routers/knowledge_base.py:91-110 y :159-175 — GET / (list) y GET /{id} sin ningún consumidor en el repo: la Console lee kb_documents directo de Supabase (page.tsx:110-123); superficie API muerta o no adoptada
- 🪦 services/api/dependencies/embeddings.py:30 — import de get_embedding_model_version con comentario 'noqa: F401 — usado por API endpoints' que es falso: ningún endpoint lo usa
- 🪦 supabase/migrations/20260527010000_kb_embedding_model_version.sql — columna embedding_model_version + índice parcial sin un solo escritor en todo el repo (router, ruta web index-pending y scripts/admin/reembed_kb_documents.py:92-94 no la setean)
- 🪦 apps/web/app/dashboard/(ai)/knowledge-base/index-pending-banner.tsx:12 — estado result seteado y jamás leído (const [, setResult]); el window.location.reload() de :24 lo vuelve inalcanzable
- 🪦 apps/web/app/dashboard/(ai)/knowledge-base/doc-card.tsx:20-34 y templates-section.tsx:8-18 — mapas de categorías de la taxonomía pre-rev.68 ('politica','producto','general'); 'general' ya ni existe en DB

**Ya sólido (no re-trabajar):** RAG híbrido maduro: semántico pgvector top-3 + boost determinístico por categoría con triggers léxicos + markers anti-alucinación cuando falta la categoría (services/ai-orchestrator/tools/kb_tool.py:145-197), con doble vía al bot (inyección en prompt orchestrator.py:7634-7639 + tool agentic kb_query knowledge.py:48-118) · Cascada de embeddings robusta y compartida: retries transitorios con backoff 1-16s, salto a fallback en model-unavailable, cache LRU 256/5min, archivos byte-equal api/orchestrator con test de paridad de hash (llm_embed.py + tests/agentic/test_llm_embed_cascade.py, 8 tests) · Contratos de límites alineados en las 3 capas: MAX 30 docs / 120 título / 3000 contenido idénticos en page.tsx:15-17 y knowledge_base.py:44-46, más CHECK constraint de 6 categorías en DB (20260429000001) validado por test de pacto (test_coherence_pact.py:174-179) · Seguridad de mutaciones completa en el router: require_write_role + RL_WRITE_DEFAULT (120/min) + @audit_log en POST/PATCH/DELETE/reindex + .eq('tenant_id') en cada query (lint AST baseline 0, ADR-0025); embedding server-side cerró la exposición de GEMINI_API_KEY en el flujo principal (rev. 72)

### Analítica · Auditoría — 58%

_Núcleo consultable y seguro (tenant-scoping + RBAC owner + MFA en export) pero el trail tiene huecos de cobertura en las mutaciones más sensibles (equipo/stock), 2 filtros muertos por drift de entity_type, y el pulido es-CO/operador está incompleto — usable por el founder, no listo para "cualquier tenant sin que nadie le explique"._

**Gaps critical/high (3):**

- ✅ `[high·M·funcional]` **Mutaciones de Usuarios y Acceso (invite/changeRole/remove/inactivate/activate) NO escriben audit_log — el trail no puede responder 'quién cambió accesos'**
  - apps/web/app/dashboard/(settings-group)/team/page.tsx:140-345 — los 6 server actions mutan tenant_users + auth.admin (signOut/deleteUser/ban) directamente sin write_audit_event; los endpoints auditados services/api/routers/settings.py:195 (PATCH /team, role_changed) y :233 (DELETE /team) existen pero NO tienen callers desde la UI
- ✅ `[high·S·fullstack]` **Chips muertos por drift: UI filtra 'kb_document' pero la API escribe 'kb_doc', y 'inventory' no tiene writer — ambos filtros devuelven siempre vacío y los eventos kb_doc se muestran sin label**
  - apps/web/app/dashboard/(analytics)/audit/page.tsx:11 ('kb_document') y :14 ('inventory') vs services/api/routers/knowledge_base.py:114,179,232,254 (@audit_log entity_type="kb_doc") y cero ocurrencias de entity_type='inventory' en todo el repo
- ✅ `[high·M·tests_uat]` **Cero tests para /api/audit/export (formato CSV, escaping de comillas, filtros, guard owner, cap 5000) y para la página (redirect no-owner, filtros combinados)**
  - apps/web/tests/ contiene solo marketplace-badges.test.mjs; los únicos *.test.ts del frontend son mfa-recovery-cookie, attribute-contract y category-tree; ningún test en tests/ referencia audit/export ni /dashboard/audit

**Medium/low:** 15 medium · 8 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ ¿Las mutaciones del bot/orchestrator (pedidos creados por conversación, consent, escalaciones) deben aparecer en Auditoría o solo acciones humanas? Hoy el trail es exclusivamente humano-vía-API; el bot tiene trazas paralelas (consent_audit_log, stock_movements, shadow log) invisibles en este módulo
- ⚖️ 'Log de acceso' del árbol funcional (.context/00-product.md:57): ¿surfacear pii_access_log y/o logins en Auditoría, o corregir el árbol para que prometa solo 'log de cambios'?
- ⚖️ Retención de audit_log: definir ventana (¿12/24 meses?) y si entra al módulo de retención per-tenant o se archiva a Storage — hoy crece sin límite hasta el offboarding
- ⚖️ ¿El capability de plan 'analytics.audit.export' debe enforcearse server-side (página + route) o el módulo es de todos los planes y el capability sobra?
- ⚖️ ¿El detalle del evento debe evolucionar a diff before/after legible (lo que promete el schema y el docstring del decorator) o basta el snapshot post-operación actual?

**Código muerto detectado:**
- 🪦 supabase/migrations/20260509010000_unified_audit_view.sql — vw_consent_events_unified creada 'para uso del operador / SIC reporting' pero sin ningún consumidor en apps/web ni services (solo una mención en comentario de contacts.py:536)
- 🪦 services/api/routers/settings.py:195 (PATCH /team/{member_user_id}) y :233 (DELETE /team/{member_user_id}) — endpoints team auditados sin callers: la UI de team usa server actions propias que mutan directo
- 🪦 apps/web/app/dashboard/(analytics)/audit/page.tsx:11,14 y app/api/audit/export/route.ts:36-37 — entries 'kb_document' e 'inventory' de ENTITY_LABELS: ningún writer produce esos entity_type a HEAD
- 🪦 apps/web/app/dashboard/(analytics)/audit/page.tsx:105 — condición role === 'owner' siempre true (los no-owner ya fueron redirigidos en línea 58)
- 🪦 apps/web/app/dashboard/(analytics)/audit/page.tsx:32 — formatAction .replace('.', ' → ') para acciones dotted ('order.status_changed') que el decorator actual nunca emite (solo posible data histórica pre-rev.72)

**Ya sólido (no re-trabajar):** Aislamiento y RBAC server-side reales: .eq('tenant_id') en página (page.tsx:75) y export (route.ts:22) + RLS en audit_log + guard owner en ambas capas (fix F0 commit 5883ca40) + sidebar gated a owner · MFA AAL2 enforceada también sobre /api/audit/export vía middleware F85 (middleware.ts:81-105) — el export dejó de ser bypasseable con sesión solo-password · Write-side maduro: decorator @audit_log uniforme adoptado en 15 routers / 17 entity_types, fire-and-forget con warning logueado (dependencies/audit.py:83-85), y 14 tests unitarios en tests/test_audit_decorator.py · Remediación F2.2 cerró los writes directos sin auditar de catalog/claims/purchases/categories — hoy pasan por la API auditada (comentarios trazables en actions.ts de cada módulo)

### Ventas · Despachos (Aveonline) — 60%

_Estimador de tarifas sólido, seguro e idempotente end-to-end, pero la mitad "guías y tracking" del módulo no tiene superficie en la consola (estados webhook sin traducir, sin links de guía/rastreo, sin retry de guía para pagos Wompi) y el router/cliente Aveonline carecen de red de tests._

**Gaps critical/high (5):**

- ✅ `[high·S·funcional]` **Guía y rastreo invisibles para el operador: label_url y tracking_url nunca se muestran en ninguna UI**
  - apps/web/app/dashboard/(sales)/shipping/page.tsx:75 el select omite label_url/tracking_url (solo trae tracking_number); grep de label_url|tracking_url en apps/web devuelve 0 usos en UI, mientras services/api/routers/wompi_webhook.py:1586-1588 sí los escribe en shipments. El operador no puede descargar el PDF de la guía ni abrir el rastreo del carrier desde la consola.
- ✅ `[high·M·funcional]` **Guía fallida post-pago Wompi (pending_generation) no tiene camino de retry en la consola**
  - services/api/routers/wompi_webhook.py:1558 persiste shipment status='pending_generation' "para que operador intervenga", pero apps/web/app/dashboard/(sales)/orders/_components/orders-manager.tsx:430-433 muestra el botón 'Generar guía COD' SOLO si payment_method==='cod' && status==='confirmed'; el endpoint services/api/routers/orders.py:831-854 sí acepta cualquier método de pago. Una orden pagada por Wompi cuya guía falló queda sin affordance de reintento en Pedidos ni en Despachos.
- ✅ `[high·S·fullstack]` **Enum de estados desincronizado: la UI no conoce 5 estados que sí se escriben en shipments.status**
  - apps/web/app/dashboard/(sales)/shipping/page.tsx:31-38 STATUS_LABELS cubre {quoted,labeled,picked_up,in_transit,delivered,cancelled}, pero los escritores reales producen 'pending'/'exception'/'returned' (services/api/routers/aveonline_webhook.py:60-94 vía fn_record_shipment_tracking_event), 'simulated' (wompi_webhook.py:1584) y 'pending_generation' (wompi_webhook.py:1558) → esos chips se renderizan como texto crudo en inglés con color fallback (page.tsx:214,244). Además 'picked_up' no lo escribe nadie.
- ✅ `[high·S·ux_ui]` **Violación regla de paleta: texto/borders con Tailwind shades 300-500 en todo el módulo**
  - page.tsx:23-28 chips (text-yellow-400/text-blue-400/text-purple-400/text-indigo-400/text-green-400/text-red-400 + border-*-500/30), page.tsx:151-156 banner text-amber-400, page.tsx:178 text-indigo-400, page.tsx:182 text-emerald-400; shipping-quote-form.tsx:278-282 text-amber-400, :335 text-red-400, :368-370 border-emerald-500/blue-500, :378-379 text-emerald-400/text-blue-400. Solo el badge COD (form:402) cumple con amber-700.
- ✅ `[high·M·tests_uat]` **Endpoints POST /shipping/quote y PATCH /{id}/rate sin tests de endpoint**
  - tests/test_a3_a4_nivel5.py:40-51 solo hace asserts sobre el TEXTO fuente del insert (columnas reales); no existe ningún test con TestClient/mocks que ejerza quote_shipment ni confirm_rate (grep 'quote_shipment|confirm_rate' en tests/ = 0) — la transición status='quoted', el sync de orders.shipping_cost y los mapeos de error Aveonline→HTTP no tienen red de regresión.

**Medium/low:** 15 medium · 12 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ ¿El cotizador debe exponer valor declarado/contenido (input real) o se acepta que el estimador diverja de la guía real (default $50.000 vs order.total_amount)?
- ⚖️ ¿El tracking merece timeline visible en la consola (shipment_tracking_events ya persiste todo con RLS lista) o basta el chip de estado? Define la mitad del alcance 'tracking' del módulo.
- ⚖️ ¿Dónde vive el retry de guía fallida (pending_generation) para órdenes Wompi: botón en Pedidos (quitando la restricción COD-only), en Despachos, o auto-retry? Hoy no existe ningún camino en consola.
- ⚖️ ¿Purga de cotizaciones huérfanas: cron automático, botón en UI, o eliminar el endpoint? Con el bot cotizando por el mismo endpoint, la tabla crece sin límite.
- ⚖️ Naming canónico: el árbol L1 (.context/00-product.md:37) dice 'Despachos', el sidebar dice 'Cotizador' — tras la decisión 'estimador puro' (63b18087) hay que alinear árbol, sidebar y H1 en una sola dirección.
- ⚖️ ¿Distinguir cotizaciones generadas por el bot vs operador en el historial (columna source en shipments)? Afecta la legibilidad del módulo en tenants con bot activo.

**Código muerto detectado:**
- 🪦 services/api/routers/shipping.py:622-646 — DELETE /shipping/orphans: endpoint sin caller (ni UI, ni cron, ni script)
- 🪦 services/api/integrations/aveonline_client.py:1016-1051 — list_webhooks(): sin ningún caller en el repo
- 🪦 services/api/integrations/aveonline_client.py:1134-1172 — get_estado(): sin ningún caller en el repo
- 🪦 apps/web/app/dashboard/(sales)/shipping/page.tsx:25,34 — status 'picked_up' en STATUS_COLORS/STATUS_LABELS: ningún escritor lo produce (solo health_metrics.py:281 lo lee)
- 🪦 apps/web/app/dashboard/(sales)/shipping/shipping-quote-form.tsx:248-254 y 417-421 — fastestIdx y render de rate.delivery_date: rama muerta con Aveonline (el mapeo backend nunca emite delivery_date)
- 🪦 apps/web/app/dashboard/(sales)/shipping/page.tsx:208 — rama del ternario `Conecta Envia`: inalcanzable porque activeProvider es const 'aveonline' (page.tsx:60)
- 🪦 services/api/routers/shipping.py:8 — docstring de GET /shipping/history: el endpoint no existe (drift documental en código)

**Ya sólido (no re-trabajar):** Aislamiento multi-tenant impecable en las 3 capas: todas las queries llevan .eq('tenant_id', tid) (page.tsx:76-88, shipping.py:579-600, aveonline_webhook.py:249-253) — coherente con ADR-0025 · Idempotencia end-to-end en quote y confirm-rate: Idempotency-Key generada en UI (lib/idempotency.ts) + begin/finalize/abort + replay con header en backend (shipping.py:474-516, 556-617) · Webhook Aveonline con defensa en profundidad ejemplar: rate-limit por IP pre-lookup (F25), secret rotativo F.10 con grace period, dedup atómico vía RPC fn_record_shipment_tracking_event, y estados que no retroceden desde terminales (migración 20260529:133-143) · Errores Aveonline tipados (Auth/NoCarriers/PackageLimit/Transient/Permanent) mapeados a códigos HTTP correctos con mensajes es-CO accionables que incluyen el siguiente paso (shipping.py:245-269)

### Configuración · Integraciones — 61%

_Núcleo conectar/probar/desconectar sólido (Aveonline ejemplar), pero NO listo para tenant autónomo: el connect de WhatsApp del hub produce un webhook que nunca funcionará, 2 de 4 URLs de webhook mostradas son incorrectas, mutaciones del hub fallan en silencio sin audit trail, y ~12 tabs son placeholders._

**Gaps critical/high (12):**

- ✅ `[critical·M·funcional]` **Hub 'Conectar WhatsApp' crea conexión Model B incompleta que nunca recibirá mensajes**
  - integrations-manager.tsx:431-449 form de 3 campos (waba_id/phone_number_id/access_token) para tenant DESCONECTADO + page.tsx:284-337 saveWhatsApp marca status='connected' sin capturar verify_token ni app_secret; el connector los exige: connector-whatsapp/routers/webhook.py:49-57 (handshake GET falla 403 sin credentials.verify_token) y webhook.py:135 (HMAC per-tenant con app_secret, ADR-0023). El panel /integrations/whatsapp sí tiene el form correcto de 6 campos (whatsapp-credentials-form.tsx:13-20 → POST /api/v1/integrations/whatsapp/credentials), pero el hub es la superficie primaria de conexión.
- ✅ `[high·S·funcional]` **Botón 'Copiar' de la webhook URL de WhatsApp está muerto (server component sin handler)**
  - whatsapp-setup.tsx:97-102 — <button> sin onClick en un componente sin 'use client'; la URL per-tenant (crítica para registrar el callback en Meta) no se puede copiar. Contrasta con aveonline-setup.tsx:623-630 donde el copy sí funciona.
- ✅ `[high·L·funcional]` **Submit de plantillas a Meta no es self-service: exige correr un script Python en el servidor**
  - whatsapp-templates.tsx:110-117 buildSubmitCommand genera 'python3.11 scripts/admin/submit_template_to_meta.py ...' y el dialog (líneas 619-660) instruye 'Copiá el comando y corrélo desde el servidor' — un operador tenant no tiene acceso al servidor; el ciclo LOCAL_DRAFT→PENDING no se puede completar desde la consola (gated por ADR-0016 D2).
- ✅ `[high·S·fullstack]` **Webhook URL de Wompi en el panel apunta a ruta inexistente (impacto dinero)**
  - wompi-setup.tsx:97 muestra 'https://api.konvi.co/api/v1/wompi/webhook' pero la ruta real es /api/v1/webhooks/wompi (services/api/main.py:173 prefix='/api/v1/webhooks' + wompi_webhook.py:39 @router.post('/wompi')). Tenant que la registre → 404: pagos APPROVED no se confirman. Flagged en fullstack-review-2026-07-03.md:3083 y NO remediado a HEAD (git log: archivo intacto desde rev106). Mitigante: el hub (integrations-manager.tsx:773) muestra el path correcto.
- ✅ `[high·S·fullstack]` **Webhook URL de Telegram incorrecta en el panel**
  - telegram-setup.tsx:71 muestra '/api/v1/telegram/webhook' pero la ruta real es /api/v1/integrations/telegram/webhook (main.py:181 prefix='/api/v1/integrations' + telegram_webhook.py:40). También flagged en review 2026-07-03 y sin remediar.
- ✅ `[high·M·fullstack]` **Host de webhooks divergente y hardcodeado: onrender.com en hub vs api.konvi.co (DNS sin configurar) en paneles, sin constante compartida**
  - integrations-manager.tsx:773 'konvi-api.onrender.com' vs wompi-setup.tsx:97 / telegram-setup.tsx:71 / meli-setup.tsx:80 / whatsapp-setup.tsx:95 'api.konvi.co'. integrations.py:142 usa WHATSAPP_CONNECTOR_URL con default api.konvi.co, var NO declarada en render.yaml; ADR-0023:150 OQ-4 confirma DNS pendiente de founder. HANDOFF.md:88-89: servicios live en *.onrender.com.
- ✅ `[high·M·ux_ui]` **Paleta founder violada en el hub y componentes legacy: shades 300-500 en texto/borders en ~40 sitios**
  - integrations-manager.tsx:215 text-green-400, :222 text-amber-400, :242-251 text-red-400, :254-267 text-emerald-400/text-red-300, :345 text-green-400, :352 text-emerald-400, :480 text-cyan-400, :607 text-yellow-400, :713 text-violet-400, :824 text-sky-400, :895 text-sky-300 (+ borders *-500/30 en cada card); aveonline-setup.tsx:326,330,370 text-amber-300/text-amber-200; disconnect-button.tsx:57 text-amber-400. Contraste: whatsapp-templates.tsx:57 documenta y cumple 'Tailwind shades 700+ por feedback_ui_colors'.
- ✅ `[high·S·ux_ui]` **Copy en voseo argentino en módulo es-CO only (12 instancias)**
  - whatsapp/page.tsx:430 'Configurá WhatsApp en la tab Setup', :441-442 'Andá a la tab Setup' / 'Completá Setup'; whatsapp-quality.tsx:20 'Conectá'; whatsapp-templates.tsx:165 'Revisalo y usá', :214 'Creá una', :233 'Creá un borrador... submitealo', :445 'Corregí... volvé a submitear', :626 'Copiá el comando y corrélo'; panel-header.tsx:53 'Configurá esta integración'; templates placeholder :86 'Podés pagarlo'. El resto del módulo usa tuteo colombiano.
- ✅ `[high·M·tenant_resiliencia]` **Server actions del hub fallan en silencio y el botón muestra '¡Conectado!' aunque nada se guardó**
  - page.tsx:289,344,350,378 — saveWhatsApp/saveWompi hacen 'return' mudo ante RBAC fail, campos vacíos o fallo de Vault; saveTelegram:118 igual; SubmitButton (components/ui/submit-button.tsx:30-37) marca saved=true en cualquier transición pending→false, mostrando savedText='¡Conectado!'. Contrasta con el patrón ActionResult {ok,error} que sí usan Aveonline (aveonline-actions.ts:25) y templates (whatsapp/page.tsx:127-128).
- ✅ `[high·L·tests_uat]` **0 tests frontend para el módulo: server actions del hub y componentes sin red de regresión**
  - apps/web solo tiene 3 archivos de test (lib/mfa-recovery-cookie.test.ts + 2 en catalog/_lib) — ninguno cubre apps/web/app/dashboard/(settings-group)/integrations/**; saveWompi/saveTelegram/saveWhatsApp/disconnects (page.tsx:113-472) y los flujos de banners/estados no tienen ningún test pese a manejar credenciales.
- ◻︎ `[high·M·observabilidad]` **Conectar/desconectar Wompi, Telegram y WhatsApp desde el hub no genera audit trail**
  - page.tsx:284-423 server actions escriben directo a tenant_integrations/notification_settings; @audit_log solo decora los endpoints API (integrations.py:92,323) que el hub NO usa (salvo disconnectMeli y el form del panel WhatsApp); grep en supabase/migrations: no hay trigger de auditoría sobre tenant_integrations. El módulo Analítica→Auditoría queda ciego a estas mutaciones sensibles.
- ◻︎ `[high·S·operador]` **Los pasos del hub para WhatsApp omiten el registro del webhook en Meta — el operador termina con un bot mudo sin saber por qué**
  - integrations-manager.tsx:408-430 pasos 1-3 solo cubren credenciales (WABA/Phone/token); la URL de callback per-tenant y el verify_token solo aparecen en el panel (whatsapp-setup.tsx:88-104) al que se llega DESPUÉS de conectar, y su botón Copiar está muerto. Nadie guía el paso Meta→Configuración→Webhooks.

**Medium/low:** 12 medium · 11 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Submit de plantillas HSM a Meta: hoy es CLI-only de admin (ADR-0016 D2, whatsapp-templates.tsx:619-660). Decidir si se mantiene el human-in-the-loop o se habilita botón self-service con pre-validación — bloquea cerrar el ciclo de plantillas desde la consola.
- ⚖️ Host canónico de webhooks: cerrar OQ-4 de ADR-0023 (DNS api.konvi.co → connector, acción founder) o unificar temporalmente en *.onrender.com y declarar WHATSAPP_CONNECTOR_URL en render.yaml. Sin esta decisión no se puede mostrar UNA URL correcta y estable (los tenants tendrían que re-registrar el webhook en Meta al migrar de host).
- ⚖️ Flujo canónico de conexión WhatsApp: decidir si el hub mantiene el form de 3 campos (solo apto para editar una conexión Model B ya existente) o redirige siempre al panel de 6 campos. Hoy conviven dos flujos y el del hub produce conexiones rotas para tenants nuevos.
- ⚖️ Alcance real de los paneles: 12 tabs 'próximamente' (Calidad, Opt-outs, Métodos pago, Transacciones, Refunds, Listings, Q&A, Mensajes, Operadores, Comandos, Capacidades, Tracking) con ETAs 'Sem 8/9/11' ya vencidas. Recortar del UI o recalendarizar — hoy el módulo promete mucho más de lo que entrega.
- ⚖️ Habilitar 'Desconectar' en los paneles dedicados (DangerZoneSection actionDisabled) vs mantener la desconexión solo en el hub — los banners de migración llevan 3+ semanas vencidos.
- ⚖️ Cuenta DEMO Aveonline con credenciales públicas en la UI (demointegracion/demointegra2021): confirmar que es política oficial de Aveonline y si se mantiene en producción.

**Código muerto detectado:**
- 🪦 apps/web/app/dashboard/(settings-group)/integrations/_components/disconnect-button.tsx:13 — WARNINGS['envia']: nunca se invoca con provider='envia' (provider eliminado rev. 109 / ADR-0019); además faltan warnings específicos para 'wompi' y 'aveonline' que sí se usan y caen al fallback genérico
- 🪦 apps/web/app/dashboard/(settings-group)/integrations/_components/panel-header.tsx:4 — docstring referencia panel '/integrations/envia' que no existe en el árbol de rutas
- 🪦 apps/web/app/dashboard/(settings-group)/integrations/wompi/_components/wompi-setup.tsx:43-46 — render paths de credentials.public_key e integrity_key_secret_id: 0 writers en todo el repo (services/, scripts/, apps/), siempre '—'
- 🪦 apps/web/app/dashboard/(settings-group)/integrations/whatsapp/_components/whatsapp-quality.tsx:9-14 — prop 'credentials' declarada y pasada (whatsapp/page.tsx:475) pero nunca usada en el componente
- 🪦 apps/web/app/dashboard/(settings-group)/integrations/aveonline/_components/aveonline-setup.tsx:472-473 — rama de copy 'El bot volverá a usar Envia si está configurado como provider activo' describe un fallback que no existe (ADR-0019: 1 provider activo sin fallback)

**Ya sólido (no re-trabajar):** Aveonline es el patrón de referencia del módulo: connect valida contra la API real antes de persistir (aveonline-actions.ts:74-121), Vault idempotente update-in-place, test/disconnect con ActionResult, selector de agentes live con loading/error/retry/refresh (aveonline-setup.tsx:94-129), y ciclo de vida completo del webhook secret (configure/rotate/delete + grace period 7 días + copy funcional + one-time secret display). · Matriz de carriers con datos comerciales SOLO de fuentes oficiales verificadas, honestidad epistémica explícita (cod:'unknown' cuando no hay fuente) y disclaimers para validar con el asesor (aveonline-carriers.tsx:35-171). · Aislamiento multi-tenant impecable: 100% de queries del módulo con .eq('tenant_id', ...), redirect de operators en todas las páginas, RBAC owner/manager por acción, y el connector valida HMAC + verify_token per-tenant (ADR-0023 aplicado de punta a punta en el backend). · Patrón Vault consistente y con migraciones reales (pgsec_create/read/update/delete/upsert en 20260426*), reuso de secret_id existente para no dejar secretos huérfanos en cada save del módulo.

### Dashboard (home operativo) — 62%

_Home operativo sólido en scoping y navegación RBAC, pero sus agregados dejan de ser fiables a escala (fetch crudo sin límite), el card "Bajo stock" no cuadra con el catálogo destino, tiene cero tests propios y ninguna madurez de primer uso para un tenant recién provisionado._

**Gaps critical/high (6):**

- ✅ `[high·S·fullstack]` **Card 'Bajo stock' no cuadra con el KPI del catálogo al que enlaza**
  - apps/web/app/dashboard/page.tsx:61-62 cuenta product_variations con .lte('stock_quantity', threshold) — incluye stock 0 y variantes de productos inactivos/archivados; el destino /dashboard/catalog cuenta solo productos activos con stock>0 (apps/web/app/dashboard/(products)/catalog/_components/products-manager.tsx:52-53: 'v.stock_quantity > 0 && v.stock_quantity <= threshold', sobre products status=active). El operador hace click en 'Bajo stock: 12' y aterriza en una página que dice otro número.
- ✅ `[high·M·fullstack]` **Charts pueden mostrar datos truncados silenciosamente (cap max-rows PostgREST)**
  - apps/web/app/dashboard/page.tsx:64-67 (messages últimos 7 días, una fila por mensaje, sin .limit() ni agregación) y :69 (orders.select('status') de TODOS los pedidos históricos). Supabase/PostgREST corta en su max-rows (default 1000) sin error: en un tenant activo la gráfica de mensajes pierde los días más recientes (order ascending) y el pie de pedidos se sesga, sin ningún aviso al operador.
- ✅ `[high·M·tenant_resiliencia]` **11 queries sin verificación de .error — alertas operativas en falso 0 ante fallo**
  - apps/web/app/dashboard/page.tsx:72-86 consume convRes.count ?? 0, lowStockRes.count ?? 0, etc. sin mirar .error de ninguna respuesta; :33 threshold cae silenciosamente a 5 si tenantRes falla. Un fallo RLS/red pinta 'Agente humano: 0' y 'Bajo stock: 0' como verdad operativa — exactamente el tipo de error enmascarado que el patrón del repo exige surfacear.
- ✅ `[high·M·tests_uat]` **Ninguna prueba de la lógica del módulo (agrupación por día, gating por rol, locks de sidebar)**
  - find apps/web -name '*.test.ts*' devuelve solo mfa-recovery-cookie.test.ts, attribute-contract.test.ts y category-tree.test.ts. La lógica de fechas/timezone de page.tsx:89-109, el filtrado de quickLinks por rol (page.tsx:120-127) y isIntegrationEnabled/isCapabilityEnabled (sidebar-client.tsx:204-207) no tienen red de regresión — la lógica de agrupación es extraíble y testeable en puro TS.
- ✅ `[high·M·performance]` **Agregación en JS con fetch de filas crudas sin límite (mensajes 7d + pedidos all-time)**
  - apps/web/app/dashboard/page.tsx:64-67 trae una fila por CADA mensaje de 7 días solo para contar por día; :69 trae el status de TODOS los pedidos históricos para agrupar en JS (statusMap :112-117). Payload crece sin cota con el tenant; debería ser RPC con GROUP BY o queries count por estado.
- ✅ `[high·M·operador]` **Sin onboarding/empty-state instructivo de primer uso**
  - apps/web/app/dashboard/dashboard-client.tsx:171-263 — no existe rama first-run: con stats en cero el home muestra 4 OpsCards en 0 + quick links, sin checklist tipo 'conecta WhatsApp → carga tu catálogo → configura tu umbral'. El sidebar bloquea Inbox sin integración (sidebar-client.tsx:57) pero el dashboard no le dice al operador nuevo que ese es su primer paso.

**Medium/low:** 13 medium · 8 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Semántica del alert 'Pedidos pendientes': hoy cuenta solo status='pending' (page.tsx:59) y excluye 'pending_payment' (órdenes bot esperando link Wompi). Definir si el operador debe ver ambos en Operaciones o si pending_payment es correctamente pasivo.
- ⚖️ KPIs del tab Negocio son acumulados all-time sin ventana temporal ni comparativa de periodo — el diseño de KpiCard anticipa trends (up/down) pero no hay decisión de qué periodo comparar (7d vs 7d anteriores, mes, etc.). Bloquea cerrar el gap 'comparativa'.
- ⚖️ .context/00-product.md (L1, Rev.5) exige que 'la navegación visible calce exactamente en este árbol' (línea 25), pero el sidebar real incluye Promociones, Categorías, Seguridad, Salud integraciones, Legal, Retención datos y Cerrar cuenta que NO están en el árbol canónico (sidebar-client.tsx:66,73,125-132). Requiere actualización formal del L1 o decisión de retirar/reubicar.
- ⚖️ ¿El home operativo debe integrar AiInsightPanel? El patrón existe y está desplegado en orders/contacts/metrics (components/ai-insight-panel.tsx) pero el dashboard —la superficie de entrada diaria— no lo usa. Decidir si es superficie objetivo del roadmap 'Sugerir con IA'.
- ⚖️ Copy canónico de providers en el quick link Integraciones ('MeLi · Envia', page.tsx:126): decidir el naming oficial ahora que el shipping activo es Aveonline (ADR-0019) y existen Wompi/Telegram/WhatsApp.

**Código muerto detectado:**
- 🪦 apps/web/app/dashboard/dashboard-client.tsx:403-423 — ramas trend 'up'/'down' de KpiCard + prop trendValue + imports TrendingUp/TrendingDown inalcanzables: page.tsx solo pasa trend="neutral" y nunca trendValue (dashboard-client.tsx:273-276)
- 🪦 apps/web/app/dashboard/dashboard-client.tsx:46 — entrada 'Boxes' en ICON_MAP sin ningún quickLink que la emita (page.tsx:120-127 solo usa MessageSquare, Package, Users, ShoppingCart, BarChart2, Plug); import Boxes (línea 9) solo vive por esa entrada muerta

**Ya sólido (no re-trabajar):** Aislamiento multi-tenant impecable: las 16 queries del módulo (page.tsx:47-69 + layout.tsx:84-90) siguen el patrón canónico ADR-0025 .eq('tenant_id', tid), y el canal realtime filtra tenant_id=eq.{tenantId} (dashboard-client.tsx:109-113). · Umbral dinámico real end-to-end: tenants.low_stock_threshold (migración 20260410010000) → page.tsx:27-33 → mismo threshold editable inline en catálogo (products-manager.tsx:122-135) — la capacidad prometida por el árbol funcional existe. · ORDER_STATUS_LABELS/COLORS 100% sincronizados con el CHECK constraint F62 (20260703160000_f62_orders_status_check.sql:17): los 7 estados cubiertos, incl. pending_payment con color ámbar diferenciado y fallback defensivo para desconocidos (dashboard-client.tsx:317). · RBAC coherente en 3 capas: quick links filtrados por rol en server (page.tsx:120-127), secciones canWrite, y sidebar con roles[] + integration gating + capability gating por plan con fail-open documentado (layout.tsx:118-120).

### WhatsApp Templates (HSM) — 62%

_Backend HSM sólido y multi-tenant seguro, pero el módulo no es self-service: el tenant redacta borradores JSON y ahí termina su autonomía — submit vía CLI admin, envío manual prometido por el Inbox inexistente, y 2 de 4 templates seeded sin consumidor._

**Gaps critical/high (8):**

- ✅ `[high·L·funcional]` **Submit a Meta no es self-service: la UI entrega al comerciante un comando python para 'correrlo desde el servidor'**
  - apps/web/app/dashboard/(settings-group)/integrations/whatsapp/_components/whatsapp-templates.tsx:110-117 (buildSubmitCommand genera 'python3.11 scripts/admin/submit_template_to_meta.py ...') y :619-658 (dialog Submit instruye 'Copiá el comando y corrélo desde el servidor'). Un tenant no tiene acceso al servidor. ADR-0016 D2 lo declara deliberado 'aceptable pre-Sem 11' (docs/adr/0016-whatsapp-hsm-templates-engine.md:92-104,327), pero no existe endpoint API ni botón que cierre el ciclo.
- ✅ `[high·L·funcional]` **El Inbox instruye 3 veces 'usa una plantilla aprobada' al expirar la CSW, pero no existe UI para enviar una plantilla — dead end**
  - apps/web/app/dashboard/inbox/_components/chat-panel.tsx:261, :275 ('Los mensajes libres serán rechazados por Meta — usa una plantilla aprobada') y :287. Cero componentes de envío de template en Inbox (grep 'template' en inbox/_components devuelve solo el banner) y ningún endpoint API expone send_template al operador (services/api/routers/ no tiene router de templates).
- ✅ `[high·M·funcional]` **Templates seeded order_confirmation_v1 y order_shipped_v1 sin ningún consumidor — notificaciones post-pago/despacho siguen siendo free-form que Meta rechaza fuera de CSW**
  - supabase/migrations/20260523000000_seed_kaiu_templates.sql seedea 4 templates, pero grep de 'order_shipped_v1|order_confirmation_v1' en services/ y apps/ devuelve 0 hits fuera del seed. services/api/routers/wompi_webhook.py:724-735 (_enqueue_whatsapp_outbound) persiste content_type='text' sin fallback HSM para pago confirmado/envío despachado.
- ✅ `[high·S·fullstack]` **Enum TemplateStatus del frontend omite FLAGGED y LIMIT_EXCEEDED que DB y connector sí persisten — chip roto y label vacío en dialog 'Ver'**
  - apps/web/app/dashboard/(settings-group)/integrations/whatsapp/page.tsx:35-36 (TemplateStatus sin FLAGGED/LIMIT_EXCEEDED) vs supabase/migrations/20260522000000_whatsapp_templates.sql:68-70 (CHECK con 8 estados) y services/connector-whatsapp/services/template_events.py:35-38. En whatsapp-templates.tsx:574 STATUS_CHIP[viewing.status] sin fallback → className undefined; :576 STATUS_LABEL[viewing.status] renderiza vacío cuando Meta pausa por LIMIT_EXCEEDED/FLAGGED.
- ✅ `[high·S·fullstack]` **Copy del Inbox promete que STOP bloquea TODO outbound HSM, pero el payment reminder HSM no chequea consent_revoked_at ni opt-out**
  - apps/web/app/dashboard/inbox/_lib/constants.ts:64 ('outbound proactivo (templates HSM) sigue bloqueado por consent_revoked_at') vs services/ai-orchestrator/worker.py:1366-1520 (_try_send_payment_reminder_hsm consulta orders/contacts/payments pero jamás consent_revoked_at) y services/ai-orchestrator/whatsapp_sender.py (0 referencias a consent/optout). Un cliente que dijo STOP recibe payment_reminder_v1. El path MARKETING sí lo gatea (worker.py:1610-1613).
- ✅ `[high·L·ux_ui]` **Editor de components = textarea JSON crudo formato Meta, sin builder visual ni preview del mensaje como lo vería el cliente**
  - apps/web/app/dashboard/(settings-group)/integrations/whatsapp/_components/whatsapp-templates.tsx:400-411 (textarea rows=14 font-mono con 'Array Meta-format... Validación profunda la hace Meta'). Un comerciante debe escribir a mano jsonb con example.body_text anidado; el único andamiaje es el placeholder inicial (:79-94).
- ✅ `[high·M·tests_uat]` **Cero tests de las server actions Next.js — la validación TS duplicada (validateComponents, parseComponentsJSON, RBAC, guardas de estado) no tiene red de regresión**
  - apps/web/app/dashboard/(settings-group)/integrations/whatsapp/page.tsx:75-122 (validadores) y :126-317 (3 actions) sin ningún .test.*; vitest está configurado (apps/web/package.json:11 'test: vitest run') y el repo ya tiene 4 archivos de test web como precedente.
- ✅ `[high·S·operador]` **El dialog Submit y el empty state exponen mecánica interna (script python del servidor) a un comerciante que no puede ejecutarla ni sabe a quién pedírsela**
  - whatsapp-templates.tsx:625-647 (dialog con comando 'python3.11 scripts/admin/submit_template_to_meta.py' y 'corrélo desde el servidor') y :232-236 (empty state: 'submitealo a Meta vía script submit_template_to_meta.py'). No hay CTA de contacto/soporte ni explicación de quién ejecuta ese paso.

**Medium/low:** 12 medium · 11 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Submit self-service: ¿se construye endpoint API + botón 'Enviar a revisión de Meta' en la UI, o se mantiene el CLI admin de ADR-0016 D2? El ADR lo marcó 'aceptable pre-Sem 11' y ya estamos post-Sem 11 — la decisión bloquea que el módulo sea usable por cualquier tenant sin intervención Konvi.
- ⚖️ Opt-out y UTILITY: ¿un STOP (consent_revoked_at) debe bloquear también el payment_reminder HSM transaccional? Ley 1581 permite transaccional sin consent marketing, pero el copy del Inbox (constants.ts:64) promete bloqueo total de 'outbound proactivo (templates HSM)'. Decidir y alinear código o copy — hoy divergen.
- ⚖️ Envío manual de plantillas desde Inbox al expirar la CSW: el banner ya lo promete tres veces ('usa una plantilla aprobada') — ¿se construye el composer de templates o se cambia el copy?
- ⚖️ order_confirmation_v1 / order_shipped_v1: ¿se cablean a los flujos post-pago (wompi_webhook) y post-despacho (aveonline_webhook) como fallback fuera de CSW, o se eliminan del seed? Hoy esas notificaciones free-form fallan silenciosamente fuera de la ventana 24h.
- ⚖️ Tabs Calidad y Opt-outs: confirmar si MA-6 Sem 11 sigue vigente o re-planificar; el dato de tier ya se persiste por webhook y nadie lo muestra.
- ⚖️ Voz del copy de la consola: este módulo usa voseo argentino ('Creá', 'Andá', 'corrélo') aislado del resto del producto es-CO — definir estándar (tuteo/usted) y normalizar.
- ⚖️ Árbol funcional L1: .context/00-product.md:62 (rev.5) solo lista Envia/MeLi/Telegram bajo Integraciones — el panel WhatsApp+plantillas no está registrado en el árbol canónico pese a la política de 'nada se agrega sin decisión formal aquí primero'.

**Código muerto detectado:**
- 🪦 services/api/lib/whatsapp_templates.py (563 líneas): helper CRUD canónico con 0 imports de producción — la UI (server actions TS), el connector (template_events.py), el sender (whatsapp_sender._get_approved_template) y el script admin reimplementan su lógica por separado; solo lo ejercitan tests via importlib. Además sus versiones update_status_from_webhook/update_quality_from_webhook (líneas 324-399) carecen del scoping F52 por tenant que sí tiene la versión viva del connector — duplicado divergente y menos seguro. Decidir: adoptarlo como fuente única o eliminarlo.
- 🪦 services/api/lib/capabilities_matrix.py:15-17,43 — capability 'hsm_templates' definida y documentada ('Antes de enviar HSM template...') con 0 call sites de is_capability_enabled en orchestrator/API: gate muerto.
- 🪦 apps/web/app/dashboard/(settings-group)/integrations/whatsapp/_components/whatsapp-setup.tsx:97-102 — botón 'Copiar' del webhook URL sin onClick (server component): control muerto.
- 🪦 supabase/migrations/20260523000000_seed_kaiu_templates.sql — order_confirmation_v1 y order_shipped_v1 seedeados sin ningún path de envío en el código (dead data hasta que se cableen a wompi_webhook/aveonline_webhook).

**Ya sólido (no re-trabajar):** Aislamiento multi-tenant ejemplar: F52 fail-closed en los 3 handlers webhook (template_events.py:63-64,141-142,213-215) con defensa waba-match simétrica (:259-266) y test explícito de rechazo cross-tenant (test_template_events_handlers.py:351-366); .eq('tenant_id') en cada query de UI, worker y script. · Paleta founder respetada de forma explícita y auditada: comentario 'Tailwind shades 700+ por feedback_ui_colors (NO 300-500)' (whatsapp-templates.tsx:57) y todos los chips/borders usan 700-900. · FSM de estados bien modelada extremo a extremo: CHECKs en DB (migración :66-78), edición solo LOCAL_DRAFT/REJECTED, delete solo LOCAL_DRAFT para preservar audit trail, REJECTED→edit→re-draft con razón de rechazo de Meta visible ('Meta dijo: ...'). · Idempotencia doble en crons HSM: orders.payment_reminder_sent_at y conversation_carts.abandoned_reminder_sent_at con índice parcial dedicado (20260524000000:24-27) y guard .is_('null') en el UPDATE para evitar carreras.

### Inbox conversacional — 65%

_Núcleo sólido (realtime con fallbacks, takeover, idempotencia, aislamiento tenant, ventana 24h Meta) pero NO terminado: media inbound del cliente invisible para el operador, RBAC rompe notas/pedidos/rerun para el rol operator, lista cap 50 sin paginación y pulido UX/paleta/tests pendiente._

**Gaps critical/high (8):**

- ✅ `[high·L·funcional]` **Media inbound del cliente (imagen/audio/documento) invisible en el chat**
  - services/connector-whatsapp/services/db_persistence.py:246-262 persiste inbound solo con media_id/media_mime (nunca media_url); apps/web/app/dashboard/inbox/_components/chat-panel.tsx:339 solo renderiza imagen si msg.media_url existe → el operador ve '[Imagen recibida]' como texto. Agrava: SKIP_REASON_NON_TEXT (services/api/domain/conversation_contract.py:20) deriva media a humano… que no puede verla. No hay proxy de descarga Meta ni persistencia a Storage.
- ✅ `[high·M·funcional]` **Lista de conversaciones cap duro 50 sin paginación ni load-more**
  - apps/web/app/dashboard/inbox/_hooks/use-conversations.ts:104 `.limit(50)` — conversaciones más antiguas que las 50 recientes son inalcanzables (la búsqueda filtra client-side sobre las 50 cargadas). No hay cursor ni 'ver más'.
- ✅ `[high·S·ux_ui]` **Violaciones de paleta founder (shades 300-500 en texto) en errores y badges**
  - chat-panel.tsx:243 text-red-400 (statusError), :316 text-red-400 (error mensajes), :364 text-red-300 (badge ✕ Error), :391 text-red-400 (sendError); conversation-list.tsx:171 text-emerald-400 (indicador Live), :258 text-red-400 (error lista); context-panel.tsx:431 text-red-500 ('Sin stock'), :449 text-red-400 (chips variantes); order-mini-form.tsx:211 text-red-500, :239 hover:text-red-400, :278 text-red-400. Regla: usar 700.
- ✅ `[high·M·tenant_resiliencia]` **Rol operator bloqueado (403) en notas/rerun/crear-pedido que la UI le ofrece**
  - services/api/dependencies/auth.py:56 WRITE_ROLES={'owner','manager'} excluye operator; conversations.py:974 (POST nota), :1022 (PATCH), :1085 (DELETE), :1127 (rerun) usan require_write_role; orders.py:127-138 create_order 'Solo owner/manager'. La UI admite operator (inbox/page.tsx:24) y monta OrderMiniForm/notas/Rerun sin chequear rol (context-panel.tsx:371, chat-panel.tsx:195-204) — el operator descubre el bloqueo con un error tras llenar el form.
- ✅ `[high·M·tests_uat]` **Endpoints notes/rerun/send-image/context sin ningún test backend**
  - grep 'conversation_notes|/rerun|send_agent_image|send-image' en tests/ → 0 archivos; services/api/routers/conversations.py:931-1411 (≈480 líneas de RBAC, soft-delete, clonado rerun, encolado imagen) sin red de regresión. context solo aparece en test_tenant_isolation_inbox (aislamiento, no lógica de cart/claims/quote-stale).
- ✅ `[high·M·tests_uat]` **0 tests frontend del Inbox pese a vitest configurado y helpers puros**
  - apps/web/vitest.config.ts:8 incluye app/**/*.test.{ts,tsx}; no existe ningún *.test.* bajo app/dashboard/inbox/ — groupConvsByPhone/isSlaBreach/formatPhone (format.ts) y wrapSelection/prefixLine (editor.ts, docstring 'testable con jsdom') sin cobertura.
- ✅ `[high·S·performance]` **Embedded messages() sin límite por conversación: cada carga/poll trae el historial completo de 50 convs**
  - apps/web/app/dashboard/inbox/_hooks/use-conversations.ts:103 select 'messages(content, direction, created_at)' sin limit foreignTable, ejecutado en mount + toggle archivadas + poll cada 20s (línea 241-243) + en cada INSERT realtime (línea 217); mismo patrón en services/api/routers/conversations.py:148-149. Payload crece linealmente con el historial solo para computar last_message.
- ✅ `[high·M·operador]` **Lista y búsqueda solo por teléfono — el nombre del contacto no existe en la lista**
  - conversation-list.tsx:96-99 renderConvRow pinta formatPhone(conv.customer_phone) (el nombre solo aparece en el header del chat vía context, chat-panel.tsx:163); búsqueda inbox-manager.tsx:75 matchea solo customer_phone y el placeholder lo admite (conversation-list.tsx:182 'Buscar por teléfono...'). Un operador con 30 clientes no reconoce a nadie sin abrir cada conv.

**Medium/low:** 13 medium · 9 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Matriz de permisos del Inbox por rol: ¿el operator (persona principal del módulo) debe poder crear notas, pedidos y reruns? Hoy WRITE_ROLES={owner,manager} lo excluye pero la UI y los docstrings asumen que sí — decidir la matriz ANTES de fixear el gap RBAC.
- ⚖️ Estrategia para media inbound del cliente: persistir a Supabase Storage al recibir (costo storage + retención Habeas Data) vs proxy on-demand contra Meta (media_id expira; latencia). Bloquea el gap funcional más visible.
- ⚖️ ¿Debe existir 'Cerrar conversación' manual en la UI? El copy de STATUS_CONFIG ya promete 'resolución manual' — o se agrega la acción o se corrige el copy.
- ⚖️ Read-path REST duplicado (GET list/{id}/messages/stats): consumirlo desde la web (unificar contrato) o eliminarlo — hoy es drift latente sin dueño.
- ⚖️ Mostrar nombre de contacto en la lista: denormalizar contact_name en conversations (write-path connector) vs join/lookup client-side por phone — decisión de modelo de datos con impacto en connector.

**Código muerto detectado:**
- 🪦 apps/web/app/dashboard/inbox/_hooks/use-messages.ts:219 — patchMessages exportado, 0 usos (helper de optimistic send nunca cableado)
- 🪦 apps/web/app/dashboard/inbox/_hooks/use-conversations.ts:270 — patchConversation exportado, 0 usos
- 🪦 apps/web/app/dashboard/inbox/_components/chat-panel.tsx:23,40 — import { useRef as _useRef } + void _useRef: import muerto suprimido a mano
- 🪦 services/api/routers/conversations.py:68-113 — GET /stats sin consumidor (ni web ni telegram ni dashboard)
- 🪦 services/api/routers/conversations.py:116-184 — GET / (list) sin consumidor: la UI lee Supabase directo
- 🪦 services/api/routers/conversations.py:187-219 — GET /{id} (detalle) sin consumidor; ya divergió (no incluye media_url)
- 🪦 services/api/routers/conversations.py:222-265 — GET /{id}/messages sin consumidor (la UI pagina directo contra Supabase). Nota: GET /{id}/cart NO es dead — es ADR-0028 cross-surface intencional con test (test_cart_canonical_shape.py)
- 🪦 apps/web/app/dashboard/inbox/_lib/types.ts:162-169 — variantes FilterStatus 'bot_active'|'human_takeover'|'closed' inalcanzables desde la UI tras Rev.109 (chips eliminados) + rama de match exacto inbox-manager.tsx:86
- 🪦 apps/web/app/dashboard/inbox/_components/attachment-uploader.tsx:31 — prop disabled nunca provista por el único caller (chat-editor-toolbar.tsx:179)

**Ya sólido (no re-trabajar):** Ventana 24h Meta enforced en backend (WINDOW_NO_INBOUND / WINDOW_EXPIRED con códigos accionables, conversations.py:694-741) + banner proactivo de 3 estados en UI (chat-panel.tsx:253-292) — compliance real, no cosmético · Idempotencia end-to-end en status/send/send-image: header UI → proxy Next reenvía → begin/finalize/abort_idempotency con replay (evita dobles Telegram/dobles envíos) · Aislamiento multi-tenant impecable: 100% de queries del router con .eq('tenant_id') o exemption justificada + tests dedicados (test_tenant_isolation_inbox.py, 5 tests) · Realtime con doble red de seguridad: postgres_changes + polling fallback (convs 20s, messages threshold 8s/tick 5s) + dedupe por id — el Inbox no requiere F5 aunque Realtime caiga

### Configuración · General+Legal+Retención — 65%

_Superficie amplia y pulida en General, pero NO está terminado: 2 flujos rotos a nivel DB según esquema canónico (cierre de cuenta con RPC sobre columna inexistente y métodos de pago bloqueados por RLS), drift retention UI↔función, mutaciones sin audit trail y cero tests frontend._

**Gaps critical/high (6):**

- ✅ `[critical·S·funcional]` **Solicitar eliminación de cuenta falla: fn_request_tenant_deletion actualiza columna inexistente is_active**
  - supabase/migrations/20260616000000_tenant_offboarding.sql:197-200 hace UPDATE public.tenant_payment_methods SET is_active=FALSE, pero la tabla solo define 'enabled' (20260603000000_tenant_payment_methods.sql:44) → error 42703 en runtime; el flujo UI closure-form.tsx:77-91 nunca completa. plpgsql no valida columnas al crear y tests/test_tenant_offboarding.py mockea el RPC, por eso pasó. Verificar drift en remote antes de asumir que producción difiere.
- ✅ `[high·S·funcional]` **Guardar métodos de pago siempre denegado por RLS (write policy service_role-only vs server action con cliente de sesión)**
  - settings/actions.ts:159-161 upsert a tenant_payment_methods con createClient() de sesión (utils/supabase/server.ts:10-12, anon key), pero la única write policy es service_role (20260603000000_tenant_payment_methods.sql:111-118; el comentario ':111 Settings UI usa endpoint API → service_role' describe un path que la UI no usa). El bot queda en fallback default-open y el tenant no puede configurar.
- ✅ `[high·M·fullstack]` **Retención: overrides con action distinta a la implementada jamás se aplican (silencio total, riesgo compliance)**
  - retention-policies-form.tsx:118-127 ofrece archive/soft_delete/hard_delete/anonymize para cada entidad; fn_apply_retention (20260508010000_retention_per_tenant_fix.sql:148-151) solo implementa messages+hard_delete, conversations+soft_delete, contacts_inactive+soft_delete, pii_access_log+hard_delete y hace ELSE CONTINUE → un tenant que elige p.ej. messages+anonymize deja de purgar mensajes para siempre sin error visible.
- ✅ `[high·S·tenant_resiliencia]` **Acciones de Legal y Retención tragan errores: el operador cree que aceptó/guardó cuando el insert/update falló**
  - legal/page.tsx:99-107 insert a tenant_legal_acceptance sin chequear {error} y :87-90 return silencioso si rol/input inválido; retention/page.tsx:88-97 update/insert sin chequear error y :76-80 return silencioso. Contradice el patrón ActionResult documentado en settings/actions.ts:26-38 (lección F140: supabase-js no lanza).
- ✅ `[high·M·tests_uat]` **Ningún test habría detectado los flujos rotos: suite backend mockea supabase y los tests de migración son regex estáticos**
  - tests/test_tenant_offboarding.py:184 (happy path 'invoca rpc' mockeado — no valida columnas del RPC); tests/test_rev95_retention_policies.py:35-57 solo asserta texto del SQL. No existe smoke de integración RPC/RLS contra schema aplicado.
- ✅ `[high·M·observabilidad]` **Cambios de configuración desde la consola sin audit trail (Auditoría nunca los muestra)**
  - settings/actions.ts:32-39 y :159-166 escriben tenants/tenant_payment_methods sin insertar en audit_log; @audit_log solo decora PATCH API sin callers (services/api/routers/settings.py:140); no hay trigger de audit sobre tenants en migraciones. Cambiar métodos de pago o horario (comportamiento del bot) no deja rastro.

**Medium/low:** 13 medium · 13 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Canal de soporte: confirmar buzón real antes de publicarlo — el módulo imprime soporte@konvi.com en 4 pantallas pero el dominio configurado con Email Routing es konvi.co (posible buzón muerto)
- ⚖️ DPA/privacy son templates que declaran 'requiere revisión legal antes de firma vinculante' (docs/legal/dpa.md:3-5): decidir si el click-wrap actual es jurídicamente suficiente antes de onboarding de tenants externos, y definir el proceso de bump de versión (CURRENT_VERSIONS hardcodeado en legal/page.tsx:24-28; el DPA ni siquiera imprime su versión v2026-05-01 en el documento)
- ⚖️ Threshold de stock bajo: el árbol canónico (.context/00-product.md:60) lo ubica en /settings pero hoy se edita en Catálogo (catalog/page.tsx:358) — actualizar el árbol L1 o añadir el campo a General (decisión formal)
- ⚖️ Retención: decidir si se implementan las 12 combinaciones entity×action restantes o se restringe la UI a las 4 soportadas por fn_apply_retention (hoy la UI promete lo que el cron no cumple)
- ⚖️ RBAC de Legal/Retención: definir si manager debe ver estos módulos en el sidebar (las páginas y el RLS ya lo permiten; el sidebar los oculta)
- ⚖️ Grace period 'lectura-solo': decidir si se refuerza a nivel DB (trigger/RLS) o se acepta que solo el API gateway lo aplica — hoy los writes directos vía Supabase lo eluden

**Código muerto detectado:**
- 🪦 apps/web/app/dashboard/(settings-group)/settings/page.tsx:212-219 — rama read-only (ReadOnlyField grid) inalcanzable: el redirect de :93 garantiza isOwner=true en todo el render (igual todos los guards {isOwner && ...} de :223-416)
- 🪦 apps/web/app/dashboard/(settings-group)/settings/account-closure/_components/closure-form.tsx:30,35 — prop tenantId declarada en Props y pasada desde page.tsx:91 pero nunca usada (destructuring solo toma tenantName/status)
- 🪦 apps/web/app/dashboard/(settings-group)/settings/page.tsx:105-111 — SELECT de display_label/notes en tenant_payment_methods que jamás se renderizan ni editan (tipados en payment-methods-form.tsx:13-14 sin uso)
- 🪦 services/api/routers/settings.py:111-183 — GET/PATCH /api/v1/settings/tenant sin ningún caller en la consola (solo tests); write-path duplicado del que hace la web por server actions
- 🪦 services/api/routers/tenant_offboarding.py:126-140 — GET /offboarding/status sin consumidor: account-closure/page.tsx:49-59 lee las columnas de tenants directo

**Ya sólido (no re-trabajar):** Patrón ActionResult con surfacing real de errores en las actions de General (settings/actions.ts:26-38, lección F140 documentada) + revalidatePath consistente · Offboarding backend robusto: frase de confirmación validada server-side (tenant_offboarding.py:227-236), rate-limit RL_WRITE_DEFAULT, owner-check en DB, log append-only con IP/email/evidence que sobrevive hard-delete (Art. 22), export por 4 grupos con cap y flag de truncamiento · Click-wrap legal sólido a nivel DB: tabla append-only con triggers que bloquean UPDATE/DELETE, unique por (tenant, doc, versión), RLS insert restringido a owner/manager (20260507010000) · Retención con RLS owner/manager en DB, defaults globales + override per-tenant visualmente diferenciado (badge azul), y fn_apply_retention multi-tenant-safe con tenant_id explícito por statement

### Configuración · Usuarios y Acceso — 66%

_Núcleo funcional y de seguridad sólido (ciclo de vida completo de miembros con hardening F82/F10 real), pero el camino vivo no deja audit trail ni tiene un solo test, la paleta viola la norma del founder en todo el módulo y quedan dos flancos service_role abiertos — usable hoy, no cerrado._

**Gaps critical/high (9):**

- ✅ `[high·S·funcional]` **Invite de usuario existente rompe con >50 usuarios globales (listUsers sin paginación)**
  - apps/web/app/dashboard/(settings-group)/team/page.tsx:176 — `adminSb.auth.admin.listUsers()` sin page/perPage (default 50) y `.find(x => x.email === email)` sobre esa primera página; en cuanto auth.users (global, cross-tenant) supere 50, el usuario existente no se encuentra → error 'usuario-no-encontrado' aunque exista.
- ✅ `[high·M·fullstack]` **Doble implementación divergente: endpoints API auditados sin callers vs server actions vivas sin audit**
  - services/api/routers/settings.py:194-260 — PATCH/DELETE /settings/team/{id} con @audit_log y 0 callers en apps/web (grep 'settings/team' no matchea); la UI reimplementa en page.tsx:217-277 con semántica distinta (signOut global + deleteUser soft que la API no hace). Dos fuentes de verdad para la misma mutación.
- ✅ `[high·L·fullstack]` **Membresía multi-tenant permitida por schema+invite pero rota en el JWT hook**
  - supabase/migrations/20260415000000_security_tenant_users_rls.sql:17-19 (UNIQUE(tenant_id,user_id) permite N tenants por user) + page.tsx:174-191 (invite de usuario existente la materializa), pero 20260426070000_auth_custom_access_token_hook.sql:36-43 elige tenant con LIMIT 1 sin ORDER BY → JWT no determinista y no existe selector de tenant.
- ✅ `[high·S·ux_ui]` **Paleta 300-500 (fluorescente) en texto/borders por todo el módulo — regla founder violada + contraste WCAG**
  - page.tsx:40-61 (text-amber-400, text-blue-400, text-slate-400 en ROLES), banners 394-489 (text-emerald-400, text-red-400, text-amber-400, text-blue-400), botones 604,617; inactivate-member-button.tsx:41,75 (text-amber-400, bg-amber-500 hover:bg-amber-400); change-role-button.tsx:71. Fondo claro #F8F5F1 (apps/web/app/globals.css:17) → contraste insuficiente; settings/page.tsx:532,600-609 ya usa el patrón correcto 700/900.
- ✅ `[high·S·ux_ui]` **Fallo del RPC get_tenant_team se enmascara como estado vacío ('Aún no hay miembros')**
  - page.tsx:120-122 — error solo a console.error y team=[]; la página muestra '0 miembros' (línea 385) y el empty state instructivo (555-559) mintiendo al operador; no hay estado de error con retry.
- ✅ `[high·S·tenant_resiliencia]` **resendInvite no valida que el email pertenezca al equipo del tenant**
  - page.tsx:345-371 — solo verifica que el caller sea owner; el email viene del FormData sin cotejarlo contra get_tenant_team → un owner puede disparar inviteUserByEmail a cualquier dirección (crea usuarios auth huérfanos y convierte a Konvi en remitente de spam/phishing), a diferencia de inviteMember que sí valida (156-159).
- ✅ `[high·M·tenant_resiliencia]` **removeMember hace deleteUser global: destruye la cuenta del usuario en su otro tenant**
  - page.tsx:273 — adminSb.auth.admin.deleteUser(targetId, true) opera globalmente sobre auth.users; el guard F82 (256-263) valida pertenencia al tenant del caller pero no exclusividad, y el camino invite-usuario-existente (174-191) permite membresía en 2 tenants.
- ✅ `[high·L·tests_uat]` **Cero red de regresión sobre el camino vivo (6 server actions)**
  - apps/web tiene vitest configurado (vitest.config.ts, script 'test') pero los únicos test files son lib/mfa-recovery-cookie.test.ts, tests/marketplace-badges.test.mjs y catalog/_lib/*.test.ts — ninguno de team/; tests/test_settings_team_api.py:132-176 testea PATCH/DELETE de settings.py:194-260, endpoints sin callers.
- ✅ `[high·M·observabilidad]` **Cero audit trail en el camino vivo: invitar/cambiar rol/inactivar/eliminar no escriben audit_log**
  - page.tsx:140-371 — ninguna action escribe audit_log ni pasa por la API auditada; el patrón canónico ya existe (promotions/page.tsx:103-104 migró a API por F2.2 justo para restaurar @audit_log+RBAC) y los endpoints team auditados (settings.py:195,233) están muertos. La tabla audit_log (20260409260000_audit_log.sql) soporta exactamente estos eventos.

**Medium/low:** 9 medium · 5 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Membresía multi-tenant por usuario: el schema la permite (UNIQUE(tenant_id,user_id)) y el invite de usuario existente la crea, pero el JWT hook (LIMIT 1 sin ORDER BY) y removeMember (deleteUser global) asumen single-tenant. Decidir: prohibirla (constraint + validación en invite) o soportarla (selector de tenant + hook determinista + remove sin deleteUser). Bloquea el cierre de los gaps fullstack/tenant_resiliencia asociados.
- ⚖️ Transferencia de ownership: 'El rol Administrador es único por negocio y no puede invitarse' — no existe camino para transferir el rol owner ni recuperar el tenant si el owner se va (soporte manual vs feature). Sin esta decisión el módulo tiene un callejón sin salida operativo.
- ⚖️ Canal canónico de mutaciones de equipo: ¿server actions directas (actual, sin audit trail) o API Gateway auditada (endpoints ya escritos pero muertos)? Promotions ya migró a API por esta misma razón (F2.2); la decisión define dónde vive el audit y elimina la duplicación.
- ⚖️ SMTP propio para emails de invitación en producción: hoy dependen del SMTP compartido de Supabase con rate limits que el propio copy de error anticipa (page.tsx:420); decidir cuándo se configura (afecta a todos los tenants a la vez).

**Código muerto detectado:**
- 🪦 services/api/routers/settings.py:194-260 — PATCH y DELETE /settings/team/{member_user_id}: 0 callers en todo el repo (la UI usa server actions); son además el único lugar con @audit_log de team_member, que por tanto nunca se ejecuta.
- 🪦 apps/web/app/dashboard/(settings-group)/team/page.tsx:103 — searchParam `tab` declarado en el tipo y nunca leído en la página.
- 🪦 apps/web/app/dashboard/(settings-group)/team/page.tsx:513,596 — condicionales `isOwner` en JSX siempre true tras el redirect de la línea 116 (solo owners llegan a renderizar).
- 🪦 apps/web/app/dashboard/(settings-group)/team/change-role-button.tsx:25 — rama `currentRole === 'owner' ? 'manager'` solo alcanzable porque page.tsx:626 no filtra owners al renderizar ChangeRoleButton (caso multi-owner que el producto declara imposible).

**Ya sólido (no re-trabajar):** Cadena de seguridad completa y verificada: custom_access_token_hook lee estado fresco de tenant_users en cada JWT (20260426070000), guards F82 verifican pertenencia al tenant ANTES de toda op service_role (page.tsx:228-236,256-263,290-298,325-333), REVOKE F10 en add_member_to_tenant (20260703100000), RLS + UNIQUE en tenant_users, y tenant_id siempre sale del JWT, nunca del form. · Ciclo de vida de miembro completo y bien modelado: pendiente (reenviar invite), activo (cambio de rol con signOut global forzado para refrescar claims), inactivo (ban nativo Supabase reversible + motivo + trazabilidad inactivated_by/at/reason), eliminado (signOut + soft-delete que preserva user_id para audit). · Flujo de invitación end-to-end real: inviteUserByEmail → /auth/callback → /set-password → dashboard, con manejo diferenciado de usuario nuevo (email) vs existente (acceso directo) y banners que explican cada caso. · RBAC de la página consistente en dos capas: sidebar oculta /dashboard/team a no-owners (sidebar-client.tsx:121) y la página redirige server-side (page.tsx:116); las 6 actions re-validan owner+tenant del JWT.

### Auth (login→sesión completa) — 66%

_Núcleo de seguridad robusto y bien diseñado (AAL2 real en web+API, recovery con defense-in-depth), pero sin pulir para tenant nuevo: paleta del founder violada en todo el módulo, dos flujos de borde rotos (suspendidos, MFA+olvido de contraseña), errores en inglés crudo y cero tests de middleware/route handlers._

**Gaps critical/high (5):**

- ✅ `[high·S·funcional]` **Página /cuenta-suspendida construida pero inalcanzable: el miembro suspendido ve 'Correo o contraseña incorrectos'**
  - apps/web/app/cuenta-suspendida/page.tsx existe completa, pero login/page.tsx:63-65 colapsa TODO error de signInWithPassword (incluido user_banned del ban nativo aplicado en team/page.tsx:304-306) al mensaje genérico. Ningún código redirige a /cuenta-suspendida (solo aparece en middleware.ts:128 como exclusión del matcher).
- ✅ `[high·M·funcional]` **Usuario con MFA que olvida su contraseña llega a un callejón sin salida en /set-password**
  - set-password/page.tsx:40-43 llama sb.auth.updateUser({password}) sin manejar el fallo AAL2; el propio código declara que Supabase exige AAL2 para updateUser cuando hay factor verified (recovery-change-password.tsx:7-9 y el manejo explícito en settings/security/page.tsx:114-117). El flujo forgot-password→/auth/confirm→/set-password entrega sesión AAL1, por lo que el cambio falla con error crudo y nada guía al user a completar el challenge TOTP primero (p.ej. redirect a /login/mfa?next=/set-password).
- ✅ `[high·S·ux_ui]` **Regla de paleta violada en todo el módulo: 15 usos de text/border con shades 300-500 (fluorescentes) en las pantallas principales de auth**
  - login/page.tsx:88,92 (text-emerald-500/80, border-amber-500/40); login/mfa/page.tsx:59; mfa-challenge-form.tsx:103 (border-red-300); forgot-password-form.tsx:44,48 (border-emerald-500/30, text-emerald-400); set-password/page.tsx:68 (border-red-500/30, text-red-400); auth/callback/page.tsx:62,66; cuenta-suspendida/page.tsx:12-13 (border-amber-500/30, text-amber-400); recovery-change-password.tsx:75,83; security-form.tsx:450; dashboard/layout.tsx:155 (border-amber-500/40). La regla del founder exige shade 700 para texto/borders.
- ✅ `[high·M·tests_uat]` **Cero tests del middleware de enforcement AAL2 — la pieza de seguridad central del módulo (redirects, gate /api, bypass cookie, fail-open)**
  - apps/web/middleware.ts:5-121 sin ningún test; los únicos vitest del web son mfa-recovery-cookie.test.ts, attribute-contract.test.ts y category-tree.test.ts (find apps/web -name '*.test.ts*').
- ✅ `[high·M·tests_uat]` **Endpoints FastAPI de MFA sin tests de router (solo la lib): reset-totp, recovery/change-password, verify con rate-limit no tienen ninguna cobertura de contrato HTTP**
  - tests/test_mfa_recovery_codes.py cubre solo lib/mfa_recovery_codes.py; grep 'routers.mfa' en tests/ = 0 resultados; test_f23_error_detail_no_leak.py:29 solo escanea el texto del archivo por leaks.

**Medium/low:** 14 medium · 12 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Suspensión visible vs opaca: decidir si el login distingue 'cuenta suspendida' (wire de /cuenta-suspendida con el error user_banned de GoTrue) o se acepta el mensaje genérico por no revelar estado de cuenta — hoy existe la página pero la decisión de mostrarla nunca se tomó
- ⚖️ Canal de rescate de lockout MFA: confirmar que soporte@konvi.com existe y se lee (el dominio del producto es konvi.co con email receive-only) y definir SLA + protocolo de verificación de identidad — hoy es la única salida ante lockout total y no está verificado
- ⚖️ Política de contraseñas: solo min 8 chars sin complejidad ni leaked-password protection (Supabase lo ofrece nativo) — decidir la vara para una consola que mueve pedidos y pagos reales
- ⚖️ Preservación de deep-link post-login (parámetro next en middleware + login + challenge MFA): decidir si se quiere, porque toca la superficie de open-redirect y debe hacerse con whitelist de paths internos
- ⚖️ Remember-device / duración del re-challenge MFA: hoy cada sesión nueva AAL1 exige TOTP siempre; decidir si un dispositivo de confianza puede saltárselo N días (tradeoff seguridad/fricción del operador diario)

**Código muerto detectado:**
- 🪦 apps/web/app/cuenta-suspendida/page.tsx — página completa huérfana: ningún flujo redirige a ella (grep repo: solo aparece en la exclusión del matcher de middleware.ts:128); los miembros suspendidos reciben ban nativo Supabase (team/page.tsx:305) y ven 'Correo o contraseña incorrectos' en login, nunca esta página
- 🪦 apps/web/app/login/mfa/_components/mfa-challenge-form.tsx:90 — query param `?recovery_used=1` se pushea a /dashboard pero nadie lo consume (el banner del layout usa la cookie HMAC, dashboard/layout.tsx:65); parámetro muerto
- 🪦 services/api/routers/mfa.py:91-98 — campos `warning_threshold` y `message` del endpoint /recovery-codes/count no los consume ninguna UI (security/page.tsx:50-57 solo lee `count` y duplica el umbral <3 en security-form.tsx:466)

**Ya sólido (no re-trabajar):** Enforcement AAL2 real y completo: middleware cubre /dashboard Y /api/* con excepción quirúrgica /api/mfa (F85), y el bypass de recovery usa cookie firmada HMAC-SHA256 ligada a user+expiry, fail-closed (middleware.ts:83-113, lib/mfa-recovery-cookie.ts) — con 9 tests vitest que cubren exactamente los ataques del F83 (literal '1', firma manipulada, cookie de otro user, expiry, payload forjado) · Recovery codes de calidad producción: 64-bit entropía token_hex, bcrypt, consumo atómico one-time vía RPC, 18 tests unitarios (services/api/lib/mfa_recovery_codes.py + tests/test_mfa_recovery_codes.py) · Defense-in-depth para sesión recovery: operaciones AAL2 (reset TOTP, cambio password) exigen consumir un SEGUNDO recovery code y pasan por admin API backend (routers/mfa.py:190-305) — diseño correcto para el caso 'perdí el teléfono' · Los 3 flujos de token correctamente separados por naturaleza técnica y documentados inline: PKCE/OTP en Route Handler (cookies server-side), implicit invite en Client Component (hash fragment) — auth/confirm/route.ts:1-20, auth/callback/page.tsx:1-14

### Ventas · Pedidos — 68%

_Backend del ciclo de vida (estados, Wompi, retry, COD) robusto y bien probado; la consola cubre el flujo básico pero no cierra el ciclo de cobro (sin UI de link de pago), solo cancela 'pending', muestra totales que no cuadran en pedidos con descuento y arrastra deuda de paleta/a11y/escala >100 pedidos._

**Gaps critical/high (5):**

- ✅ `[high·M·funcional]` **Sin UI para generar/ver/reenviar el link de pago Wompi desde la consola**
  - services/api/routers/orders.py:408-514 define POST /{order_id}/payment-link (owner/manager) pero grep 'payment-link' en apps/web = 0 resultados; un pedido creado manualmente queda en 'pending' sin manera de cobrarlo online — solo el bot (services/ai-orchestrator/tools/payment_link_tool.py) consume el endpoint
- ✅ `[high·M·funcional]` **Cancelación en UI limitada a 'pending'; API permite cancelar cualquier estado no-terminal**
  - apps/web/app/dashboard/(sales)/orders/_components/orders-manager.tsx:189 (`originalStatus === 'pending' &&`) vs services/api/routers/orders.py:68-69 (cancelled permitido desde todo no-terminal). El operador no puede cancelar pending_payment/confirmed/processing desde el módulo
- ✅ `[high·S·fullstack]` **discount_amount se persiste pero la UI ni lo consulta ni lo renderiza → desglose no cuadra con el total**
  - services/api/routers/orders.py:229 escribe discount_amount (migración supabase/migrations/20260702130000_f1_orders_discount.sql); apps/web/app/dashboard/(sales)/orders/page.tsx:45 no lo incluye en el select y orders-manager.tsx:398-410 lista ítems+envío sin línea de descuento — en un pedido bot con cupón, subtotal+envío ≠ total_amount mostrado y el operador no puede explicar la diferencia
- ✅ `[high·S·performance]` **Full-table fetch de status de TODOS los pedidos para contar en JS — y el resultado se descarta**
  - apps/web/app/dashboard/(sales)/orders/page.tsx:59-63 (select('status') sin limit sobre orders) + :65-70 reduce en JS; counts nunca se pasa al componente. Debería ser count agregado (head:true + count) o RPC por estado
- ✅ `[high·M·performance]` **Listado capado a limit(100) sin paginación ni búsqueda server: pedidos antiguos inaccesibles**
  - page.tsx:48 (.limit(100)) + orders-manager.tsx:94,213-249 — búsqueda y paginación son 100% client-side sobre esos 100; un tenant activo (>100 pedidos/mes) no puede encontrar ni operar pedidos fuera de la ventana

**Medium/low:** 16 medium · 5 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Cancelación desde consola de pedidos confirmed/processing: ¿debe reponer stock y disparar el pipeline de void/refund Wompi (order_cancellations) igual que el flujo bot, o la cancelación post-confirmación queda exclusiva del bot/Reclamos? Bloquea extender el botón Cancelar más allá de 'pending'
- ⚖️ ¿La consola debe poder generar/copiar/reenviar el link de pago Wompi de un pedido pending? El endpoint ya existe (orders.py:408) — decidir si 'Pedidos' cierra el ciclo de cobro sin depender del bot
- ⚖️ ¿Se expone modalidad de pago (COD vs link Wompi) al crear pedido manual desde consola? El backend ya lo soporta; hoy COD solo nace del flujo conversacional
- ⚖️ ¿Card inline es el diseño final o habrá vista detalle de pedido (pagos, envíos/tracking, descuento, auditoría)? Hoy el tracking COD solo se ve en un mensaje transitorio y los pagos no se ven en ninguna parte del módulo
- ⚖️ Escala objetivo del listado: ¿ventana de 100 pedidos recientes es aceptable para los tenants objetivo o se requiere paginación/búsqueda server-side antes de onboardear tenants de mayor volumen?

**Código muerto detectado:**
- 🪦 apps/web/app/dashboard/(sales)/orders/page.tsx:59-70 — query allOrdersRes (select status de TODOS los pedidos) + objeto counts calculado que jamás se pasa a OrdersManager (recalcula el suyo en orders-manager.tsx:252-258)
- 🪦 apps/web/app/dashboard/(sales)/orders/page.tsx:34,73-75 — filtrado server por searchParams.status sin ningún productor del param en el app (ningún href genera ?status=) y contradicho por el filtro client-side local
- 🪦 services/api/routers/orders.py:5 — docstring de endpoint 'GET /api/v1/orders/ — listar pedidos del tenant' que no existe en el router

**Ya sólido (no re-trabajar):** Máquina de estados backend con validación real de transición (forward-only + cancel no-terminal + idempotente) y 409 explícito — services/api/routers/orders.py:56-70,379-384, con tests dedicados (tests/test_a11_order_state_machine.py) · Webhook Wompi endurecido: firma per-tenant vía Vault, dedup por checksum, validación fail-closed de monto y moneda, guard de estados terminales, detección de webhooks huérfanos y retry de link con notificación multicanal — services/api/routers/wompi_webhook.py:112-257 · Idempotencia end-to-end en creación de pedidos: Idempotency-Key generado en el form, propagado por el proxy y consumido con begin/finalize/abort en el router — orders-new-form.tsx:139-146 → app/api/orders/route.ts:18-25 → orders.py:139-153 · Validación IDOR de FKs cross-tenant (contact_id, conversation_id, variation_id) antes del INSERT — orders.py:181-212

### Productos · Catálogo+Inventario unificado — 68%

_Núcleo CRUD+contrato de atributos (ADR-0029 F1-F4) sólido, auditado y multi-tenant correcto, pero el módulo NO está terminado: falta el historial de movimientos prometido por el árbol funcional, no se puede borrar una variante desde la UI, el stock reservado es invisible al operador, la plantilla Excel enseña un formato desalineado, y los errores de guardado del catálogo se silencian mostrando "Guardado" falso._

**Gaps critical/high (7):**

- ✅ `[high·M·funcional]` **Historial de movimientos de stock prometido por el árbol funcional NO existe en la UI**
  - .context/00-product.md:41-42 promete 'historial de movimientos colapsable' en /dashboard/catalog; stock_movements solo se ESCRIBE (apps/web/app/dashboard/(products)/catalog/page.tsx:337) y su único lector es app/api/insights/route.ts:141 — ninguna superficie del catálogo lo muestra. El drawer dice 'Cada movimiento queda registrado' (product-edit-drawer.tsx:450) pero el operador nunca puede verlos.
- ✅ `[high·S·funcional]` **Imposible eliminar una variante desde la UI — endpoint DELETE huérfano**
  - services/api/routers/products.py:623-667 implementa DELETE /products/{id}/variations/{var_id} con guard 'no si es única', pero grep en apps/web no encuentra ningún caller (solo DELETE de producto en page.tsx:304). Una variante creada por error (p.ej. combinación equivocada del generador) solo se corrige borrando el producto completo.
- ✅ `[high·L·funcional]` **Importador masivo: 3 pares fijos de atributos + sin validación de contrato en bulk (ADR-0029 F3/§4.3 incompletos)**
  - apps/web/.../catalog/_components/mass-importer.tsx:48-53 hardcodea Atributo 1/2/3; ADR-0029 §5 F3 exige 'mass-importer sin límite de 3 pares' y §4.3 'en importación masiva, HARD por fila con reporte granular' — services/api/routers/products.py:348-430 (bulk_import_products) nunca llama _validate_attributes_against_contract ni valida ejes de variante. Un producto de moda con 4 ejes no cabe y el bulk mete valores fuera de contrato que el bot citará como hechos.
- ✅ `[high·M·ux_ui]` **Violaciones masivas de la regla de paleta (shades 300-500 en texto/borders) en todo el módulo**
  - products-manager.tsx:90-106 (text-yellow-500, text-red-500, text-red-400, border-yellow-500/30, border-red-500/30); catalog-table.tsx:90,97,176,193,513,536,633 (text-yellow-500, text-amber-500, border-yellow-500/20-30); catalog-form.tsx:654 (text-red-500), :344,437 (border-amber-500/30); product-edit-drawer.tsx:85,114,437,460 (text-amber-500, border-amber-500/30); variant-matrix.tsx:116 (text-emerald-400, border-emerald-500/30); media-client.tsx:122 (text-red-400, border-red-500/30); mass-importer.tsx:315,328 (dark:text-amber-400, dark:text-green-400, border-green-500/20); promotions-manager.tsx:523 (border-slate-400). Contraste: categories-manager y promotions-manager usan 700/900 correctamente en el resto.
- ✅ `[high·M·tenant_resiliencia]` **Errores de API silenciados en TODAS las server actions del catálogo → 'Guardado' falso**
  - page.tsx:120-130 (editProduct), :164-176 (addVariation), :225-235 (editVariation), :249-259 (restore), :273-283 (deactivate), :301-310 (delete) — fetch sin verificar res.ok y catch { /* non-fatal */ }; un 422 del contrato de atributos o un 409 de SKU duplicado termina en revalidatePath + botón 'Guardado'. Contraste: categories/actions.ts:37-40 y promotions/page.tsx:105-130 sí devuelven ActionResult con el detail.
- ✅ `[high·S·observabilidad]` **Fallos de guardado del catálogo invisibles para diagnóstico: ni log, ni Sentry, ni respuesta**
  - page.tsx:130,176,235,259,283,310 — catch { /* non-fatal */ } sin console.error ni captureException; un tenant reportando 'edité el precio y no cambió' no deja NINGUNA señal en ninguna capa (la API loguea solo si la request llegó).
- ✅ `[high·S·operador]` **Plantilla Excel con fila de ejemplo desalineada: enseña el formato INCORRECTO al operador**
  - mass-importer.tsx:102-105 — exampleRow tiene 12 valores para 16 COLUMNS (:44-61): el precio 120000 cae bajo 'Atributo 2 (Ej: Talla)', 85000 bajo 'Valor 2', el precio normal muestra 32 (que era el largo), y peso/largo/ancho/alto quedan undefined (:107-111 y hoja Instrucciones :146). La fila quedó del layout previo a agregar Atributo 2/3 — el primer contacto del operador con la importación lo desorienta.

**Medium/low:** 15 medium · 13 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Media (/dashboard/(products)/media): ruta hidden pendiente de decisión formal — ¿se integra al editor de Catálogo (la galería del ImageUploadBox ya cubre el 80% del caso) o se elimina con barrido de referencias? (00-product.md §5.1)
- ⚖️ Actualizar el árbol funcional L1 (00-product.md Rev.5): Categorías y Promociones existen en sidebar y producción pero no en el tree canónico que exige calce exacto — requiere decisión formal, no es gap técnico
- ⚖️ Acceso read-only del rol operator a Productos/Promociones: el copy de Promociones lo promete y las páginas lo soportan, pero el sidebar lo oculta — decidir si el operador ve catálogo/cupones en lectura
- ⚖️ ADR-0029 fases restantes gated founder: F5 (grounding bot por capas + claims curados), F6 (GTIN/brand/mpn/currency/slug/tags), F7 (backfill KAIU Volumen/Presentación/Contenido) + curaduría de plantillas por vertical y criterio legal INVIMA/Ley 1480 para el atributo de beneficios
- ⚖️ Visibilidad de stock reservado: decidir la semántica que ve el operador (disponible vs físico vs reservado) antes de construir la UI — afecta también el ajuste manual con reservas activas

**Código muerto detectado:**
- 🪦 apps/web/app/dashboard/(products)/catalog/types.ts:48-51 — interface Category {id, name} sin ningún importador en el repo
- 🪦 apps/web/app/dashboard/(products)/catalog/_components/mass-importer.tsx:13,34 — prop tenantId declarada en Props y pasada por products-manager.tsx:185 pero nunca usada en el componente
- 🪦 apps/web/app/dashboard/(products)/catalog/_components/catalog-form.tsx:61 — estado _prefixEdited se escribe (setPrefixEdited) pero jamás se lee
- 🪦 services/api/routers/products.py:623-667 — DELETE /products/{id}/variations/{var_id} sin ningún caller en web/orchestrator/connector (solo tests); o se le da UI o es superficie muerta
- 🪦 services/api/routers/products.py:239-264,433-456 — GET /products/ y GET /products/{id} sin consumidor: la web lee por Supabase directo (RLS) y el orchestrator usa sus propias tools; superficie API viva solo en tests

**Ya sólido (no re-trabajar):** Contrato de atributos ADR-0029 F1-F4 operativo end-to-end: editor de contrato por categoría (attribute-contract-editor.tsx), inputs guiados con canonicalización y orphans visibles (_lib/attribute-contract.ts, testeado), validación HARD server-side anti-alucinación (products.py:167-234) con 14 tests (test_attribute_contract_validation.py) · Aislamiento multi-tenant impecable: todas las queries del módulo con .eq('tenant_id'), _assert_category_owned cubre los FKs id-only (products.py:144-159), lint AST con baseline 0 gaps · Patrón F2.2 completo en producto/variante/categoría/cupón: toda mutación vía API con @audit_log + require_write_role + RL_WRITE_DEFAULT + PATCH semántico exclude_unset/never_clear (products.py:131-141) — con rollback compensatorio en alta de producto (products.py:324-337) · Promociones es el patrón oro del módulo: ActionResult con errores surfaceados, delete condicional Habeas Data con re-verificación anti-race (coupons.py:183-222), tooltips de ayuda y explicación de comportamiento por tipo de descuento, paleta 700/900 correcta

### IA · Agentes IA — 68%

_CRUD multi-agente y onboarding del operador sólidos, pero el preview quedó congelado pre-multi-agente con modelos Gemini desactualizados (embedding-001 retira 2026-07-14) y la promesa "guardrails por rol" nunca se materializa en datos (tools_allowed sin escritor)._

**Gaps critical/high (6):**

- ✅ `[critical·S·fullstack]` **Preview usa gemini-embedding-001 (retiro 2026-07-14) mientras el backend ya migró a gemini-embedding-2**
  - apps/web/app/api/ai/preview/route.ts:10 y 108 hardcodean gemini-embedding-001; services/ai-orchestrator/llm_embed.py:42-54 documenta que embedding-001 se retira (doc oficial Google) y el default vigente es gemini-embedding-2, con advertencia CRÍTICA de que mezclar modelos rompe RAG (vectores incompatibles). Tras el re-embed pendiente del founder, el vector de query del preview será de otro modelo que los almacenados → match_kb_documents devuelve basura silenciosa; tras el retiro, el embed 404ea y el preview degrada al fallback top-3 sin avisar.
- ✅ `[high·M·funcional]` **Preview no es multi-agente: con >1 agente usa fallback genérico 'Vendedor Oficial'**
  - apps/web/app/api/ai/preview/route.ts:79-81 usa .maybeSingle() sobre ai_agents sin filtro is_default ni order; con 2+ agentes (rev.109 multi-agente) PostgREST retorna error PGRST116 → data null → línea 94-98 cae al agente hardcodeado 'Vendedor Oficial'. El operador prueba un bot que NO es el suyo y bot-preview.tsx:124 muestra el nombre equivocado. Tampoco hay selector de agente/rol a probar.
- ✅ `[high·M·funcional]` **Promesa 'guardrails por rol' incumplida: tools_allowed/fsm_states_allowed jamás se escriben**
  - agents-list.tsx:239-243 promete 'crear especialistas... activa guardrails por rol' y agent_templates.py:133-205 define tools_allowed por rol, pero el insert de createAgent (page.tsx:140-145) y updateAgent (page.tsx:206-217) nunca persisten tools_allowed/fsm_states_allowed. grep global confirma cero escritores. dispatcher.py:3440-3443 trata NULL como 'todas las tools' → un agente Support creado por UI puede generar links de pago (su template lo prohíbe explícitamente, agent_templates.py:66).
- ✅ `[high·S·fullstack]` **Preview hardcodea gemini-2.5-flash; el bot real corre gemini-3.5-flash por default**
  - route.ts:11 fija gemini-2.5-flash sin override por env, mientras llm_invoke.py:33 (orchestrator) tiene DEFAULT_PRIMARY_MODEL='gemini-3.5-flash' y llm_cascade.py:41-45 tiers 3.x. El propósito del preview es 'simula cómo respondería el bot' (bot-preview.tsx:60) — hoy simula con un modelo distinto. Nota: /api/insights/route.ts:237 sí respeta process.env.GEMINI_MODEL; el preview no. Los tiers de suggest (ai_agents.py:223-224) y llm_suggest.py:22 también pinean familia 2.5 (VALIDAR EN DOCUMENTACION OFICIAL fechas de deprecación 2.5).
- ✅ `[high·S·ux_ui]` **Violaciones de la regla de paleta (texto con shades 300-500)**
  - page.tsx:267 text-green-400 (badge 'Zero-Hallucinations'), page.tsx:295 text-purple-500, page.tsx:343 dark:text-amber-400, readiness-card.tsx:163 text-emerald-400/text-amber-400 (pill de score), readiness-card.tsx:173/176 iconos 400, bot-preview.tsx:113 text-red-400 (texto de error), bot-preview.tsx:127 text-emerald-400, agents-list.tsx:234 text-amber-500. Contraste: los badges de rol en agents-list.tsx:56-60 sí usan 700 (patrón correcto ya presente en el mismo módulo).
- ✅ `[high·M·tests_uat]` **Ni un test para la capa web del módulo (server actions, preview route, componentes)**
  - apps/web tiene vitest configurado (vitest.config.ts) pero solo 4 archivos de test, ninguno del módulo: createAgent/updateAgent/deleteAgent (page.tsx:106-257, incluye validación de rol único y protección del default), /api/ai/preview (rate limit, construcción de prompt, fallback KB) y ReadinessCard (lógica de 10 checks) no tienen red de regresión. El bug F7 de este mismo archivo (products status vs is_active) habría sido atrapado por un test del route.

**Medium/low:** 8 medium · 11 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Modelos Gemini del preview y de 'Sugerir con IA' (familia 2.5 + embedding-001) deben migrar junto con el gate founder de gemini-3.5-flash y el re-embed a gemini-embedding-2 — decidir si el preview migra en el MISMO deploy que el bot para preservar fidelidad (VALIDAR EN DOCUMENTACION OFICIAL: fechas de retiro de gemini-2.5-* y gemini-embedding-001 en ai.google.dev/gemini-api/docs/deprecations)
- ⚖️ Rol 'custom': hoy es creable pero el router nunca enruta hacia él — decidir entre eliminarlo del drawer de creación, restringirlo a agente default, o darle mecanismo de routing propio
- ⚖️ tools_allowed en creación de especialistas: ¿se aplica automáticamente el template del rol (opción segura, cambia comportamiento de agentes existentes con NULL) o se expone como control editable en el drawer? Requiere además decidir backfill de agentes ya creados
- ⚖️ Preview multi-agente: ¿selector de agente/rol a probar, o siempre el default? Define el alcance del fix del maybeSingle
- ⚖️ El endpoint GET /ai-agents/templates: ¿se elimina (dead code) o se integra al drawer de creación mostrando el skeleton del rol antes de 'Sugerir con IA'?

**Código muerto detectado:**
- 🪦 apps/web/app/api/ai-agents/templates/route.ts — proxy completo sin ningún consumidor en la UI (grep: cero fetches fuera de types generados)
- 🪦 services/api/routers/ai_agents.py:86-99 — GET /api/v1/ai-agents/templates solo consumido por el proxy muerto y por tests; su docstring afirma un uso frontend que no existe
- 🪦 services/api/routers/ai_agents.py:72-74 — SuggestResponse.skeleton y model_used: la UI solo consume suggested_role_description/agent_name (agents-list.tsx:137-139)
- 🪦 Columnas ai_agents.tools_allowed y fsm_states_allowed — leídas por dispatcher pero sin ningún escritor en todo el repo: infraestructura dormida (NULL = sin restricción para todos los agentes)
- 🪦 services/ai-orchestrator/lib/__pycache__/agent_templates.cpython-311.pyc — bytecode huérfano de cuando el módulo vivía en orchestrator (fuente movida a services/api/lib/)

**Ya sólido (no re-trabajar):** ReadinessCard 'Estado del bot' con 10 checks accionables, tooltips explicativos y deep-links a anclas verificadas de Settings/KB/Catálogo/Integraciones (readiness-card.tsx:50-139) — madurez de primer uso ejemplar · Cadena multi-agente coherente backend: router pre-LLM por keywords honra fallback_for_roles y el handoff sintético ejecuta side-effect REAL (human_takeover + notificación operador, dispatcher.py:1179-1180 + 3370-3383) — la promesa de la UI 'roles desmarcados escalan a humano' es verdad · Suggest con IA robusto: cascade con fallback a skeleton si respuesta <500 chars, normalización de line-wraps, truncate en última oración, RBAC write-role con test (ai_agents.py:238-265, test_rbac_marketplace_agents.py:63) · Aislamiento tenant impecable en todo el módulo: .eq('tenant_id') en cada query + RLS con WITH CHECK (migración 20260702120000) + protección del agente default no-borrable con partial unique index

### Ventas · Contactos (CRM + Habeas Data) — 72%

_Cumplimiento Habeas Data maduro (máquina de consent API-side + audit triple + UX legal cuidada), pero incompleto como CRM: falta el historial prometido por el árbol funcional, la edición no puede limpiar campos ni guardar contactos sin dirección, y el listado hace fetch sin límite._

**Gaps critical/high (4):**

- ✅ `[high·L·funcional]` **Historial del contacto (prometido por el árbol funcional) no existe**
  - .context/00-product.md:36 define 'Contactos ← CRM mínimo: cliente, historial, consent habeas data' y :93 lista 'Historial de un contacto' como Tab. La card (contacts-manager.tsx:890-1008) no muestra pedidos, conversaciones ni links a Inbox/Pedidos; el único 'historial' vive en el SAR export JSON (data_subject_request.py:154-165), invisible en la UI.
- ✅ `[high·M·funcional]` **Editar no puede limpiar campos: vaciar notes/email/documento/dirección se pierde silenciosamente**
  - services/api/routers/contacts.py:427 `data = {k: v ... if v is not None}` descarta todo null; page.tsx:434-440 envía name/email/notes/document/address como null al vaciarlos. El operador ve 'Cambios guardados correctamente' (contacts-manager.tsx:368) pero el valor viejo reaparece tras refresh. Única vía de borrado de un campo = Anonimizar total.
- ✅ `[high·M·fullstack]` **Contrato PATCH UI↔API roto para vaciado de campos (mismo root cause que el gap funcional)**
  - contacts.py:427 filtra None; page.tsx editContact:434-440 usa null como 'vaciar'. No existe sentinel para distinguir 'no tocar' de 'poner en null' — el shipping_phone lo documenta como intencional (page.tsx:419-424) pero name/email/notes/address heredan la misma semántica sin quererlo.
- ✅ `[high·S·ux_ui]` **Edit form bloquea guardar cualquier cambio si el contacto no tiene dirección (caso típico: contactos creados por el bot)**
  - contacts-manager.tsx:1186 pasa showBuildingDetails al AddressSelector de Edit → address-selector.tsx:75 `required={showBuildingDetails}` en street, :154 en barrio, :166 tipo de destino. Corregir solo el nombre de un contacto sin dirección exige inventar dirección completa. Contradice el propio comentario 'el form permite crear contactos sin dirección — el bot la pide después' (contacts-manager.tsx:228-231).

**Medium/low:** 10 medium · 14 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ ¿'Eliminar' (hard cascade que borra orders/payments/shipments) debe seguir expuesto al owner en producción? El endpoint se autodocumenta 'uso testing/admin (NO producción regular)' (contacts.py:552) y borra órdenes que el propio soft-delete dice retener 10 años por Cod. Comercio Art. 60 (contacts.py:673) — y ese soft-delete respetuoso de retención está huérfano.
- ⚖️ Purge físico a 30 días de contactos anonimizados sin órdenes: implementar el cron prometido (services/cron, Fase 13) o retirar la promesa del contrato del endpoint y de la respuesta al operador.
- ⚖️ Derecho de rectificación Art. 16: ¿se declara cubierto por el edit form (y se retira type='rectify' del SAR) o se construye la cola de revisión para los 'pending_review' que hoy solo quedan en audit log?
- ⚖️ Semántica de vaciado en PATCH: definir cómo el operador borra un campo individual (sentinel explícito vs null) — hoy la única supresión parcial posible es la anonimización total.
- ⚖️ Paginación server-side del listado: decidir umbral (¿500 contactos?) antes de onboardear tenants con volumen — el bot crea un contact por cada teléfono entrante y el fetch es unbounded.
- ⚖️ Historial del contacto (tab prometida por el árbol funcional rev.5): ¿pedidos + conversaciones embebidos en Contactos, o links cruzados a Pedidos/Inbox filtrados por contacto?

**Código muerto detectado:**
- 🪦 services/api/routers/contacts.py:658-728 — DELETE /api/v1/contacts/{id} (soft-delete con retención): 0 callers en web/bot/scripts (la UI usa POST /purge); además promete un cron de purge a 30 días inexistente
- 🪦 services/api/routers/contacts.py:5 — docstring promete GET /api/v1/contacts/ que no existe como endpoint
- 🪦 apps/web/app/dashboard/(sales)/contacts/page.tsx:100 — searchParams.q declarado y nunca leído
- 🪦 apps/web/app/dashboard/(sales)/contacts/page.tsx:111,126-127 — filtro server-side ?consent= sin ningún escritor en la UI (los chips filtran client-side el mismo dataset: doble filtro redundante)
- 🪦 apps/web/app/dashboard/(sales)/contacts/page.tsx:209 — 'TI' en la whitelist de document_type del addContact: el dropdown lo eliminó (rev.102) y la API lo rechaza (DOCUMENT_TYPES_CO)
- 🪦 apps/web/app/dashboard/(sales)/contacts/_components/helpers/upload-evidence.ts:96 — campo url:'' persistido 'por compat con código que aún la lee' (bucket privado lo invalidó; nadie lo consume)

**Ya sólido (no re-trabajar):** Máquina de estados de consent centralizada API-side (_compute_consent_update, contacts.py:163-271) con unit tests reales de paridad UI↔API (tests/test_a9_editcontact_consent.py): guards soft-revoke, renovación post-anonimización con evidencia ≥10 chars, mergedEvidence con cap 50 renewals, sync consent_given_at (F116). · Audit trail triple completo: @audit_log de entidad + pii_access_log field-level (Art. 9) + consent_audit_log append-only con phone_hash — SAR export incluye primary_identifier jerárquico (documento > phone > UUID) y el printable HTML no requiere deps server-side. · Patrón ActionResult (F68) en todas las server actions: el operador ve la causa real (409 teléfono duplicado, guard Wompi de purge con instrucciones de espera, sesión expirada) en vez del digest genérico de Next.js. · Router API con idempotencia (begin/finalize/abort), rate-limit RL_WRITE_DEFAULT y RBAC granular: write=owner/manager, purge y reactivar consent=owner-only con tooltip educativo para el manager.

### Configuración · Seguridad/MFA — 74%

_Funcionalmente completo end-to-end y con seguridad bien diseñada (HMAC cookie, bcrypt, RPC atómico), pero le falta pulido de cierre: paleta fuera de regla, sin confirmación en acción destructiva, sin escape en el challenge, cero audit trail de mutaciones sensibles y cero tests HTTP de los endpoints de bypass AAL2._

**Gaps critical/high (4):**

- ✅ `[high·S·ux_ui]` **'Regenerar códigos de respaldo' revoca los 8 códigos anteriores al instante sin dialog de confirmación**
  - apps/web/app/dashboard/(settings-group)/settings/security/_components/security-form.tsx:496-508 — onClick={generateRecoveryCodes} directo; el backend borra previos en fn_regenerate_mfa_recovery_codes (migración, DELETE incondicional). Re-enroll y disable sí tienen Dialog (líneas 543-664); regenerate no.
- ✅ `[high·S·ux_ui]` **El challenge /login/mfa no tiene salida: ni cerrar sesión/cambiar cuenta ni guía si perdiste también los códigos**
  - apps/web/app/login/mfa/_components/mfa-challenge-form.tsx:100-201 solo alterna TOTP↔recovery; apps/web/app/login/mfa/page.tsx:49-74 no ofrece logout ni contacto de soporte. Un usuario que perdió authenticator y códigos queda mirando un formulario sin instrucción (la ayuda vive en settings/security/page.tsx:183-186, inalcanzable en AAL1).
- ✅ `[high·M·tests_uat]` **Los endpoints de bypass AAL2 (reset-totp, recovery/change-password) no tienen ningún test HTTP**
  - grep en tests/ no encuentra ningún test que importe routers/mfa ni llame recovery/reset-totp o recovery/change-password; el único test que toca mfa.py es tests/test_f23_error_detail_no_leak.py:29 (chequeo estático de strings, no de comportamiento). Son los endpoints que usan admin API con service_role — los más sensibles del módulo.
- ✅ `[high·M·observabilidad]` **Mutaciones de seguridad sensibles no escriben en audit_log pese a existir el decorator canónico**
  - services/api/routers/mfa.py no usa el decorator @audit_log (services/api/dependencies/audit.py:1-40, patrón Rev. 72 usado por claims/coupons/orders/etc.); regenerar códigos, consumir recovery code, reset de TOTP y cambio de password vía admin API (mfa.py:101-305) solo dejan logger lines — invisibles en Analítica → Auditoría, que el árbol funcional define como 'log de acceso/cambios' (.context/00-product.md:57).

**Medium/low:** 12 medium · 6 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Buzón de soporte canónico: la UI promete soporte@konvi.com (dominio .com, probablemente no operado) mientras la infra real es konvi.co receive-only — definir y unificar el contacto antes de que un tenant bloqueado lo necesite (afecta también settings/health y account-closure)
- ⚖️ Lockout total (sin authenticator ni recovery codes) = reset manual del founder vía SQL Editor (documentado en la migración como decisión anti-abuso) — decidir si se necesita tooling admin antes de escalar a más tenants
- ⚖️ No existe política 'MFA obligatoria para el equipo del tenant' (owner no puede exigir MFA a manager/operator) — decidir si se requiere dado el compliance Habeas Data
- ⚖️ Ratificar dos compromisos de seguridad documentados: (a) sesión recovery = bypass AAL2 por 24h (verify/route.ts), (b) fail-open del check AAL ante outage de Supabase Auth (middleware.ts:109-112)
- ⚖️ El cambio de contraseña vía recovery no revoca otras sesiones activas ni invalida la cookie de recovery vigente — decidir postura (revocar sesiones tras password reset es práctica estándar)

**Código muerto detectado:**
- 🪦 Query param '?recovery_used=1' (apps/web/app/login/mfa/_components/mfa-challenge-form.tsx:90) — nadie lo lee; el banner de layout.tsx:65 usa la cookie HMAC
- 🪦 Campos de respuesta nunca consumidos por la UI: warning_threshold y message del count (services/api/routers/mfa.py:91-97), remaining/warning del verify (mfa.py:157-163), deleted_factors del reset-totp (mfa.py:268)
- 🪦 Props message/error de /login/mfa (page.tsx:68) — ningún redirect del repo los alimenta
- 🪦 apps/web/app/dashboard/account/page.tsx — redirect legacy a settings/security no listado en la tabla de rutas hidden de .context/00-product.md §5.1 (la política exige listarlo o eliminarlo)

**Ya sólido (no re-trabajar):** Ciclo completo sin features a medias: enroll TOTP + QR, challenge login, recovery codes one-time, re-enroll con doble verificación, disable — todo cableado UI→proxy→API→DB sin TODOs · Seguridad de la sesión recovery bien resuelta post-F83/F85: cookie HMAC fail-closed ligada a user+expiry (apps/web/lib/mfa-recovery-cookie.ts) con 8 tests unit, y gate AAL2 del middleware cubriendo /dashboard Y /api (middleware.ts:83-114) · Recovery codes con higiene criptográfica correcta: bcrypt (no SHA), consume atómico FOR UPDATE vía RPC SECURITY DEFINER, GRANTs solo service_role, RLS user-scoped (supabase/migrations/20260620000000_mfa_recovery_codes.sql) · Defense-in-depth real: operaciones AAL2-bypass (reset TOTP, cambio password en sesión recovery) exigen consumir un SEGUNDO recovery code (services/api/routers/mfa.py:212-305)

### Bot conversacional (orchestrator) — 85%

_Módulo maduro y defendido en profundidad (resolvers pre-LLM + 15 invariants + gates legales fail-closed) — listo para KAIU; para el SEGUNDO tenant hay 3 fugas de multi-tenancy (branding KAIU hardcodeado en domain filter, persona de ai_agents ignorada en el path per-state primario, default legacy en provisioning) que son fixes S-M, no rediseño._

**Gaps critical/high (3):**

- ✅ `[high·S·funcional]` **Domain filter (médico/medicamentos) responde con branding KAIU hardcodeado a TODO tenant agentic**
  - services/ai-orchestrator/agentic/dispatcher.py:1281-1299 — el redirect pre-LLM dice literalmente 'Soy asistente de venta de productos de KAIU Living Natural' y '¿Te puedo ayudar con algún producto de cosmética natural KAIU?'; tenant_name está disponible en el scope (línea 1066) pero no se usa. Cualquier otro tenant cuyo cliente pregunte algo médico recibe la marca de KAIU.
- ✅ `[high·S·funcional]` **Tenant nuevo cae por default al bot legacy V1 con prompts KAIU-brandeados (agentic_enabled no se provisiona)**
  - agentic/dispatcher.py:38-69 default False + :250-261 path legacy; supabase/migrations/20260702190000_f3_provision_tenant.sql y scripts/admin/provision_tenant.py no crean el row tenant_integrations provider='agentic'; docs/operations/onboarding-tenants.md no menciona el paso de cutover. El prompt legacy hardcodea 'Sara Camila de KAIU Living Natural' (services/ai-orchestrator/prompt/builder.py:696,746,796).
- ✅ `[high·M·fullstack]` **build_prompt_for_state (path V3 primario) ignora agent_name, role_description y philosophy: el bot siempre se presenta como 'Sara Camila' aunque el tenant configure otro agente en /dashboard/ai-agents**
  - agentic/dispatcher.py:2612-2635 — la llamada a build_prompt_for_state no pasa agent_name ni role_description (que SÍ se pasan al monolito V2 en :1185-1204, luego sobrescrito); agentic/prompt/builder.py:156 default agent_name='Sara Camila' y la firma (150-179) ni siquiera acepta role_description/philosophy; apps/web/app/dashboard/(ai)/ai-agents/agents-list.tsx:155 escribe role_description que el path primario nunca lee. El router multi-agente (ADR-0017) selecciona agente pero su persona solo aplica en el fallback monolito.

**Medium/low:** 4 medium · 13 low (detalle en el JSON crudo).

**Decisiones de producto pendientes (bloquean cierre — founder):**
- ⚖️ Campo `city` estructurado en contacts para el gate anti-teleporte (cotiza Bogotá / dirección Medellín) — follow-up explícito del coverage-map (conversation-coverage-map.md:52-54), decidido NO hackear; requiere decisión de modelo de datos
- ⚖️ Retiro del path legacy V1: ¿flip del default a agentic_enabled=true (o provisioning que cree el row provider='agentic') y eliminación del monolito? Hoy el default de un tenant nuevo es el bot legacy KAIU-brandeado
- ⚖️ Manejo de mensajes `location` de WhatsApp como input de dirección de envío (hoy se descartan lat/long) y de `document` (comprobantes PDF) — ¿se procesan o se declara fuera de alcance?
- ⚖️ Palanca 7 parcial declarada 'marginal diferida' (anáfora-en-greeting, PII-voluntaria pre-consent) — confirmar cierre o descartar formalmente en el coverage-map
- ⚖️ Modelo gemini-3.5-flash como default en develop (agent.py:50, multimodal.py:34) con deploy gated — validación founder pendiente antes de merge a production (ya trackeado en next-steps)

**Código muerto detectado:**
- 🪦 services/ai-orchestrator/dian_normalization.py — 0 imports en todo el repo (grep exhaustivo): diccionario DIAN de normalización de direcciones nunca conectado
- 🪦 Tools granulares save_email/save_name/save_document/save_address/save_shipping_phone (agentic/tools/contact.py:489-829): registradas en el registry pero ausentes de TODO tools_subset (agentic/prompt/tools_subset.py:64-146) → invisibles al LLM en el path per-state primario; solo alcanzables en el fallback monolito. Consolidar en save_contact_field o exponerlas.
- 🪦 agentic/prompt/states.py:371-381 human_handoff_prompt — inalcanzable: el gate _should_skip_for_conv_status (dispatcher.py:129-131) corta antes de invocar el LLM en human_takeover (placeholder declarado, mantener o documentar)
- 🪦 Path legacy V1 completo (orchestrator.py 10.462 líneas + fsm/ + checkout_form.py + slot_extractors.py + llm_router.py + guardrails.py) — vivo SOLO para tenants sin cutover agentic; con KAIU migrado y la política de tenants nuevos en agentic, es un monolito zombie con branding KAIU hardcodeado cuyo retiro (strangler-fig) no tiene fecha

**Ya sólido (no re-trabajar):** Arquitectura de coherencia en 3 capas real y verificable: resolvers determinísticos pre-LLM (consent, COD/credit, carrier, cupones, cancelación/retracto Ley 1480, purchase intent, variantes, shipping, imagen, receptor alterno, disponibilidad de método de pago) + tools subset per-estado + 15 invariants post-LLM con pipeline ordenado y razón documentada por bug real · FSM de 9 estados con resolver puro determinístico (agentic/state_machine/resolver.py) — POST_PAYMENT alcanzable para COD (fix F49 vía order_status) con tests de regresión (tests/agentic/test_state_machine_resolver.py:44-239); requires_requote invalida cotizaciones stale y bloquea link de pago (gate REQUOTE_PENDING en legacy_adapters/payment.py:47-53) · Gates legales deterministas ANTES del LLM y fail-closed: opt-out STOP, re-opt-in, menor de edad (Decreto 1377), DSR Habeas Data no-keyword con self-service Art.14 enmascarado y paper-trail en consent_audit_log (dispatcher.py:104-211,450-599) · Escalación multi-capa completa: tool + FakeEscalationInvariant (fuerza side-effect real), router handoff con consumer real, silent escalation al agotar recoveries, degraded 2-strike con Telegram, y SLA tracker de human_takeover en el worker (worker.py:134-141)

---

## Puntos ciegos del audit (crítico de completitud) — Fase 0.1

Superficies del producto SIN dueño en los 23 módulos auditados. Requieren mini-audit (Fase 0.1) o asignarse a una fase de cierre:

- Módulo 'Ventas · Promociones' (cupones) completo sin auditar: está vivo en el sidebar ('/dashboard/promotions' en apps/web/app/dashboard/sidebar-client.tsx), tiene UI propia (apps/web/app/dashboard/(sales)/promotions/page.tsx + promotions-manager.tsx), router API dedicado (services/api/routers/coupons.py, 222 líneas, ADR-0015 D10, escrituras auditadas F2.2), tabla coupon_redemptions con gate Habeas Data anti hard-delete, flag is_customer_visible que gobierna qué anuncia el bot, y redención bot-side en services/ai-orchestrator/tools/cart_tool.py. Ninguno de los 23 módulos lo reclama — afecta directamente precios cobrados (integridad comercial) y explica en parte el gap 'totales que no cuadran en pedidos con descuento' que Pedidos reportó sin dueño causal.
- Emails transaccionales al cliente final (Resend) sin dueño: services/api/routers/wompi_webhook.py contiene un subsistema completo de emails de ciclo de vida (_send_payment_confirmation_email línea 1025 + composers _compose_payment_email_html:1609, _compose_payment_failed_email_html:1725, _compose_shipment_label_ready_email_html:1821, _compose_shipment_in_transit_email_html:1906, _compose_shipment_delivered_email_html:1952), disparados también desde aveonline_webhook.py:312-379. Es best-effort silencioso (si RESEND_API_KEY falta → skip con log, RESEND_FROM_EMAIL default 'noreply@commerce-ops.local' no productivo). Ni Pedidos ni Despachos mencionan contenido, deliverability, dominio remitente ni fallos silenciosos de esta superficie cara-al-cliente.
- Subsistema de notificaciones al operador end-to-end sin dueño: services/ai-orchestrator/notifications.py (eventos human_takeover, consent_revoked, sar_received por Telegram + email) + telegram_notifications.py (unificación rev.109 a notification_settings como única fuente, historia previa de desincronía silenciosa entre 2 paths) + services/api/routers/telegram_webhook.py (webhook bidireccional: comandos /resolver y /estado del operador, secret token, 503 si no configurado, setWebhook manual documentado como INTERVENCION HUMANA) + alertas de pagos pendientes >25min y calidad WhatsApp (documentadas en integrations/telegram/page.tsx). El audit de Integraciones solo cubre el connect del hub; nadie auditó si las alertas llegan, el RBAC de los comandos por chat_id, ni que las tabs 'Operadores' y 'Comandos' son comingSoon.
- Página 'Salud de mis integraciones' (/dashboard/settings/health) sin auditar: apps/web/app/dashboard/(settings-group)/settings/health/page.tsx (Rev.109 J.2.11, per-tenant, owner/manager) + pipeline que la alimenta (services/ai-orchestrator/worker.py:_collect_health_metrics_if_due:2195 y _notify_health_transitions:2248 + health_metrics.py, cron 5min con alerta Telegram healthy→warning/critical). El audit de 'Configuración · General+Legal+Retención' enumeró General/Legal/Retention y no esta ruta; Integraciones tampoco la nombra.
- Jobs proactivos del worker con superficie de producto sin módulo dueño: services/ai-orchestrator/worker.py ejecuta _send_payment_reminders_if_due:1191 (+_try_send_payment_reminder_hsm:1366, HSM al cliente), _send_cart_abandoned_reminders_if_due:1522, _release_expired_pending_payment_orders:1879 (libera stock reservado — toca el 'stock reservado invisible' que Catálogo reportó), _poll_wompi_pending_voids_if_due:1745 y _check_human_takeover_sla_if_due:937 (SLA escalación). Son comportamiento cliente-visible y de inventario (frecuencia, opt-out, ventana 24h Meta, dinero) que ni Bot (85%, pipeline conversacional) ni WhatsApp Templates (redacción/submit) ni Pedidos auditaron como flujo; existe además trigger manual admin scripts/admin/send_payment_reminder.py.
- Superficie transversal 'IA embebida por módulo' sin dueño: apps/web/app/api/insights/route.ts (llama Gemini con prompts por módulo inventory/orders/contacts/metrics y devuelve hallazgos/acciones/alerta) consumido por components/ai-insight-panel.tsx embebido en contacts/page.tsx, orders/_components/orders-manager.tsx y metrics/page.tsx — ninguno de esos 3 audits lo menciona (¿modelo vigente?, ¿límites?, ¿tenant-scoping del data payload?). Mismo patrón: services/api/routers/catalog_ai.py ('Sugerir con IA' descripción + safety_note con blocklist anti-claims Ley 1480) y lib/llm_suggest.py, tampoco nombrados por el audit de Catálogo.
- Gestor de Media (/dashboard/(products)/media) y el bucket tenant-media: ruta hidden pero funcional (media-client.tsx, upload/listado a Supabase Storage 'tenant-media'), documentada como pendiente de decisión en .context/00-product.md §5.1. Ni Catálogo ni Design System la mencionan, y ningún módulo audita las policies de aislamiento multi-tenant de Storage (el resto del audit se concentró en RLS de tablas).
- Página Categorías (/dashboard/categories) con entrada propia en sidebar: apps/web/app/dashboard/(products)/categories/{page.tsx,actions.ts,_components} implementa ADR-0027 (categorías OPERATIVAS que el bot presenta al cliente) con routers product_categories.py y product_attribute_definitions.py. El audit 'Catálogo+Inventario unificado' se ancló en ADR-0029 F1-F4 y no nombra esta ruta ni el ADR-0027 — cobertura a lo sumo parcial (verificar con el auditor del módulo).
- Offboarding como pipeline cross-cutting parcialmente cubierto: el audit de Configuración solo flaggeó el RPC de cierre roto, pero existe _OFFBOARDING_GATE aplicado como dependency a ~20 routers (services/api/main.py:139-191, modo read-only durante gracia), el router services/api/routers/tenant_offboarding.py y el hard-delete diferido en worker (_run_tenant_hard_delete_if_due, worker.py:2096). Nadie auditó que el gate realmente bloquee escrituras en todos los módulos ni que el hard-delete borre completo (Habeas Data retención).
- Delivery receipts de WhatsApp outbound sin superficie auditada: services/connector-whatsapp/services/parser.py parsea value.statuses[] (EVENT_TYPE_OUTBOUND_STATUS, delivered_at/read_at/pricing, línea ~156-213) y template_events.py persiste quality_rating y tier del número. El audit de Inbox no dice si el operador ve entregado/leído/fallo de sus mensajes, y ningún módulo audita la visibilidad de la calidad/tier del número WhatsApp (solo la alerta Telegram la menciona de pasada).

**Superficies/flujos transversales no cubiertos:**

- Flujos E2E cross-módulo: nadie validó las costuras pedido→pago Wompi→email cliente→creación guía Aveonline→tracking→entregado→reclamo, ni carrito abandonado→recordatorio HSM→conversión, ni consent revocado→notificación operador→efecto en bot. Cada audit vio su tramo; los handoffs (wompi_webhook dispara shipment + email + HSM; aveonline_webhook dispara emails + estados) son exactamente donde los gaps por-módulo se componen.
- Journey día-1 del tenant nuevo POST-provisión: Onboarding auditó la maquinaria de provisión, pero no el camino primer login → configurar notification_settings/Telegram → primer template aprobado → salud en verde → primer pedido cobrado. Varios audits notaron 'madurez de primer uso baja' por módulo; nadie evaluó la secuencia completa.
- Consola admin/founder como superficie operativa: scripts/admin/ (provision_tenant.py, submit_template_to_meta.py, send_payment_reminder.py, reembed_kb_documents.py, seed vault) son el 'Platform Console' de facto — sin RBAC, sin audit trail propio, operados a mano contra producción. Solo el CLI de templates fue mencionado (de pasada) por el audit HSM.
- Supabase Storage como capa: buckets (tenant-media, media inbound del Inbox) con sus policies de aislamiento — el método del audit cubrió RLS de tablas (ADR-0025) pero ninguna categoría cubre Storage.
- Emails de Auth de Supabase (invite de team/page.tsx vía inviteUserByEmail, recovery, confirm): el audit de Auth cubrió los flujos web pero no el contenido/branding/es-CO/deliverability de los emails que el sistema manda en su nombre.
- Coherencia del API Gateway como producto: rate limits (RL_WRITE_DEFAULT), CORS, versionado /api/v1, y el contrato de error es-CO uniforme entre ~27 routers — cada audit vio su router; nadie auditó la superficie HTTP agregada que consume el frontend.

_Método del crítico: Método: comparé los 23 módulos auditados contra (a) las 24 rutas vivas del sidebar (apps/web/app/dashboard/sidebar-client.tsx), (b) los 27 routers registrados en services/api/main.py:139-191, (c) los ~15 jobs del worker (services/ai-orchestrator/worker.py) y (d) el árbol funcional canónico .context/00-product.md. Hallazgos de mayor severidad: (1) Promociones/cupones es un módulo completo del sidebar con dinero de por medio y cero cobertura; (2) el subsistema de emails transaccionales al cliente (5 plantillas en wompi_webhook.py:1609-1952, best-effort silencioso) no tiene dueño; (3) las notificaciones al operador (notification_settings + Telegram bidireccional + email) son la columna vertebral de la escalación humana y solo fueron auditadas en su tab de connect. Confianza: alta en blind spots 1-7 (evidencia directa en código y sidebar); media en 8-10 (posible cobertura parcial dentro de audits existentes — verificar con cada auditor antes de contar como gap nuevo). Deliberadamente NO listé: DSR/SIC (tienen UI en contacts y settings/legal, plausiblemente dentro de los audits de Contactos y Config·Legal), wompi/meli webhooks core (reclamados por Pedidos/MeLi), rutas legacy redirect (inventory, account), y servicios README-only (cron, shopify, mercadolibre connector) que no son superficie real. Sesgo residual: no pude verificar el texto completo de los 23 informes originales, solo sus resúmenes — si algún informe interno ya cubre p.ej. categorías o el health page, esos ítems bajan a 'cubierto sin resumir'._

---

## Propuesta de cierre — Fases 1..7 (orden por nivel arquitectónico)

Orden razonado: **transversales primero** (los cimientos levantan todos los módulos y evitan retrabajo — lección del finiquito Fase A), luego el **camino del dinero**, luego el resto por dependencia. Esfuerzos = suma ponderada de los gaps del módulo (S=0.3d · M=1.2d · L=3.5d), **estimación relativa para priorizar, no compromiso de calendario**.

| Fase | Módulos | Gaps | Peso (~días-dev) | Racional |
|---|---|---|---|---|
| **F1 · Cimientos transversales** | design_system | 23 | ~20 | design system (paleta 700, a11y primitivos, tokens) + patrones compartidos: agregación server-side con ventana, error-surfacing en reads, loading/empty states canónicos. Cada módulo posterior se cierra contra primitivos YA correctos — evita retrabajo doble. En paralelo: Fase 0.1 (mini-audit de los 16 puntos ciegos). |
| **F2 · Camino del dinero (VENTAS+Inbox)** | inbox, orders, shipping, claims, contacts | 145 | ~88 | el flujo que factura: conversación→pedido→pago→despacho→postventa. + Promociones/cupones (punto ciego sin dueño). |
| **F3 · Productos y canales** | catalog, marketplace_meli, purchases | 103 | ~77 | catálogo unificado (+ decisión media/categories), sync MeLi, reposición. |
| **F4 · Verdad numérica** | metrics, finance, dashboard_home, audit_log | 112 | ~68 | las 4 superficies analíticas comparten la misma causa raíz (fetch-all sin ventana, conteo en JS) — se cierran juntas con el patrón de agregación de F1. |
| **F5 · IA y conocimiento** | knowledge_base, ai_agents, whatsapp_templates, bot_engine | 105 | ~68 | KB/RAG, agentes, templates HSM y el remate del bot engine (ya 85%). |
| **F6 · Identidad y configuración** | settings_general, security_mfa, team_rbac, integrations, auth_flows | 143 | ~94 | settings, MFA, RBAC, integraciones + puntos ciegos: health page, notificaciones operador, emails transaccionales. |
| **F7 · Onboarding + gate final** | tenant_onboarding | 30 | ~28 | camino provisión→operando repetible + UAT journey E2E con tenant FRESCO (pedido→pago→guía→entrega→reclamo) + flujos cross-módulo del crítico. Gate: 100% verde = ecosistema cerrado. |
| **TOTAL** | 23 módulos | 661 | **~443** | + Fase 0.1 puntos ciegos (~5-8d audit) |

**Cadencia propuesta:** cada fase cierra con (1) gaps resueltos con tests, (2) UAT dinámico del flujo real del módulo, (3) validate.sh --ci verde, (4) deploy a production (expand-contract si aplica). Sin pasar a la siguiente fase con la anterior abierta (lección Q1 finiquito).

**Decisiones founder requeridas ANTES de F1** (extraídas de los módulos — lista completa en cada sección):

1. ⚖️ Los 16 puntos ciegos del crítico: ¿Fase 0.1 formal (mini-audit, ~5-8d) o asignarlos direct a fases?
2. ⚖️ `rma_requests` (retracto Ley 1480): ¿cablear el flujo completo en Reclamos o DROP de la tabla?
3. ⚖️ Ruta `media` hidden: ¿integrar al editor de Catálogo o módulo propio visible?
4. ⚖️ Dark mode: hoy NO existe theming — ¿se agrega al DoD o se difiere post-Platform Console?
5. ⚖️ Sentry: DSNs por configurar en Render (decidido: se valida al abordar Platform Console).
