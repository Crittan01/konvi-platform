// @vitest-environment jsdom
// Smoke tests de los primitivos motion del DS: montan, renderizan children y
// pasan className. jsdom no anima; lo que se verifica es el contrato de
// render (y que el stub de matchMedia basta para useReducedMotion).
import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { FadeIn, StaggerList, StaggerItem, Pressable } from './motion'

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

describe('Motion primitives', () => {
  it('FadeIn renderiza children y conserva className', () => {
    render(<FadeIn className="card">Contenido</FadeIn>)
    const el = screen.getByText('Contenido')
    expect(el).toBeInTheDocument()
    expect(el.className).toContain('card')
  })

  it('StaggerList + StaggerItem renderizan los ítems en orden', () => {
    render(
      <StaggerList>
        <StaggerItem>uno</StaggerItem>
        <StaggerItem>dos</StaggerItem>
      </StaggerList>,
    )
    expect(screen.getByText('uno')).toBeInTheDocument()
    expect(screen.getByText('dos')).toBeInTheDocument()
  })

  it('Pressable renderiza children como wrapper interactivo', () => {
    render(<Pressable data-testid="press"><span>Toca</span></Pressable>)
    expect(screen.getByTestId('press')).toBeInTheDocument()
    expect(screen.getByText('Toca')).toBeInTheDocument()
  })
})
