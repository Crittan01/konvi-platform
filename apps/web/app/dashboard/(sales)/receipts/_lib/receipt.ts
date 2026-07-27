/**
 * Lectura del snapshot congelado de un comprobante.
 *
 * El snapshot es JSONB armado por `rpc_issue_receipt` (ADR-0040) y NO se re-consulta contra
 * datos vivos: eso es justamente lo que convierte el documento en comprobante. Estas
 * funciones solo LEEN — si algún día hay que cambiar qué dice el documento, se cambia el
 * armado en SQL, no acá, o los comprobantes viejos empezarían a decir cosas nuevas.
 *
 * Puro y sin dependencias de React a propósito: la degradación (qué pasa cuando un campo
 * falta) es la parte que más importa y tiene que poder probarse sin renderizar nada.
 */

export type ReceiptItem = {
  titulo?: string
  cantidad?: number
  precio_unitario?: number
  total_linea?: number
}

export type ReceiptSnapshot = {
  version?: number
  emitido_at?: string
  pedido?: { id?: string; estado?: string; fecha?: string; forma_pago?: string }
  vendedor?: {
    nombre?: string
    documento?: string
    direccion?: string
    email?: string
    completa?: boolean
    faltantes?: string[]
    usa_nombre_comercial?: boolean
  }
  comprador?: { nombre?: string; telefono?: string; email?: string }
  aceptacion?: { fecha?: string; mensaje_id?: string; meta_message_id?: string }
  items?: ReceiptItem[]
  totales?: {
    subtotal?: number
    descuento?: number
    envio?: number
    total?: number
    moneda?: string
  }
}

export type Receipt = {
  id: string
  numero: string
  issued_at: string
  voided_at: string | null
  void_reason: string | null
  ack_sent_at: string | null
  ack_skipped_reason: string | null
  email_sent_at: string | null
  email_skipped_reason: string | null
  snapshot: ReceiptSnapshot
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
 * El 2026-07-25 se corrigieron 31 formateos que no fijaban zona: el servidor de Render usa
 * UTC y mostraba los pedidos de la noche como del día siguiente. En un comprobante una
 * fecha corrida no es cosmética — es la que cuenta para el retracto y la garantía.
 */
export function fechaCO(iso: string | null | undefined, conHora = true): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('es-CO', {
    timeZone: 'America/Bogota',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    ...(conHora ? { hour: '2-digit', minute: '2-digit' } : {}),
  })
}

/** Las líneas de identificación que SÍ tienen valor. El renderizador no filtra: si un
 *  campo está vacío, acá no aparece — un "Documento: —" es peor que no tener la línea. */
export function lineasVendedor(s: ReceiptSnapshot): Array<[string, string]> {
  const v = s?.vendedor ?? {}
  const pares: Array<[string, string | undefined]> = [
    ['Vendedor', v.nombre],
    ['Documento', v.documento],
    ['Dirección', v.direccion],
    ['Correo', v.email],
  ]
  return pares.filter((p): p is [string, string] => Boolean(p[1]))
}

export function lineasComprador(s: ReceiptSnapshot): Array<[string, string]> {
  const c = s?.comprador ?? {}
  const pares: Array<[string, string | undefined]> = [
    ['Comprador', c.nombre],
    ['Teléfono', c.telefono],
    ['Correo', c.email],
  ]
  return pares.filter((p): p is [string, string] => Boolean(p[1]))
}

/**
 * Cómo se dice, en el documento, cuál manifestación del comprador lo originó.
 *
 * Ley 1480 art. 50 lit. d): la aceptación debe ser "expresa, inequívoca y verificable por
 * la autoridad competente". Un comprobante que no dice a qué aceptación corresponde obliga
 * a ir a buscarla al historial de WhatsApp — que hasta ahora se borraba a los 180 días.
 *
 * Devuelve `null` cuando el pedido no tiene aceptación registrada (lo creó un operador, o
 * es anterior a este registro). En ese caso NO se muestra nada: un comprobante que dijera
 * "aceptación: —" afirmaría algo sobre la prueba que no le consta.
 */
export function lineaAceptacion(
  s: ReceiptSnapshot,
): { fecha: string; referencia: string | null } | null {
  const a = s?.aceptacion
  if (!a?.fecha) return null
  return {
    fecha: fechaCO(a.fecha),
    // El id de Meta es atestación de un TERCERO: la fecha y el contenido de ese mensaje no
    // dependen solo de nuestra base. Por eso se prefiere al id interno cuando existe.
    referencia: a.meta_message_id ?? a.mensaje_id ?? null,
  }
}

export function formaPago(s: ReceiptSnapshot): string {
  return (s?.pedido?.forma_pago ?? '') === 'cod' ? 'Contra entrega' : 'Pago en línea'
}

/**
 * Estado de entrega al comprador, en una frase.
 *
 * Los dos canales son independientes: un comprobante puede haber llegado por uno y no por
 * el otro. El operador necesita saberlo para responder "¿le llegó?" sin adivinar.
 */
export function estadoEntrega(r: Receipt): { texto: string; alerta: boolean } {
  const wa = Boolean(r.ack_sent_at)
  const mail = Boolean(r.email_sent_at)
  if (wa && mail) return { texto: 'Entregado por WhatsApp y correo', alerta: false }
  if (wa) return { texto: 'Entregado por WhatsApp', alerta: false }
  if (mail) return { texto: 'Entregado por correo', alerta: false }
  // Ninguno salió: importa POR QUÉ, porque el plazo legal corre igual.
  const motivo = r.ack_skipped_reason ?? r.email_skipped_reason
  if (motivo === 'fuera_de_ventana_csw') {
    return { texto: 'Sin entregar — fuera de la ventana de WhatsApp', alerta: true }
  }
  if (motivo === 'comprador_sin_correo') {
    return { texto: 'Sin entregar — el comprador no tiene correo', alerta: true }
  }
  if (motivo) return { texto: `Sin entregar — ${motivo}`, alerta: true }
  return { texto: 'Pendiente de entrega', alerta: false }
}

/** Suma de las líneas, para poder mostrar que el documento cuadra consigo mismo. */
export function totalLineas(s: ReceiptSnapshot): number {
  return (s?.items ?? []).reduce((acc, i) => acc + Number(i?.total_linea ?? 0), 0)
}
