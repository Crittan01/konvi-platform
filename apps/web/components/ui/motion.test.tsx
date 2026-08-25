// @vitest-environment jsdom
// Smoke tests de los primitivos motion del DS: montan, renderizan children y
// pasan className. jsdom no anima; lo que se verifica es el contrato de
// render (y que el stub de matchMedia basta para useReducedMotion).
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { AnimatePresence, BubbleIn, FadeIn, StaggerList, StaggerItem, Pressable } from './motion'

let reduceMotion = false

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

describe('BubbleIn (T7.2)', () => {
  it('enter={false} renderiza children y conserva className (sin entrada)', () => {
    render(<BubbleIn enter={false} className="flex gap-2">Burbuja</BubbleIn>)
    const el = screen.getByText('Burbuja')
    expect(el).toBeInTheDocument()
    expect(el.className).toContain('flex')
  })

  it('enter (default) dentro de AnimatePresence initial={false} renderiza igual', () => {
    render(
      <AnimatePresence initial={false}>
        <BubbleIn className="flex">Nueva</BubbleIn>
      </AnimatePresence>,
    )
    expect(screen.getByText('Nueva')).toBeInTheDocument()
  })

  it('con prefers-reduced-motion el render no se rompe (variante fade)', () => {
    reduceMotion = true
    render(<BubbleIn>Reducida</BubbleIn>)
    expect(screen.getByText('Reducida')).toBeInTheDocument()
  })
})
