'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { CORE_API_URL } from '@/lib/runtime-env'

// Rev. 72 — Purchases ahora pasa por el router API (cierra drift D2).
// Antes este archivo escribía directo a Supabase desde RSC, sin RBAC ni audit.
// El router /api/v1/purchases valida tenant, RBAC, persiste y dispara audit_log.

async function getToken(): Promise<string> {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  return session?.access_token ?? ''
}

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const token = await getToken()
  return fetch(`${CORE_API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(options.headers ?? {}),
    },
  })
}

export async function addSupplier(formData: FormData) {
  const name = (formData.get('name') as string)?.trim() || ''
  if (!name) return

  const body: Record<string, unknown> = { name }
  const email = (formData.get('contact_email') as string)?.trim()
  const phone = (formData.get('phone') as string)?.trim()
  const lead = parseInt((formData.get('lead_time_days') as string) || '0', 10)
  if (email) body.contact_email = email
  if (phone) body.phone = phone
  if (!Number.isNaN(lead)) body.lead_time_days = lead

  const res = await apiFetch('/api/v1/purchases/suppliers', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!res.ok) console.error('addSupplier failed:', await res.text())
  revalidatePath('/dashboard/purchases')
}

export async function createPurchaseOrder(formData: FormData) {
  const supplier_id = (formData.get('supplier_id') as string) || ''
  const itemsStr = (formData.get('items') as string) || ''
  if (!supplier_id || !itemsStr) return

  let items: Array<{ variation_id: string; quantity: number; unit_cost: number }>
  try {
    items = JSON.parse(itemsStr)
  } catch {
    return
  }
  if (!items.length) return

  const expected_str = (formData.get('expected_date') as string) || ''
  const body: Record<string, unknown> = { supplier_id, items }
  if (expected_str) body.expected_date = new Date(expected_str).toISOString()

  const res = await apiFetch('/api/v1/purchases/', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!res.ok) console.error('createPurchaseOrder failed:', await res.text())
  revalidatePath('/dashboard/purchases')
}

export async function cancelPurchaseOrder(poId: string) {
  const res = await apiFetch(`/api/v1/purchases/${poId}/cancel`, { method: 'POST' })
  if (!res.ok) console.error('cancelPurchaseOrder failed:', await res.text())
  revalidatePath('/dashboard/purchases')
}

export async function receivePurchaseOrder(poId: string) {
  const res = await apiFetch(`/api/v1/purchases/${poId}/receive`, { method: 'POST' })
  if (!res.ok) console.error('receivePurchaseOrder failed:', await res.text())
  revalidatePath('/dashboard/purchases')
}
