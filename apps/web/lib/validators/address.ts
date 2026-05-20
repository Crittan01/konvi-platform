/**
 * Validators de dirección estructurada (rev. 69 · simplificado Sem 7 F2 cierre 2026-05-19).
 *
 * Espejo del helper Python en
 * services/api/dependencies/contact_validators.py.
 *
 * Decisión arquitectónica founder 2026-05-19 (Opción 1 SIMPLIFY):
 * `building_type` con 4 escenarios reales, sin `delivery_context` ortogonal.
 *
 *   building_type ∈ {casa, edificio, conjunto, oficina}
 *
 *   - casa: street + city + barrio (+ reference opcional).
 *   - edificio: + apartment (+ floor opcional + complex_name opcional).
 *   - conjunto: + conjunto_type ∈ {torres, casas}:
 *       - torres: tower + apartment.
 *       - casas: apartment (alias semántico "casa #X").
 *   - oficina: + apartment (= oficina #) (+ floor opcional + company_name opcional).
 *
 * Floor + company_name son SIEMPRE opcionales — no entran en required.
 */

export const BUILDING_TYPES = ['casa', 'edificio', 'conjunto', 'oficina'] as const
export type BuildingType = (typeof BUILDING_TYPES)[number]

export const BUILDING_TYPE_LABELS: Record<BuildingType, string> = {
  casa: 'Casa',
  edificio: 'Edificio / Apartamento',
  conjunto: 'Conjunto residencial',
  oficina: 'Oficina / Lugar de trabajo',
}

export const CONJUNTO_TYPES = ['torres', 'casas'] as const
export type ConjuntoType = (typeof CONJUNTO_TYPES)[number]

export const CONJUNTO_TYPE_LABELS: Record<ConjuntoType, string> = {
  torres: 'Torres (torre + apartamento)',
  casas: 'Casas (conjunto cerrado de casas)',
}

export interface StructuredAddress {
  street?: string | null
  number?: string | null
  neighborhood?: string | null
  city?: string | null
  state?: string | null
  dane_code?: string | null
  country?: string | null
  building_type?: BuildingType | null
  conjunto_type?: ConjuntoType | null
  tower?: string | null
  apartment?: string | null
  complex_name?: string | null
  reference?: string | null
  // Sem 7 F2 cierre 2026-05-19 — campos opcionales para oficina y edificio.
  floor?: string | null
  company_name?: string | null
}

/** Campos requeridos según building_type + conjunto_type.
 *
 * Sem 7 F2 cierre 2026-05-20 — P6 opción C (acuerdo founder):
 * `neighborhood` es OBLIGATORIO en residencial (casa/edificio/conjunto)
 * — transportadoras CO lo usan para sub-zonificar tarifa+ETA.
 * En OFICINA es OPCIONAL — edificios empresariales en zonas céntricas
 * no necesitan barrio para entrega.
 *
 * Espejo de `services/api/dependencies/contact_validators.py::address_required_fields`.
 */
export function addressRequiredFields(
  buildingType: BuildingType | null | undefined,
  conjuntoType?: ConjuntoType | null,
): string[] {
  const baseResidencial = ['street', 'neighborhood', 'city', 'state', 'dane_code']
  const baseOficina = ['street', 'city', 'state', 'dane_code']  // sin neighborhood
  if (buildingType === 'oficina') return [...baseOficina, 'apartment']
  if (buildingType === 'edificio') return [...baseResidencial, 'apartment']
  if (buildingType === 'conjunto') {
    if (conjuntoType === 'casas') return [...baseResidencial, 'apartment']
    // 'torres' (o conjunto_type ausente — back-compat) → tower + apartment.
    return [...baseResidencial, 'tower', 'apartment']
  }
  return baseResidencial // casa o no especificado
}

export interface AddressValidationResult {
  ok: boolean
  missing: string[]
}

/**
 * Valida que la dirección esté completa según building_type + conjunto_type.
 * Retorna lista de campos faltantes si no está completa.
 *
 * `floor` y `company_name` NO son obligatorios — son metadata informativa.
 */
export function validateAddress(addr: StructuredAddress | null | undefined): AddressValidationResult {
  if (!addr) return { ok: false, missing: addressRequiredFields(null) }
  const bt = (addr.building_type || '').toString().toLowerCase().trim() as BuildingType | ''
  if (bt && !(BUILDING_TYPES as readonly string[]).includes(bt)) {
    return { ok: false, missing: [`building_type inválido (debe ser ${BUILDING_TYPES.join(', ')})`] }
  }
  const ct = (addr.conjunto_type || '').toString().toLowerCase().trim() as ConjuntoType | ''
  if (ct && !(CONJUNTO_TYPES as readonly string[]).includes(ct)) {
    return { ok: false, missing: [`conjunto_type inválido (debe ser ${CONJUNTO_TYPES.join(', ')})`] }
  }
  // Si conjunto sin sub-tipo declarado → tower+apt por back-compat
  // (matching Python contact_validators.py).
  const required = addressRequiredFields(bt || null, ct || null)
  const missing = required.filter(field => !((addr as Record<string, unknown>)[field] || '').toString().trim())
  return { ok: missing.length === 0, missing }
}
