/**
 * Helpers de auth compartidos por el módulo login→sesión (F6 cierre auth_flows).
 *
 *  - translateAuthError: traduce códigos/mensajes de Supabase GoTrue a es-CO.
 *    Supabase devuelve mensajes crudos en inglés ("Email link is invalid or has
 *    expired", "Invalid login credentials"). El operador colombiano nunca debe
 *    verlos: se mapean por `error.code` (contrato estable de GoTrue) y, si el
 *    código es desconocido, se usa un fallback neutral que NO filtra detalle
 *    interno ni revela si el correo existe.
 *  - isBannedError: detecta el ban nativo de Supabase (ban_duration) para
 *    enrutar al miembro suspendido a /cuenta-suspendida en vez del genérico.
 *  - needsAal2: detecta que updateUser exige AAL2 (sesión recovery AAL1 con
 *    factor TOTP verified) para guiar al challenge en vez de fallar en crudo.
 *  - safeNextPath: valida el parámetro `next` (deep-link) como ruta interna
 *    same-origin. Cierra el open-redirect de /auth/confirm (vector de phishing:
 *    next=https://evil.com ganaba sobre origin).
 */

/** Forma mínima de un AuthError de GoTrue (evita acoplar al tipo interno). */
type AuthErrorLike = { code?: string | null; message?: string | null } | null | undefined

const AUTH_MESSAGES_ES: Record<string, string> = {
  invalid_credentials: 'Correo o contraseña incorrectos.',
  invalid_grant: 'Correo o contraseña incorrectos.',
  email_not_confirmed: 'Debes confirmar tu correo antes de entrar. Revisa tu bandeja de entrada.',
  user_banned: 'Tu cuenta está suspendida. Contacta al administrador de tu negocio.',
  user_not_found: 'Correo o contraseña incorrectos.',
  over_request_rate_limit: 'Demasiados intentos. Espera unos minutos e inténtalo de nuevo.',
  over_email_send_rate_limit: 'Enviaste demasiadas solicitudes seguidas. Espera unos minutos e inténtalo de nuevo.',
  otp_expired: 'El enlace expiró o ya fue utilizado. Solicita uno nuevo.',
  otp_disabled: 'Este método de verificación no está disponible. Solicita un enlace nuevo.',
  flow_state_expired: 'El enlace expiró. Solicita uno nuevo.',
  flow_state_not_found: 'El enlace es inválido o ya fue utilizado. Solicita uno nuevo.',
  bad_code_verifier: 'No pudimos validar el enlace en este navegador. Ábrelo en el mismo dispositivo donde lo solicitaste.',
  weak_password: 'La contraseña es demasiado débil. Usa al menos 8 caracteres combinando letras y números.',
  same_password: 'La nueva contraseña no puede ser igual a la anterior.',
  session_not_found: 'Tu sesión expiró. Inicia sesión de nuevo.',
  session_expired: 'Tu sesión expiró. Inicia sesión de nuevo.',
  validation_failed: 'Los datos ingresados no son válidos. Verifícalos e inténtalo de nuevo.',
}

const GENERIC_ES = 'No pudimos completar la operación. Inténtalo de nuevo.'

/** Devuelve el `code` de GoTrue si el error lo trae (contrato estable). */
export function getAuthErrorCode(err: unknown): string | undefined {
  if (!err || typeof err !== 'string') {
    const e = err as AuthErrorLike
    if (e && typeof e === 'object' && typeof e.code === 'string' && e.code.length > 0) {
      return e.code
    }
  }
  return undefined
}

/**
 * Traduce un AuthError a es-CO. Prioriza `error.code`; si es desconocido,
 * devuelve `fallback` (neutral, sin filtrar el mensaje crudo en inglés).
 */
export function translateAuthError(err: unknown, fallback: string = GENERIC_ES): string {
  const code = getAuthErrorCode(err)
  if (code && AUTH_MESSAGES_ES[code]) return AUTH_MESSAGES_ES[code]
  return fallback
}

/** El miembro fue baneado nativamente (ban_duration) por el owner del tenant. */
export function isBannedError(err: unknown): boolean {
  const code = getAuthErrorCode(err)
  if (code === 'user_banned') return true
  const msg = (err as AuthErrorLike)?.message
  return typeof msg === 'string' && /user is banned|user_banned/i.test(msg)
}

/**
 * updateUser({password}) exige AAL2 cuando hay un factor TOTP verified y la
 * sesión actual es AAL1 (p.ej. sesión de recovery por email). Supabase reporta
 * esto por mensaje ("AAL2 required...") o por código insufficient_aal.
 */
export function needsAal2(err: unknown): boolean {
  const code = getAuthErrorCode(err)
  if (code === 'insufficient_aal') return true
  const msg = (err as AuthErrorLike)?.message
  return typeof msg === 'string' && /aal2|insufficient.*aal|higher.*aal/i.test(msg)
}

/**
 * Valida un parámetro `next` (deep-link) como ruta interna same-origin.
 * Rechaza URLs absolutas, protocol-relative (//host), y trucos de barra
 * invertida que el navegador normaliza a //. Devuelve `fallback` si no es una
 * ruta interna segura. Preserva pathname + query; descarta el hash.
 */
export function safeNextPath(
  next: string | null | undefined,
  fallback: string = '/dashboard',
): string {
  if (typeof next !== 'string' || next.length === 0) return fallback
  if (!next.startsWith('/')) return fallback
  // Trucos que resuelven a otro origen: //host, /\host, /%2F, /%5C
  if (/^\/[/\\]/.test(next) || /^\/%2[fF]/.test(next) || /^\/%5[cC]/.test(next)) return fallback
  try {
    // Base sentinel: si `next` inyecta un host, u.origin deja de ser el sentinel.
    const base = 'http://internal.invalid'
    const u = new URL(next, base)
    if (u.origin !== base) return fallback
    return u.pathname + u.search
  } catch {
    return fallback
  }
}
