/**
 * window — ventana temporal server-side del P&L en hora Colombia (F4 2026-07-04).
 *
 * ANTES: page.tsx traía TODO el histórico de orders+order_items+expenses sin
 * ventana ni límite y filtraba en JS. Con >1000 pedidos PostgREST trunca a
 * max-rows SIN error → el P&L quedaba silenciosamente incorrecto. Ahora la
 * ventana se resuelve server-side por searchParam y las queries van acotadas
 * `.gte(fromUTC).lte(toUTC)`.
 *
 * Colombia = UTC-5 sin DST. "Mes actual" = desde el 1 a las 00:00 hora Colombia
 * (= 05:00 UTC) hasta ahora — nunca `toISOString().slice` crudo.
 */
export type FinanceRange = 'month' | 'last_month' | 'all'

const OFFSET_MS = 5 * 60 * 60 * 1000 // Bogota → UTC = +5h

export function parseRange(v: string | undefined): FinanceRange {
  return v === 'last_month' || v === 'all' ? v : 'month'
}

/** 00:00 hora Colombia del primer día del mes (year,monthIdx) → ISO UTC. */
function bogotaMonthStartUTC(year: number, monthIdx: number): Date {
  // 00:00 Colombia = 05:00 UTC de ese mismo día calendario.
  return new Date(Date.UTC(year, monthIdx, 1, 5, 0, 0, 0))
}

export type Window = { fromUTC: string; toUTC: string; label: string }

export function financeWindow(range: FinanceRange, now: Date = new Date()): Window {
  // "Ahora" en calendario Colombia para saber el mes en curso.
  const bogotaNow = new Date(now.getTime() - OFFSET_MS)
  const y = bogotaNow.getUTCFullYear()
  const m = bogotaNow.getUTCMonth()

  if (range === 'all') {
    return { fromUTC: new Date(0).toISOString(), toUTC: now.toISOString(), label: 'Todo el histórico' }
  }

  if (range === 'last_month') {
    const from = bogotaMonthStartUTC(y, m - 1)
    // fin exclusivo: 1 ms antes del inicio del mes actual.
    const to = new Date(bogotaMonthStartUTC(y, m).getTime() - 1)
    const label = capitalize(from.toLocaleDateString('es-CO', { timeZone: 'America/Bogota', month: 'long', year: 'numeric' }))
    return { fromUTC: from.toISOString(), toUTC: to.toISOString(), label }
  }

  // month (por defecto)
  const from = bogotaMonthStartUTC(y, m)
  const label = capitalize(from.toLocaleDateString('es-CO', { timeZone: 'America/Bogota', month: 'long', year: 'numeric' }))
  return { fromUTC: from.toISOString(), toUTC: now.toISOString(), label }
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}
