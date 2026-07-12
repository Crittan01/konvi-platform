import { describe, it, expect } from 'vitest'
import { errorDetailToString, errorDetailCode } from './errors'

describe('errorDetailToString', () => {
  it('devuelve el string tal cual cuando detail es string', () => {
    expect(errorDetailToString('Status inválido', 'fb')).toBe('Status inválido')
  })

  it('extrae message cuando detail es objeto (ventana 24h Meta) — evita el crash de React', () => {
    const detail = { code: 'WINDOW_EXPIRED', message: 'Fuera de ventana 24h Meta.', hours: 30 }
    expect(errorDetailToString(detail, 'fb')).toBe('Fuera de ventana 24h Meta.')
  })

  it('cae al fallback cuando detail es objeto sin message', () => {
    expect(errorDetailToString({ code: 'X' }, 'No se pudo enviar')).toBe('No se pudo enviar')
  })

  it('cae al fallback con null/undefined/message vacío', () => {
    expect(errorDetailToString(null, 'fb')).toBe('fb')
    expect(errorDetailToString(undefined, 'fb')).toBe('fb')
    expect(errorDetailToString({ message: '  ' }, 'fb')).toBe('fb')
  })
})

describe('errorDetailCode', () => {
  it('extrae code cuando detail es objeto', () => {
    expect(errorDetailCode({ code: 'WINDOW_NO_INBOUND', message: 'x' })).toBe('WINDOW_NO_INBOUND')
  })
  it('devuelve null cuando no hay code', () => {
    expect(errorDetailCode('string')).toBeNull()
    expect(errorDetailCode({ message: 'x' })).toBeNull()
    expect(errorDetailCode(null)).toBeNull()
  })
})
