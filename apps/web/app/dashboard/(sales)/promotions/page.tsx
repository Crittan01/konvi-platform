/**
 * Promociones — UI Tenant Console (Sem 6 I.2.8 / ADR-0015 D10).
 *
 * Página para que tenants admin (owner / manager) gestionen su catálogo
 * de cupones: crear, editar, desactivar (NUNCA hard delete — preserva
 * `coupon_redemptions` audit Habeas Data).
 *
 * Observa stats per cupón: `redemptions_count` actual vs `max_redemptions`.
 *
 * Routing: /dashboard/promotions (grupo Ventas en sidebar).
 */
import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Tag, AlertTriangle } from 'lucide-react'
import PromotionsManager from './_components/promotions-manager'

export const metadata = {
  title: 'Promociones — Commerce Ops',
  description: 'Gestión de cupones y descuentos del tenant.',
}

// ─── Tipos ───────────────────────────────────────────────────────────────────

export type DiscountType = 'percent' | 'fixed_amount' | 'free_shipping'

export type Coupon = {
  id: string
  code: string
  description: string | null
  discount_type: DiscountType
  discount_value: number
  min_subtotal_cents: number
  max_redemptions: number | null
  redemptions_count: number
  valid_from: string | null
  valid_until: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  /**
   * True si existe al menos una fila en `coupon_redemptions` referenciando
   * este cupón (cualquier status: applied/consumed/revoked). Sirve como
   * gate para hard-delete: si has_historical_redemptions=true, NO
   * permitimos eliminar (preservar audit Habeas Data).
   */
  has_historical_redemptions: boolean
}

const VALID_DISCOUNT_TYPES = new Set<DiscountType>([
  'percent', 'fixed_amount', 'free_shipping',
])

// ─── Validators backend (espejan DB CHECK constraints) ───────────────────────

function validateCouponInput(input: {
  code: string
  discount_type: DiscountType
  discount_value: number
  min_subtotal_cents: number
  max_redemptions: number | null
  valid_from: string | null
  valid_until: string | null
}): string | null {
  if (!input.code.match(/^[A-Z0-9_-]{3,30}$/)) {
    return 'Código debe tener 3-30 caracteres mayúsculas/dígitos/-/_'
  }
  if (!VALID_DISCOUNT_TYPES.has(input.discount_type)) {
    return 'Tipo de descuento inválido.'
  }
  if (input.discount_value < 0) {
    return 'Valor del descuento no puede ser negativo.'
  }
  if (input.discount_type === 'percent' && input.discount_value > 100) {
    return 'Porcentaje no puede ser mayor a 100.'
  }
  if (input.min_subtotal_cents < 0) {
    return 'Mínimo de subtotal no puede ser negativo.'
  }
  if (input.max_redemptions !== null && input.max_redemptions <= 0) {
    return 'Máximo de redenciones debe ser positivo (o vacío para ilimitado).'
  }
  if (input.valid_from && input.valid_until) {
    if (new Date(input.valid_until) <= new Date(input.valid_from)) {
      return 'Fecha de fin debe ser posterior a fecha de inicio.'
    }
  }
  return null
}

// ─── Server actions ──────────────────────────────────────────────────────────

async function createCouponAction(formData: FormData): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos para crear cupones.' }
  }

  const code = ((formData.get('code') as string) || '').trim().toUpperCase()
  const description = ((formData.get('description') as string) || '').trim() || null
  const discount_type = (formData.get('discount_type') as DiscountType) || 'percent'
  const discount_value = parseInt(((formData.get('discount_value') as string) || '0'), 10)
  const min_subtotal_pesos = parseInt(((formData.get('min_subtotal_pesos') as string) || '0'), 10)
  const min_subtotal_cents = min_subtotal_pesos * 100
  const max_red_raw = ((formData.get('max_redemptions') as string) || '').trim()
  const max_redemptions = max_red_raw ? parseInt(max_red_raw, 10) : null
  const valid_from = ((formData.get('valid_from') as string) || '').trim() || null
  const valid_until = ((formData.get('valid_until') as string) || '').trim() || null

  const validationError = validateCouponInput({
    code, discount_type, discount_value, min_subtotal_cents,
    max_redemptions, valid_from, valid_until,
  })
  if (validationError) return { ok: false, error: validationError }

  // INSERT — RLS Tenant Isolation aplica vía JWT app_metadata.
  const { error } = await sb.from('coupons').insert({
    tenant_id: meta.tenant_id,
    code,
    description,
    discount_type,
    discount_value,
    min_subtotal_cents,
    max_redemptions,
    valid_from,
    valid_until,
    is_active: true,
    created_by: user?.id ?? null,
  })

  if (error) {
    if (error.code === '23505') {
      return { ok: false, error: `Ya existe un cupón con código "${code}".` }
    }
    return { ok: false, error: `Error al crear: ${error.message}` }
  }

  revalidatePath('/dashboard/promotions')
  return { ok: true }
}

async function updateCouponAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos.' }
  }

  const id = ((formData.get('id') as string) || '').trim()
  if (!id) return { ok: false, error: 'ID de cupón requerido.' }

  // Editamos solo campos NO impactan auditoría (NO permitimos cambiar
  // `code` post-creación porque coupon_redemptions referencia coupon_id;
  // cambiar code rompe trazabilidad histórica).
  const description = ((formData.get('description') as string) || '').trim() || null
  const discount_value = parseInt(((formData.get('discount_value') as string) || '0'), 10)
  const min_subtotal_pesos = parseInt(((formData.get('min_subtotal_pesos') as string) || '0'), 10)
  const min_subtotal_cents = min_subtotal_pesos * 100
  const max_red_raw = ((formData.get('max_redemptions') as string) || '').trim()
  const max_redemptions = max_red_raw ? parseInt(max_red_raw, 10) : null
  const valid_from = ((formData.get('valid_from') as string) || '').trim() || null
  const valid_until = ((formData.get('valid_until') as string) || '').trim() || null
  const discount_type = (formData.get('discount_type') as DiscountType) || 'percent'

  // Lookup para preservar code original.
  const { data: existing } = await sb
    .from('coupons')
    .select('code, discount_type')
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)
    .single()
  if (!existing) return { ok: false, error: 'Cupón no encontrado.' }

  const validationError = validateCouponInput({
    code: existing.code, discount_type, discount_value,
    min_subtotal_cents, max_redemptions, valid_from, valid_until,
  })
  if (validationError) return { ok: false, error: validationError }

  const { error } = await sb
    .from('coupons')
    .update({
      description,
      discount_type,
      discount_value,
      min_subtotal_cents,
      max_redemptions,
      valid_from,
      valid_until,
    })
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)

  if (error) return { ok: false, error: `Error al actualizar: ${error.message}` }

  revalidatePath('/dashboard/promotions')
  return { ok: true }
}

async function toggleCouponActiveAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos.' }
  }

  const id = ((formData.get('id') as string) || '').trim()
  const targetActive = formData.get('is_active') === 'true'
  if (!id) return { ok: false, error: 'ID requerido.' }

  const { error } = await sb
    .from('coupons')
    .update({ is_active: targetActive })
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)

  if (error) return { ok: false, error: `Error: ${error.message}` }

  revalidatePath('/dashboard/promotions')
  return { ok: true }
}

/**
 * DELETE condicional — Habeas Data audit preservation.
 *
 * Permite hard-delete SOLO cuando el cupón nunca tuvo redenciones
 * (`coupon_redemptions` count = 0 — incluyendo applied/consumed/revoked).
 * Caso legítimo: owner crea cupón con error, lo elimina antes que se use.
 *
 * Si tiene redenciones históricas → rechazo con mensaje claro. El owner
 * debe usar `is_active=false` (toggle) en su lugar para preservar audit.
 *
 * Defensa server-side: re-verificamos count en backend (no confiamos en
 * UI flag). Esto cubre el caso race-condition: UI muestra "delete OK"
 * porque count=0 al renderizar, pero entre el render y el click un
 * cliente WhatsApp aplicó el cupón.
 */
async function deleteCouponAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos.' }
  }

  const id = ((formData.get('id') as string) || '').trim()
  if (!id) return { ok: false, error: 'ID requerido.' }

  // Re-check defensivo en backend.
  const { count, error: countErr } = await sb
    .from('coupon_redemptions')
    .select('id', { count: 'exact', head: true })
    .eq('coupon_id', id)
    .eq('tenant_id', meta.tenant_id)

  if (countErr) {
    return { ok: false, error: `No pude verificar redenciones: ${countErr.message}` }
  }
  if ((count ?? 0) > 0) {
    return {
      ok: false,
      error:
        'Este cupón ya tuvo redenciones (clientes lo aplicaron). ' +
        'No se puede eliminar para preservar auditoría Habeas Data. ' +
        'Usa "Desactivar" en su lugar.',
    }
  }

  // Lookup code para mensaje + audit log de la eliminación.
  const { data: existing } = await sb
    .from('coupons')
    .select('code')
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)
    .single()
  if (!existing) return { ok: false, error: 'Cupón no encontrado.' }

  const { error } = await sb
    .from('coupons')
    .delete()
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)

  if (error) return { ok: false, error: `Error al eliminar: ${error.message}` }

  revalidatePath('/dashboard/promotions')
  return { ok: true }
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default async function PromotionsPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const canWrite = role === 'owner' || role === 'manager'

  let coupons: Coupon[] = []
  if (tenantId) {
    const { data } = await supabase
      .from('coupons')
      .select(
        'id, code, description, discount_type, discount_value, ' +
        'min_subtotal_cents, max_redemptions, redemptions_count, ' +
        'valid_from, valid_until, is_active, created_at, updated_at'
      )
      .eq('tenant_id', tenantId)
      .order('is_active', { ascending: false })
      .order('created_at', { ascending: false })

    const couponsRaw = Array.isArray(data)
      ? (data as unknown as Omit<Coupon, 'has_historical_redemptions'>[])
      : []

    // Lookup batch: cuáles cupones tienen redemptions históricas (cualquier
    // status). Una sola query con DISTINCT evita N round-trips.
    let usedCouponIds = new Set<string>()
    if (couponsRaw.length > 0) {
      const ids = couponsRaw.map((c) => c.id)
      const { data: redData } = await supabase
        .from('coupon_redemptions')
        .select('coupon_id')
        .in('coupon_id', ids)
        .eq('tenant_id', tenantId)
      usedCouponIds = new Set(
        (redData ?? []).map((r) => r.coupon_id as string),
      )
    }

    coupons = couponsRaw.map((c) => ({
      ...c,
      has_historical_redemptions: usedCouponIds.has(c.id),
    })) as Coupon[]
  }

  const activeCount = coupons.filter(c => c.is_active).length

  return (
    <div className="px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex items-center gap-3">
        <Tag className="h-6 w-6 text-emerald-700" />
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            Promociones
          </h1>
          <p className="text-sm text-slate-700">
            Gestiona los cupones de descuento de tu tienda.
            Los clientes los aplican vía WhatsApp con &quot;tengo el cupón XXX&quot;.
          </p>
        </div>
      </div>

      {!canWrite && (
        <div className="mb-4 rounded-md border border-amber-700 bg-amber-50 p-3 text-sm text-amber-900">
          <AlertTriangle className="inline h-4 w-4 mr-1" />
          Solo el rol Administrador o Supervisor puede crear/editar cupones.
          Tú (operador) puedes ver el catálogo en modo lectura.
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-3 text-sm text-slate-700">
        <span><b>{coupons.length}</b> cupones totales</span>
        <span className="text-emerald-700">·</span>
        <span><b>{activeCount}</b> activos</span>
      </div>

      <PromotionsManager
        initialCoupons={coupons}
        canWrite={canWrite}
        createCouponAction={createCouponAction}
        updateCouponAction={updateCouponAction}
        toggleCouponActiveAction={toggleCouponActiveAction}
        deleteCouponAction={deleteCouponAction}
      />
    </div>
  )
}
