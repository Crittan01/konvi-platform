/**
 * Validators de documento de identidad colombiano (rev. 69).
 *
 * Espejo del helper Python en
 * services/api/dependencies/contact_validators.py — mismas reglas para
 * que el frontend pueda validar antes de enviar al backend.
 *
 * Tipos aceptados: alineados con Wompi customer_data.legal_id_type para CO.
 */

export const DOCUMENT_TYPES_CO = ['CC', 'CE', 'NIT', 'PP', 'TI', 'OTHER'] as const
export type DocumentTypeCO = (typeof DOCUMENT_TYPES_CO)[number]

export const DOCUMENT_TYPE_LABELS: Record<DocumentTypeCO, string> = {
  CC: 'Cédula de Ciudadanía',
  CE: 'Cédula de Extranjería',
  NIT: 'NIT (empresa)',
  PP: 'Pasaporte',
  TI: 'Tarjeta de Identidad',
  OTHER: 'Otro',
}

interface LengthRule {
  min: number
  max: number
  digitsOnly: boolean
}

const DOC_LEN_RULES: Record<DocumentTypeCO, LengthRule> = {
  CC:    { min: 6, max: 12, digitsOnly: true },
  CE:    { min: 4, max: 8,  digitsOnly: true },
  NIT:   { min: 9, max: 13, digitsOnly: false }, // admite '-1' del DV
  PP:    { min: 6, max: 15, digitsOnly: false },
  TI:    { min: 8, max: 11, digitsOnly: true },
  OTHER: { min: 3, max: 30, digitsOnly: false },
}

/** Limpia separadores comunes (puntos, espacios). Mantiene el guión del DV en NIT. */
export function normalizeDocumentNumber(raw: string | null | undefined): string {
  if (!raw) return ''
  return raw.replace(/\./g, '').replace(/\s/g, '').trim()
}

export interface DocumentValidationResult {
  ok: boolean
  error?: string
}

/**
 * Valida tipo + número de documento.
 *
 * - Si ambos vacíos → ok (campos opcionales hasta que el bot los pida).
 * - Si uno vacío y el otro no → error (deben ir juntos).
 * - Tipo debe estar en DOCUMENT_TYPES_CO.
 * - Número debe pasar reglas de longitud / formato según tipo.
 *
 * Nota: la validación de DV NIT (módulo-11) se hace en el backend (rev. 69).
 * El frontend solo valida estructura — backend rechaza si DV mal calculado.
 */
export function validateColombianDocument(
  docType: string | null | undefined,
  docNumber: string | null | undefined,
): DocumentValidationResult {
  const type = (docType || '').trim().toUpperCase()
  const number = normalizeDocumentNumber(docNumber)

  if (!type && !number) return { ok: true }
  if (!type || !number) {
    return { ok: false, error: 'Tipo y número de documento deben ir juntos.' }
  }
  if (!(DOCUMENT_TYPES_CO as readonly string[]).includes(type)) {
    return { ok: false, error: `Tipo de documento inválido. Aceptados: ${DOCUMENT_TYPES_CO.join(', ')}.` }
  }

  const rules = DOC_LEN_RULES[type as DocumentTypeCO]
  if (rules.digitsOnly && !/^\d+$/.test(number)) {
    return { ok: false, error: `Número de ${type} debe ser solo dígitos.` }
  }
  const lengthCheck = number.replace(/-/g, '')
  if (lengthCheck.length < rules.min || lengthCheck.length > rules.max) {
    return {
      ok: false,
      error: `Número de ${type} debe tener entre ${rules.min} y ${rules.max} caracteres.`,
    }
  }
  return { ok: true }
}
