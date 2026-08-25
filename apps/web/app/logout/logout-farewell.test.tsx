// @vitest-environment jsdom
// T7.10 — el farewell del logout ejecuta el signOut (action) al montar y
// redirige al login (best-effort: también si la action falla).
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import LogoutFarewell from './logout-farewell'

const mocks = { replace: vi.fn() }
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mocks.replace }),
}))

describe('LogoutFarewell (T7.10)', () => {
  it('muestra el estado de cierre y llama la action una sola vez', async () => {
    const action = vi.fn().mockResolvedValue(undefined)
    render(<LogoutFarewell action={action} />)
    expect(screen.getByRole('status')).toHaveTextContent('Cerrando tu sesión')
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith('/login'))
    expect(action).toHaveBeenCalledTimes(1)
  })

  it('redirige al login aunque la action falle (best-effort)', async () => {
    const action = vi.fn().mockRejectedValue(new Error('network down'))
    render(<LogoutFarewell action={action} />)
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith('/login'))
    expect(action).toHaveBeenCalledTimes(1)
  })
})
