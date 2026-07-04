'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { CORE_API_URL } from '@/lib/runtime-env'

// F-doc (Fase 6): las server actions devuelven ActionResult en vez de throw. En prod
// Next.js reemplaza el message de un throw en Server Action por texto genérico + digest;
// el operador perdía la causa (fallo del API, validación). Patrón canónico ya en contacts.
type ActionResult = { ok: boolean; error?: string }

// Rev. 72 — Purchases ahora pasa por el router API (cierra drift D2).
// Antes este archivo escribía directo a Supabase desde RSC, sin RBAC ni audit.
// El router /api/v1/purchases valida tenant, RBAC, persiste y dispara audit_log.

async function getToken(): Promise<string> {
  const supabase = await createClient()
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

export async function addSupplier(formData: FormData): Promise<ActionResult> {
  const name = (formData.get('name') as string)?.trim() || ''
  if (!name) return { ok: false, error: 'El nombre del proveedor es requerido.' }

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
  // F140/F-doc: no tragar el fallo, pero devolverlo como ActionResult (no throw, que
  // Next.js enmascara en prod) → el consumidor muestra res.error.
  if (!res.ok) return { ok: false, error: (await res.text()).slice(0, 200) || 'No se pudo guardar el proveedor' }
  revalidatePath('/dashboard/purchases')
  return { ok: true }
}

export async function createPurchaseOrder(formData: FormData): Promise<ActionResult> {
  const supplier_id = (formData.get('supplier_id') as string) || ''
  const itemsStr = (formData.get('items') as string) || ''
  if (!supplier_id || !itemsStr) return { ok: false, error: 'Falta proveedor o ítems.' }

  let items: Array<{ variation_id: string; quantity: number; unit_cost: number }>
  try {
    items = JSON.parse(itemsStr)
  } catch {
    return { ok: false, error: 'Ítems con formato inválido.' }
  }
  if (!items.length) return { ok: false, error: 'La orden debe tener al menos un ítem.' }

  const expected_str = (formData.get('expected_date') as string) || ''
  const body: Record<string, unknown> = { supplier_id, items }
  if (expected_str) body.expected_date = new Date(expected_str).toISOString()

  const res = await apiFetch('/api/v1/purchases/', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!res.ok) return { ok: false, error: (await res.text()).slice(0, 200) || 'No se pudo crear la orden de compra' }
  revalidatePath('/dashboard/purchases')
  return { ok: true }
}

export async function cancelPurchaseOrder(poId: string): Promise<ActionResult> {
  const res = await apiFetch(`/api/v1/purchases/${poId}/cancel`, { method: 'POST' })
  if (!res.ok) return { ok: false, error: (await res.text()).slice(0, 200) || 'No se pudo cancelar la orden' }
  revalidatePath('/dashboard/purchases')
  return { ok: true }
}

export async function receivePurchaseOrder(poId: string): Promise<ActionResult> {
  const res = await apiFetch(`/api/v1/purchases/${poId}/receive`, { method: 'POST' })
  if (!res.ok) return { ok: false, error: (await res.text()).slice(0, 200) || 'No se pudo recibir la orden' }
  revalidatePath('/dashboard/purchases')
  return { ok: true }
}
