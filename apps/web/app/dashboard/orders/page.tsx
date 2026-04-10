import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Package, Clock, ChevronRight, Plus } from 'lucide-react'
import OrdersNewForm from './orders-new-form'
import Link from 'next/link'

type Variation = { id: string; price: number | null; attributes: Record<string, string> | null }
type Product   = { id: string; title: string; product_variations: Variation[] }
type Contact   = { id: string; phone: string; name: string | null }
type OrderItem = { title: string; quantity: number; unit_price: number }
type Order = {
  id: string
  status: string
  total_amount: number
  notes: string | null
  created_at: string
  contacts: Contact | Contact[] | null
  order_items: OrderItem[]
}

const STATUS_LABELS: Record<string, string> = {
  pending:    'Pendiente',
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

const STATUS_NEXT: Record<string, string> = {
  pending:    'confirmed',
  confirmed:  'processing',
  processing: 'shipped',
  shipped:    'delivered',
}

const STATUS_COLORS: Record<string, string> = {
  pending:    'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  confirmed:  'bg-blue-500/15 text-blue-400 border-blue-500/30',
  processing: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  shipped:    'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  delivered:  'bg-green-500/15 text-green-400 border-green-500/30',
  cancelled:  'bg-red-500/15 text-red-400 border-red-500/30',
}

const STATUS_ICONS: Record<string, string> = {
  pending:    '⏳',
  confirmed:  '✅',
  processing: '⚙️',
  shipped:    '📦',
  delivered:  '🏁',
  cancelled:  '❌',
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

export default async function OrdersPage({
  searchParams,
}: {
  searchParams?: { status?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  const filterStatus = searchParams?.status ?? 'all'

  let orders: Order[] = []
  let products: Product[] = []
  let contacts: Contact[] = []
  let counts: Record<string, number> = {}

  if (tenantId) {
    const [ordersRes, productsRes, contactsRes, allOrdersRes] = await Promise.all([
      supabase
        .from('orders')
        .select('id, status, total_amount, notes, created_at, contacts(id, phone, name), order_items(title, quantity, unit_price)')
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
  async function advanceStatus(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const orderId = formData.get('order_id') as string
    const nextStatus = formData.get('next_status') as string
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      await fetch(`${API_URL}/api/v1/orders/${orderId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ status: nextStatus }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
    } catch { /* non-fatal */ }
    revalidatePath('/dashboard/orders')
  }

  async function cancelOrder(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('orders').update({ status: 'cancelled' })
      .eq('id', formData.get('order_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/orders')
  }

  // ── UI ────────────────────────────────────────────────────────────────────
  const TAB_FILTERS = ['all', 'pending', 'confirmed', 'processing', 'shipped', 'delivered', 'cancelled']

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Package className="h-5 w-5 text-primary" /> Pedidos
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {counts['all'] ?? 0} pedidos totales
          </p>
        </div>
        <Badge variant="outline" className="text-xs capitalize self-start sm:self-auto">
          {role}
        </Badge>
      </div>

      {/* Filtros de estado — scrollable horizontal en mobile */}
      <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1">
        {TAB_FILTERS.map(s => (
          <Link
            key={s}
            href={s === 'all' ? '/dashboard/orders' : `/dashboard/orders?status=${s}`}
            className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
              filterStatus === s
                ? 'bg-primary/15 text-primary border-primary/40'
                : 'border-border text-muted-foreground hover:text-foreground hover:bg-accent'
            }`}
          >
            {STATUS_ICONS[s] ?? '🔘'}
            <span>{s === 'all' ? 'Todos' : STATUS_LABELS[s]}</span>
            {counts[s] !== undefined && counts[s] > 0 && (
              <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${
                filterStatus === s ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground'
              }`}>
                {counts[s]}
              </span>
            )}
          </Link>
        ))}
      </div>

      {/* Grid principal */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

        {/* Formulario nuevo pedido */}
        {canWrite && (
          <div className="xl:col-span-1">
            <OrdersNewForm products={products} contacts={contacts} apiUrl={API_URL} />
          </div>
        )}

        {/* Lista de pedidos */}
        <div className={canWrite ? 'xl:col-span-2' : 'xl:col-span-3'}>
          {orders.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 rounded-xl border border-dashed border-border text-center">
              <Package className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground text-sm">
                {filterStatus === 'all' ? 'No hay pedidos aún.' : `No hay pedidos con estado "${STATUS_LABELS[filterStatus] ?? filterStatus}".`}
              </p>
              {filterStatus !== 'all' && (
                <Link href="/dashboard/orders" className="mt-2 text-xs text-primary hover:underline">
                  Ver todos los pedidos
                </Link>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {orders.map((o) => {
                const nextStatus = STATUS_NEXT[o.status]
                const colorClass = STATUS_COLORS[o.status] || 'bg-gray-500/15 text-gray-400'
                const contact = Array.isArray(o.contacts) ? o.contacts[0] : o.contacts
                const revenue = o.total_amount ?? o.order_items.reduce((acc, i) => acc + i.unit_price * i.quantity, 0)

                return (
                  <div
                    key={o.id}
                    className="rounded-xl border border-border bg-card p-4 hover:border-primary/30 hover:shadow-sm transition-all"
                  >
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <div className="min-w-0 flex-1">
                        {/* ID + Fecha */}
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-mono text-muted-foreground">#...{o.id.slice(-8)}</span>
                          <span className="text-xs text-muted-foreground flex items-center gap-0.5">
                            <Clock className="h-3 w-3" />
                            {new Date(o.created_at).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' })}
                          </span>
                        </div>
                        {/* Contacto */}
                        <p className="font-medium text-sm text-foreground truncate">
                          {contact?.name || contact?.phone || 'Sin contacto'}
                        </p>
                        {/* Ítems */}
                        {o.order_items.length > 0 && (
                          <p className="text-xs text-muted-foreground mt-0.5 truncate">
                            {o.order_items.map(i => `${i.quantity}× ${i.title}`).join(', ')}
                          </p>
                        )}
                        {o.notes && (
                          <p className="text-xs text-muted-foreground mt-1 italic">{o.notes}</p>
                        )}
                      </div>
                      {/* Status + Total */}
                      <div className="text-right shrink-0 space-y-1">
                        <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border ${colorClass}`}>
                          {STATUS_ICONS[o.status]} {STATUS_LABELS[o.status] ?? o.status}
                        </span>
                        <p className="font-bold text-primary text-base">
                          ${revenue.toFixed(2)}
                        </p>
                        {o.order_items.length > 0 && (
                          <p className="text-xs text-muted-foreground">
                            {o.order_items.length} ítem{o.order_items.length !== 1 ? 's' : ''}
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Acciones */}
                    {canWrite && o.status !== 'delivered' && o.status !== 'cancelled' && (
                      <div className="flex gap-2 pt-3 border-t border-border">
                        {nextStatus && (
                          <form action={advanceStatus}>
                            <input type="hidden" name="order_id" value={o.id} />
                            <input type="hidden" name="next_status" value={nextStatus} />
                            <Button type="submit" size="sm" variant="outline" className="h-7 text-xs gap-1">
                              <ChevronRight className="h-3 w-3" />
                              {STATUS_LABELS[nextStatus]}
                            </Button>
                          </form>
                        )}
                        <Link
                          href={`/dashboard/shipping?order=${o.id}`}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:bg-accent transition-colors h-7"
                        >
                          📦 Crear envío
                        </Link>
                        <form action={cancelOrder} className="ml-auto">
                          <input type="hidden" name="order_id" value={o.id} />
                          <Button type="submit" size="sm" variant="ghost" className="h-7 text-xs text-destructive hover:text-destructive hover:bg-destructive/10">
                            Cancelar
                          </Button>
                        </form>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
