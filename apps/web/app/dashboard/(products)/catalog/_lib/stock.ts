// BLOQUE G-1 — fórmula canónica de "bajo stock", compartida por la stat card del
// catálogo, el filtro de la tabla (deep-link `?filter=low_stock`) y —conceptualmente—
// el count del dashboard home. Una sola verdad evita que las 3 superficies deriven.
//
// "Bajo stock" = quedan unidades pero por debajo (o igual) del umbral del tenant.
// Excluye agotados (stock === 0), que se cuentan aparte.
import type { Variation } from '../types'

export function isLowStockVariation(
  v: Pick<Variation, 'stock_quantity'>,
  threshold: number,
): boolean {
  return v.stock_quantity > 0 && v.stock_quantity <= threshold
}

/** Un producto está en "bajo stock" si ALGUNA de sus variaciones lo está. */
export function productHasLowStock(
  p: { product_variations: Pick<Variation, 'stock_quantity'>[] },
  threshold: number,
): boolean {
  return p.product_variations.some(v => isLowStockVariation(v, threshold))
}
