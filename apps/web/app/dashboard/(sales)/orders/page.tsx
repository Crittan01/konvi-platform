import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
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
  shipping_cost: number | null
  notes: string | null
  created_at: string
  contacts: Contact | Contact[] | null
  order_items: OrderItem[]
}

export default async function OrdersPage({
  searchParams,
}: {
  searchParams?: { status?: string }
}) {
  // Sem 5 perf: cached.
  const { getCachedUser, getCachedTenantMeta } = await import('@/utils/supabase/cached-user')
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = createClient()

  const filterStatus = searchParams?.status ?? 'all'

  let orders: Order[] = []
  let products: Product[] = []
  let contacts: Contact[] = []
  let counts: Record<string, number> = {}

  if (tenantId) {
    const [ordersRes, productsRes, contactsRes, allOrdersRes] = await Promise.all([
      supabase
        .from('orders')
        .select('id, status, total_amount, shipping_cost, notes, created_at, payment_method, contacts(id, phone, name), order_items(title, quantity, unit_price)')
        .eq('tenant_id', tenantId)
        .order('created_at', { ascending: false })
        .limit(100),
      supabase
        .from('products')
        .select('id, title, product_variations(id, price, attributes)')
        .eq('tenant_id', tenantId)
        .eq('status', 'active'),
      supabase
        .from('contacts')
        .select('id, phone, name')
        .eq('tenant_id', tenantId)
        .order('name'),
      supabase
        .from('orders')
        .select('status')
        .eq('tenant_id', tenantId),
    ])

    const allOrders = (allOrdersRes.data as unknown as { status: string }[]) || []
    counts = allOrders.reduce((acc, o) => {
      acc[o.status] = (acc[o.status] ?? 0) + 1
      return acc
    }, {} as Record<string, number>)
    counts['all'] = allOrders.length

    let fetched = (ordersRes.data as unknown as Order[]) || []
    if (filterStatus !== 'all') {
      fetched = fetched.filter(o => o.status === filterStatus)
    }
    orders = fetched
    products = (productsRes.data as Product[]) || []
    contacts = (contactsRes.data as Contact[]) || []
  }

  // ── Server Actions ────────────────────────────────────────────────────────
  async function updateOrderStatus(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    
    const orderId = formData.get('order_id') as string
    const isCancel = formData.get('cancel') === 'true'
    const nextStatus = formData.get('next_status') as string
    
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return

    // F2.2: cancel y avance de estado pasan AMBOS por la API. El cancel antes escribía directo a
    // Supabase (sin @audit_log ni validación de transición); ahora reusa el mismo PATCH auditado.
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
      // F139: NO tragar el fallo (antes: sin check de res.ok + catch vacío) — una transición inválida
      // (400/409), RBAC (403) o timeout dejaban al operador sin ningún aviso (el spinner terminaba y se
      // repintaba el mismo estado). Lanzar lo surface vía el error boundary.
      if (!res.ok) throw new Error((await res.text()).slice(0, 200) || `Error ${res.status}`)
    } catch (e) {
      throw e instanceof Error ? e : new Error('No se pudo actualizar el pedido (timeout o red)')
    }

    revalidatePath('/dashboard/orders')
  }

  // Rev. 108 Fase B — Generar guía Aveonline manualmente desde Inbox.
  // Aplicación principal: órdenes COD (que no disparan wompi_webhook).
  // Owner + manager.
  async function generateShippingGuide(
    formData: FormData,
  ): Promise<{ ok: boolean; message?: string; tracking?: string }> {
    'use server'
    const sb = createClient()
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
      updateStatusAction={updateOrderStatus}
      generateShippingGuideAction={generateShippingGuide}
    />
  )
}
