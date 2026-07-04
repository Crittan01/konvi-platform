'use server'

import { revalidatePath } from 'next/cache'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

const SESSION_EXPIRED = 'Tu sesión expiró. Recarga la página e inicia sesión de nuevo.'

async function getToken(): Promise<string> {
  const supabase = await createClient()
  const { data: { session } } = await supabase.auth.getSession()
  return session?.access_token ?? ''
}

/**
 * Extrae un mensaje legible de la respuesta de error del API.
 * FastAPI responde `{"detail": "..."}`; sin este parseo el operador veía el
 * JSON crudo como error de fila. Traduce además códigos comunes a copy es-CO.
 */
async function parseApiError(res: Response, fallback: string): Promise<string> {
  if (res.status === 401) return SESSION_EXPIRED
  const raw = await res.text().catch(() => '')
  if (raw) {
    try {
      const parsed = JSON.parse(raw)
      const detail = parsed?.detail ?? parsed?.message
      if (typeof detail === 'string' && detail.trim()) return detail
      if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
    } catch {
      // no era JSON: devolver el texto plano recortado
      return raw.length > 300 ? `${raw.slice(0, 300)}…` : raw
    }
  }
  if (res.status === 502 || res.status === 503) {
    return 'Mercado Libre no respondió. Intenta de nuevo en unos segundos.'
  }
  return fallback || `Error ${res.status}.`
}

export async function linkListing(meliId: string, variationId: string, meliPrice?: number, meliVariationId?: number) {
  const token = await getToken()
  if (!token) return { error: SESSION_EXPIRED }
  try {
    const body: Record<string, unknown> = { meli_id: meliId, variation_id: variationId, meli_price: meliPrice }
    if (meliVariationId != null) body.meli_variation_id = meliVariationId

    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify(body)
    })
    if (!res.ok) throw new Error(await parseApiError(res, 'No se pudo vincular la publicación.'))
    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al vincular' }
  }
}

export async function unlinkListing(listingId: string) {
  const token = await getToken()
  if (!token) return { error: SESSION_EXPIRED }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/link/${listingId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!res.ok) throw new Error(await parseApiError(res, 'No se pudo desvincular la publicación.'))
    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al desvincular' }
  }
}

export async function changeListingStatus(listingId: string, status: 'active' | 'paused') {
  const token = await getToken()
  if (!token) return { error: SESSION_EXPIRED }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/${listingId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ status })
    })
    if (!res.ok) throw new Error(await parseApiError(res, 'No se pudo actualizar el estado.'))
    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al actualizar estado' }
  }
}

export async function importFromMeli(meliId: string, categoryId?: string) {
  const token = await getToken()
  if (!token) return { error: SESSION_EXPIRED }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ meli_id: meliId, category_id: categoryId || null })
    })
    if (!res.ok) throw new Error(await parseApiError(res, 'No se pudo importar la publicación.'))
    revalidatePath('/dashboard/marketplace')
    revalidatePath('/dashboard/catalog')
    return { success: true, data: await res.json().catch(() => null) }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al importar' }
  }
}

export async function syncStockFromSupabase(listingId: string) {
  const token = await getToken()
  if (!token) return { error: SESSION_EXPIRED }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/${listingId}/sync-stock`, {
      method: 'PATCH',
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!res.ok) throw new Error(await parseApiError(res, 'No se pudo sincronizar el stock.'))
    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al sincronizar stock' }
  }
}
