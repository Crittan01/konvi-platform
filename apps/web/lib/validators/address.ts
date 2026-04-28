/**
 * Validators de dirección estructurada (rev. 69).
 *
 * Espejo del helper Python en
 * services/api/dependencies/contact_validators.py.
 *
 * Schema canónico documentado en migración 20260429000000_contacts_document_and_address.
 */

export const BUILDING_TYPES = ['casa', 'edificio', 'conjunto'] as const
export type BuildingType = (typeof BUILDING_TYPES)[number]

export const BUILDING_TYPE_LABELS: Record<BuildingType, string> = {
  casa: 'Casa',
  edificio: 'Edificio / Apartamento',
  conjunto: 'Conjunto residencial',
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
  tower?: string | null
  apartment?: string | null
  complex_name?: string | null
  reference?: string | null
}

/** Campos requeridos según building_type. */
export function addressRequiredFields(buildingType: BuildingType | null | undefined): string[] {
  const base = ['street', 'neighborhood', 'city', 'state', 'dane_code']
  if (buildingType === 'edificio') return [...base, 'apartment']
  if (buildingType === 'conjunto') return [...base, 'tower', 'apartment']
  return base // casa o no especificado
}

export interface AddressValidationResult {
  ok: boolean
  missing: string[]
}

/**
 * Valida que la dirección esté completa según building_type.
 * Retorna lista de campos faltantes si no está completa.
 */
export function validateAddress(addr: StructuredAddress | null | undefined): AddressValidationResult {
  if (!addr) return { ok: false, missing: addressRequiredFields(null) }
  const bt = (addr.building_type || '').toString().toLowerCase().trim() as BuildingType | ''
  if (bt && !(BUILDING_TYPES as readonly string[]).includes(bt)) {
    return { ok: false, missing: [`building_type inválido (debe ser ${BUILDING_TYPES.join(', ')})`] }
  }
  const required = addressRequiredFields(bt || null)
  const missing = required.filter(field => !((addr as Record<string, unknown>)[field] || '').toString().trim())
  return { ok: missing.length === 0, missing }
}
