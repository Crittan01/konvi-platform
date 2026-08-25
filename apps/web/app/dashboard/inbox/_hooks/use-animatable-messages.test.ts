// @vitest-environment jsdom
// useAnimatableMessageIds (T7.2): SOLO los mensajes NUEVOS tras la carga
// inicial entran con animación. Defensa del requisito duro del brief:
// el dedupe polling/realtime NUNCA re-anima (mismo id → nunca en el set).
//
// Patrón de aserción: se graba TODA la historia de passes de render (el set
// vive un solo pass para la burbuja nueva: `initial` aplica al montar; tras
// el commit el efecto la marca vista y el pass asentado vuelve a vacío).
// Así se verifica AMBAS mitades: "animó en el montaje" Y "no re-anima después".
import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useAnimatableMessageIds } from './use-animatable-messages'
import type { Message } from '../_lib/types'

const msg = (id: string, ts: string): Message => ({
  id,
  direction: 'inbound',
  content: `mensaje ${id}`,
  content_type: 'text',
  created_at: ts,
  processed: true,
})

// Escalera de timestamps (ms crecientes).
const T = {
  t0: '2026-08-25T10:00:00.000Z',
  t1: '2026-08-25T10:01:00.000Z',
  t2: '2026-08-25T10:02:00.000Z',
  t3: '2026-08-25T10:03:00.000Z',
  t5: '2026-08-25T10:05:00.000Z',
  t6: '2026-08-25T10:06:00.000Z',
  t7: '2026-08-25T10:07:00.000Z',
}

interface Props {
  convId: string | null
  loadedConvId: string | null
  messages: Message[]
}

const setup = (initial: Props) => {
  // Historia de passes: ids animables por render, en orden.
  const history: string[][] = []
  const view = renderHook(
    ({ convId, loadedConvId, messages }: Props) => {
      const ids = useAnimatableMessageIds(convId, loadedConvId, messages)
      history.push([...ids].sort())
      return ids
    },
    { initialProps: initial },
  )
  return { ...view, history }
}

/** ¿Algún pass animó exactamente estos ids? */
const animated = (history: string[][], ids: string[]) =>
  history.some(pass => pass.join(',') === [...ids].sort().join(','))

describe('useAnimatableMessageIds', () => {
  it('la carga inicial NO anima (aunque traiga muchos mensajes)', () => {
    const { rerender, history } = setup({ convId: 'c1', loadedConvId: null, messages: [] })
    expect(history.every(p => p.length === 0)).toBe(true)
    // Llega la data de c1: ningún pass anima (anti-cascada).
    rerender({ convId: 'c1', loadedConvId: 'c1', messages: [msg('m1', T.t1), msg('m2', T.t2)] })
    expect(history.every(p => p.length === 0)).toBe(true)
  })

  it('un mensaje NUEVO anexado al final SÍ anima (realtime/polling/optimistic)', () => {
    const { rerender, history } = setup({ convId: 'c1', loadedConvId: 'c1', messages: [msg('m1', T.t1)] })
    expect(history.every(p => p.length === 0)).toBe(true) // carga inicial
    history.length = 0
    rerender({ convId: 'c1', loadedConvId: 'c1', messages: [msg('m1', T.t1), msg('m2', T.t2)] })
    expect(animated(history, ['m2'])).toBe(true) // animó en el pass de montaje…
    expect(history.at(-1)).toEqual([]) // …y el pass asentado ya no lo anima
  })

  it('dedupe polling/realtime: re-render con los mismos ids NO re-anima', () => {
    const base = [msg('m1', T.t1), msg('m2', T.t2)]
    const { rerender, history } = setup({ convId: 'c1', loadedConvId: 'c1', messages: base })
    rerender({ convId: 'c1', loadedConvId: 'c1', messages: [...base, msg('m3', T.t3)] })
    expect(animated(history, ['m3'])).toBe(true)
    history.length = 0
    // El replace del polling trae los mismos ids (m3 incluido): cero animación.
    rerender({ convId: 'c1', loadedConvId: 'c1', messages: [msg('m1', T.t1), msg('m2', T.t2), msg('m3', T.t3)] })
    expect(history.every(p => p.length === 0)).toBe(true)
  })

  it('dos inserts en el mismo milisegundo: el segundo también anima (>=)', () => {
    const { rerender, history } = setup({ convId: 'c1', loadedConvId: 'c1', messages: [msg('m1', T.t1)] })
    rerender({ convId: 'c1', loadedConvId: 'c1', messages: [msg('m1', T.t1), msg('m2', T.t1)] })
    expect(animated(history, ['m2'])).toBe(true)
  })

  it('prepend histórico de loadMore (created_at más viejo) NO anima', () => {
    const { rerender, history } = setup({
      convId: 'c1',
      loadedConvId: 'c1',
      messages: [msg('m2', T.t2), msg('m3', T.t3)],
    })
    history.length = 0
    rerender({
      convId: 'c1',
      loadedConvId: 'c1',
      messages: [msg('m0', T.t0), msg('m1', T.t1), msg('m2', T.t2), msg('m3', T.t3)],
    })
    expect(history.every(p => p.length === 0)).toBe(true)
  })

  it('cambio de conversación: ni la pintura stale ni la nueva carga inicial animan', () => {
    const { rerender, history } = setup({ convId: 'c1', loadedConvId: 'c1', messages: [msg('m1', T.t1)] })
    rerender({ convId: 'c1', loadedConvId: 'c1', messages: [msg('m1', T.t1), msg('m2', T.t2)] })
    expect(animated(history, ['m2'])).toBe(true)
    history.length = 0
    // Switch a c2: `messages` aún muestra data STALE de c1 (loadedConvId lo delata).
    rerender({ convId: 'c2', loadedConvId: 'c1', messages: [msg('m1', T.t1), msg('m2', T.t2)] })
    expect(history.every(p => p.length === 0)).toBe(true)
    // Llega la carga inicial de c2 — MÁS RECIENTE que el max visto de c1:
    // sin el guard loadedConvId esto animaría una cascada.
    rerender({ convId: 'c2', loadedConvId: 'c2', messages: [msg('n1', T.t6), msg('n2', T.t7)] })
    expect(history.every(p => p.length === 0)).toBe(true)
    // Y tras la carga, un nuevo en c2 sí anima.
    rerender({ convId: 'c2', loadedConvId: 'c2', messages: [msg('n1', T.t6), msg('n2', T.t7), msg('n3', T.t7)] })
    expect(animated(history, ['n3'])).toBe(true)
  })

  it('conversación vacía: el PRIMER mensaje que llega sí anima', () => {
    const { rerender, history } = setup({ convId: 'c3', loadedConvId: 'c3', messages: [] })
    expect(history.every(p => p.length === 0)).toBe(true)
    rerender({ convId: 'c3', loadedConvId: 'c3', messages: [msg('x1', T.t5)] })
    expect(animated(history, ['x1'])).toBe(true)
  })

  it('sin conversación seleccionada nada anima', () => {
    const { rerender, history } = setup({ convId: null, loadedConvId: null, messages: [] })
    rerender({ convId: null, loadedConvId: null, messages: [] })
    expect(history.every(p => p.length === 0)).toBe(true)
  })
})
