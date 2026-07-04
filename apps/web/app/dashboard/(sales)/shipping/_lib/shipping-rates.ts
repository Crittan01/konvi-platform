// Lógica pura del módulo Despachos, extraída para test (convención repo: _lib + vitest).

/**
 * Normaliza un código DANE a 5 dígitos.
 * Acepta el formato de 8 dígitos con sufijo '000' (p.ej. "05001000" → "05001").
 */
export function normalizeDaneCode(raw?: string | null): string {
  const digits = String(raw ?? '').replace(/\D/g, '')
  if (digits.length === 8 && digits.endsWith('000')) return digits.slice(0, 5)
  return digits.slice(0, 5)
}

export interface RateLike {
  rate_id?: string
  id?: string
  [key: string]: unknown
}

export interface RateHighlights {
  cheapest?: RateLike
  fastest?: RateLike
}

/**
 * Resuelve el índice de la tarifa "más rápida" dentro de `rates` usando los
 * highlights que calcula el backend (shipping.py _build_rate_highlights, basado
 * en delivery_estimate). Se hace matching por rate_id/id porque el frontend
 * reordena `rates` por precio, así que los índices no coinciden con el backend.
 *
 * Devuelve -1 si no hay fastest o no se encuentra (nunca revienta).
 */
export function resolveFastestIdx(rates: RateLike[], highlights?: RateHighlights): number {
  const fastest = highlights?.fastest
  if (!fastest) return -1
  const targetId = fastest.rate_id ?? fastest.id
  if (targetId == null) return -1
  return rates.findIndex(r => (r.rate_id ?? r.id) === targetId)
}
