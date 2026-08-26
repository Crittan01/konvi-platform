// @vitest-environment jsdom
// T7.8 — cobertura de render del DS. ResponsiveDialog: una acción, dos
// presentaciones (Spec WOW §4.4) — Dialog centrado en ≥lg, bottom-sheet vaul
// en <lg. La rama la decide useMediaQuery('(min-width: 1024px)').
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { ResponsiveDialog } from './responsive-dialog'

let isDesktop = false

beforeAll(() => {
  // jsdom no implementa matchMedia; getter para que el mql cacheado por query
  // (module-level en use-media-query) relea la rama vigente en cada test.
  window.matchMedia = ((query: string) => ({
    get matches() { return query.includes('min-width') ? isDesktop : false },
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
  isDesktop = false
  cleanup()
})

function renderRd() {
  return render(
    <ResponsiveDialog
      open
      onOpenChange={() => {}}
      title="Ajuste de stock"
      description="Suma o resta unidades"
      footer={<button>Aplicar</button>}
    >
      <p>Formulario del flujo</p>
    </ResponsiveDialog>,
  )
}

describe('ResponsiveDialog', () => {
  it('desktop (≥lg): presentación Dialog — sin handle de drawer', () => {
    isDesktop = true
    renderRd()
    expect(screen.getByText('Ajuste de stock')).toBeInTheDocument()
    expect(screen.getByText('Suma o resta unidades')).toBeInTheDocument()
    expect(screen.getByText('Formulario del flujo')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Aplicar' })).toBeInTheDocument()
    const content = document.querySelector('[role="dialog"]') as HTMLElement
    expect(content.querySelector('div.h-1\\.5.w-12')).toBeNull()
  })

  it('móvil (<lg): presentación bottom-sheet — handle visible + mismo contrato', () => {
    isDesktop = false
    renderRd()
    expect(screen.getByText('Ajuste de stock')).toBeInTheDocument()
    expect(screen.getByText('Formulario del flujo')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Aplicar' })).toBeInTheDocument()
    const content = document.querySelector('[role="dialog"]') as HTMLElement
    expect(content.querySelector('div.h-1\\.5.w-12')).not.toBeNull()
  })
})
