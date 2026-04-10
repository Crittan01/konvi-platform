import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import OrdersNewForm from './orders-new-form'

type Variation = { id: string; price: number | null; attributes: Record<string, string> | null }
type Product = { id: string; title: string; product_variations: Variation[] }
type Contact = { id: string; phone: string; name: string | null }
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

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

export default async function OrdersPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  let orders: Order[] = []
  let products: Product[] = []
  let contacts: Contact[] = []

  if (tenantId) {
    const [ordersRes, productsRes, contactsRes] = await Promise.all([
      supabase
        .from('orders')
        .select('id, status, total_amount, notes, created_at, contacts(id, phone, name), order_items(title, quantity, unit_price)')
        .eq('tenant_id', tenantId)
        .order('created_at', { ascending: false })
        .limit(50),
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
    ])
    orders = (ordersRes.data as unknown as Order[]) || []
    products = (productsRes.data as Product[]) || []
    contacts = (contactsRes.data as Contact[]) || []
  }

  // ── Server Actions ────────────────────────────────────────────────────────
  // advanceStatus llama al API (no Supabase directo) para que el backend
  // gestione el decremento de stock al confirmar (pending → confirmed).

  async function advanceStatus(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const orderId = formData.get('order_id') as string
    const nextStatus = formData.get('next_status') as string
    const token = s?.access_token
    if (!token) return

    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      await fetch(`${API_URL}/api/v1/orders/${orderId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ status: nextStatus }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
    } catch {
      // Non-fatal: revalidatePath still runs — UI will reflect DB state on next load
    }

    revalidatePath('/dashboard/orders')
  }

  async function cancelOrder(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    await sb.from('orders')
      .update({ status: 'cancelled' })
      .eq('id', formData.get('order_id') as string)
      .eq('tenant_id', m.tenant_id)

    revalidatePath('/dashboard/orders')
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Pedidos</h1>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* Formulario nuevo pedido — multi-item Client Component */}
        {canWrite && (
          <div className="col-span-1">
            <OrdersNewForm
              products={products}
              contacts={contacts}
              apiUrl={API_URL}
            />
          </div>
        )}

        {/* Lista de pedidos */}
        <div className={canWrite ? 'col-span-2' : 'col-span-3'}>
          <div className="space-y-3">
            {orders.length === 0 ? (
              <div className="p-8 border rounded-lg border-dashed text-center">
                <p className="text-muted-foreground">No hay pedidos aún.</p>
              </div>
            ) : (
              orders.map((o) => {
                const nextStatus = STATUS_NEXT[o.status]
                const colorClass = STATUS_COLORS[o.status] || 'bg-gray-500/15 text-gray-400'
                return (
                  <Card key={o.id}>
                    <CardContent className="p-5">
                      <div className="flex justify-between items-start mb-3">
                        <div>
                          <p className="text-xs text-muted-foreground font-mono">#{o.id.slice(-8)}</p>
                          <p className="font-medium">
                            {(() => {
                              const c = Array.isArray(o.contacts) ? o.contacts[0] : o.contacts
                              return c?.name || c?.phone || 'Sin contacto'
                            })()}
                          </p>
                          {o.order_items.length > 0 && (
                            <p className="text-sm text-muted-foreground">
                              {o.order_items.map(i => `${i.quantity}× ${i.title}`).join(', ')}
                            </p>
                          )}
                          {o.notes && <p className="text-xs text-muted-foreground mt-1 italic">{o.notes}</p>}
                        </div>
                        <div className="text-right shrink-0 ml-4 space-y-1">
                          <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full border ${colorClass}`}>
                            {STATUS_LABELS[o.status] ?? o.status}
                          </span>
                          <p className="font-bold text-primary">${o.total_amount}</p>
                          <p className="text-xs text-muted-foreground">
                            {new Date(o.created_at).toLocaleDateString('es-MX')}
                          </p>
                        </div>
                      </div>

                      {canWrite && o.status !== 'delivered' && o.status !== 'cancelled' && (
                        <div className="flex gap-2 pt-2 border-t border-border">
                          {nextStatus && (
                            <form action={advanceStatus}>
                              <input type="hidden" name="order_id" value={o.id} />
                              <input type="hidden" name="next_status" value={nextStatus} />
                              <Button type="submit" size="sm" variant="outline">
                                → {STATUS_LABELS[nextStatus]}
                              </Button>
                            </form>
                          )}
                          <form action={cancelOrder}>
                            <input type="hidden" name="order_id" value={o.id} />
                            <Button type="submit" size="sm" variant="ghost" className="text-destructive hover:text-destructive">
                              Cancelar
                            </Button>
                          </form>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )
              })
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
