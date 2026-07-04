'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { CORE_API_URL } from '@/lib/runtime-env'

// ADR-0027 — las categorías per-tenant (operativas, las que el bot presenta) se gestionan vía el
// router API /api/v1/product-categories: RBAC + audit_log + tenant scoping. NO escritura directa.

async function getToken(): Promise<string> {
  const supabase = await createClient()
  const { data: { session } } = await supabase.auth.getSession()
  return session?.access_token ?? ''
}

const REVALIDATE = '/dashboard/categories'

export async function createCategory(data: {
  name: string
  display_label: string
  sort_order?: number
  parent_id?: string | null   // F2: categoría padre (vertical). null/undefined = raíz.
}) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/product-categories/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({
        name: data.name,
        display_label: data.display_label,
        sort_order: data.sort_order ?? 0,
        parent_id: data.parent_id ?? null,
      }),
    })
    if (!res.ok) {
      const detail = await res.text()
      return { error: detail || res.statusText }
    }
    revalidatePath(REVALIDATE)
    return { success: true }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error creando categoría' }
  }
}

export async function updateCategory(id: string, data: {
  display_label?: string
  name?: string
  sort_order?: number
  parent_id?: string | null   // F2: reasignar padre. Enviar solo si se quiere cambiar.
}) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const body: Record<string, unknown> = {}
    if (data.display_label !== undefined) body.display_label = data.display_label
    if (data.name !== undefined) body.name = data.name
    if (data.sort_order !== undefined) body.sort_order = data.sort_order
    if (data.parent_id !== undefined) body.parent_id = data.parent_id

    const res = await fetch(`${CORE_API_URL}/api/v1/product-categories/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const detail = await res.text()
      return { error: detail || res.statusText }
    }
    revalidatePath(REVALIDATE)
    return { success: true }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error actualizando categoría' }
  }
}

export async function deleteCategory(id: string) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/product-categories/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` },
    })
    if (!res.ok) {
      const detail = await res.text()
      return { error: detail || res.statusText }
    }
    revalidatePath(REVALIDATE)
    return { success: true }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error eliminando categoría' }
  }
}

// ─── Contrato de atributos por categoría (ADR-0029 D3) — vía /api/v1/product-attribute-definitions ───
// RBAC + @audit_log + validación server-side (type, ownership, code único). NO escritura directa.

const ATTR_API = `${CORE_API_URL}/api/v1/product-attribute-definitions`

export type AttributeDefInput = {
  product_category_id: string
  label: string
  type: 'select' | 'metric' | 'number' | 'boolean' | 'text'
  unit?: string | null
  is_variant_axis?: boolean
  allowed_values?: (string | number)[]
  sort_order?: number
}

export async function createAttributeDef(data: AttributeDefInput) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const res = await fetch(`${ATTR_API}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({
        product_category_id: data.product_category_id,
        label: data.label,
        type: data.type,
        unit: data.unit ?? null,
        is_variant_axis: data.is_variant_axis ?? false,
        allowed_values: data.allowed_values ?? [],
        sort_order: data.sort_order ?? 0,
      }),
    })
    if (!res.ok) return { error: (await res.text()) || res.statusText }
    revalidatePath(REVALIDATE)
    return { success: true }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error creando atributo' }
  }
}

export async function updateAttributeDef(id: string, data: Partial<Omit<AttributeDefInput, 'product_category_id'>>) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const body: Record<string, unknown> = {}
    if (data.label !== undefined) body.label = data.label
    if (data.type !== undefined) body.type = data.type
    if (data.unit !== undefined) body.unit = data.unit
    if (data.is_variant_axis !== undefined) body.is_variant_axis = data.is_variant_axis
    if (data.allowed_values !== undefined) body.allowed_values = data.allowed_values
    if (data.sort_order !== undefined) body.sort_order = data.sort_order
    const res = await fetch(`${ATTR_API}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify(body),
    })
    if (!res.ok) return { error: (await res.text()) || res.statusText }
    revalidatePath(REVALIDATE)
    return { success: true }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error actualizando atributo' }
  }
}

export async function deleteAttributeDef(id: string) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const res = await fetch(`${ATTR_API}/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` },
    })
    if (!res.ok) return { error: (await res.text()) || res.statusText }
    revalidatePath(REVALIDATE)
    return { success: true }
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'Error eliminando atributo' }
  }
}
