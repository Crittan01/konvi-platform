'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { CORE_API_URL } from '@/lib/runtime-env'

// Rev. 72 — los claims ahora pasan por el router API (cierra drift D1).
// Antes este archivo escribía directo a Supabase desde RSC, sin RBAC ni audit.
// El router /api/v1/claims valida tenant, RBAC, persiste y dispara audit_log.

async function getToken(): Promise<string> {
  const supabase = await createClient()
  const { data: { session } } = await supabase.auth.getSession()
  return session?.access_token ?? ''
}

// Convierte el cuerpo de error de FastAPI en un mensaje legible en es-CO.
// FastAPI devuelve {"detail": "..."} (HTTPException) o {"detail": [{msg,loc}]} (422 Pydantic).
// Sin esto, el banner del operador mostraba el JSON crudo (gap ux_ui).
async function readApiError(res: Response, fallback: string): Promise<string> {
  const raw = await res.text()
  if (!raw) return `${fallback} (${res.status})`
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown }
    const detail = parsed?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const msgs = detail
        .map(d => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : null))
        .filter(Boolean)
      if (msgs.length) return msgs.join('; ')
    }
  } catch {
    // no era JSON — cae al texto plano (truncado para no volcar HTML de un 502)
  }
  return raw.slice(0, 200)
}

export async function createClaim(data: {
  order_id: string
  customer_id: string | null
  reason: string
  requested_amount?: number
  resolution_notes?: string
}) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }

  try {
    const body: Record<string, unknown> = {
      order_id: data.order_id,
      customer_id: data.customer_id,
      reason: data.reason,
    }
    if (data.requested_amount !== undefined) body.requested_amount = data.requested_amount
    if (data.resolution_notes) body.resolution_notes = data.resolution_notes

    const res = await fetch(`${CORE_API_URL}/api/v1/claims/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      return { error: await readApiError(res, 'No se pudo crear el reclamo') }
    }
    revalidatePath('/dashboard/claims')
    return { success: true }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'Error creando reclamo'
    return { error: msg }
  }
}

// BLOQUE G-2: registra el monto reembolsado en un reclamo YA 'refunded' con monto NULL
// (backfill histórico). PATCH solo refunded_amount → path de corrección de la API.
export async function correctRefundAmount(claimId: string, refundedAmount: number) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/claims/${claimId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ refunded_amount: refundedAmount }),
    })
    if (!res.ok) return { error: await readApiError(res, 'No se pudo registrar el monto') }
    revalidatePath('/dashboard/claims')
    return { success: true }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error registrando el monto' }
  }
}

export async function updateClaimStatus(
  claimId: string, status: string, notes?: string, refundedAmount?: number,
) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }

  try {
    const body: Record<string, unknown> = { status }
    if (notes !== undefined) body.resolution_notes = notes
    // BLOQUE G-2: monto REAL reembolsado (obligatorio al pasar a 'refunded'; el KPI
    // net-revenue lo resta). La API lo exige en esa transición.
    if (refundedAmount !== undefined) body.refunded_amount = refundedAmount

    const res = await fetch(`${CORE_API_URL}/api/v1/claims/${claimId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      return { error: await readApiError(res, 'No se pudo actualizar el reclamo') }
    }
    revalidatePath('/dashboard/claims')
    return { success: true }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'Error actualizando reclamo'
    return { error: msg }
  }
}

// ─── Reversión del pago (Ley 1480 art. 51 + Decreto 1074 cap. 2.2.2.51) ──────
//
// Figura DISTINTA del reembolso de arriba. Acá el dinero lo devuelve el emisor del medio
// de pago, no nosotros; nuestra obligación es emitir la constancia de la queja con fecha y
// causal (art. 2.2.2.51.4). El comprador la necesita para notificar a su banco
// (art. 2.2.2.51.7 num. 6): sin ella no puede ejercer el derecho.

export type ConstanciaReversion = {
  id: string
  radicado: string
  causal: string
  valor: number
  es_parcial: boolean
  instrumento: string | null
  bien_a_disposicion: boolean
  presentada_at: string
  constancia_emitida_at: string | null
  constancia_entregada_at: string | null
  constancia_entrega_fallida: string | null
  reembolso_directo_at: string | null
  reversion_confirmada_at: string | null
  doble_pago_detectado_at: string | null
  estado: string
  constancia: Record<string, unknown> | null
}

export async function registrarReversion(claimId: string, data: {
  causal: string
  razones: string
  valor: number
  instrumento?: string
  es_parcial?: boolean
  bien_a_disposicion?: boolean
}) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/claims/${claimId}/reversion`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ ...data, canal: 'inbox' }),
    })
    if (!res.ok) return { error: await readApiError(res, 'No se pudo radicar la reversión') }
    revalidatePath('/dashboard/claims')
    return { success: true, data: (await res.json()) as ConstanciaReversion }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error radicando la reversión' }
  }
}

export async function obtenerReversion(claimId: string) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/claims/${claimId}/reversion`, {
      headers: { 'Authorization': `Bearer ${token}` },
      cache: 'no-store',
    })
    // 404 no es un error a mostrar: la mayoría de los reclamos no son de reversión.
    if (res.status === 404) return { success: true, data: null }
    if (!res.ok) return { error: await readApiError(res, 'No se pudo leer la reversión') }
    return { success: true, data: (await res.json()) as ConstanciaReversion }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error leyendo la reversión' }
  }
}

export async function registrarMovimientoReversion(
  claimId: string, via: 'reembolso_directo' | 'reversion_emisor', valor: number,
) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/claims/${claimId}/reversion/movimiento`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ via, valor }),
    })
    if (!res.ok) return { error: await readApiError(res, 'No se pudo registrar el movimiento') }
    revalidatePath('/dashboard/claims')
    return { success: true, data: (await res.json()) as ConstanciaReversion }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error registrando el movimiento' }
  }
}
