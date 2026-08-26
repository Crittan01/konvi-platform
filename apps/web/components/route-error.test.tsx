// @vitest-environment jsdom
// T7.6 — RouteError: boundary compartido por módulo (anti-falso-0 §3.2:
// error + retry + link a inicio, con digest cuando existe).
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { RouteError } from './route-error'

// cleanup explícito: sin globals de vitest no hay auto-cleanup de RTL; un árbol
// montado que sobrevive al teardown de jsdom deja trabajo del scheduler de React
// corriendo sin `window` (flake intermitente "window is not defined" bajo carga).
afterEach(cleanup)

const base = {
  title: 'Error al cargar Pedidos',
  description: 'No se pudieron cargar los pedidos.',
  logTag: 'OrdersError',
}

describe('RouteError (T7.6)', () => {
  it('renderiza título + descripción + retry + link a inicio', () => {
    const reset = vi.fn()
    render(<RouteError {...base} error={new Error('boom')} reset={reset} />)
    expect(screen.getByText('Error al cargar Pedidos')).toBeInTheDocument()
    expect(screen.getByText('No se pudieron cargar los pedidos.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Reintentar/ }))
    expect(reset).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('link', { name: /Ir al inicio/ })).toHaveAttribute('href', '/dashboard')
  })

  it('muestra el digest cuando existe y lo omite cuando no', () => {
    const withDigest = Object.assign(new Error('x'), { digest: 'abc123' })
    const { rerender } = render(<RouteError {...base} error={withDigest} reset={() => {}} />)
    expect(screen.getByText('#abc123')).toBeInTheDocument()
    rerender(<RouteError {...base} error={new Error('x')} reset={() => {}} />)
    expect(screen.queryByText('#abc123')).toBeNull()
  })

  it('loguea con el tag del módulo', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<RouteError {...base} error={new Error('boom')} reset={() => {}} />)
    expect(spy).toHaveBeenCalledWith('[OrdersError]', expect.any(Error))
    spy.mockRestore()
  })
})
