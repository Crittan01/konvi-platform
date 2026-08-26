// @vitest-environment jsdom
// T7.8 — cobertura de render del DS. Carousel (embla): region con roles de
// carrusel/diapositiva y dots con guard (ocultos cuando hay ≤1 snap — en
// jsdom embla no tiene layout engine y reporta 1 snap, justo el caso borde
// que el guard cubre).
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { render, screen, cleanup, renderHook } from '@testing-library/react'
import { Carousel, CarouselContent, CarouselDots, CarouselItem, useCarousel } from './carousel'

beforeAll(() => {
  // jsdom no implementa matchMedia y embla lo consulta para las opciones
  // responsivas (OptionsHandler). Stub mínimo, mismo patrón que motion.test.
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
  // jsdom tampoco implementa los observers que embla usa al activarse
  // (SlidesInView / ResizeHandler). Stubs sin comportamiento: el carrusel
  // queda con 1 snap — justo el caso borde que cubre el test del guard.
  const NoopObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.IntersectionObserver = window.IntersectionObserver ?? (NoopObserver as unknown as typeof IntersectionObserver)
  window.ResizeObserver = window.ResizeObserver ?? (NoopObserver as unknown as typeof ResizeObserver)
})

afterEach(cleanup)

function renderCarousel() {
  return render(
    <Carousel>
      <CarouselContent>
        <CarouselItem>KPI uno</CarouselItem>
        <CarouselItem>KPI dos</CarouselItem>
        <CarouselItem>KPI tres</CarouselItem>
      </CarouselContent>
      <CarouselDots />
    </Carousel>,
  )
}

describe('Carousel', () => {
  it('renderiza como region carrusel con los items como diapositivas', () => {
    renderCarousel()
    expect(screen.getByRole('region')).toHaveAttribute('aria-roledescription', 'carrusel')
    const slides = screen.getAllByRole('group')
    expect(slides).toHaveLength(3)
    for (const s of slides) expect(s).toHaveAttribute('aria-roledescription', 'diapositiva')
    expect(screen.getByText('KPI dos')).toBeInTheDocument()
  })

  it('dots: guard count<=1 — sin layout engine (jsdom) embla reporta 1 snap y no se pintan', () => {
    renderCarousel()
    // El guard `if (count <= 1) return null` es el comportamiento correcto
    // cuando todo cabe en el viewport (o no hay medición, como en jsdom).
    expect(screen.queryByRole('button', { name: /Ir a la tarjeta/ })).not.toBeInTheDocument()
  })

  it('useCarousel fuera de <Carousel> lanza error claro', () => {
    expect(() => renderHook(() => useCarousel())).toThrow(/<Carousel>/)
  })
})
