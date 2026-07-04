'use server'

import { revalidatePath } from 'next/cache'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

async function getToken(): Promise<string> {
  const supabase = await createClient()
  const { data: { session } } = await supabase.auth.getSession()
  return session?.access_token ?? ''
}

export async function linkListing(meliId: string, variationId: string, meliPrice?: number, meliVariationId?: number) {
  const token = await getToken()
  try {
    const body: Record<string, unknown> = { meli_id: meliId, variation_id: variationId, meli_price: meliPrice }
    if (meliVariationId != null) body.meli_variation_id = meliVariationId

    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify(body)
    })
    if (!res.ok) {
      const detail = await res.text()
      throw new Error(detail || res.statusText)
    }
    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al vincular' }
  }
}

export async function unlinkListing(listingId: string) {
  const token = await getToken()
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/link/${listingId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!res.ok) {
      const detail = await res.text()
      throw new Error(detail || res.statusText)
    }
    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al desvincular' }
  }
}

export async function changeListingStatus(listingId: string, status: 'active' | 'paused') {
  const token = await getToken()
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/${listingId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ status })
    })
    if (!res.ok) {
      const detail = await res.text()
      throw new Error(detail || res.statusText)
    }
    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al actualizar estado' }
  }
}

export async function importFromMeli(meliId: string, categoryId?: string) {
  const token = await getToken()
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ meli_id: meliId, category_id: categoryId || null })
    })
    if (!res.ok) {
      const detail = await res.text()
      throw new Error(detail || res.statusText)
    }
    revalidatePath('/dashboard/marketplace')
    revalidatePath('/dashboard/catalog')
    return { success: true, data: await res.json() }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al importar' }
  }
}

export async function syncStockFromSupabase(listingId: string) {
  const token = await getToken()
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/${listingId}/sync-stock`, {
      method: 'PATCH',
      headers: { 'Authorization': `Bearer ${token}` }
    })
    if (!res.ok) {
      const detail = await res.text()
      throw new Error(detail || res.statusText)
    }
    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch (error) {
    return { error: error instanceof Error ? error.message : 'Error al sincronizar stock' }
  }
}
