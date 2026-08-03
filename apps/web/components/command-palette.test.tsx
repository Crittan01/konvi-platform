// @vitest-environment jsdom
// Tests de la command palette (Spec WOW §4.3): apertura por atajo ⌘K, filtrado
// de acciones de navegación, búsqueda federada de entidades (Supabase browser
// mockeado) y estado vacío. jsdom no implementa matchMedia/scrollIntoView —
// se stubbean (cmdk hace scrollIntoView al mover la selección).
import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import CommandPalette from './command-palette'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  tableData: {} as Record<string, { data: unknown; error: unknown }>,
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mocks.push }),
}))

vi.mock('@/utils/supabase/client', () => ({
  createClient: () => ({
    from: (table: string) => {
      const result = mocks.tableData[table] ?? { data: [], error: null }
      // Chain thenable: cada método devuelve el mismo chain; `await` resuelve
      // el resultado fijado por el test para esa tabla.
      const chain: Record<string, unknown> = {}
      for (const m of ['select', 'ilike', 'eq', 'in', 'order', 'limit']) {
        chain[m] = () => chain
      }
      chain.then = (resolve: (v: unknown) => unknown) => resolve(result)
      return chain
    },
  }),
}))

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
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {})
  // cmdk mide el área de lista con ResizeObserver (jsdom no lo implementa).
  globalThis.ResizeObserver = globalThis.ResizeObserver ?? class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
})

beforeEach(() => {
  mocks.push.mockClear()
  mocks.tableData = {}
})

// vitest corre con globals:false → el auto-cleanup de Testing Library no se
// registra; sin esto las palettes de tests anteriores quedan montadas (y el
// listener global de ⌘K de cada una responde al atajo).
afterEach(() => cleanup())

function renderPalette() {
  return render(
    <CommandPalette
      role="owner"
      integrations={{ whatsapp: true, shipping: true, mercadolibre: true }}
      planCapabilities={{}}
    />,
  )
}

function openPalette() {
  fireEvent.keyDown(document, { key: 'k', metaKey: true })
}

describe('CommandPalette', () => {
  it('abre con ⌘K y lista acciones de navegación del sidebar', () => {
    renderPalette()
    expect(screen.queryByText('Navegación')).not.toBeInTheDocument()
    openPalette()
    expect(screen.getByText('Navegación')).toBeInTheDocument()
    // Hojas de NAV_ITEMS visibles para owner con integraciones conectadas
    expect(screen.getByText('Métricas')).toBeInTheDocument()
    expect(screen.getByText('Finanzas')).toBeInTheDocument()
  })

  it('Ctrl+K también abre la palette', () => {
    renderPalette()
    fireEvent.keyDown(document, { key: 'k', ctrlKey: true })
    expect(screen.getByText('Navegación')).toBeInTheDocument()
  })

  it('filtra las acciones de navegación al escribir', async () => {
    renderPalette()
    openPalette()
    const input = screen.getByPlaceholderText(/Buscar módulos/)
    fireEvent.change(input, { target: { value: 'métr' } })
    await waitFor(() => {
      expect(screen.getByText('Métricas')).toBeInTheDocument()
      expect(screen.queryByText('Finanzas')).not.toBeInTheDocument()
    })
  })

  it('Enter sobre la primera acción navega con router.push', async () => {
    renderPalette()
    openPalette()
    const input = screen.getByPlaceholderText(/Buscar módulos/)
    await waitFor(() => expect(screen.getByText('Dashboard')).toBeInTheDocument())
    fireEvent.keyDown(input, { key: 'Enter' })
    // Primer leaf de NAV_ITEMS = Dashboard (/dashboard)
    expect(mocks.push).toHaveBeenCalledWith('/dashboard')
  })

  it('búsqueda federada: muestra contactos, pedidos y productos (debounce 300ms)', async () => {
    mocks.tableData = {
      contacts: { data: [{ id: 'c1', name: 'Juan Pérez', phone: '+57312555' }], error: null },
      orders: {
        data: [{
          id: 'a1b2c3-4567', status: 'pending', total_amount: 42000,
          created_at: '2026-08-01', contacts: { name: 'Juan Pérez', phone: '+57312555' },
        }],
        error: null,
      },
      products: { data: [{ id: 'p1', title: 'Juanabá artesanal' }], error: null },
      product_variations: { data: [], error: null },
    }
    renderPalette()
    openPalette()
    const input = screen.getByPlaceholderText(/Buscar módulos/)
    fireEvent.change(input, { target: { value: 'juan' } })
    await waitFor(() => {
      expect(screen.getByText('Contactos')).toBeInTheDocument()
      expect(screen.getByText('Pedidos')).toBeInTheDocument()
      expect(screen.getByText('Productos')).toBeInTheDocument()
    }, { timeout: 2000 })
    expect(screen.getByText('Juan Pérez')).toBeInTheDocument()
    expect(screen.getByText('Juanabá artesanal')).toBeInTheDocument()
    // El pedido enlaza al detalle al seleccionarlo
    fireEvent.keyDown(input, { key: 'ArrowDown' })
  })

  it('muestra estado vacío cuando nada coincide', async () => {
    renderPalette()
    openPalette()
    const input = screen.getByPlaceholderText(/Buscar módulos/)
    fireEvent.change(input, { target: { value: 'zzzz sin match' } })
    await waitFor(() => {
      expect(screen.getByText(/Sin resultados para/)).toBeInTheDocument()
    }, { timeout: 2000 })
  })
})
