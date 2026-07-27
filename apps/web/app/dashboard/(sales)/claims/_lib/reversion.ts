/**
 * Vocabulario y estado de la reversión del pago, sin React.
 *
 * La reversión NO es el reembolso que ya vive en este módulo. Acá el dinero lo devuelve el
 * emisor del medio de pago del comprador; nuestra obligación es emitir la constancia de la
 * queja con fecha y causal (Decreto 1074 art. 2.2.2.51.4), que él necesita para notificar
 * a su banco (art. 2.2.2.51.7 num. 6). Sin ella no puede ejercer el derecho.
 *
 * Puro a propósito, igual que `receipts/_lib/receipt.ts`: lo que más importa es cómo se
 * degrada —qué se muestra cuando falta un dato, cuándo se avisa del doble pago— y eso
 * tiene que poder probarse sin renderizar nada.
 */

/**
 * Las cinco causales del art. 2.2.2.51.2. Lista CERRADA, espejo del CHECK en DB y del
 * validador de la API.
 *
 * El texto es el que ve y escoge una persona: la causal la DECLARA el consumidor y el
 * operador la transcribe. La norma pide "indicación de la causal que sustenta la
 * petición", así que no se infiere de lo que escribió.
 */
export const CAUSALES: ReadonlyArray<{ value: string; label: string; ayuda: string }> = [
  { value: 'fraude', label: 'No reconoce la compra (fraude)', ayuda: 'Art. 2.2.2.51.2 num. 1' },
  { value: 'operacion_no_solicitada', label: 'No pidió esto', ayuda: 'num. 2' },
  { value: 'producto_no_recibido', label: 'No le llegó el producto', ayuda: 'num. 3' },
  {
    value: 'producto_no_corresponde',
    label: 'Le llegó algo distinto a lo que pidió',
    ayuda: 'num. 4 — tampoco cumple lo informado',
  },
  { value: 'producto_defectuoso', label: 'Le llegó defectuoso', ayuda: 'num. 5' },
]

export function causalLabel(value: string | null | undefined): string {
  return CAUSALES.find(c => c.value === value)?.label ?? value ?? '—'
}

export type Reversion = {
  radicado?: string
  causal?: string
  valor?: number
  es_parcial?: boolean
  instrumento?: string | null
  presentada_at?: string
  constancia_emitida_at?: string | null
  constancia_entregada_at?: string | null
  constancia_entrega_fallida?: string | null
  reembolso_directo_at?: string | null
  reversion_confirmada_at?: string | null
  doble_pago_detectado_at?: string | null
  estado?: string
}

/**
 * En qué va la constancia, en una frase.
 *
 * Se distingue "emitida" de "entregada" porque la obligación del art. 2.2.2.51.4 no se
 * agota emitiendo: el comprador tiene que TENERLA para adjuntarla a su notificación. Una
 * constancia emitida y no entregada es un incumplimiento a medias, y el operador necesita
 * verlo para mandarla por otro medio.
 */
export function estadoConstancia(r: Reversion): { texto: string; alerta: boolean } {
  if (r.constancia_entrega_fallida) {
    return {
      texto: `No se pudo entregar (${r.constancia_entrega_fallida}). Hay que hacérsela llegar por otro medio.`,
      alerta: true,
    }
  }
  if (r.constancia_entregada_at) return { texto: 'Entregada al comprador', alerta: false }
  if (r.constancia_emitida_at) return { texto: 'Emitida — pendiente de entrega', alerta: false }
  return { texto: 'Sin constancia', alerta: true }
}

/**
 * Por dónde volvió el dinero, y si volvió por los dos.
 *
 * El art. 2.2.2.51.10 contempla expresamente el doble pago —el comerciante reembolsa
 * mientras el emisor reversa en paralelo— y dice que el consumidor debe devolver esos
 * recursos. Si el operador no lo ve, la plata simplemente se pierde.
 */
export function estadoDinero(r: Reversion): { texto: string; alerta: boolean } {
  const directo = Boolean(r.reembolso_directo_at)
  const emisor = Boolean(r.reversion_confirmada_at)
  if (directo && emisor) {
    return {
      texto:
        'El dinero salió DOS VECES: se reembolsó directamente y además el emisor reversó. ' +
        'Hay que contactar al comprador para que devuelva el excedente (art. 2.2.2.51.10).',
      alerta: true,
    }
  }
  if (emisor) return { texto: 'El emisor reversó el cargo', alerta: false }
  if (directo) return { texto: 'Se reembolsó directamente', alerta: false }
  return { texto: 'El dinero todavía no ha vuelto', alerta: false }
}

/** Pesos colombianos, sin centavos: acá no circulan. */
export function cop(value: unknown): string {
  const n = typeof value === 'number' ? value : Number(value ?? 0)
  if (!Number.isFinite(n)) return '$0'
  return `$${n.toLocaleString('es-CO', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

/**
 * Fecha en hora Colombia, SIEMPRE explícita.
 *
 * En una constancia la fecha no es cosmética: es lo que prueba que la queja se presentó
 * dentro de los cinco días hábiles del art. 2.2.2.51.4. El servidor de Render corre en
 * UTC y mostraba los hechos de la noche como del día siguiente.
 */
export function fechaCO(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('es-CO', {
    timeZone: 'America/Bogota',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Si un pedido admite siquiera esta figura.
 *
 * Art. 2.2.2.51.1: la reversión "no procede cuando [los pagos] hayan sido realizados por
 * medio de canales presenciales". Contra entrega en efectivo no tiene instrumento
 * electrónico que reversar. Se comprueba acá para no ofrecerle al operador un botón que
 * la API va a rechazar, y sobre todo para que no le prometa al comprador un derecho que
 * no tiene.
 */
export function admiteReversion(formaPago: string | null | undefined): boolean {
  const fp = (formaPago ?? '').trim().toLowerCase()
  if (!fp) return false
  return !['cod', 'cash', 'efectivo'].includes(fp)
}
