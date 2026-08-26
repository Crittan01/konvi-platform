// @vitest-environment jsdom
// T7.11 — PageHeader: cabecera de módulo con identidad (tile de marca
// degradado + glow, título como h1 único, contexto y acciones; coreografía
// vía wrappers DS — reduced-motion estático tras montar).
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { ShieldCheck } from 'lucide-react'
import { PageHeader } from './page-header'

let reduceMotion = false

beforeAll(() => {
  // jsdom no implementa matchMedia; useReducedMotionDS lo consulta al montar.
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

describe('PageHeader (T7.11)', () => {
  it('renderiza título como h1 + descripción + tile de marca con glifo blanco', () => {
    const { container } = render(
      <PageHeader icon={ShieldCheck} title="Seguridad" description="Protege tu cuenta" />,
    )
    expect(screen.getByRole('heading', { level: 1, name: 'Seguridad' })).toBeInTheDocument()
    expect(screen.getByText('Protege tu cuenta')).toBeInTheDocument()
    // Tile: degradado primary→amber + glow de la casa + icono blanco, todo aria-hidden
    const tile = container.querySelector('span[aria-hidden="true"]')!
    expect(tile.className).toContain('bg-gradient-to-br')
    expect(tile.className).toContain('from-primary')
    expect(tile.className).toContain('glow-primary')
    const svg = tile.querySelector('svg')
    expect(svg).not.toBeNull()
    // En SVG, className es SVGAnimatedString — leer el atributo.
    expect(svg!.getAttribute('class')).toContain('text-white')
  })

  it('sin description no renderiza el párrafo de contexto', () => {
    render(<PageHeader icon={ShieldCheck} title="Solo título" />)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Solo título')
    expect(screen.queryByText('Protege tu cuenta')).not.toBeInTheDocument()
  })

  it('slot actions a la derecha cuando se pasa; ausente si no', () => {
    const { container, unmount } = render(
      <PageHeader icon={ShieldCheck} title="Con acción" actions={<button>Exportar CSV</button>} />,
    )
    expect(screen.getByRole('button', { name: 'Exportar CSV' })).toBeInTheDocument()
    unmount()
    const { container: c2 } = render(<PageHeader icon={ShieldCheck} title="Sin acción" />)
    expect(c2.querySelectorAll('button')).toHaveLength(0)
    expect(container).toBeTruthy()
  })

  it('hace merge de className en el contenedor', () => {
    const { container } = render(
      <PageHeader icon={ShieldCheck} title="X" className="mb-6" />,
    )
    expect(container.firstElementChild!.className).toContain('mb-6')
    expect(container.firstElementChild!.className).toContain('justify-between')
  })

  it('con prefers-reduced-motion el render es estático y completo', () => {
    reduceMotion = true
    render(<PageHeader icon={ShieldCheck} title="Reducida" description="sin cascada" />)
    expect(screen.getByRole('heading', { level: 1, name: 'Reducida' })).toBeInTheDocument()
    expect(screen.getByText('sin cascada')).toBeInTheDocument()
  })
})
