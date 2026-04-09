import { createClient } from '@/utils/supabase/server'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const STATUS_LABELS: Record<string, string> = {
  pending:    'Pendiente',
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

const STATUS_COLORS: Record<string, string> = {
  pending:    'bg-yellow-100 text-yellow-800',
  confirmed:  'bg-blue-100 text-blue-800',
  processing: 'bg-purple-100 text-purple-800',
  shipped:    'bg-indigo-100 text-indigo-800',
  delivered:  'bg-green-100 text-green-800',
  cancelled:  'bg-red-100 text-red-800',
}

export default async function MetricsPage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'

  if (!tenantId) {
    return (
      <div className="p-8 text-center text-muted-foreground">
        Sin acceso — tenant no configurado.
      </div>
    )
  }

  // ── Consultas paralelas ───────────────────────────────────────────────────
  const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString()

  const [
    messagesRes,
    conversationsRes,
    ordersRes,
    orderItemsRes,
    contactsRes,
    productsRes,
  ] = await Promise.all([
    supabase
      .from('messages')
      .select('id, direction, created_at')
      .eq('tenant_id', tenantId)
      .gte('created_at', thirtyDaysAgo),
    supabase
      .from('conversations')
      .select('id, status')
      .eq('tenant_id', tenantId),
    supabase
      .from('orders')
      .select('id, status, total_amount, created_at')
      .eq('tenant_id', tenantId),
    supabase
      .from('order_items')
      .select('title, quantity, unit_price')
      .eq('tenant_id', tenantId),
    supabase
      .from('contacts')
      .select('id')
      .eq('tenant_id', tenantId),
    supabase
      .from('products')
      .select('id, status')
      .eq('tenant_id', tenantId),
  ])

  const messages     = messagesRes.data ?? []
  const conversations = conversationsRes.data ?? []
  const orders       = ordersRes.data ?? []
  const orderItems   = orderItemsRes.data ?? []
  const contacts     = contactsRes.data ?? []
  const products     = productsRes.data ?? []

  // ── Cálculos ─────────────────────────────────────────────────────────────

  const inboundMessages  = messages.filter(m => m.direction === 'inbound').length
  const outboundMessages = messages.filter(m => m.direction === 'outbound').length

  const activeConversations = conversations.filter(c => c.status === 'active').length
  const humanConversations  = conversations.filter(c => c.status === 'human').length

  const totalRevenue = orders
    .filter(o => o.status !== 'cancelled')
    .reduce((sum, o) => sum + (Number(o.total_amount) || 0), 0)

  const deliveredRevenue = orders
    .filter(o => o.status === 'delivered')
    .reduce((sum, o) => sum + (Number(o.total_amount) || 0), 0)

  // Pedidos por estado
  const ordersByStatus: Record<string, number> = {}
  for (const o of orders) {
    ordersByStatus[o.status] = (ordersByStatus[o.status] ?? 0) + 1
  }

  // Productos más vendidos (top 5 por cantidad)
  const itemTotals: Record<string, { quantity: number; revenue: number }> = {}
  for (const item of orderItems) {
    if (!itemTotals[item.title]) itemTotals[item.title] = { quantity: 0, revenue: 0 }
    itemTotals[item.title].quantity += item.quantity
    itemTotals[item.title].revenue += item.quantity * Number(item.unit_price)
  }
  const topProducts = Object.entries(itemTotals)
    .sort((a, b) => b[1].quantity - a[1].quantity)
    .slice(0, 5)

  const activeProducts = products.filter(p => p.status === 'active').length

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-primary">Métricas</h1>
          <p className="text-sm text-muted-foreground mt-1">Últimos 30 días (mensajes) · Histórico (pedidos)</p>
        </div>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      {/* ── KPI Cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Mensajes (30d)</p>
            <p className="text-3xl font-bold text-primary mt-1">{messages.length}</p>
            <p className="text-xs text-muted-foreground mt-1">
              {inboundMessages} recibidos · {outboundMessages} enviados
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Conversaciones</p>
            <p className="text-3xl font-bold text-primary mt-1">{conversations.length}</p>
            <p className="text-xs text-muted-foreground mt-1">
              {activeConversations} IA activa · {humanConversations} con humano
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Pedidos</p>
            <p className="text-3xl font-bold text-primary mt-1">{orders.length}</p>
            <p className="text-xs text-muted-foreground mt-1">
              ${totalRevenue.toLocaleString('es-MX', { minimumFractionDigits: 0 })} en ventas
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Contactos</p>
            <p className="text-3xl font-bold text-primary mt-1">{contacts.length}</p>
            <p className="text-xs text-muted-foreground mt-1">
              {activeProducts} productos activos
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-6">

        {/* ── Pedidos por estado ── */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Pedidos por estado</CardTitle>
          </CardHeader>
          <CardContent>
            {orders.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin pedidos aún.</p>
            ) : (
              <div className="space-y-2">
                {Object.entries(ordersByStatus)
                  .sort((a, b) => b[1] - a[1])
                  .map(([status, count]) => (
                    <div key={status} className="flex justify-between items-center">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-800'}`}>
                        {STATUS_LABELS[status] ?? status}
                      </span>
                      <span className="font-semibold">{count}</span>
                    </div>
                  ))}
                <div className="pt-2 border-t flex justify-between items-center">
                  <span className="text-xs text-muted-foreground">Entregado — ingresos confirmados</span>
                  <span className="font-bold text-primary">
                    ${deliveredRevenue.toLocaleString('es-MX', { minimumFractionDigits: 0 })}
                  </span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Productos más vendidos ── */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Productos más vendidos</CardTitle>
          </CardHeader>
          <CardContent>
            {topProducts.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin ventas registradas aún.</p>
            ) : (
              <div className="space-y-3">
                {topProducts.map(([title, data], i) => (
                  <div key={title} className="flex justify-between items-start">
                    <div className="flex gap-2 items-start">
                      <span className="text-xs text-muted-foreground font-mono w-4">{i + 1}</span>
                      <p className="text-sm font-medium leading-tight">{title}</p>
                    </div>
                    <div className="text-right shrink-0 ml-4">
                      <p className="text-sm font-semibold">{data.quantity} uds.</p>
                      <p className="text-xs text-muted-foreground">
                        ${data.revenue.toLocaleString('es-MX', { minimumFractionDigits: 0 })}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

      </div>
    </div>
  )
}
