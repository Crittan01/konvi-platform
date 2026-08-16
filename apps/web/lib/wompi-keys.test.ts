import { describe, expect, it } from 'vitest'
import { wompiKeysMatchEnvironment } from './wompi-keys'

// S0.2 (plan segregación 2026-08-16): el guardado de credenciales Wompi
// rechaza llaves de un ambiente pegadas con el selector del otro.
describe('wompiKeysMatchEnvironment', () => {
  it('acepta llaves sandbox con ambiente sandbox', () => {
    expect(wompiKeysMatchEnvironment('sandbox', 'prv_test_abc', 'test_events_xyz')).toEqual({ ok: true })
  })

  it('acepta llaves prod con ambiente production', () => {
    expect(wompiKeysMatchEnvironment('production', 'prv_prod_abc', 'prod_events_xyz')).toEqual({ ok: true })
  })

  it('rechaza private key prod con ambiente sandbox', () => {
    const r = wompiKeysMatchEnvironment('sandbox', 'prv_prod_abc', 'test_events_xyz')
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.error).toContain('prv_test_')
      expect(r.error).toContain('sandbox')
    }
  })

  it('rechaza events key prod con ambiente sandbox', () => {
    const r = wompiKeysMatchEnvironment('sandbox', 'prv_test_abc', 'prod_events_xyz')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('test_events_')
  })

  it('rechaza private key test con ambiente production', () => {
    const r = wompiKeysMatchEnvironment('production', 'prv_test_abc', 'prod_events_xyz')
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.error).toContain('prv_prod_')
      expect(r.error).toContain('producción')
    }
  })

  it('rechaza events key test con ambiente production', () => {
    const r = wompiKeysMatchEnvironment('production', 'prv_prod_abc', 'test_events_xyz')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('prod_events_')
  })

  it('rechaza llaves sin prefijo reconocido en ambos ambientes', () => {
    expect(wompiKeysMatchEnvironment('sandbox', 'cualquier', 'test_events_xyz').ok).toBe(false)
    expect(wompiKeysMatchEnvironment('production', 'prv_prod_abc', 'cualquier').ok).toBe(false)
  })
})
