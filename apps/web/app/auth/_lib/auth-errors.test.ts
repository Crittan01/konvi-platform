import { describe, it, expect } from 'vitest'
import {
  getAuthErrorCode,
  translateAuthError,
  isBannedError,
  needsAal2,
  safeNextPath,
} from './auth-errors'

describe('getAuthErrorCode', () => {
  it('extrae el code de un AuthError', () => {
    expect(getAuthErrorCode({ code: 'invalid_credentials', message: 'x' })).toBe('invalid_credentials')
  })
  it('ignora strings, null y objetos sin code', () => {
    expect(getAuthErrorCode('invalid_credentials')).toBeUndefined()
    expect(getAuthErrorCode(null)).toBeUndefined()
    expect(getAuthErrorCode({ message: 'x' })).toBeUndefined()
    expect(getAuthErrorCode({ code: '' })).toBeUndefined()
  })
})

describe('translateAuthError (es-CO, sin filtrar inglés)', () => {
  it('traduce credenciales inválidas', () => {
    expect(translateAuthError({ code: 'invalid_credentials', message: 'Invalid login credentials' }))
      .toBe('Correo o contraseña incorrectos.')
  })
  it('traduce email sin confirmar', () => {
    expect(translateAuthError({ code: 'email_not_confirmed' }))
      .toMatch(/confirmar tu correo/i)
  })
  it('traduce rate limit', () => {
    expect(translateAuthError({ code: 'over_request_rate_limit' }))
      .toMatch(/demasiados intentos/i)
  })
  it('traduce enlace OTP expirado', () => {
    expect(translateAuthError({ code: 'otp_expired' })).toMatch(/expiró/i)
  })
  it('nunca devuelve el mensaje crudo en inglés para códigos desconocidos', () => {
    const out = translateAuthError(
      { code: 'zzz_unknown', message: 'Email link is invalid or has expired' },
      'El enlace es inválido o expiró. Solicita uno nuevo.',
    )
    expect(out).not.toMatch(/[a-z] link is invalid/i)
    expect(out).toMatch(/inválido o expiró/i)
  })
  it('usa el fallback provisto cuando no hay code', () => {
    expect(translateAuthError('boom', 'fallback-x')).toBe('fallback-x')
  })
})

describe('isBannedError', () => {
  it('detecta por code user_banned', () => {
    expect(isBannedError({ code: 'user_banned', message: 'User is banned' })).toBe(true)
  })
  it('detecta por mensaje cuando no hay code', () => {
    expect(isBannedError({ message: 'User is banned' })).toBe(true)
  })
  it('no marca credenciales inválidas como ban', () => {
    expect(isBannedError({ code: 'invalid_credentials' })).toBe(false)
  })
})

describe('needsAal2', () => {
  it('detecta por mensaje AAL2 (contrato observado de updateUser)', () => {
    expect(needsAal2({ message: 'AAL2 required to update password' })).toBe(true)
  })
  it('detecta por code insufficient_aal', () => {
    expect(needsAal2({ code: 'insufficient_aal' })).toBe(true)
  })
  it('no marca credenciales inválidas', () => {
    expect(needsAal2({ code: 'invalid_credentials', message: 'nope' })).toBe(false)
  })
})

describe('safeNextPath (anti open-redirect)', () => {
  it('acepta rutas internas y preserva el query', () => {
    expect(safeNextPath('/dashboard/orders/123')).toBe('/dashboard/orders/123')
    expect(safeNextPath('/dashboard/inbox?tab=open')).toBe('/dashboard/inbox?tab=open')
  })
  it('descarta el hash', () => {
    expect(safeNextPath('/dashboard#section')).toBe('/dashboard')
  })
  it('rechaza URLs absolutas (phishing)', () => {
    expect(safeNextPath('https://evil.com')).toBe('/dashboard')
    expect(safeNextPath('http://evil.com/x')).toBe('/dashboard')
  })
  it('rechaza protocol-relative y trucos de barra', () => {
    for (const bad of ['//evil.com', '/\\evil.com', '/%2Fevil.com', '/%5Cevil.com']) {
      expect(safeNextPath(bad)).toBe('/dashboard')
    }
  })
  it('rechaza valores no-ruta y vacíos → fallback', () => {
    expect(safeNextPath(undefined)).toBe('/dashboard')
    expect(safeNextPath(null)).toBe('/dashboard')
    expect(safeNextPath('')).toBe('/dashboard')
    expect(safeNextPath('dashboard')).toBe('/dashboard')
    expect(safeNextPath('javascript:alert(1)')).toBe('/dashboard')
  })
  it('respeta un fallback personalizado', () => {
    expect(safeNextPath('https://evil.com', '/login')).toBe('/login')
  })
})
