/**
 * Validators de documento de identidad colombiano (rev. 69, ajustado rev. 102).
 *
 * Espejo del helper Python en
 * services/api/dependencies/contact_validators.py — mismas reglas para
 * que el frontend pueda validar antes de enviar al backend.
 *
 * Tipos aceptados: alineados con Wompi customer_data.legal_id_type para CO.
 *
 * **Rev. 102** — TI (Tarjeta de Identidad) removido: corresponde a menores
 * de edad (7-17 años). Decreto 1377/2013 Art. 7 prohíbe el tratamiento de
 * datos de menores sin autorización del representante legal — flujo no
 * soportado por el sistema. Si se requiere, implementar flujo de
 * representante legal (Sprint dedicado, F8 backlog).
 *
 * **Rev. 102** — Rangos ajustados a realidad colombiana (eran laxos):
 *   CC  6-12 → 6-10 (cédula CO máx. 10 dígitos)
 *   CE  4-8  → 6-7  (Migración Colombia)
 *   NIT 9-13 → 9-11 (9 dígitos + DV opcional con guion)
 *   PP  6-15 → 6-15 (sin cambio: cubre pasaportes extranjeros)
 */

export const DOCUMENT_TYPES_CO = ['CC', 'CE', 'NIT', 'PP', 'OTHER'] as const
export type DocumentTypeCO = (typeof DOCUMENT_TYPES_CO)[number]

export const DOCUMENT_TYPE_LABELS: Record<DocumentTypeCO, string> = {
  CC: 'Cédula de Ciudadanía',
  CE: 'Cédula de Extranjería',
  NIT: 'NIT (empresa)',
  PP: 'Pasaporte',
  OTHER: 'Otro',
}

interface LengthRule {
  min: number
  max: number
  digitsOnly: boolean
}

const DOC_LEN_RULES: Record<DocumentTypeCO, LengthRule> = {
  CC:    { min: 6, max: 10, digitsOnly: true },
  CE:    { min: 6, max: 7,  digitsOnly: true },
  NIT:   { min: 9, max: 11, digitsOnly: false }, // admite '-DV' (1 dígito)
  PP:    { min: 6, max: 15, digitsOnly: false },
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
