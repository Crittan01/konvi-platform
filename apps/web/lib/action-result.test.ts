import { describe, it, expect } from 'vitest'
import { ok, fail, type ActionResult } from './action-result'

describe('action-result (contrato canónico de server actions)', () => {
  it('ok() marca éxito y opcionalmente lleva mensaje', () => {
    expect(ok()).toEqual({ ok: true, message: undefined })
    expect(ok('Guardado')).toEqual({ ok: true, message: 'Guardado' })
  })

  it('fail() marca error con causa (nunca throw enmascarado)', () => {
    const r: ActionResult = fail('No se pudo guardar: RLS')
    expect(r.ok).toBe(false)
    expect(r.error).toBe('No se pudo guardar: RLS')
  })
})
