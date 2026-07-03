import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { signRecoveryCookie, verifyRecoveryCookie } from './mfa-recovery-cookie'

// F83 — la cookie de recovery MFA debe estar firmada con HMAC (antes era el literal '1',
// fabricable por cualquiera → bypass total de AAL2).

const SECRET = 'test-secret-0123456789abcdef0123456789abcdef'
const USER = 'user-abc'
const NOW = 1_700_000_000

describe('mfa-recovery-cookie', () => {
  beforeAll(() => { process.env.MFA_RECOVERY_COOKIE_SECRET = SECRET })
  afterAll(() => { delete process.env.MFA_RECOVERY_COOKIE_SECRET })

  it('firma y verifica un round-trip válido', async () => {
    const value = await signRecoveryCookie(USER, NOW + 3600)
    expect(await verifyRecoveryCookie(value, USER, NOW)).toBe(true)
  })

  it('rechaza el literal viejo "1" (el bypass que arreglamos)', async () => {
    expect(await verifyRecoveryCookie('1', USER, NOW)).toBe(false)
  })

  it('rechaza una firma manipulada', async () => {
    const value = await signRecoveryCookie(USER, NOW + 3600)
    const tampered = value.slice(0, -2) + (value.endsWith('aa') ? 'bb' : 'aa')
    expect(await verifyRecoveryCookie(tampered, USER, NOW)).toBe(false)
  })

  it('rechaza si el userId no coincide (cookie de otro usuario)', async () => {
    const value = await signRecoveryCookie(USER, NOW + 3600)
    expect(await verifyRecoveryCookie(value, 'otro-user', NOW)).toBe(false)
  })

  it('rechaza una cookie expirada', async () => {
    const value = await signRecoveryCookie(USER, NOW - 1)
    expect(await verifyRecoveryCookie(value, USER, NOW)).toBe(false)
  })

  it('rechaza payload con user manipulado pero exp/sig originales', async () => {
    const value = await signRecoveryCookie(USER, NOW + 3600)
    const [, exp, sig] = value.split(':')
    expect(await verifyRecoveryCookie(`atacante:${exp}:${sig}`, 'atacante', NOW)).toBe(false)
  })

  it('fail-closed: sin secreto configurado, verify siempre false', async () => {
    delete process.env.MFA_RECOVERY_COOKIE_SECRET
    const value = `${USER}:${NOW + 3600}:cualquiercosa`
    expect(await verifyRecoveryCookie(value, USER, NOW)).toBe(false)
    process.env.MFA_RECOVERY_COOKIE_SECRET = SECRET
  })

  it('rechaza valores malformados', async () => {
    for (const bad of ['', 'a:b', 'a:b:c:d', 'user::sig']) {
      expect(await verifyRecoveryCookie(bad, USER, NOW)).toBe(false)
    }
  })
})
