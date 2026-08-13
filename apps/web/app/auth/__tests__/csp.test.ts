import { describe, it, expect, beforeEach, vi } from 'vitest'
import { NextRequest } from 'next/server'
import { buildCsp } from '@/lib/csp'

// G5 — CSP con nonce por request. Cubre el builder (lib/csp.ts) y la emisión
// del header en el proxy. La regla de oro: NUNCA 'unsafe-inline' ni
// 'unsafe-eval' en script-src fuera de dev.

function scriptSrcOf(csp: string): string {
  return csp.split(';').map((d) => d.trim()).find((d) => d.startsWith('script-src')) ?? ''
}

describe('buildCsp', () => {
  it('script-src lleva el nonce del request + strict-dynamic, sin unsafe-inline/eval en prod', () => {
    const csp = buildCsp('ABC123=', false)
    const script = scriptSrcOf(csp)
    expect(script).toContain("'nonce-ABC123='")
    expect(script).toContain("'strict-dynamic'")
    expect(script).not.toContain("'unsafe-inline'")
    expect(script).not.toContain("'unsafe-eval'")
  })

  it('directivas de endurecimiento presentes', () => {
    const csp = buildCsp('n', false)
    for (const d of [
      "default-src 'self'",
      "object-src 'none'",
      "base-uri 'none'",
      "form-action 'self'",
      "frame-src 'none'",
      "frame-ancestors 'self'",
      "worker-src 'self'",
    ]) {
      expect(csp).toContain(d)
    }
  })

  it('prod incluye upgrade-insecure-requests; dev no (localhost es http)', () => {
    expect(buildCsp('n', false)).toContain('upgrade-insecure-requests')
    expect(buildCsp('n', true)).not.toContain('upgrade-insecure-requests')
  })

  it('dev permite unsafe-eval (React Refresh); prod nunca', () => {
    expect(scriptSrcOf(buildCsp('n', true))).toContain("'unsafe-eval'")
    expect(scriptSrcOf(buildCsp('n', false))).not.toContain("'unsafe-eval'")
  })

  it('img-src mantiene Supabase/MeLi/data/blob y connect-src los orígenes por env', () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://tenant.supabase.co'
    process.env.API_URL = 'https://konvi-api.onrender.com'
    const csp = buildCsp('n', false)
    expect(csp).toContain('img-src')
    expect(csp).toContain('https://http2.mlstatic.com')
    expect(csp).toContain('https://tenant.supabase.co')
    expect(csp).toContain('wss://tenant.supabase.co')
    expect(csp).toContain('https://konvi-api.onrender.com')
  })
})

// ── Emisión en el proxy ──────────────────────────────────────────────────────
// Mismo harness de mocks que proxy.test.ts (Supabase + recovery cookie).

const state = vi.hoisted(() => ({
  user: null as null | { id: string },
}))

vi.mock('@supabase/ssr', () => ({
  createServerClient: () => ({
    auth: {
      getUser: async () => ({ data: { user: state.user } }),
      mfa: {
        getAuthenticatorAssuranceLevel: async () => ({ data: null }),
      },
    },
  }),
}))

vi.mock('@/lib/mfa-recovery-cookie', () => ({
  verifyRecoveryCookie: async () => false,
}))

// Import DESPUÉS de declarar los mocks.
import { proxy } from '../../../proxy'

describe('proxy — emisión CSP (G5)', () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'http://localhost'
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'anon'
    state.user = null
  })

  it('toda respuesta pass-through lleva Content-Security-Policy con nonce', async () => {
    const res = await proxy(new NextRequest('http://localhost:3000/algo-publico'))
    const csp = res.headers.get('content-security-policy')
    expect(csp).toBeTruthy()
    expect(csp).toContain("'nonce-")
    expect(csp).toContain("'strict-dynamic'")
    expect(scriptSrcOf(csp!)).not.toContain("'unsafe-inline'")
  })

  it('dos requests generan nonces distintos', async () => {
    const r1 = await proxy(new NextRequest('http://localhost:3000/a'))
    const r2 = await proxy(new NextRequest('http://localhost:3000/a'))
    const n1 = r1.headers.get('content-security-policy')!.match(/'nonce-([^']+)'/)?.[1]
    const n2 = r2.headers.get('content-security-policy')!.match(/'nonce-([^']+)'/)?.[1]
    expect(n1).toBeTruthy()
    expect(n1).not.toBe(n2)
  })
})
