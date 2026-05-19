/**
 * Validators de dirección estructurada (rev. 69 · ampliado Sem 7 F2 cierre 2026-05-19).
 *
 * Espejo del helper Python en
 * services/api/dependencies/contact_validators.py.
 *
 * Schema canónico documentado en migración 20260429000000_contacts_document_and_address.
 *
 * Tres dimensiones ortogonales del modelo address:
 *   1. building_type ∈ {casa, edificio, conjunto} — tipo de construcción.
 *   2. conjunto_type ∈ {torres, casas} — solo aplica si building_type='conjunto'.
 *      - torres: torre + apartamento (modelo original).
 *      - casas: solo apartment (alias semántico de "casa #X" — sin torre).
 *   3. delivery_context ∈ {residencia, oficina, otro} — ortogonal al
 *      building_type. Default 'residencia'. Si 'oficina' → company_name
 *      opcional. NO obligatorio para envío.
 */

export const BUILDING_TYPES = ['casa', 'edificio', 'conjunto'] as const
export type BuildingType = (typeof BUILDING_TYPES)[number]

export const BUILDING_TYPE_LABELS: Record<BuildingType, string> = {
  casa: 'Casa',
  edificio: 'Edificio / Apartamento',
  conjunto: 'Conjunto residencial',
}

export const CONJUNTO_TYPES = ['torres', 'casas'] as const
export type ConjuntoType = (typeof CONJUNTO_TYPES)[number]

export const CONJUNTO_TYPE_LABELS: Record<ConjuntoType, string> = {
  torres: 'Torres (torre + apartamento)',
  casas: 'Casas (conjunto cerrado de casas)',
}

export const DELIVERY_CONTEXTS = ['residencia', 'oficina', 'otro'] as const
export type DeliveryContext = (typeof DELIVERY_CONTEXTS)[number]

export const DELIVERY_CONTEXT_LABELS: Record<DeliveryContext, string> = {
  residencia: 'Residencia',
  oficina: 'Oficina / Lugar de trabajo',
  otro: 'Otro',
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
  delivery_context?: DeliveryContext | null
  company_name?: string | null
}

/** Campos requeridos según building_type + conjunto_type. */
export function addressRequiredFields(
  buildingType: BuildingType | null | undefined,
  conjuntoType?: ConjuntoType | null,
): string[] {
  const base = ['street', 'neighborhood', 'city', 'state', 'dane_code']
  if (buildingType === 'edificio') return [...base, 'apartment']
  if (buildingType === 'conjunto') {
    if (conjuntoType === 'casas') return [...base, 'apartment']
    // 'torres' (o conjunto_type ausente — back-compat) → tower + apartment.
    return [...base, 'tower', 'apartment']
  }
  return base // casa o no especificado
}

export interface AddressValidationResult {
  ok: boolean
  missing: string[]
}

/**
 * Valida que la dirección esté completa según building_type + conjunto_type.
 * Retorna lista de campos faltantes si no está completa.
 *
 * `delivery_context` y `company_name` NO son obligatorios para completeness —
 * son metadata informativa (default 'residencia' si ausente).
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
  const dc = (addr.delivery_context || '').toString().toLowerCase().trim() as DeliveryContext | ''
  if (dc && !(DELIVERY_CONTEXTS as readonly string[]).includes(dc)) {
    return { ok: false, missing: [`delivery_context inválido (debe ser ${DELIVERY_CONTEXTS.join(', ')})`] }
  }
  // Si conjunto sin sub-tipo declarado → tower+apt por back-compat
  // (matching Python contact_validators.py).
  const required = addressRequiredFields(bt || null, ct || null)
  const missing = required.filter(field => !((addr as Record<string, unknown>)[field] || '').toString().trim())
  return { ok: missing.length === 0, missing }
}
