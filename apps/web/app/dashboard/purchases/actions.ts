'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { CORE_API_URL } from '@/lib/runtime-env'
import { ok, fail, type ActionResult } from '@/lib/action-result'

// Rev. 72 — Purchases pasa por el router API (cierra drift D2). El router
// /api/v1/purchases valida tenant, RBAC, persiste y dispara audit_log.
//
// F3 — los fallos ya NO llegan como JSON crudo de FastAPI al alert del browser:
// apiError() traduce el 422/detalle a copy es-CO y deja rastro server-side
// (console.error) — antes el error solo existía en el alert efímero del operador.

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

/**
 * Traduce el cuerpo de un error del API a copy es-CO. FastAPI devuelve 422 como
 * `{"detail":[{"type":"greater_than","loc":[...],"msg":"..."}]}` y 4xx de negocio
 * como `{"detail":"texto"}`. Sin esto, el JSON crudo terminaba en el toast.
 */
async function apiError(res: Response, fallback: string): Promise<string> {
  let raw = ''
  try {
    raw = await res.text()
  } catch {
    /* sin cuerpo */
  }
  // Log server-side para diagnóstico (el operador solo ve copy amable).
  console.error(`[purchases] API ${res.status} ${res.statusText}: ${raw.slice(0, 500)}`)

  if (res.status === 401 || res.status === 403) {
    return 'No tienes permisos para esta operación.'
  }
  if (res.status === 404) {
    return 'La orden ya no existe o fue modificada. Refresca la página.'
  }
  if (res.status === 409) {
    return 'La orden cambió de estado. Refresca la página e intenta de nuevo.'
  }
  try {
    const body = JSON.parse(raw) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      const msgs = body.detail
        .map((d: { msg?: string }) => (typeof d?.msg === 'string' ? d.msg : null))
        .filter(Boolean)
      if (msgs.length) return `Datos inválidos: ${msgs.join('; ')}`
    }
  } catch {
    /* no era JSON */
  }
  if (res.status >= 500) return 'El servidor tuvo un problema. Intenta de nuevo en un momento.'
  return fallback
}

export async function addSupplier(formData: FormData): Promise<ActionResult> {
  const name = (formData.get('name') as string)?.trim() || ''
  if (!name) return fail('El nombre del proveedor es requerido.')

  const body: Record<string, unknown> = { name }
  const email = (formData.get('contact_email') as string)?.trim()
  const phone = (formData.get('phone') as string)?.trim()
  const leadRaw = (formData.get('lead_time_days') as string) || ''
  if (email) body.contact_email = email
  if (phone) body.phone = phone
  if (leadRaw.trim() !== '') {
    const lead = parseInt(leadRaw, 10)
    if (!Number.isNaN(lead) && lead >= 0) body.lead_time_days = lead
  }

  const res = await apiFetch('/api/v1/purchases/suppliers', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!res.ok) return fail(await apiError(res, 'No se pudo guardar el proveedor.'))
  revalidatePath('/dashboard/purchases')
  return ok('Proveedor guardado.')
}

export async function updateSupplier(supplierId: string, formData: FormData): Promise<ActionResult> {
  if (!supplierId) return fail('Falta el identificador del proveedor.')
  const name = (formData.get('name') as string)?.trim() || ''
  if (!name) return fail('El nombre del proveedor es requerido.')

  const body: Record<string, unknown> = { name }
  // Enviamos siempre email/phone (incluso vacíos → null) para permitir limpiarlos;
  // el API valida el patrón cuando no son null.
  const email = (formData.get('contact_email') as string)?.trim()
  const phone = (formData.get('phone') as string)?.trim()
  const leadRaw = (formData.get('lead_time_days') as string) || ''
  if (email) body.contact_email = email
  if (phone) body.phone = phone
  if (leadRaw.trim() !== '') {
    const lead = parseInt(leadRaw, 10)
    if (!Number.isNaN(lead) && lead >= 0) body.lead_time_days = lead
  }

  const res = await apiFetch(`/api/v1/purchases/suppliers/${supplierId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
  if (!res.ok) return fail(await apiError(res, 'No se pudo actualizar el proveedor.'))
  revalidatePath('/dashboard/purchases')
  return ok('Proveedor actualizado.')
}

export async function setSupplierActive(supplierId: string, isActive: boolean): Promise<ActionResult> {
  if (!supplierId) return fail('Falta el identificador del proveedor.')
  const res = await apiFetch(`/api/v1/purchases/suppliers/${supplierId}`, {
    method: 'PATCH',
    body: JSON.stringify({ is_active: isActive }),
  })
  if (!res.ok) return fail(await apiError(res, 'No se pudo cambiar el estado del proveedor.'))
  revalidatePath('/dashboard/purchases')
  return ok(isActive ? 'Proveedor reactivado.' : 'Proveedor desactivado.')
}

export async function createPurchaseOrder(formData: FormData): Promise<ActionResult> {
  const supplier_id = (formData.get('supplier_id') as string) || ''
  const itemsStr = (formData.get('items') as string) || ''
  if (!supplier_id) return fail('Selecciona un proveedor.')
  if (!itemsStr) return fail('Agrega al menos un ítem a la orden.')

  let items: Array<{ variation_id: string; quantity: number; unit_cost: number }>
  try {
    items = JSON.parse(itemsStr)
  } catch {
    return fail('Los ítems tienen un formato inválido.')
  }
  if (!Array.isArray(items) || !items.length) return fail('La orden debe tener al menos un ítem.')

  // Validación de negocio en el boundary: qty entera > 0 y costo >= 0. El backend
  // también lo valida (gt=0), pero surfaceamos el error en es-CO antes del round-trip.
  for (const it of items) {
    if (!it.variation_id) return fail('Hay un ítem sin producto seleccionado.')
    if (!Number.isInteger(it.quantity) || it.quantity <= 0) {
      return fail('La cantidad de cada ítem debe ser un número entero mayor a 0.')
    }
    if (typeof it.unit_cost !== 'number' || Number.isNaN(it.unit_cost) || it.unit_cost < 0) {
      return fail('El costo de cada ítem no puede ser negativo.')
    }
  }

  const expected_str = (formData.get('expected_date') as string) || ''
  const body: Record<string, unknown> = { supplier_id, items }
  if (expected_str) body.expected_date = new Date(expected_str).toISOString()

  const res = await apiFetch('/api/v1/purchases/', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!res.ok) return fail(await apiError(res, 'No se pudo crear la orden de compra.'))
  revalidatePath('/dashboard/purchases')
  return ok('Orden de compra creada.')
}

export async function editPurchaseOrder(poId: string, formData: FormData): Promise<ActionResult> {
  if (!poId) return fail('Falta el identificador de la orden.')
  const itemsStr = (formData.get('items') as string) || ''
  if (!itemsStr) return fail('Agrega al menos un ítem a la orden.')

  let items: Array<{ variation_id: string; quantity: number; unit_cost: number }>
  try {
    items = JSON.parse(itemsStr)
  } catch {
    return fail('Los ítems tienen un formato inválido.')
  }
  if (!Array.isArray(items) || !items.length) return fail('La orden debe tener al menos un ítem.')

  // Mismo boundary de validación que createPurchaseOrder (qty entera > 0, costo >= 0).
  for (const it of items) {
    if (!it.variation_id) return fail('Hay un ítem sin producto seleccionado.')
    if (!Number.isInteger(it.quantity) || it.quantity <= 0) {
      return fail('La cantidad de cada ítem debe ser un número entero mayor a 0.')
    }
    if (typeof it.unit_cost !== 'number' || Number.isNaN(it.unit_cost) || it.unit_cost < 0) {
      return fail('El costo de cada ítem no puede ser negativo.')
    }
  }

  const body: Record<string, unknown> = { items }
  // La fecha estimada solo se envía cuando trae valor (actualiza/fija). Vaciarla
  // no está soportado por el contrato del API (expected_date None = "sin cambio").
  const expected_str = (formData.get('expected_date') as string) || ''
  if (expected_str) body.expected_date = new Date(expected_str).toISOString()

  const res = await apiFetch(`/api/v1/purchases/${poId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
  if (!res.ok) return fail(await apiError(res, 'No se pudo actualizar la orden de compra.'))
  revalidatePath('/dashboard/purchases')
  return ok('Orden de compra actualizada.')
}

export async function cancelPurchaseOrder(poId: string): Promise<ActionResult> {
  const res = await apiFetch(`/api/v1/purchases/${poId}/cancel`, { method: 'POST' })
  if (!res.ok) return fail(await apiError(res, 'No se pudo cancelar la orden.'))
  revalidatePath('/dashboard/purchases')
  return ok('Orden cancelada.')
}

export async function receivePurchaseOrder(poId: string): Promise<ActionResult> {
  const res = await apiFetch(`/api/v1/purchases/${poId}/receive`, { method: 'POST' })
  if (!res.ok) return fail(await apiError(res, 'No se pudo recibir la orden.'))
  revalidatePath('/dashboard/purchases')
  return ok('Orden recibida — inventario y costos actualizados.')
}
