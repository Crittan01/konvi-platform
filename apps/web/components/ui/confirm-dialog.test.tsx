// @vitest-environment jsdom
// T7.8 — cobertura de render del DS. ConfirmDialog: el reemplazo promise-based
// de los confirm() nativos (34 sitios migrados). Contrato: requiere provider,
// resuelve true/false según el botón, labels por defecto en español y
// variante destructive en el botón de confirmar.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { ConfirmProvider, useConfirm } from './confirm-dialog'

afterEach(cleanup)

function Harness({ opts }: { opts?: Parameters<ReturnType<typeof useConfirm>>[0] }) {
  const confirm = useConfirm()
  const [result, setResult] = useState('')
  return (
    <div>
      <button
        onClick={() => {
          void confirm(opts ?? { title: '¿Eliminar producto?', description: 'No se puede deshacer.', confirmLabel: 'Eliminar', destructive: true })
            .then(v => setResult(v ? 'dijo-si' : 'dijo-no'))
        }}
      >
        lanzar
      </button>
      <span data-testid="resultado">{result}</span>
    </div>
  )
}

describe('ConfirmDialog', () => {
  it('useConfirm fuera de <ConfirmProvider> lanza error claro', () => {
    function SinProvider() {
      useConfirm()
      return null
    }
    expect(() => render(<SinProvider />)).toThrow(/ConfirmProvider/)
  })

  it('muestra título/descripción/labels y "Eliminar" resuelve true', async () => {
    const user = userEvent.setup()
    render(<ConfirmProvider><Harness /></ConfirmProvider>)
    await user.click(screen.getByText('lanzar'))
    expect(await screen.findByText('¿Eliminar producto?')).toBeInTheDocument()
    expect(screen.getByText('No se puede deshacer.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Eliminar' }))
    expect(await screen.findByText('dijo-si')).toBeInTheDocument()
  })

  it('"Cancelar" resuelve false y cierra el diálogo', async () => {
    const user = userEvent.setup()
    render(<ConfirmProvider><Harness /></ConfirmProvider>)
    await user.click(screen.getByText('lanzar'))
    await screen.findByText('¿Eliminar producto?')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(await screen.findByText('dijo-no')).toBeInTheDocument()
    expect(screen.queryByText('¿Eliminar producto?')).not.toBeInTheDocument()
  })

  it('destructive=true pinta el botón de confirmar con la variante destructive', async () => {
    const user = userEvent.setup()
    render(<ConfirmProvider><Harness /></ConfirmProvider>)
    await user.click(screen.getByText('lanzar'))
    const btn = await screen.findByRole('button', { name: 'Eliminar' })
    expect(btn.className).toContain('bg-destructive')
  })

  it('labels por defecto: Cancelar/Confirmar cuando no se pasan', async () => {
    const user = userEvent.setup()
    render(<ConfirmProvider><Harness opts={{ title: '¿Seguro?' }} /></ConfirmProvider>)
    await user.click(screen.getByText('lanzar'))
    expect(await screen.findByRole('button', { name: 'Confirmar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeInTheDocument()
  })
})
