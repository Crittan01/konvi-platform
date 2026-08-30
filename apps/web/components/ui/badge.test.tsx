// @vitest-environment jsdom
// F1 2026-07-04: fija el fix de contraste AA de Badge (antes success/warning
// eran bg-green-500/yellow-500 + text-white, ~2:1, bajo el mínimo AA).
// FASE 2 (2026-08-30): las aserciones migran de shades de paleta a los tokens
// semánticos de status (mismo patrón wash+fg, ahora theme-aware dark nativo).
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { Badge } from './badge'

afterEach(cleanup)

describe('Badge', () => {
  it('success usa el token semántico de status (no text-white ilegible)', () => {
    render(<Badge variant="success">Pagado</Badge>)
    const el = screen.getByText('Pagado')
    expect(el.className).toContain('text-success-fg')
    expect(el.className).toContain('bg-success-bg')
    expect(el.className).not.toContain('text-white')
  })

  it('warning usa el token semántico de status con contraste AA', () => {
    render(<Badge variant="warning">Pendiente</Badge>)
    const el = screen.getByText('Pendiente')
    expect(el.className).toContain('text-warning-fg')
    expect(el.className).toContain('bg-warning-bg')
    expect(el.className).not.toContain('bg-yellow-500')
  })

  it('default se mantiene sobre primary', () => {
    render(<Badge>Nuevo</Badge>)
    expect(screen.getByText('Nuevo').className).toContain('bg-primary')
  })
})
