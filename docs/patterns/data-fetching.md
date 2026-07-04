# Patrón canónico de data-fetching — Tenant Console

**Establecido en F1 (2026-07-04)** como cimiento del cierre del ecosistema tenant.
Todos los módulos (F2-F7) deben seguir estas reglas. El audit de completitud
2026-07-04 encontró que la debilidad sistémica #1 es la analítica que hace
fetch-all sin ventana y no verifica errores (métricas 30% perf, finanzas 38%,
dashboard con conteos truncados).

## 1. Todo listado/analítica se acota (paginación o ventana temporal)

PostgREST corta en `max-rows` (default 1000) **sin error**: una query que trae
"todos los pedidos históricos" para contar en JS devuelve datos truncados y
sesgados en un tenant activo, sin ningún aviso.

- **Contar** → `.select('id', { count: 'exact', head: true })` (no traer filas).
- **Agregar por tiempo** → filtrar por ventana con `lib/date-window.ts`
  (`bogotaWindowUTC(n).fromUTC`), nunca traer todo el histórico al cliente.
- **Sumar montos** → preferir un RPC/vista agregada en Postgres sobre traer filas
  y reducir en JS. Si se trae, acotar por ventana + advertir si se topa el límite.

```ts
// ❌ trunca a 1000 sin avisar
const { data } = await sb.from('orders').select('total_amount')
const total = (data ?? []).reduce((a, o) => a + o.total_amount, 0)

// ✅ acotado + agregado en DB
const { data, error } = await sb.rpc('orders_revenue_since', { p_from: bogotaWindowUTC(30).fromUTC })
```

## 2. Fechas y agrupación por día: SIEMPRE hora Colombia

Colombia es UTC-5 sin DST. Agrupar por día en UTC manda los eventos de las
19:00-24:00 al día siguiente. Usar `bogotaDayKey()` / `bogotaDayKeys()` /
`bogotaWindowUTC()` de `lib/date-window.ts` — nunca `toISOString().slice(0,10)`
crudo sobre un `created_at`.

## 3. Los errores de lectura se SURFACEAN, nunca se caen a cero silencioso

Un fallo de RLS/red que se ignora pinta "Bajo stock: 0" o "Agente humano: 0"
como verdad operativa — peor que un error visible.

```ts
// ❌ falso 0 ante fallo
const count = res.count ?? 0

// ✅ diferenciar "0 real" de "no se pudo cargar"
if (res.error) {
  // server component: renderizar estado de error (no el empty state de primer uso)
  // o loggear + marcar la métrica como no disponible ('—'), no como 0.
}
const count = res.count ?? 0
```

En **server components** con múltiples queries paralelas, destructurar `error`
de cada `Promise.all` y decidir por-tarjeta si mostrar dato, '—' (no disponible)
o un banner de error — no colapsar todo a 0.

## 4. Mutaciones: contrato `ActionResult`, feedback por toast

- Server actions de mutación devuelven `ActionResult` (`lib/action-result.ts`),
  nunca `throw` (se enmascara en prod).
- Éxito/error se comunican por **toast** (`sonner`), canal único del DS.
- Confirmaciones destructivas por `useConfirm()` (`components/ui/confirm-dialog`),
  nunca `confirm()` nativo.
- `SubmitButton` muestra "Guardado" solo si la action devolvió `ok` (dentro de
  `<ActionResultForm>`).

## 5. Coherencia de KPI entre módulos

Una métrica que enlaza a otro módulo (p.ej. "Bajo stock" del dashboard → Catálogo)
debe usar la **misma fórmula** que el módulo destino. Definir el criterio una vez
(idealmente en un helper compartido) y consumirlo en ambos lados.
