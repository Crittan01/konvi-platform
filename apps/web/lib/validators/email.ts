/**
 * Validator de email (rev. 79).
 *
 * Espejo del pattern Pydantic en
 *   services/api/routers/contacts.py::ContactCreate.email
 *
 * Regla:
 *   ^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$
 *
 * Rechaza casos típicos basura:
 *   "abc", "@x.co", "a@b", "a@b..co", "a b@c.co"
 *
 * NOTA: el regex es deliberadamente conservador. RFC 5322 admite formas más
 * exóticas (quoted-strings, IDN), pero nuestro stack (Wompi recibo + Envia
 * notificación) las rechaza upstream — mejor fallar acá con mensaje claro.
 */

export const EMAIL_PATTERN =
  /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/

export const EMAIL_PATTERN_SOURCE = EMAIL_PATTERN.source
export const EMAIL_MAX_LENGTH = 254

export interface EmailValidationResult {
  ok: boolean
  reason: 'empty' | 'too_long' | 'invalid_format' | null
}

export function validateEmail(value: string | null | undefined): EmailValidationResult {
  const v = (value ?? '').trim()
  if (!v) return { ok: false, reason: 'empty' }
  if (v.length > EMAIL_MAX_LENGTH) return { ok: false, reason: 'too_long' }
  if (!EMAIL_PATTERN.test(v)) return { ok: false, reason: 'invalid_format' }
  return { ok: true, reason: null }
}

export function isValidEmail(value: string | null | undefined): boolean {
  return validateEmail(value).ok
}
