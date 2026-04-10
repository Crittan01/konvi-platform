import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'

type Variation = { id: string; price: number }
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
  pending:    'bg-yellow-100 text-yellow-800',
  confirmed:  'bg-blue-100 text-blue-800',
  processing: 'bg-purple-100 text-purple-800',
  shipped:    'bg-indigo-100 text-indigo-800',
  delivered:  'bg-green-100 text-green-800',
  cancelled:  'bg-red-100 text-red-800',
}

export default async function OrdersPage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
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
        .select('id, title, product_variations(id, price)')
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

  async function createOrder(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const t = m.tenant_id

    const contactId = formData.get('contact_id') as string || null
    const productId = formData.get('product_id') as string
    const variationId = formData.get('variation_id') as string || null
    const productTitle = formData.get('product_title') as string
    const unitPrice = parseFloat(formData.get('unit_price') as string)
    const quantity = parseInt(formData.get('quantity') as string)
    const notes = formData.get('notes') as string || null
    const total = unitPrice * quantity

    const { data: order } = await sb.from('orders').insert({
      tenant_id: t,
      contact_id: contactId || null,
      status: 'pending',
      total_amount: total,
      notes,
    }).select().single()

    if (order) {
      await sb.from('order_items').insert({
        order_id: order.id,
        tenant_id: t,
        product_id: productId || null,
        variation_id: variationId || null,
        title: productTitle,
        unit_price: unitPrice,
        quantity,
      })
    }
    revalidatePath('/dashboard/orders')
  }

  async function advanceStatus(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    await sb.from('orders')
      .update({ status: formData.get('next_status') as string })
      .eq('id', formData.get('order_id') as string)
      .eq('tenant_id', m.tenant_id)

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

        {/* Formulario nuevo pedido */}
        {canWrite && (
          <div className="col-span-1">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Nuevo Pedido</CardTitle>
              </CardHeader>
              <CardContent>
                <form action={createOrder} className="space-y-4">
                  <div className="space-y-2">
                    <Label>Contacto</Label>
                    <select name="contact_id" className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm">
                      <option value="">Sin contacto</option>
                      {contacts.map(c => (
                        <option key={c.id} value={c.id}>
                          {c.name ? `${c.name} (${c.phone})` : c.phone}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-2">
                    <Label>Producto</Label>
                    <select
                      name="product_id"
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                      required
                    >
                      <option value="">Seleccionar producto</option>
                      {products.map(p => {
                        const v = p.product_variations?.[0]
                        return (
                          <option
                            key={p.id}
                            value={p.id}
                            data-price={v?.price ?? 0}
                            data-variation={v?.id ?? ''}
                          >
                            {p.title} — ${v?.price ?? '?'}
                          </option>
                        )
                      })}
                    </select>
                    {/* Hidden fields para title y variation_id — se llenarán al seleccionar */}
                    <input type="hidden" name="product_title" id="product_title_hidden" />
                    <input type="hidden" name="variation_id" id="variation_id_hidden" />
                    <input type="hidden" name="unit_price" id="unit_price_hidden" />
                  </div>

                  <div className="space-y-2">
                    <Label>Precio unitario ($)</Label>
                    <Input name="unit_price" type="number" step="0.01" min="0.01" placeholder="0.00" required />
                  </div>

                  <div className="space-y-2">
                    <Label>Cantidad</Label>
                    <Input name="quantity" type="number" min="1" defaultValue="1" required />
                  </div>

                  <div className="space-y-2">
                    <Label>Notas</Label>
                    <Input name="notes" placeholder="Instrucciones especiales..." />
                  </div>

                  <Button type="submit" className="w-full">Crear pedido</Button>
                </form>
              </CardContent>
            </Card>
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
                const colorClass = STATUS_COLORS[o.status] || 'bg-gray-100 text-gray-800'
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
                          <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full ${colorClass}`}>
                            {STATUS_LABELS[o.status] ?? o.status}
                          </span>
                          <p className="font-bold text-primary">${o.total_amount}</p>
                          <p className="text-xs text-muted-foreground">
                            {new Date(o.created_at).toLocaleDateString('es-MX')}
                          </p>
                        </div>
                      </div>

                      {canWrite && o.status !== 'delivered' && o.status !== 'cancelled' && (
                        <div className="flex gap-2 pt-2 border-t">
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
