// ADR-0027 / ADR-0029 — helpers puros (sin React) del módulo Categorías.
// Extraídos de los componentes para poder cubrirlos con tests (vitest) sin montar UI.

import type { AttributeDef } from '../_components/attribute-contract-editor'

/**
 * Clave normalizada (`name`, única por tenant) derivada del label visible:
 * sin acentos, minúsculas, `_` por separadores. Es el mismo criterio que el
 * bot usa para el matching por categoría, por eso debe ser determinístico.
 */
export function slugify(s: string): string {
  return s
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '') // diacríticos combinantes
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

/**
 * Convierte el texto «opciones separadas por coma» del editor de contrato en el
 * array `allowed_values`. Para tipos numéricos (metric/number) castea a Number
 * cuando el token es numérico; para boolean/text no hay lista cerrada.
 */
export function parseAllowedValues(
  type: AttributeDef['type'],
  allowedText: string,
): (string | number)[] {
  if (type === 'boolean' || type === 'text') return []
  return allowedText
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
    .map(v => ((type === 'metric' || type === 'number') && v !== '' && !isNaN(Number(v)) ? Number(v) : v))
}
