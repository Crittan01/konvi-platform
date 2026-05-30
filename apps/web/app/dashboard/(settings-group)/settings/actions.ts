'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'

// ── Auth helper compartido ────────────────────────────────────────────────────
// Verifica que el usuario autenticado sea owner del tenant.
// Si no tiene permiso, redirige a /dashboard — nunca retorna null silenciosamente.

async function getOwnerTenantId(): Promise<string> {
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const m = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id || m.role !== 'owner') {
    redirect('/dashboard')
  }
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
  await updateTenant(tenantId, {
    name:              (formData.get('name') as string)?.trim() || undefined,
    nit:               (formData.get('nit') as string)?.trim()  || null,
    email_contacto:    (formData.get('email_contacto') as string)?.trim() || null,
    telefono_contacto: (formData.get('telefono_contacto') as string)?.trim() || null,
  })
  revalidateSettings()
}

export async function saveFilosofia(formData: FormData) {
  const tenantId = await getOwnerTenantId()
  await updateTenant(tenantId, {
    tono_comunicacion: (formData.get('tono_comunicacion') as string) || 'amigable',
    mision:            (formData.get('mision') as string)?.trim() || null,
    vision:            (formData.get('vision') as string)?.trim() || null,
    valores:           (formData.get('valores') as string)?.trim() || null,
  })
  revalidatePath('/dashboard/settings')
}

export async function saveHorarioAsesor(formData: FormData) {
  const tenantId = await getOwnerTenantId()
  const daysRaw = formData.getAll('support_days') as string[]
  const days = daysRaw.map(Number).filter(d => d >= 1 && d <= 7)
  const open  = (formData.get('support_open')  as string)?.trim()
  const close = (formData.get('support_close') as string)?.trim()
  const after_hours_message = (formData.get('after_hours_message') as string)?.trim() || null
  // Rev. 68 — escalation_role configurable por tenant (default 'asesor').
  const ALLOWED_ROLES = new Set(['asesor', 'especialista', 'consultor', 'agente'])
  const raw_role = (formData.get('escalation_role') as string)?.trim() || 'asesor'
  const escalation_role = ALLOWED_ROLES.has(raw_role) ? raw_role : 'asesor'
  const support_schedule = days.length && open && close ? { days, open, close } : null
  await updateTenant(tenantId, { support_schedule, after_hours_message, escalation_role })
  revalidatePath('/dashboard/settings')
}


export async function savePresenciaDigital(formData: FormData) {
  const tenantId = await getOwnerTenantId()

  const store_type = (formData.get('store_type') as string) || 'fisica'

  let store_locations: Record<string, unknown>[] = []
  try {
    const raw = formData.get('store_locations') as string
    if (raw) store_locations = JSON.parse(raw)
  } catch { /* keep empty */ }

  // Rev. 71 — Sanitización defensiva de is_primary:
  //  · Coerce a boolean (evita "true"/"false" strings).
  //  · Garantiza exactamente UNA sede con is_primary=true. Si ninguna lo es, la primera hereda.
  if (Array.isArray(store_locations) && store_locations.length > 0) {
    let primaryAssigned = false
    store_locations = store_locations.map((loc) => {
      const isPrimary = loc?.is_primary === true || loc?.is_primary === 'true'
      if (isPrimary && !primaryAssigned) {
        primaryAssigned = true
        return { ...loc, is_primary: true }
      }
      return { ...loc, is_primary: false }
    })
    if (!primaryAssigned) {
      store_locations[0] = { ...store_locations[0], is_primary: true }
    }
  }

  const social_links: Record<string, string> = {}
  for (const red of ['instagram', 'facebook', 'tiktok', 'youtube', 'website']) {
    const val = (formData.get(`social_${red}`) as string)?.trim()
    if (val) social_links[red] = val
  }

  await updateTenant(tenantId, { store_type, store_locations, social_links })
  revalidatePath('/dashboard/settings')
}

/**
 * Rev. 108 modular — Métodos de pago per-tenant (tenant_payment_methods).
 * Founder feedback 2026-05-27: "este sea totalmente modular".
 *
 * Persiste en tabla `tenant_payment_methods` (whitelist constrained:
 * 'cod', 'online_wompi'). Upsert per método. Server action invocada
 * desde apps/web/app/dashboard/(settings-group)/settings/payment-methods-form.tsx.
 */
export async function savePaymentMethods(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const tenantId = await getOwnerTenantId()
    const sb = createClient()

    const codEnabled = formData.get('cod_enabled') === '1'
    const onlineEnabled = formData.get('online_wompi_enabled') === '1'

    // Validación: al menos uno habilitado.
    if (!codEnabled && !onlineEnabled) {
      return {
        ok: false,
        error: 'Debes habilitar al menos un método de pago.',
      }
    }

    // Upsert per método. UNIQUE(tenant_id, method) en tabla.
    const rows = [
      { tenant_id: tenantId, method: 'cod', enabled: codEnabled },
      { tenant_id: tenantId, method: 'online_wompi', enabled: onlineEnabled },
    ]
    const { error } = await sb
      .from('tenant_payment_methods')
      .upsert(rows, { onConflict: 'tenant_id,method' })

    if (error) {
      return { ok: false, error: `Error guardando: ${error.message}` }
    }
    revalidatePath('/dashboard/settings')
    return { ok: true }
  } catch (e) {
    return {
      ok: false,
      error: e instanceof Error ? e.message : 'Error desconocido',
    }
  }
}

export async function saveShippingOrigin(formData: FormData) {
  const tenantId = await getOwnerTenantId()

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
