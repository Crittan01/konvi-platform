import { Suspense } from 'react'
import { createClient } from '@/utils/supabase/server'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import MetricsFilters from './metrics-filters'
import { MessagesBarChart, OrdersPieChart } from './metrics-charts'

const DAY_LABELS = ['Do', 'Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá']

const STATUS_COLORS: Record<string, string> = {
  pending:    'bg-yellow-500/15 text-yellow-400 border border-yellow-500/30',
  confirmed:  'bg-blue-500/15 text-blue-400 border border-blue-500/30',
  processing: 'bg-purple-500/15 text-purple-400 border border-purple-500/30',
  shipped:    'bg-indigo-500/15 text-indigo-400 border border-indigo-500/30',
  delivered:  'bg-green-500/15 text-green-400 border border-green-500/30',
  cancelled:  'bg-red-500/15 text-red-400 border border-red-500/30',
}

const STATUS_LABELS: Record<string, string> = {
  pending:    'Pendiente',
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

function getPeriodDays(period: string): number | null {
  if (period === '7')  return 7
  if (period === '30') return 30
  if (period === '90') return 90
  return null // 'all'
}

export default async function MetricsPage({
  searchParams,
}: {
  searchParams: { period?: string }
}) {
  const period = searchParams?.period ?? '30'
  const days = getPeriodDays(period)

  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const since = days
    ? new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString()
    : new Date(0).toISOString()

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
      .gte('created_at', since),
    supabase
      .from('conversations')
      .select('id, status')
      .eq('tenant_id', tenantId),
    supabase
      .from('orders')
      .select('id, status, total_amount, created_at')
      .eq('tenant_id', tenantId)
      .gte('created_at', since),
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

  const messages      = messagesRes.data ?? []
  const conversations = conversationsRes.data ?? []
  const orders        = (ordersRes.data ?? []) as { id: string; status: string; total_amount: number; created_at: string }[]
  const orderItems    = orderItemsRes.data ?? []
  const contacts      = contactsRes.data ?? []
  const products      = productsRes.data ?? []

  // ── KPIs ──────────────────────────────────────────────────────────────────

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

  const activeProducts = products.filter(p => p.status === 'active').length

  // ── Pedidos por estado ────────────────────────────────────────────────────
  const ordersByStatus: Record<string, number> = {}
  for (const o of orders) {
    ordersByStatus[o.status] = (ordersByStatus[o.status] ?? 0) + 1
  }

  // ── Productos más vendidos ────────────────────────────────────────────────
  const itemTotals: Record<string, { quantity: number; revenue: number }> = {}
  for (const item of orderItems) {
    const it = item as { title: string; quantity: number; unit_price: number }
    if (!itemTotals[it.title]) itemTotals[it.title] = { quantity: 0, revenue: 0 }
    itemTotals[it.title].quantity += it.quantity
    itemTotals[it.title].revenue += it.quantity * Number(it.unit_price)
  }
  const topProducts = Object.entries(itemTotals)
    .sort((a, b) => b[1].quantity - a[1].quantity)
    .slice(0, 5)

  // ── Mensajes por día (chart) ──────────────────────────────────────────────
  const msgsPerDay: Record<string, number> = {}
  for (const msg of messages) {
    const d = new Date(msg.created_at)
    const label = DAY_LABELS[d.getDay()]
    msgsPerDay[label] = (msgsPerDay[label] ?? 0) + 1
  }
  const barData = DAY_LABELS.map(d => ({ day: d, mensajes: msgsPerDay[d] ?? 0 }))

  // ── Pedidos por estado (pie) ──────────────────────────────────────────────
  const pieData = Object.entries(ordersByStatus).map(([status, count]) => ({
    name: status,
    value: count,
  }))

  const periodLabel = days ? `Últimos ${days} días` : 'Todo el tiempo'

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-primary">Métricas</h1>
          <p className="text-sm text-muted-foreground mt-1">{periodLabel}</p>
        </div>
        <div className="flex items-center gap-3">
          <Suspense>
            <MetricsFilters current={period} />
          </Suspense>
          <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
        </div>
      </div>

      {/* ── KPI Cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Mensajes</p>
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
              {activeConversations} IA · {humanConversations} humano
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

      {/* ── Gráficas ── */}
      <div className="grid md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Mensajes por día de semana</CardTitle>
          </CardHeader>
          <CardContent>
            <MessagesBarChart data={barData} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Pedidos por estado</CardTitle>
          </CardHeader>
          <CardContent>
            {pieData.length > 0 ? (
              <OrdersPieChart data={pieData} />
            ) : (
              <p className="text-sm text-muted-foreground">Sin pedidos en el período.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Tablas ── */}
      <div className="grid md:grid-cols-2 gap-6">

        {/* Pedidos por estado (tabla) */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Desglose de pedidos</CardTitle>
          </CardHeader>
          <CardContent>
            {orders.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin pedidos en el período.</p>
            ) : (
              <div className="space-y-2">
                {Object.entries(ordersByStatus)
                  .sort((a, b) => b[1] - a[1])
                  .map(([status, count]) => (
                    <div key={status} className="flex justify-between items-center">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLORS[status] ?? 'bg-muted text-muted-foreground'}`}>
                        {STATUS_LABELS[status] ?? status}
                      </span>
                      <span className="font-semibold text-sm">{count}</span>
                    </div>
                  ))}
                <div className="pt-2 border-t flex justify-between items-center">
                  <span className="text-xs text-muted-foreground">Entregado — ingresos confirmados</span>
                  <span className="font-bold text-primary text-sm">
                    ${deliveredRevenue.toLocaleString('es-MX', { minimumFractionDigits: 0 })}
                  </span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Productos más vendidos */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Productos más vendidos</CardTitle>
          </CardHeader>
          <CardContent>
            {topProducts.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin ventas registradas.</p>
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
