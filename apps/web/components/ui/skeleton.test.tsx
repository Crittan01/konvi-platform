// @vitest-environment jsdom
// T7.8 — cobertura de render del DS. Skeleton: primitivo de carga
// (animate-pulse + tokens) con merge de className.
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { Skeleton } from './skeleton'

afterEach(cleanup)

describe('Skeleton', () => {
  it('renderiza div con la animación y tokens base', () => {
    const { container } = render(<Skeleton />)
    const el = container.firstChild as HTMLElement
    expect(el.tagName).toBe('DIV')
    expect(el.className).toContain('animate-pulse')
    expect(el.className).toContain('bg-muted')
    expect(el.className).toContain('rounded-md')
  })

  it('hace merge del className (formas de fila/tarjeta las da el consumidor)', () => {
    const { container } = render(<Skeleton className="h-16 rounded-lg bg-border/40" />)
    const el = container.firstChild as HTMLElement
    expect(el.className).toContain('h-16')
    expect(el.className).toContain('rounded-lg')
    expect(el.className).toContain('bg-border/40')
  })
})
