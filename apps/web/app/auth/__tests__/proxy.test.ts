import { describe, it, expect, beforeEach, vi } from 'vitest'
import { NextRequest } from 'next/server'

// F6 — tests del proxy (ex-middleware, Next 16) de enforcement AAL2 (la pieza de
// seguridad central del módulo auth). Se mockean SÓLO Supabase y la verificación
// HMAC de la cookie de recovery; NextRequest/NextResponse son reales para no
// falsear el contrato.

const state = vi.hoisted(() => ({
  user: null as null | { id: string },
  aal: null as null | { currentLevel: string; nextLevel: string },
  aalThrows: false,
  recoveryValid: false,
}))

vi.mock('@supabase/ssr', () => ({
  createServerClient: () => ({
    auth: {
      getUser: async () => ({ data: { user: state.user } }),
      mfa: {
        getAuthenticatorAssuranceLevel: async () => {
          if (state.aalThrows) throw new Error('supabase auth down')
          return { data: state.aal }
        },
      },
    },
  }),
}))

vi.mock('@/lib/mfa-recovery-cookie', () => ({
  verifyRecoveryCookie: async () => state.recoveryValid,
}))

// Import DESPUÉS de declarar los mocks.
import { proxy } from '../../../proxy'

function reqFor(path: string, opts: { recoveryCookie?: string; method?: string } = {}) {
  const r = new NextRequest(`http://localhost:3000${path}`, { method: opts.method ?? 'GET' })
  if (opts.recoveryCookie) r.cookies.set('mfa_recovery_session', opts.recoveryCookie)
  return r
}

const AAL_NEEDS_MFA = { currentLevel: 'aal1', nextLevel: 'aal2' }
const AAL_OK = { currentLevel: 'aal2', nextLevel: 'aal2' }

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'http://localhost'
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = 'anon'
  state.user = null
  state.aal = null
  state.aalThrows = false
  state.recoveryValid = false
})

function isPassThrough(res: Response): boolean {
  return res.headers.get('x-middleware-next') === '1'
}

describe('proxy — sesión ausente', () => {
  it('redirige /dashboard/* a /login preservando el deep-link en ?next=', async () => {
    const res = await proxy(reqFor('/dashboard/orders/123'))
    expect(res.status).toBe(307)
    const loc = res.headers.get('location')!
    expect(loc).toContain('/login')
    const next = new URL(loc).searchParams.get('next')
    expect(next).toBe('/dashboard/orders/123')
  })

  it('preserva también el query del destino en next', async () => {
    const res = await proxy(reqFor('/dashboard/inbox?tab=open'))
    const next = new URL(res.headers.get('location')!).searchParams.get('next')
    expect(next).toBe('/dashboard/inbox?tab=open')
  })

  it('no toca rutas fuera de /dashboard cuando no hay user', async () => {
    const res = await proxy(reqFor('/algo-publico'))
    expect(isPassThrough(res)).toBe(true)
  })
})

describe('proxy — gate AAL2 en /dashboard', () => {
  beforeEach(() => { state.user = { id: 'u1' } })

  it('redirige al challenge cuando la sesión es AAL1 con factor verified', async () => {
    state.aal = AAL_NEEDS_MFA
    const res = await proxy(reqFor('/dashboard/settings'))
    expect(res.status).toBe(307)
    const loc = new URL(res.headers.get('location')!)
    expect(loc.pathname).toBe('/login/mfa')
    expect(loc.searchParams.get('next')).toBe('/dashboard/settings')
  })

  it('deja pasar cuando la sesión ya es AAL2', async () => {
    state.aal = AAL_OK
    const res = await proxy(reqFor('/dashboard'))
    expect(isPassThrough(res)).toBe(true)
  })

  it('deja pasar AAL1 si la cookie de recovery está firmada y vigente (bypass legítimo)', async () => {
    state.aal = AAL_NEEDS_MFA
    state.recoveryValid = true
    const res = await proxy(reqFor('/dashboard', { recoveryCookie: 'valida' }))
    expect(isPassThrough(res)).toBe(true)
  })
})

describe('proxy — gate AAL2 en /api (F85)', () => {
  beforeEach(() => { state.user = { id: 'u1' }; state.aal = AAL_NEEDS_MFA })

  it('bloquea /api/* con 401 JSON (no redirect) cuando falta AAL2', async () => {
    const res = await proxy(reqFor('/api/audit/export'))
    expect(res.status).toBe(401)
    const body = await res.json()
    expect(body.detail).toBe('MFA requerida')
  })

  it('exceptúa /api/mfa/* (flujo de recovery pre-AAL2)', async () => {
    const res = await proxy(reqFor('/api/mfa/recovery-codes/verify'))
    expect(isPassThrough(res)).toBe(true)
  })
})

describe('proxy — fail-open observable ante outage de Supabase Auth', () => {
  it('deja pasar Y emite señal (console.error) si el check de AAL lanza', async () => {
    state.user = { id: 'u1' }
    state.aalThrows = true
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const res = await proxy(reqFor('/dashboard'))
    expect(isPassThrough(res)).toBe(true)
    expect(spy).toHaveBeenCalledOnce()
    expect(String(spy.mock.calls[0][0])).toContain('fail-open')
    spy.mockRestore()
  })
})

// YELLOW-7 (auditoría OWASP 2026-08-23): el fail-open queda acotado a lecturas.
describe('proxy — fail-closed en mutaciones ante outage de Supabase Auth', () => {
  it('POST /dashboard/* recibe 503 JSON si el check de AAL lanza', async () => {
    state.user = { id: 'u1' }
    state.aalThrows = true
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const res = await proxy(reqFor('/dashboard/orders', { method: 'POST' }))
    expect(res.status).toBe(503)
    const body = await res.json()
    expect(body.detail).toBe('Verificación MFA temporalmente no disponible. Reintenta.')
    expect(spy).toHaveBeenCalledOnce()
    spy.mockRestore()
  })

  it('POST /api/* también recibe 503 (no 401) si el check de AAL lanza', async () => {
    state.user = { id: 'u1' }
    state.aalThrows = true
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const res = await proxy(reqFor('/api/conversations/c1/send', { method: 'POST' }))
    expect(res.status).toBe(503)
    spy.mockRestore()
  })
})
