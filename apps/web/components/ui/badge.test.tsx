// @vitest-environment jsdom
// F1 2026-07-04: fija el fix de contraste AA de Badge (antes success/warning
// eran bg-green-500/yellow-500 + text-white, ~2:1, bajo el mínimo AA).
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { Badge } from './badge'

afterEach(cleanup)

describe('Badge', () => {
  it('success usa el patrón wash+texto-800 del tema (no text-white ilegible)', () => {
    render(<Badge variant="success">Pagado</Badge>)
    const el = screen.getByText('Pagado')
    expect(el.className).toContain('text-emerald-800')
    expect(el.className).not.toContain('text-white')
  })

  it('warning usa amber del tema con contraste AA', () => {
    render(<Badge variant="warning">Pendiente</Badge>)
    const el = screen.getByText('Pendiente')
    expect(el.className).toContain('text-amber-800')
    expect(el.className).not.toContain('bg-yellow-500')
  })

  it('default se mantiene sobre primary', () => {
    render(<Badge>Nuevo</Badge>)
    expect(screen.getByText('Nuevo').className).toContain('bg-primary')
  })
})
