import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import OrdersManager from './_components/orders-manager'
import { CORE_API_URL } from '@/lib/runtime-env'

type Variation = { id: string; price: number | null; attributes: Record<string, string> | null }
type Product   = { id: string; title: string; product_variations: Variation[] }
type Contact   = { id: string; phone: string; name: string | null }
type OrderItem = { title: string; quantity: number; unit_price: number }
type Order = {
  id: string
  status: string
  total_amount: number
  discount_amount: number | null
  shipping_cost: number | null
  notes: string | null
  created_at: string
  contacts: Contact | Contact[] | null
  order_items: OrderItem[]
}

// Estados persistidos por el backend (VALID_STATUSES en orders.py).
const STATUS_KEYS = [
  'pending', 'pending_payment', 'confirmed', 'processing', 'shipped', 'delivered', 'cancelled',
] as const
const VALID_STATUS_SET = new Set<string>(STATUS_KEYS)

const FORM_SELECT_LIMIT = 1000
// D7 — página server-side. Fija el tope de filas por página y elimina el cap
// client-side de 100 que dejaba inseleccionables los pedidos antiguos.
const ORDERS_PER_PAGE = 20

export default async function OrdersPage(props: {
  searchParams: Promise<{
    status?: string; q?: string; page?: string; contact_id?: string; id?: string
  }>
}) {
  const sp = await props.searchParams

  // D8 — deep-link por id: redirige a la vista de detalle (consumidor natural
  // de los enlaces desde Reclamos / Contactos).
  if (sp.id) redirect(`/dashboard/orders/${sp.id}`)

  const { getCachedUser, getCachedTenantMeta } = await import('@/utils/supabase/cached-user')
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  // D1 (RBAC) — operator opera el módulo (crear/avanzar). Dinero irreversible
  // (cancelar, link de pago, guía) queda en owner/manager.
  const canWrite = ['owner', 'manager', 'operator'].includes(role)
  const canManageMoney = ['owner', 'manager'].includes(role)
  const supabase = await createClient()

  // ── Parámetros de filtro/paginación ───────────────────────────────────────
  const status = sp.status && VALID_STATUS_SET.has(sp.status) ? sp.status : 'all'
  const q = (sp.q ?? '').replace(/[%_]/g, '').trim().slice(0, 60)
  const contactId = sp.contact_id || null
  const parsedPage = parseInt(sp.page ?? '1', 10)
  const page = Number.isFinite(parsedPage) && parsedPage > 0 ? parsedPage : 1
  const offset = (page - 1) * ORDERS_PER_PAGE

  let orders: Order[] = []
  let products: Product[] = []
  let contacts: Contact[] = []
  let counts: Record<string, number> = {}
  let filteredCount = 0
  let contactName: string | null = null
  let loadError: string | null = null

  if (tenantId) {
    // D7 — búsqueda server-side por contacto (nombre/teléfono). Resolvemos los
    // contact_id que coinciden y filtramos pedidos por ese conjunto. Dos ilike
    // en lugar de .or() para seguir el patrón del repo (audit/page.tsx).
    let searchContactIds: string[] | null = null
    if (q) {
      const [byName, byPhone] = await Promise.all([
        supabase.from('contacts').select('id').eq('tenant_id', tenantId).ilike('name', `%${q}%`).limit(200),
        supabase.from('contacts').select('id').eq('tenant_id', tenantId).ilike('phone', `%${q}%`).limit(200),
      ])
      searchContactIds = Array.from(new Set([
        ...((byName.data as { id: string }[] | null) ?? []),
        ...((byPhone.data as { id: string }[] | null) ?? []),
      ].map(r => r.id)))
    }

    // Listado paginado (count exacto para la barra de paginación).
    let listQuery = supabase
      .from('orders')
      .select(
        'id, status, total_amount, discount_amount, shipping_cost, notes, created_at, payment_method, contacts(id, phone, name), order_items(title, quantity, unit_price)',
        { count: 'exact' },
      )
      .eq('tenant_id', tenantId)
      .order('created_at', { ascending: false })
      .range(offset, offset + ORDERS_PER_PAGE - 1)

    if (status !== 'all') listQuery = listQuery.eq('status', status)
    if (contactId) listQuery = listQuery.eq('contact_id', contactId)
    // Si hay búsqueda sin coincidencias de contacto → resultado vacío inmediato.
    if (searchContactIds !== null) {
      if (searchContactIds.length === 0) listQuery = listQuery.eq('contact_id', '00000000-0000-0000-0000-000000000000')
      else listQuery = listQuery.in('contact_id', searchContactIds)
    }

    // Conteos por estado (badges). Lente persistente = tenant + contacto; el
    // texto de búsqueda no afecta las pestañas (reflejan la distribución real).
    const countBase = () => {
      let cq = supabase.from('orders').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId)
      if (contactId) cq = cq.eq('contact_id', contactId)
      return cq
    }

    const [listRes, productsRes, contactsRes, allCountRes, ...statusCountRes] = await Promise.all([
      listQuery,
      supabase
        .from('products')
        .select('id, title, product_variations(id, price, attributes)')
        .eq('tenant_id', tenantId)
        .eq('status', 'active')
        .order('title')
        .limit(FORM_SELECT_LIMIT),
      supabase
        .from('contacts')
        .select('id, phone, name')
        .eq('tenant_id', tenantId)
        .order('name')
        .limit(FORM_SELECT_LIMIT),
      countBase(),
      ...STATUS_KEYS.map(s => countBase().eq('status', s)),
    ])

    if (listRes.error) {
      loadError = 'No se pudieron cargar los pedidos. Reintenta en unos segundos.'
    }

    counts = { all: allCountRes.count ?? 0 }
    STATUS_KEYS.forEach((s, i) => { counts[s] = statusCountRes[i]?.count ?? 0 })

    orders = (listRes.data as unknown as Order[]) || []
    filteredCount = listRes.count ?? 0
    products = (productsRes.data as Product[]) || []
    contacts = (contactsRes.data as Contact[]) || []

    // D9 — nombre del contacto para el banner de filtro.
    if (contactId) {
      const { data: c } = await supabase
        .from('contacts').select('name, phone').eq('id', contactId).eq('tenant_id', tenantId).maybeSingle()
      if (c) contactName = c.name || c.phone
    }
  }

  const totalPages = Math.max(1, Math.ceil(filteredCount / ORDERS_PER_PAGE))

  // ── Server Actions ────────────────────────────────────────────────────────
  async function updateOrderStatus(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    // D1: operator puede avanzar estado / editar; cancelar (refund) es owner/manager.
    if (!m.tenant_id || !['owner', 'manager', 'operator'].includes(m.role ?? '')) {
      throw new Error('No tienes permisos para actualizar el pedido.')
    }

    const orderId = formData.get('order_id') as string
    const isCancel = formData.get('cancel') === 'true'
    const nextStatus = formData.get('next_status') as string

    if (isCancel && !['owner', 'manager'].includes(m.role ?? '')) {
      throw new Error('Solo owner o manager pueden cancelar un pedido (implica reembolso).')
    }

    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) throw new Error('Tu sesión expiró. Vuelve a iniciar sesión.')

    const targetStatus = isCancel ? 'cancelled' : nextStatus
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${CORE_API_URL}/api/v1/orders/${orderId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ status: targetStatus }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) throw new Error((await res.text()).slice(0, 200) || `Error ${res.status}`)
    } catch (e) {
      throw e instanceof Error ? e : new Error('No se pudo actualizar el pedido (timeout o red)')
    }

    revalidatePath('/dashboard/orders')
  }

  // Generar guía Aveonline manualmente (COD). owner + manager (genera costos).
  async function generateShippingGuide(
    formData: FormData,
  ): Promise<{ ok: boolean; message?: string; tracking?: string }> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, message: 'Sin permisos para generar guías.' }
    }
    const orderId = formData.get('order_id') as string
    if (!orderId) return { ok: false, message: 'order_id requerido' }

    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return { ok: false, message: 'Sesión expirada' }

    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 40000)
      const resp = await fetch(
        `${CORE_API_URL}/api/v1/orders/${orderId}/generate-shipping-guide`,
        {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` },
          signal: ctrl.signal,
        },
      )
      clearTimeout(timeout)
      const data = await resp.json().catch(() => ({}))
      if (!resp.ok) {
        return {
          ok: false,
          message: (data as { detail?: string }).detail || `HTTP ${resp.status}`,
        }
      }
      const dataTyped = data as {
        ok?: boolean
        idempotent?: boolean
        shipment?: { tracking_number?: string }
        error?: string
      }
      if (!dataTyped.ok) {
        return {
          ok: false,
          message: dataTyped.error || 'No se pudo generar la guía.',
        }
      }
      revalidatePath('/dashboard/orders')
      return {
        ok: true,
        tracking: dataTyped.shipment?.tracking_number,
        message: dataTyped.idempotent
          ? `Guía ya existía: ${dataTyped.shipment?.tracking_number}`
          : `Guía generada: ${dataTyped.shipment?.tracking_number}`,
      }
    } catch (err) {
      return {
        ok: false,
        message: err instanceof Error ? err.message : 'Error de red',
      }
    }
  }

  // ── UI ────────────────────────────────────────────────────────────────────
  return (
    <OrdersManager
      initialOrders={orders}
      products={products}
      contacts={contacts}
      role={role}
      canWrite={canWrite}
      canManageMoney={canManageMoney}
      counts={counts}
      filteredCount={filteredCount}
      currentPage={page}
      totalPages={totalPages}
      perPage={ORDERS_PER_PAGE}
      status={status}
      query={q}
      contactId={contactId}
      contactName={contactName}
      loadError={loadError}
      updateStatusAction={updateOrderStatus}
      generateShippingGuideAction={generateShippingGuide}
    />
  )
}
