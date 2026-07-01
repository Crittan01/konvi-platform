/**
 * ADR-0029 F3 — lógica pura del contrato de atributos por categoría.
 *
 * Extraída del catalog-form para (a) aislar la lógica que 2 rondas de revisión adversarial demostraron
 * propensa a error (divergencia estado↔UI en un overlay sobre datos free-form), (b) blindarla con tests
 * de regresión, y (c) reusarla en las superficies que faltan (edit-drawer, mass-importer).
 *
 * Invariante central: el valor que se persiste SIEMPRE es el que el usuario ve. Nunca se envía un valor
 * fantasma oculto — de ahí `finalizeAttrs` (dedup keep-first == lo que muestra el dropdown, que lee con .find).
 */
import type { AttributeDef } from '../types'

export type Attr = { key: string; value: string }

/** Clave normalizada para matching case/espacio-insensible (evita ejes duplicados 'volumen' vs 'Volumen '). */
export const normKey = (s: string): string => s.trim().toLowerCase()

/** Valor mostrable/almacenable de una opción: valor + unidad ('10' + 'ml' → '10ml'). */
export const optionOf = (d: AttributeDef, val: string): string => (d.unit ? `${val}${d.unit}` : val)

/** Opciones canónicas de un atributo de conjunto cerrado. */
export const optionsFor = (d: AttributeDef): string[] => (d.allowed_values ?? []).map(v => optionOf(d, v))

/** Lee el valor de un atributo por label, con matching normalizado. */
export const getAttrValue = (attrs: Attr[], label: string): string =>
  attrs.find(a => normKey(a.key) === normKey(label))?.value ?? ''

/** ¿El valor actual está presente pero fuera del conjunto de opciones? (→ el dropdown lo expone como visible). */
export const orphanValue = (cur: string, opts: string[]): string | null =>
  cur && !opts.includes(cur) ? cur : null

/**
 * Alinea atributos (p.ej. generados por el matrix) contra el contrato: key → label canónico, y valor → la
 * opción canónica (match case/espacio-insensible, con o sin unidad). Si el valor no matchea ninguna opción,
 * se preserva tal cual (el dropdown lo expondrá como "fuera de contrato", nunca se oculta).
 */
export function canonicalizeAttrs(attrs: Attr[], contractAttrs: AttributeDef[]): Attr[] {
  return attrs.map(a => {
    const d = contractAttrs.find(x => normKey(x.label) === normKey(a.key))
    if (!d) return a
    const av = a.value.trim().toLowerCase().replace(/\s+/g, '')
    const match = (d.allowed_values ?? []).find(val => {
      const withUnit = optionOf(d, val).toLowerCase().replace(/\s+/g, '')
      return withUnit === av || String(val).toLowerCase().replace(/\s+/g, '') === av
    })
    return { key: d.label, value: match !== undefined ? optionOf(d, match) : a.value }
  })
}

/**
 * Normaliza JUSTO antes de enviar: canonicaliza + DEDUP por clave normalizada, conservando la PRIMERA
 * ocurrencia (== la que muestra el dropdown, que lee con .find). Garantiza payload == UI aunque el estado
 * haya acumulado colisiones (matrix, entrada manual, cambio de categoría).
 */
export function finalizeAttrs(attrs: Attr[], contractAttrs: AttributeDef[]): Attr[] {
  const seen = new Set<string>()
  const out: Attr[] = []
  for (const a of canonicalizeAttrs(attrs, contractAttrs)) {
    const k = normKey(a.key)
    if (k && seen.has(k)) continue
    if (k) seen.add(k)
    out.push(a)
  }
  return out
}

/** attrs → objeto plano, descartando pares vacíos. */
export function attrsToObj(attrs: Attr[]): Record<string, string> {
  const obj: Record<string, string> = {}
  for (const a of attrs) if (a.key.trim() && a.value.trim()) obj[a.key.trim()] = a.value.trim()
  return obj
}
