'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { CORE_API_URL } from '@/lib/runtime-env'

// ── Auth helper compartido ────────────────────────────────────────────────────
// Verifica que el usuario autenticado sea owner del tenant.
// Si no tiene permiso, redirige a /dashboard — nunca retorna null silenciosamente.

async function getOwnerTenantId(): Promise<string> {
  const sb = await createClient()
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

// F-doc (Fase 6): las server actions devuelven ActionResult en vez de throw (Next.js
// enmascara el message de un throw en prod). El wrapper client <ActionForm> lee res.error.
// NOTA: getOwnerTenantId() usa redirect() (throw NEXT_REDIRECT) — eso DEBE propagar; por
// eso updateTenant retorna ActionResult (no lanza) y las actions NO envuelven en try/catch.
export type ActionResult = { ok: boolean; error?: string }

// F6 — fuente única auditada: las mutaciones del tenant enrutan por el endpoint
// PATCH /api/v1/settings/tenant (Pydantic + @audit_log + rate-limit) en vez de
// escribir directo a Supabase. El endpoint aplica semántica PATCH (exclude_unset):
// un campo enviado como null LIMPIA, un campo omitido queda intacto. El caller ya
// validó owner vía getOwnerTenantId; aquí adjuntamos el access_token de sesión.
// El param tenantId se conserva por firma (el tenant lo deriva el backend del JWT).
async function updateTenant(_tenantId: string, data: Record<string, unknown>): Promise<ActionResult> {
  const sb = await createClient()
  const { data: { session } } = await sb.auth.getSession()
  if (!session?.access_token) {
    return { ok: false, error: 'Tu sesión expiró. Vuelve a iniciar sesión e inténtalo de nuevo.' }
  }
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/settings/tenant`, {
      method: 'PATCH',
      headers: {
        'Authorization': `Bearer ${session.access_token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
      cache: 'no-store',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
      // F6 observabilidad: server actions no imprimen nada por defecto en Render.
      console.error('[settings.updateTenant] http=%s detail=%s', res.status, err.detail)
      return { ok: false, error: `No se pudo guardar: ${err.detail || `Error ${res.status}`}` }
    }
    return { ok: true }
  } catch (e) {
    console.error('[settings.updateTenant] excepción:', e)
    return { ok: false, error: e instanceof Error ? e.message : 'Error de red al guardar' }
  }
}

// ── Validadores server-side ────────────────────────────────────────────────────
// El frontend NO es seguridad (principio 2): el pattern HTML es UX, la validación
// real vive aquí. Estos datos alimentan guías de envío + prompt del bot.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/
const CO_CEL_RE = /^3\d{9}$/ // celular Colombia: 10 dígitos, empieza en 3

// ── Acciones exportadas ───────────────────────────────────────────────────────

export async function saveTenant(formData: FormData): Promise<ActionResult> {
  const tenantId = await getOwnerTenantId()

  const name    = (formData.get('name') as string)?.trim() || ''
  const email   = (formData.get('email_contacto') as string)?.trim() || ''
  const celular = (formData.get('telefono_contacto') as string)?.trim() || ''

  if (!name) return { ok: false, error: 'El nombre del negocio es obligatorio.' }
  if (email && !EMAIL_RE.test(email)) {
    return { ok: false, error: 'El email de contacto no tiene un formato válido (ej: contacto@minegocio.com).' }
  }
  if (celular && !CO_CEL_RE.test(celular)) {
    return { ok: false, error: 'El celular debe tener 10 dígitos y empezar por 3 (ej: 3121234567).' }
  }

  const res = await updateTenant(tenantId, {
    name,
    nit:               (formData.get('nit') as string)?.trim()  || null,
    email_contacto:    email || null,
    telefono_contacto: celular || null,
  })
  if (res.ok) revalidateSettings()
  return res
}

export async function saveFilosofia(formData: FormData): Promise<ActionResult> {
  const tenantId = await getOwnerTenantId()
  const res = await updateTenant(tenantId, {
    tono_comunicacion: (formData.get('tono_comunicacion') as string) || 'amigable',
    mision:            (formData.get('mision') as string)?.trim() || null,
    vision:            (formData.get('vision') as string)?.trim() || null,
    valores:           (formData.get('valores') as string)?.trim() || null,
    // business_pitch: el bot lo inyecta como 1ª línea de identidad ("Eres {agente}, {pitch}").
    // Antes solo se podía setear por SQL; ahora editable aquí (gap de coherencia bot↔web).
    business_pitch:    (formData.get('business_pitch') as string)?.trim() || null,
  })
  if (res.ok) revalidatePath('/dashboard/settings')
  return res
}

export async function saveHorarioAsesor(formData: FormData): Promise<ActionResult> {
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

  // F6: validar coherencia del horario ANTES de persistir. Antes se aceptaba
  // close < open (horario imposible) y se anulaba el schedule en silencio si
  // faltaban días — el operador creía tener asesor configurado y no lo tenía.
  if (open && close && open >= close) {
    return { ok: false, error: 'La hora de cierre debe ser posterior a la de apertura.' }
  }
  const partialSchedule = (days.length > 0 || !!open || !!close)
  const completeSchedule = days.length > 0 && !!open && !!close
  if (partialSchedule && !completeSchedule) {
    return { ok: false, error: 'Para definir el horario de asesor selecciona al menos un día y las horas de apertura y cierre. Déjalos todos vacíos si no atiendes con asesor humano.' }
  }
  const support_schedule = completeSchedule ? { days, open, close } : null
  const res = await updateTenant(tenantId, { support_schedule, after_hours_message, escalation_role })
  if (res.ok) revalidatePath('/dashboard/settings')
  return res
}


export async function savePresenciaDigital(formData: FormData): Promise<ActionResult> {
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

  const res = await updateTenant(tenantId, { store_type, store_locations, social_links })
  if (res.ok) revalidatePath('/dashboard/settings')
  return res
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
    const sb = await createClient()

    const codEnabled = formData.get('cod_enabled') === '1'
    const onlineEnabled = formData.get('online_wompi_enabled') === '1'

    // Validación: al menos uno habilitado.
    if (!codEnabled && !onlineEnabled) {
      return {
        ok: false,
        error: 'Debes habilitar al menos un método de pago.',
      }
    }

    // display_label / notes: el bot los inyecta al prompt (tenant_payment_methods.py).
    // Antes no eran editables desde la UI — el tenant no podía personalizar cómo el
    // bot nombra/explica cada método. null los deja en el default del prompt.
    const clean = (v: FormDataEntryValue | null, max: number) => {
      const s = (v as string | null)?.trim()
      return s ? s.slice(0, max) : null
    }
    const codLabel   = clean(formData.get('cod_display_label'), 60)
    const codNotes   = clean(formData.get('cod_notes'), 240)
    const onlineLabel = clean(formData.get('online_wompi_display_label'), 60)
    const onlineNotes = clean(formData.get('online_wompi_notes'), 240)

    // Upsert per método. UNIQUE(tenant_id, method) en tabla.
    const rows = [
      { tenant_id: tenantId, method: 'cod', enabled: codEnabled, display_label: codLabel, notes: codNotes },
      { tenant_id: tenantId, method: 'online_wompi', enabled: onlineEnabled, display_label: onlineLabel, notes: onlineNotes },
    ]
    const { error } = await sb
      .from('tenant_payment_methods')
      .upsert(rows, { onConflict: 'tenant_id,method' })

    if (error) {
      console.error('[settings.savePaymentMethods] tenant=%s error=%s', tenantId, error.message)
      return { ok: false, error: `Error guardando: ${error.message}` }
    }
    revalidatePath('/dashboard/settings')
    return { ok: true }
  } catch (e) {
    console.error('[settings.savePaymentMethods] excepción:', e)
    return {
      ok: false,
      error: e instanceof Error ? e.message : 'Error desconocido',
    }
  }
}

export async function saveShippingOrigin(formData: FormData): Promise<ActionResult> {
  const tenantId = await getOwnerTenantId()

  const fields = ['name', 'company', 'street', 'city', 'state', 'postal_code', 'country', 'phone', 'dane_code']
  const origin: Record<string, string> = {}
  for (const f of fields) {
    const val = (formData.get(`origin_${f}`) as string)?.trim()
    if (val) origin[f] = val
  }
  // Mantener postal_code y dane_code alineados para la cotización Aveonline (CO, DANE 5 dígitos)
  if (origin.dane_code && !origin.postal_code) origin.postal_code = origin.dane_code
  if (origin.postal_code && !origin.dane_code)  origin.dane_code  = origin.postal_code

  const res = await updateTenant(tenantId, { shipping_origin: origin })
  if (res.ok) revalidatePath('/dashboard/settings')
  return res
}
