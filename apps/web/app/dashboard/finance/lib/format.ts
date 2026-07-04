/**
 * format — moneda y fecha es-CO deterministas para Finanzas (F4 2026-07-04).
 *
 * es-CO only. Formato fijo en SSR y cliente (sin hydration mismatch) y fechas
 * ancladas a America/Bogota para no mostrar el gasto "de hoy" como ayer.
 */
const COP = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 0 })

/** '$1.234.567' — pesos colombianos, sin decimales. */
export function formatCOP(value: number | null | undefined): string {
  return `$${COP.format(Math.round(Number(value) || 0))}`
}

/** Igual que formatCOP pero con signo negativo explícito para egresos. */
export function formatCOPNegative(value: number | null | undefined): string {
  const v = Math.round(Number(value) || 0)
  return v === 0 ? formatCOP(0) : `-${formatCOP(Math.abs(v))}`
}

/** Fecha corta es-CO fija en zona horaria Colombia. */
export function formatBogotaDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('es-CO', {
    timeZone: 'America/Bogota',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}
