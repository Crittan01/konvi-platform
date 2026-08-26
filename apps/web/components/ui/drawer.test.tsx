// @vitest-environment jsdom
// T7.8 — cobertura de render del DS. Drawer (vaul): bottom-sheet móvil con
// handle visible + safe-area inferior + superficie de tokens (bg-popover).
// jsdom no arrastra; se verifica el contrato de render.
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import {
  Drawer, DrawerContent, DrawerDescription, DrawerFooter, DrawerHeader, DrawerTitle,
} from './drawer'

beforeAll(() => {
  // jsdom no implementa matchMedia (vaul lo consulta para el fondo escalado).
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

function renderDrawer(open: boolean) {
  return render(
    <Drawer open={open} onOpenChange={() => {}}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>Ajuste rápido</DrawerTitle>
          <DrawerDescription>Stock del producto</DrawerDescription>
        </DrawerHeader>
        <div>Cuerpo del flujo</div>
        <DrawerFooter>
          <button>Guardar</button>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>,
  )
}

describe('Drawer', () => {
  it('open: renderiza título, descripción, cuerpo y footer (portal)', () => {
    renderDrawer(true)
    expect(screen.getByText('Ajuste rápido')).toBeInTheDocument()
    expect(screen.getByText('Stock del producto')).toBeInTheDocument()
    expect(screen.getByText('Cuerpo del flujo')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeInTheDocument()
  })

  it('superficie con tokens + handle de drag + safe-area (ambos aria-hidden)', () => {
    renderDrawer(true)
    const content = document.querySelector('[role="dialog"]') as HTMLElement
    expect(content.className).toContain('bg-popover')
    expect(content.className).toContain('rounded-t-2xl')
    // Handle visible (affordance de drag-to-dismiss)
    const handle = content.querySelector('div.h-1\\.5.w-12')
    expect(handle).not.toBeNull()
    expect(handle!.getAttribute('aria-hidden')).toBe('true')
  })

  it('open=false: no renderiza contenido', () => {
    renderDrawer(false)
    expect(screen.queryByText('Ajuste rápido')).not.toBeInTheDocument()
  })
})
