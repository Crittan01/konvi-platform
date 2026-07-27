import { describe, expect, it } from 'vitest'

import {
  CAUSALES,
  admiteReversion,
  causalLabel,
  cop,
  estadoConstancia,
  estadoDinero,
  fechaCO,
} from './reversion'

describe('causales', () => {
  it('son exactamente las cinco del art. 2.2.2.51.2', () => {
    // Una sexta sería una causal inventada; una menos, un derecho recortado.
    expect(CAUSALES.map(c => c.value)).toEqual([
      'fraude',
      'operacion_no_solicitada',
      'producto_no_recibido',
      'producto_no_corresponde',
      'producto_defectuoso',
    ])
  })

  it('cada una apunta a su numeral', () => {
    for (const c of CAUSALES) expect(c.ayuda).toMatch(/num\.\s*\d/)
  })

  it('una causal desconocida se muestra tal cual, no se traga', () => {
    expect(causalLabel('otra_cosa')).toBe('otra_cosa')
    expect(causalLabel(null)).toBe('—')
  })
})

describe('admiteReversion', () => {
  // Art. 2.2.2.51.1: no procede sobre canales presenciales.
  it('el pago electrónico sí', () => {
    expect(admiteReversion('credit')).toBe(true)
  })

  it('contra entrega en efectivo no', () => {
    for (const fp of ['cod', 'COD', ' efectivo ', 'cash']) {
      expect(admiteReversion(fp)).toBe(false)
    }
  })

  it('sin forma de pago tampoco: la constancia afirma hechos', () => {
    expect(admiteReversion(null)).toBe(false)
    expect(admiteReversion('')).toBe(false)
  })
})

describe('estadoConstancia', () => {
  it('distingue emitida de entregada', () => {
    // La obligación no se agota emitiendo: el comprador tiene que TENERLA para
    // adjuntarla a su notificación al banco (art. 2.2.2.51.7 num. 6).
    expect(estadoConstancia({ constancia_emitida_at: 'x' }).texto).toMatch(/pendiente/i)
    expect(estadoConstancia({ constancia_emitida_at: 'x', constancia_entregada_at: 'y' }).texto)
      .toMatch(/entregada/i)
  })

  it('una entrega fallida se marca como alerta y dice qué pasó', () => {
    const e = estadoConstancia({ constancia_emitida_at: 'x', constancia_entrega_fallida: 'sin_telefono' })
    expect(e.alerta).toBe(true)
    expect(e.texto).toContain('sin_telefono')
  })

  it('sin constancia es una alerta, no un estado neutro', () => {
    expect(estadoConstancia({}).alerta).toBe(true)
  })
})

describe('estadoDinero', () => {
  it('avisa cuando salió por los dos caminos', () => {
    // Art. 2.2.2.51.10: el consumidor debe devolver el excedente. Si el operador no lo
    // ve, la plata se pierde.
    const e = estadoDinero({ reembolso_directo_at: 'a', reversion_confirmada_at: 'b' })
    expect(e.alerta).toBe(true)
    expect(e.texto).toContain('2.2.2.51.10')
  })

  it('un solo camino no es una alerta', () => {
    expect(estadoDinero({ reversion_confirmada_at: 'b' }).alerta).toBe(false)
    expect(estadoDinero({ reembolso_directo_at: 'a' }).alerta).toBe(false)
  })

  it('sin movimientos lo dice sin alarmar', () => {
    const e = estadoDinero({})
    expect(e.alerta).toBe(false)
    expect(e.texto).toMatch(/todavía no/i)
  })
})

describe('formato', () => {
  it('los pesos van sin centavos', () => {
    expect(cop(68000)).toBe('$68.000')
    expect(cop('no-es-un-numero')).toBe('$0')
  })

  it('la fecha va en hora Colombia aunque el servidor esté en UTC', () => {
    // En una constancia la fecha prueba que la queja entró dentro de los 5 días hábiles.
    const previa = process.env.TZ
    process.env.TZ = 'UTC'
    try {
      // 2026-07-27 02:00Z = 2026-07-26 21:00 en Bogotá.
      expect(fechaCO('2026-07-27T02:00:00Z')).toMatch(/\b26\b/)
    } finally {
      process.env.TZ = previa
    }
  })

  it('una fecha ausente o inválida no rompe la vista', () => {
    expect(fechaCO(null)).toBe('—')
    expect(fechaCO('mañana')).toBe('—')
  })
})
