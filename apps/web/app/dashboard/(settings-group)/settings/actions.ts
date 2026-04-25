'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'

// ── Auth helper compartido ────────────────────────────────────────────────────
// Retorna el tenant_id solo si el usuario autenticado es owner.
// Retorna null si no hay sesión, no tiene tenant o no es owner.

async function getOwnerTenantId(): Promise<string | null> {
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const m = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id || m.role !== 'owner') return null
  return m.tenant_id
}

function revalidateSettings() {
  revalidatePath('/dashboard/settings')
  revalidatePath('/dashboard')
}

async function updateTenant(tenantId: string, data: Record<string, unknown>) {
  const sb = createClient()
  await sb.from('tenants').update(data).eq('id', tenantId)
}

// ── Acciones exportadas ───────────────────────────────────────────────────────

export async function saveTenant(formData: FormData) {
  const tenantId = await getOwnerTenantId()
  if (!tenantId) return
  await updateTenant(tenantId, {
    name:              (formData.get('name') as string)?.trim() || undefined,
    nit:               (formData.get('nit') as string)?.trim()  || null,
    email_contacto:    (formData.get('email_contacto') as string)?.trim() || null,
    telefono_contacto: (formData.get('telefono_contacto') as string)?.trim() || null,
  })
  revalidateSettings()
}

export async function saveOperativa(formData: FormData) {
  const tenantId = await getOwnerTenantId()
  if (!tenantId) return
  const threshold = parseInt(formData.get('low_stock_threshold') as string, 10)
  if (Number.isInteger(threshold) && threshold >= 1 && threshold <= 999) {
    await updateTenant(tenantId, { low_stock_threshold: threshold })
  }
  revalidateSettings()
}

export async function savePresenciaDigital(formData: FormData) {
  const tenantId = await getOwnerTenantId()
  if (!tenantId) return

  const store_type = (formData.get('store_type') as string) || 'fisica'

  let store_locations: object[] = []
  try {
    const raw = formData.get('store_locations') as string
    if (raw) store_locations = JSON.parse(raw)
  } catch { /* keep empty */ }

  const social_links: Record<string, string> = {}
  for (const red of ['instagram', 'facebook', 'tiktok', 'youtube', 'website']) {
    const val = (formData.get(`social_${red}`) as string)?.trim()
    if (val) social_links[red] = val
  }

  await updateTenant(tenantId, { store_type, store_locations, social_links })
  revalidatePath('/dashboard/settings')
}

export async function saveHorario(formData: FormData) {
  const tenantId = await getOwnerTenantId()
  if (!tenantId) return
  const business_hours = (formData.get('business_hours') as string)?.trim() || null
  await updateTenant(tenantId, { business_hours })
  revalidatePath('/dashboard/settings')
}

export async function saveShippingOrigin(formData: FormData) {
  const tenantId = await getOwnerTenantId()
  if (!tenantId) return

  const fields = ['name', 'company', 'street', 'city', 'state', 'postal_code', 'country', 'phone', 'dane_code']
  const origin: Record<string, string> = {}
  for (const f of fields) {
    const val = (formData.get(`origin_${f}`) as string)?.trim()
    if (val) origin[f] = val
  }
  // Mantener postal_code y dane_code alineados para Envia quote (CO, DANE 8 dígitos)
  if (origin.dane_code && !origin.postal_code) origin.postal_code = origin.dane_code
  if (origin.postal_code && !origin.dane_code)  origin.dane_code  = origin.postal_code

  await updateTenant(tenantId, { shipping_origin: origin })
  revalidatePath('/dashboard/settings')
}
