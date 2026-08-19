import { describe, it, expect, beforeEach, vi } from 'vitest'
import { NextRequest } from 'next/server'

// F6 — tests del route handler /auth/confirm (PKCE + OTP). Cubre el fix de
// open-redirect (next controlado por el atacante en el link del correo) y la
// traducción es-CO de errores crudos de Supabase.

const state = vi.hoisted(() => ({
  exchangeError: null as null | { code?: string; message: string },
  otpError: null as null | { code?: string; message: string },
}))

vi.mock('@supabase/ssr', () => ({
  createServerClient: () => ({
    auth: {
      exchangeCodeForSession: async () => ({ error: state.exchangeError }),
      verifyOtp: async () => ({ error: state.otpError }),
    },
  }),
}))

vi.mock('next/headers', () => ({
  cookies: async () => ({ get: () => undefined, set: () => {} }),
}))

import { GET } from './route'

function get(url: string) {
  return GET(new NextRequest(`http://localhost:3000${url}`))
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'http://localhost'
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = 'anon'
  state.exchangeError = null
  state.otpError = null
})

describe('/auth/confirm — PKCE (?code=)', () => {
  it('intercambia el código y redirige al next interno', async () => {
    const res = await get('/auth/confirm?code=abc&next=' + encodeURIComponent('/set-password?mode=reset'))
    const loc = new URL(res.headers.get('location')!)
    expect(loc.pathname).toBe('/set-password')
    expect(loc.searchParams.get('mode')).toBe('reset')
  })

  it('bloquea open-redirect: next absoluto a otro origen cae al fallback interno', async () => {
    const res = await get('/auth/confirm?code=abc&next=https://evil.com/phish')
    const loc = new URL(res.headers.get('location')!)
    expect(loc.host).toBe('localhost:3000')
    expect(loc.pathname).toBe('/dashboard')
  })

  it('bloquea open-redirect protocol-relative (//evil.com)', async () => {
    const res = await get('/auth/confirm?code=abc&next=' + encodeURIComponent('//evil.com'))
    const loc = new URL(res.headers.get('location')!)
    expect(loc.host).toBe('localhost:3000')
    expect(loc.pathname).toBe('/dashboard')
  })

  it('traduce el error de Supabase a es-CO (no filtra inglés) al fallar el exchange', async () => {
    state.exchangeError = { code: 'otp_expired', message: 'Email link is invalid or has expired' }
    const res = await get('/auth/confirm?code=abc')
    const loc = new URL(res.headers.get('location')!)
    expect(loc.pathname).toBe('/login')
    const err = loc.searchParams.get('error')!
    expect(err).not.toMatch(/link is invalid/i)
    expect(err).toMatch(/expiró/i)
  })
})

describe('/auth/confirm — OTP (?token_hash=)', () => {
  it('verifica el OTP y redirige al next interno', async () => {
    const res = await get('/auth/confirm?token_hash=xyz&type=recovery&next=/dashboard/inbox')
    const loc = new URL(res.headers.get('location')!)
    expect(loc.pathname).toBe('/dashboard/inbox')
  })

  it('traduce el error del OTP a es-CO', async () => {
    state.otpError = { code: 'otp_expired', message: 'Token has expired or is invalid' }
    const res = await get('/auth/confirm?token_hash=xyz&type=recovery')
    const err = new URL(res.headers.get('location')!).searchParams.get('error')!
    expect(err).toMatch(/expiró/i)
  })
})

describe('/auth/confirm — sin parámetros', () => {
  it('redirige a /login con mensaje es-CO de enlace inválido', async () => {
    const res = await get('/auth/confirm')
    const loc = new URL(res.headers.get('location')!)
    expect(loc.pathname).toBe('/login')
    expect(loc.searchParams.get('error')).toMatch(/inv[aá]lido o expirado/i)
  })
})
