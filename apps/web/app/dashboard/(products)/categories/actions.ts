'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { CORE_API_URL } from '@/lib/runtime-env'

// ADR-0027 — las categorías per-tenant (operativas, las que el bot presenta) se gestionan vía el
// router API /api/v1/product-categories: RBAC + audit_log + tenant scoping. NO escritura directa.

async function getToken(): Promise<string> {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  return session?.access_token ?? ''
}

const REVALIDATE = '/dashboard/categories'

export async function createCategory(data: {
  name: string
  display_label: string
  sort_order?: number
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
}) {
  const token = await getToken()
  if (!token) return { error: 'Unauthorized' }
  try {
    const body: Record<string, unknown> = {}
    if (data.display_label !== undefined) body.display_label = data.display_label
    if (data.name !== undefined) body.name = data.name
    if (data.sort_order !== undefined) body.sort_order = data.sort_order

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
