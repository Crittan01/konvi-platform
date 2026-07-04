import { describe, it, expect } from 'vitest'
import { bogotaDayKey, bogotaWindowUTC, bogotaDayKeys, bogotaLocalToUTC, utcToBogotaLocal } from './date-window'

describe('date-window (hora Colombia, UTC-5)', () => {
  it('un mensaje a las 22:00 Colombia (03:00 UTC del día siguiente) cuenta en el día Colombia correcto', () => {
    // 2026-07-04 22:00 Colombia == 2026-07-05T03:00:00Z
    expect(bogotaDayKey('2026-07-05T03:00:00Z')).toBe('2026-07-04')
  })

  it('medianoche UTC pertenece al día Colombia anterior (19:00 del día previo)', () => {
    expect(bogotaDayKey('2026-07-04T00:00:00Z')).toBe('2026-07-03')
  })

  it('bogotaWindowUTC(7) arranca a las 05:00Z del día Colombia más antiguo', () => {
    const now = new Date('2026-07-04T15:00:00Z') // 10:00 Colombia
    const { fromUTC } = bogotaWindowUTC(7, now)
    // 7 días atrás incluyendo hoy → inicio = 2026-06-28 00:00 Colombia = 2026-06-28T05:00:00Z
    expect(fromUTC).toBe('2026-06-28T05:00:00.000Z')
  })

  it('bogotaDayKeys lista los días Colombia en orden', () => {
    const now = new Date('2026-07-04T15:00:00Z')
    expect(bogotaDayKeys(3, now)).toEqual(['2026-07-02', '2026-07-03', '2026-07-04'])
  })

  it('bogotaLocalToUTC ancla el wall-clock Colombia a UTC-5', () => {
    // 22:00 Colombia == 03:00 UTC del día siguiente
    expect(bogotaLocalToUTC('2026-07-04T22:00')).toBe('2026-07-05T03:00:00.000Z')
    expect(bogotaLocalToUTC('')).toBeNull()
    expect(bogotaLocalToUTC(null)).toBeNull()
  })

  it('utcToBogotaLocal es el inverso (round-trip)', () => {
    expect(utcToBogotaLocal('2026-07-05T03:00:00.000Z')).toBe('2026-07-04T22:00')
    expect(utcToBogotaLocal(null)).toBe('')
    expect(bogotaLocalToUTC(utcToBogotaLocal('2026-07-05T03:00:00.000Z'))).toBe('2026-07-05T03:00:00.000Z')
  })
})
