// @vitest-environment jsdom
// Smoke tests de GlowButton (CTA magnético/líquido — PASO 3): monta, respeta
// disabled, el tap no rompe y el span de brillo está presente. jsdom no anima
// ni implementa matchMedia; se verifica el contrato de render (mismo patrón
// de stub que motion.test.tsx — pointer: fine resuelve false → sin magnetismo).
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { GlowButton } from './glow-button'

beforeAll(() => {
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

afterEach(cleanup)

describe('GlowButton', () => {
  it('renderiza children como botón y conserva className', () => {
    render(<GlowButton className="w-full">Entrar</GlowButton>)
    const btn = screen.getByRole('button', { name: 'Entrar' })
    expect(btn).toBeInTheDocument()
    expect(btn.className).toContain('w-full')
  })

  it('respeta disabled y type submit', () => {
    render(<GlowButton type="submit" disabled>Ingresando...</GlowButton>)
    const btn = screen.getByRole('button', { name: 'Ingresando...' })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('type', 'submit')
  })

  it('tap (whileTap) no crashea el render', () => {
    render(<GlowButton>Entrar</GlowButton>)
    const btn = screen.getByRole('button', { name: 'Entrar' })
    fireEvent.mouseDown(btn)
    fireEvent.mouseUp(btn)
    expect(btn).toBeInTheDocument()
  })

  it('incluye el span de brillo líquido (aria-hidden) para el hover', () => {
    const { container } = render(<GlowButton>Entrar</GlowButton>)
    const shine = container.querySelector('span[aria-hidden]')
    expect(shine).not.toBeNull()
    expect(shine?.className).toContain('group-hover:translate-x-full')
    expect(shine?.className).toContain('motion-reduce:hidden')
  })
})
