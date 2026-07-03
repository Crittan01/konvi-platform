// F83 (seguridad) — firma/verificación HMAC de la cookie de sesión de recovery MFA.
//
// Antes la cookie era el literal '1': un atacante con la contraseña robada (sesión AAL1) simplemente
// añadía `Cookie: mfa_recovery_session=1` y el middleware omitía el enforcement AAL2 → bypass total de MFA.
// Ahora el valor es `${userId}:${exp}:${sig}` firmado con HMAC-SHA256 ligado al user + expiry, imposible de
// fabricar sin el secreto. crypto.subtle funciona en Node (route handlers) y en Edge (middleware).

export const RECOVERY_SESSION_COOKIE = 'mfa_recovery_session'

function b64url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

async function hmacSign(secret: string, payload: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  )
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload))
  return b64url(sig)
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i)
  return diff === 0
}

/** Firma el valor de la cookie: `${userId}:${exp}:${sig}`. exp es epoch seconds absoluto. */
export async function signRecoveryCookie(userId: string, expSeconds: number): Promise<string> {
  const secret = process.env.MFA_RECOVERY_COOKIE_SECRET
  if (!secret) throw new Error('MFA_RECOVERY_COOKIE_SECRET no configurado')
  const payload = `${userId}:${expSeconds}`
  return `${payload}:${await hmacSign(secret, payload)}`
}

/**
 * Verifica firma + userId + expiry. Fail-closed: devuelve false si falta el secreto, el valor está
 * malformado, la firma no coincide, el userId no es el de la sesión, o expiró.
 */
export async function verifyRecoveryCookie(
  value: string | undefined | null,
  userId: string | undefined | null,
  nowSeconds: number,
): Promise<boolean> {
  const secret = process.env.MFA_RECOVERY_COOKIE_SECRET
  if (!secret || !value || !userId) return false
  const parts = value.split(':')
  if (parts.length !== 3) return false
  const [uid, expStr, sig] = parts
  const exp = Number(expStr)
  if (!uid || !Number.isFinite(exp)) return false
  if (uid !== userId) return false
  if (exp <= nowSeconds) return false
  const expected = await hmacSign(secret, `${uid}:${exp}`)
  return timingSafeEqual(sig, expected)
}
