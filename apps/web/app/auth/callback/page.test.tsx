// @vitest-environment jsdom
// F6 — tests de /auth/callback (flujo implicit de invitación: tokens en el hash
// fragment). Cubre setSession + redirect al next validado (anti open-redirect) y
// el estado de error traducido a es-CO.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const nav = vi.hoisted(() => ({
  replace: vi.fn(),
  params: new URLSearchParams(),
}))
const sb = vi.hoisted(() => ({
  setSessionError: null as null | { message: string },
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
}))

vi.mock('@/utils/supabase/client', () => ({
  createClient: () => ({
    auth: { setSession: async () => ({ error: sb.setSessionError }) },
  }),
}))

import AuthCallbackPage from './page'

function setHash(h: string) {
  window.location.hash = h
}

beforeEach(() => {
  nav.replace.mockReset()
  nav.params = new URLSearchParams()
  sb.setSessionError = null
  setHash('')
})
afterEach(() => setHash(''))

describe('/auth/callback', () => {
  it('establece la sesión y redirige al next por defecto (/set-password)', async () => {
    setHash('#access_token=AAA&refresh_token=BBB')
    render(<AuthCallbackPage />)
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith('/set-password'))
  })

  it('bloquea open-redirect: next=//evil.com cae al fallback interno', async () => {
    nav.params = new URLSearchParams({ next: '//evil.com' })
    setHash('#access_token=AAA&refresh_token=BBB')
    render(<AuthCallbackPage />)
    await waitFor(() => expect(nav.replace).toHaveBeenCalled())
    expect(nav.replace).toHaveBeenCalledWith('/set-password')
    expect(nav.replace).not.toHaveBeenCalledWith('//evil.com')
  })

  it('respeta un next interno válido', async () => {
    nav.params = new URLSearchParams({ next: '/dashboard/team' })
    setHash('#access_token=AAA&refresh_token=BBB')
    render(<AuthCallbackPage />)
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith('/dashboard/team'))
  })

  it('muestra error es-CO cuando no hay tokens en el hash', async () => {
    setHash('')
    render(<AuthCallbackPage />)
    expect(await screen.findByText(/Enlace inválido/i)).toBeInTheDocument()
    expect(nav.replace).not.toHaveBeenCalled()
  })
})
