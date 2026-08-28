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
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { CORE_API_URL } from '@/lib/runtime-env'
import { revalidatePath } from 'next/cache'
import { Tag, AlertTriangle } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import PromotionsManager from './_components/promotions-manager'
import { bogotaLocalToUTC } from '@/lib/date-window'

/**
 * fixed_amount: la UI captura PESOS pero DB/engine/bot usan CENTAVOS (migración
 * 20260515000000). percent (0-100) y free_shipping se guardan crudos.
 */
function couponDiscountToCents(discount_type: DiscountType, raw: number): number {
  return discount_type === 'fixed_amount' ? raw * 100 : raw
}

export const metadata = {
  title: 'Promociones',
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
  is_customer_visible: boolean  // F4.2 — si false, el bot no lo anuncia (solo aplica por código)
  created_at: string
  updated_at: string
  /**
   * True si existe al menos una fila en `coupon_redemptions` referenciando
   * este cupón (cualquier status: applied/consumed/revoked). Sirve como
   * gate para hard-delete: si has_historical_redemptions=true, NO
   * permitimos eliminar (preservar audit Habeas Data).
   */
  has_historical_redemptions: boolean
  /**
   * Total de filas en `coupon_redemptions` para este cupón (todos los
   * status). Útil para mostrar al owner un contador de "histórico" en
   * la tabla, distinto de `redemptions_count` que solo cuenta consumed
   * (orden APPROVED). Diferenciar evita confusión cuando el contador
   * de uso oficial es 0 pero hay aplicaciones revocadas en historial.
   */
  total_historical_redemptions: number
}

/**
 * Fila de `coupon_redemptions` para la vista de auditoría de redenciones
 * (F2 — sheet de solo-lectura al click en el contador de usos). Columnas
 * mínimas que responden "¿qué órdenes usaron este cupón y por cuánto?":
 * estado FSM, monto aplicado (snapshot histórico), orden vinculada y las
 * marcas de tiempo del ciclo applied → consumed / revoked.
 */
export type RedemptionStatus = 'applied' | 'consumed' | 'revoked'

export type Redemption = {
  id: string
  order_id: string | null
  discount_applied_cents: number
  status: RedemptionStatus
  applied_at: string
  consumed_at: string | null
  revoked_at: string | null
  revoked_reason: string | null
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

// F2.2: escrituras de cupones vía API (restaura @audit_log + RBAC server-side). La validación
// client-side (validateCouponInput) queda como fast-fail; la API re-valida y es la autoridad.
async function writeCouponApi(
  method: string, path: string, token: string, body?: unknown,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const ctrl = new AbortController()
    const timeout = setTimeout(() => ctrl.abort(), 15000)
    const res = await fetch(`${CORE_API_URL}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    })
    clearTimeout(timeout)
    if (!res.ok) {
      const j = await res.json().catch(() => null)
      const d = (j as { detail?: unknown } | null)?.detail
      const msg = typeof d === 'string'
        ? d
        : Array.isArray(d) ? ((d[0] as { msg?: string })?.msg ?? 'Error de validación') : `Error ${res.status}`
      return { ok: false, error: msg }
    }
    return { ok: true }
  } catch {
    return { ok: false, error: 'Error de red. Intenta de nuevo.' }
  }
}

async function createCouponAction(formData: FormData): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos para crear cupones.' }
  }

  const code = ((formData.get('code') as string) || '').trim().toUpperCase()
  const description = ((formData.get('description') as string) || '').trim() || null
  const discount_type = (formData.get('discount_type') as DiscountType) || 'percent'
  const discount_value = couponDiscountToCents(
    discount_type, parseInt(((formData.get('discount_value') as string) || '0'), 10))
  const min_subtotal_pesos = parseInt(((formData.get('min_subtotal_pesos') as string) || '0'), 10)
  const min_subtotal_cents = min_subtotal_pesos * 100
  const max_red_raw = ((formData.get('max_redemptions') as string) || '').trim()
  const max_redemptions = max_red_raw ? parseInt(max_red_raw, 10) : null
  // datetime-local = hora Colombia → UTC (antes se persistía crudo = corrido 5h)
  const valid_from = bogotaLocalToUTC(((formData.get('valid_from') as string) || '').trim())
  const valid_until = bogotaLocalToUTC(((formData.get('valid_until') as string) || '').trim())

  const validationError = validateCouponInput({
    code, discount_type, discount_value, min_subtotal_cents,
    max_redemptions, valid_from, valid_until,
  })
  if (validationError) return { ok: false, error: validationError }

  const { data: { session } } = await sb.auth.getSession()
  const token = session?.access_token
  if (!token) return { ok: false, error: 'Sesión inválida.' }

  // POST vía API → audita la creación + RBAC server-side. is_active y created_by los setea el API.
  const result = await writeCouponApi('POST', '/api/v1/coupons', token, {
    code, description, discount_type, discount_value, min_subtotal_cents,
    max_redemptions, valid_from, valid_until,
    is_customer_visible: formData.get('is_customer_visible') === 'on',  // F4.2: anunciable por el bot
  })
  if (!result.ok) return result

  revalidatePath('/dashboard/promotions')
  return { ok: true }
}

async function updateCouponAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = await createClient()
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
  const discount_type = (formData.get('discount_type') as DiscountType) || 'percent'
  const discount_value = couponDiscountToCents(
    discount_type, parseInt(((formData.get('discount_value') as string) || '0'), 10))
  const min_subtotal_pesos = parseInt(((formData.get('min_subtotal_pesos') as string) || '0'), 10)
  const min_subtotal_cents = min_subtotal_pesos * 100
  const max_red_raw = ((formData.get('max_redemptions') as string) || '').trim()
  const max_redemptions = max_red_raw ? parseInt(max_red_raw, 10) : null
  const valid_from = bogotaLocalToUTC(((formData.get('valid_from') as string) || '').trim())
  const valid_until = bogotaLocalToUTC(((formData.get('valid_until') as string) || '').trim())

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

  const { data: { session } } = await sb.auth.getSession()
  const token = session?.access_token
  if (!token) return { ok: false, error: 'Sesión inválida.' }

  // PATCH vía API → audita la edición. `code` no se envía (inmutable). description=null se limpia.
  const result = await writeCouponApi('PATCH', `/api/v1/coupons/${id}`, token, {
    description, discount_type, discount_value, min_subtotal_cents,
    max_redemptions, valid_from, valid_until,
    is_customer_visible: formData.get('is_customer_visible') === 'on',  // F4.2
  })
  if (!result.ok) return result

  revalidatePath('/dashboard/promotions')
  return { ok: true }
}

async function toggleCouponActiveAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos.' }
  }

  const id = ((formData.get('id') as string) || '').trim()
  const targetActive = formData.get('is_active') === 'true'
  if (!id) return { ok: false, error: 'ID requerido.' }

  const { data: { session } } = await sb.auth.getSession()
  const token = session?.access_token
  if (!token) return { ok: false, error: 'Sesión inválida.' }

  // Activar/desactivar vía API (auditado). El PATCH parcial solo toca is_active.
  const result = await writeCouponApi('PATCH', `/api/v1/coupons/${id}`, token, { is_active: targetActive })
  if (!result.ok) return result

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
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos.' }
  }

  const id = ((formData.get('id') as string) || '').trim()
  if (!id) return { ok: false, error: 'ID requerido.' }

  const { data: { session } } = await sb.auth.getSession()
  const token = session?.access_token
  if (!token) return { ok: false, error: 'Sesión inválida.' }

  // DELETE vía API: el backend re-verifica el conteo de redenciones (anti-race) y rechaza con 409 +
  // mensaje Habeas Data si el cupón ya se usó, o lo elimina y audita si nunca tuvo redenciones.
  const result = await writeCouponApi('DELETE', `/api/v1/coupons/${id}`, token)
  if (!result.ok) return result

  revalidatePath('/dashboard/promotions')
  return { ok: true }
}

/**
 * Lee las redenciones de UN cupón (solo-lectura, auditoría). RLS-scoped:
 * usa el cliente Supabase del usuario (JWT) + filtro explícito por
 * `tenant_id` (ADR-0025) → doble defensa contra fugas cross-tenant. No pasa
 * por la API porque es lectura pura (mismo patrón que la carga de cupones).
 *
 * Degrada con seguridad: cualquier fallo devuelve `{ ok:false, error }` que
 * el sheet muestra con opción de reintento; nunca lanza a la UI.
 */
async function fetchRedemptionsAction(
  couponId: string,
): Promise<{ ok: boolean; rows?: Redemption[]; error?: string }> {
  'use server'
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string }
  if (!meta.tenant_id) return { ok: false, error: 'Sesión inválida.' }

  const id = (couponId || '').trim()
  if (!id) return { ok: false, error: 'ID de cupón requerido.' }

  const { data, error } = await sb
    .from('coupon_redemptions')
    .select(
      'id, order_id, discount_applied_cents, status, ' +
      'applied_at, consumed_at, revoked_at, revoked_reason',
    )
    .eq('coupon_id', id)
    .eq('tenant_id', meta.tenant_id)
    .order('applied_at', { ascending: false })
    .limit(500)

  if (error) {
    return { ok: false, error: 'No pudimos cargar las redenciones. Reintenta en un momento.' }
  }
  return { ok: true, rows: (data ?? []) as unknown as Redemption[] }
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default async function PromotionsPage() {
  // Sem 5 perf: cached deduplicates auth.getUser con DashboardLayout.
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = await createClient()

  let coupons: Coupon[] = []
  // Error de carga surfaceado a la UI: sin esto un fallo de Supabase caía en
  // el empty-state ("Aún no tienes cupones") — un falso-0 que oculta el
  // incidente. La UI distingue error (con reintento) de lista vacía real.
  let loadError: string | null = null
  if (tenantId) {
    const { data, error } = await supabase
      .from('coupons')
      .select(
        'id, code, description, discount_type, discount_value, ' +
        'min_subtotal_cents, max_redemptions, redemptions_count, ' +
        'valid_from, valid_until, is_active, is_customer_visible, created_at, updated_at'
      )
      .eq('tenant_id', tenantId)
      .order('is_active', { ascending: false })
      .order('created_at', { ascending: false })

    if (error) {
      loadError = 'No pudimos cargar los cupones. Reintenta en un momento.'
    }

    const couponsRaw = Array.isArray(data)
      ? (data as unknown as Omit<Coupon, 'has_historical_redemptions'>[])
      : []

    // Conteo de redenciones históricas (cualquier status) per cupón.
    // Antes: 1 query `.select('coupon_id')` sin count → supabase-js capa a
    // 1000 filas por default y subcontaba en silencio para cupones populares.
    // Ahora: un COUNT exacto (head:true, no transfiere filas) por cupón, en
    // paralelo. head+count devuelve el total real sin el cap de 1000.
    const histCounts = new Map<string, number>()
    if (couponsRaw.length > 0) {
      const results = await Promise.all(
        couponsRaw.map(async (c) => {
          const { count, error: cErr } = await supabase
            .from('coupon_redemptions')
            .select('id', { count: 'exact', head: true })
            .eq('coupon_id', c.id)
            .eq('tenant_id', tenantId)
          return { id: c.id, count: count ?? 0, err: cErr }
        })
      )
      for (const r of results) {
        if (r.err && !loadError) {
          loadError = 'No pudimos cargar el historial de redenciones. Reintenta en un momento.'
        }
        histCounts.set(r.id, r.count)
      }
    }

    coupons = couponsRaw.map((c) => {
      const hist = histCounts.get(c.id) ?? 0
      return {
        ...c,
        has_historical_redemptions: hist > 0,
        total_historical_redemptions: hist,
      }
    }) as Coupon[]
  }

  const activeCount = coupons.filter(c => c.is_active).length

  return (
    <div className="space-y-6">
      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={Tag}
        title="Promociones"
        description={
          <>
            {coupons.length} cupones totales · {activeCount} activos.
            Los clientes los aplican vía WhatsApp con &quot;tengo el cupón XXX&quot;.
          </>
        }
      />

      {!canWrite && (
        <div className="rounded-md border border-amber-700/40 bg-amber-700/5 p-3 text-sm text-amber-900">
          <AlertTriangle className="inline h-4 w-4 mr-1" />
          Solo el rol Administrador o Supervisor puede crear/editar cupones.
          Tú (operador) puedes ver el catálogo en modo lectura.
        </div>
      )}

      <PromotionsManager
        initialCoupons={coupons}
        loadError={loadError}
        canWrite={canWrite}
        createCouponAction={createCouponAction}
        updateCouponAction={updateCouponAction}
        toggleCouponActiveAction={toggleCouponActiveAction}
        deleteCouponAction={deleteCouponAction}
        fetchRedemptionsAction={fetchRedemptionsAction}
      />
    </div>
  )
}
