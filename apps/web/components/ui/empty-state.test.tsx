// @vitest-environment jsdom
// T7.8 — cobertura de render del DS. EmptyState: contrato de variantes
// (default con borde dashed / plain para vacíos dentro de un panel ya
// enmarcado), icono aria-hidden y slot de acción (CTA).
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { Inbox } from 'lucide-react'
import { EmptyState } from './empty-state'

afterEach(cleanup)

describe('EmptyState', () => {
  it('variante default: borde dashed + título y descripción', () => {
    render(<EmptyState title="Sin pedidos" description="Cuando compren aparecerá aquí." />)
    const root = screen.getByText('Sin pedidos').closest('div')!
    expect(root.className).toContain('border-dashed')
    expect(root.className).toContain('rounded-xl')
    expect(screen.getByText('Cuando compren aparecerá aquí.')).toBeInTheDocument()
  })

  it('variante plain: sin borde propio (vive dentro de una Card)', () => {
    render(<EmptyState variant="plain" title="Vacío plano" />)
    const root = screen.getByText('Vacío plano').closest('div')!
    expect(root.className).not.toContain('border-dashed')
    expect(root.className).not.toContain('rounded-xl')
  })

  it('icono decorativo: renderiza svg aria-hidden', () => {
    const { container } = render(<EmptyState icon={Inbox} title="Con icono" />)
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
    expect(svg!.getAttribute('aria-hidden')).toBe('true')
  })

  it('slot action: renderiza el CTA bajo la descripción', () => {
    render(
      <EmptyState
        title="Sin gastos"
        action={<button>Registrar gasto</button>}
      />,
    )
    expect(screen.getByRole('button', { name: 'Registrar gasto' })).toBeInTheDocument()
  })

  it('sin título la descripción no lleva margen de título (mt-1)', () => {
    render(<EmptyState description="Solo descripción" />)
    expect(screen.getByText('Solo descripción').className).not.toContain('mt-1')
  })

  it('pop de entrada: la raíz lleva la utility empty-state-pop del DS', () => {
    render(<EmptyState title="Con pop" />)
    const root = screen.getByText('Con pop').closest('div')!
    expect(root.className).toContain('empty-state-pop')
  })

  it('icono con vida: flotación (icon-float) + halo radial estático aria-hidden', () => {
    const { container } = render(<EmptyState icon={Inbox} title="Vivo" />)
    const svg = container.querySelector('svg')!
    expect(svg.classList.contains('icon-float')).toBe(true)
    const halo = container.querySelector('.bg-primary\\/10')
    expect(halo).not.toBeNull()
    expect(halo!.getAttribute('aria-hidden')).toBe('true')
  })
})
