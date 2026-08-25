// @vitest-environment jsdom
// T7.5 — resolver del título de topbar (fuente única NAV_ITEMS + overrides de
// huérfanas) y smoke del componente (FadeIn keyeado por destino).
import { describe, it, expect, beforeAll, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import TopbarTitle, { resolveTopbarTitle } from './topbar-title'

const mocks = { pathname: '/dashboard' }
vi.mock('next/navigation', () => ({
  usePathname: () => mocks.pathname,
}))

beforeAll(() => {
  // jsdom no implementa matchMedia; useReducedMotion lo consulta al montar.
  window.matchMedia = window.matchMedia ?? ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})

describe('resolveTopbarTitle (T7.5)', () => {
  it('resuelve hojas directas y agrupadas desde NAV_ITEMS', () => {
    expect(resolveTopbarTitle('/dashboard')).toEqual({ label: 'Dashboard' })
    expect(resolveTopbarTitle('/dashboard/inbox')).toEqual({ label: 'Inbox' })
    expect(resolveTopbarTitle('/dashboard/orders')).toEqual({ label: 'Pedidos', group: 'Ventas' })
    expect(resolveTopbarTitle('/dashboard/catalog')).toEqual({ label: 'Productos' })
    expect(resolveTopbarTitle('/dashboard/metrics')).toEqual({ label: 'Métricas', group: 'Analítica' })
  })

  it('prefijo más largo gana en rutas anidadas (detalle hereda su módulo)', () => {
    expect(resolveTopbarTitle('/dashboard/settings/security')).toEqual({
      label: 'Seguridad', group: 'Configuración',
    })
    expect(resolveTopbarTitle('/dashboard/orders/9f1c-24ab')).toEqual({
      label: 'Pedidos', group: 'Ventas',
    })
  })

  it('overrides de huérfanas y precisión de integraciones', () => {
    expect(resolveTopbarTitle('/dashboard/media')).toEqual({ label: 'Media', group: 'Productos' })
    expect(resolveTopbarTitle('/dashboard/integrations/whatsapp')).toEqual({
      label: 'WhatsApp', group: 'Integraciones',
    })
    expect(resolveTopbarTitle('/dashboard/integrations/telegram')).toEqual({
      label: 'Telegram', group: 'Integraciones',
    })
    expect(resolveTopbarTitle('/dashboard/integrations')).toEqual({
      label: 'Integraciones', group: 'Configuración',
    })
  })
})

describe('TopbarTitle (T7.5)', () => {
  it('renderiza el destino actual con aria-current', () => {
    mocks.pathname = '/dashboard/claims'
    render(<TopbarTitle />)
    const el = screen.getByText('Reclamos')
    expect(el).toBeInTheDocument()
    expect(el).toHaveAttribute('aria-current', 'page')
    expect(screen.getByText(/Ventas/)).toBeInTheDocument()
  })
})
