// @vitest-environment jsdom
// T7.3 — pill de destino activo que VIAJA (NavPill con layoutId) respetando
// aria-current y el badge de takeover del inbox. jsdom no anima: se verifica
// el contrato de render (una sola pill, bajo el link activo, aria intacto).
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { BottomNav } from './bottom-nav'

let reduceMotion = false

const mocks = { pathname: '/dashboard/inbox' }
vi.mock('next/navigation', () => ({
  usePathname: () => mocks.pathname,
}))

beforeAll(() => {
  // jsdom no implementa matchMedia; useReducedMotion lo consulta al montar.
  window.matchMedia = window.matchMedia ?? ((query: string) => ({
    matches: query.includes('reduce') ? reduceMotion : false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})

afterEach(() => {
  reduceMotion = false
  cleanup()
})

const pillIn = (el: HTMLElement) => el.querySelector('[class*="bg-primary/10"]')

describe('BottomNav (T7.3)', () => {
  it('pinta la pill SOLO bajo el destino activo y aria-current intacto', () => {
    render(<BottomNav />)
    const inbox = screen.getByRole('link', { name: 'Inbox' })
    const pedidos = screen.getByRole('link', { name: 'Pedidos' })
    expect(inbox).toHaveAttribute('aria-current', 'page')
    expect(pedidos).not.toHaveAttribute('aria-current')
    expect(pillIn(inbox)).not.toBeNull()
    expect(pillIn(pedidos)).toBeNull()
  })

  it('el badge de takeover sigue vivo (aria-label + conteo)', () => {
    render(<BottomNav inboxBadge={3} />)
    const inbox = screen.getByRole('link', {
      name: 'Inbox, 3 conversaciones necesitan atención humana',
    })
    expect(inbox).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText('3')).toBeInTheDocument()
    // La pill no se come el badge: ambos dentro del mismo link.
    expect(pillIn(inbox)).not.toBeNull()
  })

  it('con prefers-reduced-motion la pill se pinta estática (mismo contrato)', () => {
    reduceMotion = true
    render(<BottomNav />)
    const inbox = screen.getByRole('link', { name: 'Inbox' })
    expect(inbox).toHaveAttribute('aria-current', 'page')
    expect(pillIn(inbox)).not.toBeNull()
  })
})
