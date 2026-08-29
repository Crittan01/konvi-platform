// @vitest-environment jsdom
// Smoke tests del Bento (grid asimétrico de KPIs — PASO 4): el grid monta las
// cards, span/row caen en el ítem de grid (hijo directo), interactive añade
// card-hover + cursor-pointer y la prop stagger se acepta. jsdom no anima; se
// verifica el contrato de render (stub de matchMedia como en motion.test.tsx).
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { BentoCard, BentoGrid } from './bento'

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
})

afterEach(cleanup)

describe('Bento (BentoGrid + BentoCard)', () => {
  it('BentoGrid renderiza las cards hijas con las clases de grid base', () => {
    render(
      <BentoGrid>
        <BentoCard>Ventas hoy</BentoCard>
        <BentoCard>Ventas este mes</BentoCard>
      </BentoGrid>,
    )
    expect(screen.getByText('Ventas hoy')).toBeInTheDocument()
    expect(screen.getByText('Ventas este mes')).toBeInTheDocument()
    const grid = screen.getByText('Ventas hoy').closest('.grid')
    expect(grid).not.toBeNull()
    expect(grid?.className).toContain('lg:grid-cols-4')
  })

  it('span={2} y row={2} caen en el ítem de grid (no en la card interior)', () => {
    const { container } = render(
      <BentoGrid>
        <BentoCard span={2} row={2}>Hero</BentoCard>
      </BentoGrid>,
    )
    const item = container.querySelector('.lg\\:col-span-2')
    expect(item).not.toBeNull()
    expect(item?.className).toContain('lg:row-span-2')
  })

  it('interactive añade card-hover + cursor-pointer; estática no los lleva', () => {
    const { container } = render(
      <BentoGrid>
        <BentoCard interactive>Navega</BentoCard>
        <BentoCard>Estática</BentoCard>
      </BentoGrid>,
    )
    const interactiveCard = screen.getByText('Navega').closest('.card-hover')
    expect(interactiveCard).not.toBeNull()
    expect(interactiveCard?.className).toContain('cursor-pointer')
    expect(screen.getByText('Estática').closest('.card-hover')).toBeNull()
    expect(container.querySelectorAll('.card-hover')).toHaveLength(1)
  })

  it('acepta stagger y className sin romper el render', () => {
    render(
      <BentoGrid stagger={0.12} className="hidden lg:grid">
        <BentoCard>KPI</BentoCard>
      </BentoGrid>,
    )
    const card = screen.getByText('KPI')
    expect(card).toBeInTheDocument()
    expect(card.closest('.hidden')).not.toBeNull()
  })
})
