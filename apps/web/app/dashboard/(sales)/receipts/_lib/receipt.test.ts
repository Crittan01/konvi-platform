import { afterEach, describe, expect, it } from 'vitest'
import {
  cop,
  estadoEntrega,
  fechaCO,
  formaPago,
  lineaAceptacion,
  lineasComprador,
  lineasVendedor,
  totalLineas,
  type Receipt,
  type ReceiptSnapshot,
} from './receipt'

/**
 * Lo que se prueba acá es la DEGRADACIÓN, que es donde un comprobante se rompe de verdad:
 * qué se muestra cuando un campo del snapshot no está. Un "Documento: —" impreso en un
 * documento con valor probatorio es peor que no tener la línea.
 */

const SNAP: ReceiptSnapshot = {
  version: 1,
  pedido: { forma_pago: 'credit' },
  vendedor: {
    nombre: 'KAIU S.A.S.',
    documento: 'NIT 900123456-7',
    direccion: 'Calle 100 # 15-20, Bogotá, Colombia',
    email: 'hola@kaiu.co',
    completa: true,
  },
  comprador: { nombre: 'Ana Pérez', telefono: '+573001112233' },
  items: [{ titulo: 'Serum facial', cantidad: 2, precio_unitario: 25000, total_linea: 50000 }],
  totales: { subtotal: 50000, descuento: 0, envio: 18000, total: 68000, moneda: 'COP' },
}

const BASE: Receipt = {
  id: 'r-1',
  numero: 'CP-000042',
  issued_at: '2026-07-25T15:30:00Z',
  voided_at: null,
  void_reason: null,
  ack_sent_at: null,
  ack_skipped_reason: null,
  email_sent_at: null,
  email_skipped_reason: null,
  snapshot: SNAP,
}

describe('dinero', () => {
  it('usa el formato colombiano sin centavos', () => {
    expect(cop(68000)).toBe('$68.000')
    expect(cop(1234567)).toBe('$1.234.567')
  })

  it('no revienta con datos ausentes o basura', () => {
    expect(cop(null)).toBe('$0')
    expect(cop(undefined)).toBe('$0')
    expect(cop('no es un número')).toBe('$0')
  })
})

describe('fechas', () => {
  // Esta máquina de desarrollo corre en America/Bogota, así que un test ingenuo pasaría
  // AUNQUE la función no fijara la zona — verde por suerte, y ciego justo al escenario que
  // importa: Render corre en UTC. Se fuerza la zona del proceso para simularlo.
  const tzOriginal = process.env.TZ
  afterEach(() => {
    process.env.TZ = tzOriginal
  })

  it('las muestra en hora Colombia AUNQUE el servidor esté en UTC', () => {
    process.env.TZ = 'UTC'
    // 15:30 UTC = 10:30 en Bogotá. Sin fijar zona, el servidor mostraría las 15:30 y un
    // pedido de la noche aparecería como del día siguiente — y esa fecha es la que cuenta
    // para el retracto y la garantía.
    const f = fechaCO('2026-07-25T15:30:00Z')
    expect(f).toContain('10:30')
    expect(f).not.toContain('03:30')
  })

  it('y el día no se corre cuando la compra fue de noche', () => {
    process.env.TZ = 'UTC'
    // 02:00 UTC del 26 = 21:00 del 25 en Bogotá. Es el caso que rompía el panel.
    const f = fechaCO('2026-07-26T02:00:00Z')
    // Se ancla el DÍA al inicio: un `not.toContain('26')` ingenuo falla porque el año
    // también lo contiene.
    expect(f).toMatch(/^25 de jul/)
    expect(f).toContain('09:00')
  })

  it('no inventa nada cuando el dato falta', () => {
    expect(fechaCO(null)).toBe('—')
    expect(fechaCO('fecha inválida')).toBe('—')
  })

  it('puede omitir la hora', () => {
    expect(fechaCO('2026-07-25T15:30:00Z', false)).not.toContain(':')
  })
})

describe('identificación', () => {
  it('lista al vendedor completo', () => {
    expect(lineasVendedor(SNAP).map(([r]) => r)).toEqual([
      'Vendedor', 'Documento', 'Dirección', 'Correo',
    ])
  })

  it('NUNCA devuelve un rótulo sin valor', () => {
    const parcial: ReceiptSnapshot = { vendedor: { nombre: 'Tienda' } }
    const lineas = lineasVendedor(parcial)
    expect(lineas).toEqual([['Vendedor', 'Tienda']])
    expect(lineas.every(([, v]) => Boolean(v))).toBe(true)
  })

  it('mantiene el orden entre dos lecturas', () => {
    // Un comprobante no puede cambiar de forma entre dos impresiones.
    expect(lineasVendedor(SNAP)).toEqual(lineasVendedor(SNAP))
  })

  it('tolera un snapshot vacío', () => {
    expect(lineasVendedor({})).toEqual([])
    expect(lineasComprador({})).toEqual([])
  })

  it('omite el correo del comprador cuando no lo dio', () => {
    expect(lineasComprador(SNAP).map(([r]) => r)).toEqual(['Comprador', 'Teléfono'])
  })
})

describe('forma de pago', () => {
  it('distingue contra entrega, que el comprador paga en la puerta', () => {
    expect(formaPago({ pedido: { forma_pago: 'cod' } })).toBe('Contra entrega')
  })

  it('cae a pago en línea por defecto', () => {
    expect(formaPago(SNAP)).toBe('Pago en línea')
    expect(formaPago({})).toBe('Pago en línea')
  })
})

describe('estado de entrega al comprador', () => {
  it('los dos canales son independientes', () => {
    expect(estadoEntrega({ ...BASE, ack_sent_at: 'x' }).texto).toBe('Entregado por WhatsApp')
    expect(estadoEntrega({ ...BASE, email_sent_at: 'x' }).texto).toBe('Entregado por correo')
    expect(estadoEntrega({ ...BASE, ack_sent_at: 'x', email_sent_at: 'x' }).texto)
      .toBe('Entregado por WhatsApp y correo')
  })

  it('ninguno entregado sin motivo es pendiente, no alarma', () => {
    const e = estadoEntrega(BASE)
    expect(e.texto).toBe('Pendiente de entrega')
    expect(e.alerta).toBe(false)
  })

  it('explica POR QUÉ no salió, porque el plazo legal corre igual', () => {
    const csw = estadoEntrega({ ...BASE, ack_skipped_reason: 'fuera_de_ventana_csw' })
    expect(csw.texto).toContain('fuera de la ventana')
    expect(csw.alerta).toBe(true)

    const sinMail = estadoEntrega({ ...BASE, email_skipped_reason: 'comprador_sin_correo' })
    expect(sinMail.texto).toContain('no tiene correo')
    expect(sinMail.alerta).toBe(true)
  })

  it('un motivo desconocido igual se muestra en vez de tragarse', () => {
    const e = estadoEntrega({ ...BASE, ack_skipped_reason: 'motivo_nuevo' })
    expect(e.texto).toContain('motivo_nuevo')
    expect(e.alerta).toBe(true)
  })

  it('si un canal SÍ entregó, el motivo del otro no genera alarma', () => {
    const e = estadoEntrega({
      ...BASE, email_sent_at: 'x', ack_skipped_reason: 'fuera_de_ventana_csw',
    })
    expect(e.texto).toBe('Entregado por correo')
    expect(e.alerta).toBe(false)
  })
})

describe('coherencia del documento', () => {
  it('la suma de las líneas da el subtotal', () => {
    expect(totalLineas(SNAP)).toBe(SNAP.totales!.subtotal)
  })

  it('y las cuentas del documento cierran', () => {
    const t = SNAP.totales!
    expect(t.subtotal! + t.envio! - t.descuento!).toBe(t.total)
  })

  it('sin ítems no revienta', () => {
    expect(totalLineas({})).toBe(0)
  })
})

describe('lineaAceptacion', () => {
  // Ley 1480 art. 50 lit. d): la aceptación debe ser "verificable por la autoridad
  // competente". Antes solo existía como texto suelto en una conversación que se borraba.
  it('muestra la fecha y prefiere el id de Meta como referencia', () => {
    const a = lineaAceptacion({
      aceptacion: {
        fecha: '2026-07-26T15:30:00Z',
        mensaje_id: 'interno-1',
        meta_message_id: 'wamid.ABC',
      },
    })
    expect(a?.referencia).toBe('wamid.ABC')
    expect(a?.fecha).not.toBe('—')
  })

  it('cae al id interno si Meta no dio uno', () => {
    expect(
      lineaAceptacion({ aceptacion: { fecha: '2026-07-26T15:30:00Z', mensaje_id: 'interno-1' } })
        ?.referencia,
    ).toBe('interno-1')
  })

  it('sin aceptación registrada no dice nada, en vez de decir "—"', () => {
    // Un comprobante que dijera "aceptación: —" afirmaría algo sobre la prueba que no le
    // consta. Los pedidos creados por un operador no tienen aceptación del comprador.
    expect(lineaAceptacion({})).toBeNull()
    expect(lineaAceptacion({ aceptacion: {} })).toBeNull()
  })

  it('la fecha va en hora Colombia, no en la del servidor', () => {
    // El 2026-07-25 se corrigieron 31 formateos sin zona: Render corre en UTC y mostraba
    // los pedidos de la noche como del día siguiente. En una aceptación la fecha es la que
    // cuenta para el retracto.
    const previa = process.env.TZ
    process.env.TZ = 'UTC'
    try {
      // 2026-07-26 02:00Z = 2026-07-25 21:00 en Bogotá.
      expect(lineaAceptacion({ aceptacion: { fecha: '2026-07-26T02:00:00Z' } })?.fecha)
        .toMatch(/\b25\b/)
    } finally {
      process.env.TZ = previa
    }
  })
})
