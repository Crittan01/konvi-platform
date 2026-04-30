'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { CORE_API_URL } from '@/lib/runtime-env'

// Rev. 72 — los claims ahora pasan por el router API (cierra drift D1).
// Antes este archivo escribía directo a Supabase desde RSC, sin RBAC ni audit.
// El router /api/v1/claims valida tenant, RBAC, persiste y dispara audit_log.

async function getToken(): Promise<string> {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  return session?.access_token ?? ''
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
      const detail = await res.text()
      return { error: detail || res.statusText }
    }
    revalidatePath('/dashboard/claims')
    return { success: true }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'Error creando reclamo'
    return { error: msg }
  }
}

export async function updateClaimStatus(claimId: string, status: string, notes?: string) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }

  try {
    const body: Record<string, unknown> = { status }
    if (notes !== undefined) body.resolution_notes = notes

    const res = await fetch(`${CORE_API_URL}/api/v1/claims/${claimId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const detail = await res.text()
      return { error: detail || res.statusText }
    }
    revalidatePath('/dashboard/claims')
    return { success: true }
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'Error actualizando reclamo'
    return { error: msg }
  }
}
