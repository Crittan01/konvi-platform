import { describe, it, expect } from 'vitest'
import { formatPhone, PHONE_COUNTRIES } from './phone-countries'
import {
  consentSourceLabel,
  attachmentSkipMessage,
  CONSENT_SOURCE_LABEL,
} from './consent-source-help'

describe('formatPhone', () => {
  it('formatea un número colombiano E.164 de 12 dígitos como +57 XXX XXX XXXX', () => {
    expect(formatPhone('+573125835649')).toBe('+57 312 583 5649')
    expect(formatPhone('573125835649')).toBe('+57 312 583 5649')
  })

  it('ignora caracteres no numéricos antes de formatear', () => {
    expect(formatPhone('+57 312-583-5649')).toBe('+57 312 583 5649')
  })

  it('devuelve el raw original cuando la entrada no tiene dígitos', () => {
    expect(formatPhone('')).toBe('')
    expect(formatPhone('sin numero')).toBe('sin numero')
  })

  it('detecta prefijos multi-dígito antes que +1 (orden de prefijos)', () => {
    // 593 = Ecuador. Un match ingenuo de "+1" o "+59" rompería esto; la
    // función debe reconocer 593 completo.
    expect(formatPhone('593991234567')).toBe('+593 991234567')
  })

  it('formatea un número USA/Canadá (+1) sin colisionar con prefijos largos', () => {
    expect(formatPhone('15551234567')).toBe('+1 5551234567')
  })

  it('cae al fallback +digits cuando no alcanza la longitud mínima del prefijo', () => {
    // 6 dígitos: ningún prefijo cumple prefix.length + 7.
    expect(formatPhone('123456')).toBe('+123456')
  })

  it('cubre cada país soportado con su placeholder', () => {
    for (const country of PHONE_COUNTRIES) {
      const formatted = formatPhone(country.code + country.placeholderDigits)
      expect(formatted.startsWith('+')).toBe(true)
    }
  })
})

describe('consentSourceLabel', () => {
  it('traduce el valor crudo a etiqueta legible', () => {
    expect(consentSourceLabel('manual_console')).toBe('Consola (operador)')
    expect(consentSourceLabel('in_person')).toBe('Presencial')
    expect(consentSourceLabel('marketplace_meli')).toBe('Marketplace Mercado Libre')
  })

  it('devuelve el crudo si no hay etiqueta conocida', () => {
    expect(consentSourceLabel('desconocido')).toBe('desconocido')
  })

  it('devuelve cadena vacía para null/undefined', () => {
    expect(consentSourceLabel(null)).toBe('')
    expect(consentSourceLabel(undefined)).toBe('')
  })

  it('todas las etiquetas del dropdown existen en el mapa', () => {
    for (const key of ['manual_console', 'whatsapp', 'web_form', 'phone_call', 'in_person', 'import', 'other']) {
      expect(CONSENT_SOURCE_LABEL[key]).toBeTruthy()
    }
  })
})

describe('attachmentSkipMessage', () => {
  it('mapea los motivos persistidos a mensajes accionables', () => {
    expect(attachmentSkipMessage('too_large')).toMatch(/5 MB/)
    expect(attachmentSkipMessage('mime_not_allowed')).toMatch(/formato/i)
    expect(attachmentSkipMessage('storage_error')).toMatch(/almacenamiento/i)
  })

  it('da un fallback genérico para motivos desconocidos', () => {
    expect(attachmentSkipMessage('otra_cosa')).toBe('No se pudo guardar el archivo adjunto.')
  })

  it('devuelve null cuando no hay motivo', () => {
    expect(attachmentSkipMessage(null)).toBeNull()
    expect(attachmentSkipMessage(undefined)).toBeNull()
  })
})
