import { Suspense } from 'react'
import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { BarChart2, MessageSquare, ShoppingCart, Users, Package, TrendingUp, CheckCircle2, XCircle, ArrowDownToLine, AlertCircle } from 'lucide-react'
import MetricsFilters from './metrics-filters'
import { MessagesBarChart, OrdersPieChart } from './metrics-charts'
import AiInsightPanel from '@/components/ai-insight-panel'

const DAY_LABELS = ['Do', 'Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá']

const STATUS_COLORS: Record<string, string> = {
  pending:    'bg-yellow-500/15 text-yellow-700 border border-yellow-700/30',
  pending_payment: 'bg-amber-500/15 text-amber-700 border border-amber-700/30',  // F62
  confirmed:  'bg-blue-500/15 text-blue-700 border border-blue-700/30',
  processing: 'bg-purple-500/15 text-purple-400 border border-purple-500/30',
  shipped:    'bg-indigo-500/15 text-indigo-400 border border-indigo-500/30',
  delivered:  'bg-green-500/15 text-green-700 border border-green-700/30',
  cancelled:  'bg-red-500/15 text-red-700 border border-red-700/30',
}

const STATUS_LABELS: Record<string, string> = {
  pending:    'Pendiente',
  pending_payment: 'Esperando pago',  // F62: órdenes bot con link Wompi
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
  return null
}

export default async function MetricsPage(
  props: {
    searchParams: Promise<{ period?: string }>
  }
) {
  const searchParams = await props.searchParams;
  const period = searchParams?.period ?? '30'
  const days   = getPeriodDays(period)

  const ROLE_LABELS: Record<string, string> = { owner: 'Administrador', manager: 'Supervisor', operator: 'Gestor' }

  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  // Guard server-side (matriz 2026-07-02): Métricas = owner/manager. Sin esto un operator entra por URL directa.
  if (role !== 'owner' && role !== 'manager') redirect('/dashboard')

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const since = days
    ? new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString()
    : new Date(0).toISOString()

  const [messagesRes, conversationsRes, ordersRes, orderItemsRes, contactsRes, productsRes, claimsRes] = await Promise.all([
    supabase.from('messages').select('id, direction, created_at').eq('tenant_id', tenantId).gte('created_at', since),
    supabase.from('conversations').select('id, status').eq('tenant_id', tenantId),
    supabase.from('orders').select('id, status, total_amount, created_at').eq('tenant_id', tenantId).gte('created_at', since),
    supabase.from('order_items').select('title, quantity, unit_price').eq('tenant_id', tenantId),
    supabase.from('contacts').select('id').eq('tenant_id', tenantId),
    supabase.from('products').select('id, status').eq('tenant_id', tenantId),
    supabase.from('claims').select('id, status, reason, requested_amount, created_at').eq('tenant_id', tenantId).gte('created_at', since),
  ])

  const messages      = messagesRes.data ?? []
  const conversations = conversationsRes.data ?? []
  const orders        = (ordersRes.data ?? []) as { id: string; status: string; total_amount: number; created_at: string }[]
  const orderItems    = orderItemsRes.data ?? []
  const contacts      = contactsRes.data ?? []
  const products      = productsRes.data ?? []
  const claims        = (claimsRes.data ?? []) as { id: string; status: string; reason: string; requested_amount: number | null; created_at: string }[]

  // ── KPIs ──────────────────────────────────────────────────────────────────
  const inboundMessages  = messages.filter(m => m.direction === 'inbound').length
  const outboundMessages = messages.filter(m => m.direction === 'outbound').length
  const botConversations   = conversations.filter(c => c.status === 'bot_active').length
  const humanConversations = conversations.filter(c => c.status === 'human_takeover').length

  const totalRevenue = orders.filter(o => o.status !== 'cancelled')
    .reduce((sum, o) => sum + (Number(o.total_amount) || 0), 0)
  const deliveredRevenue = orders.filter(o => o.status === 'delivered')
    .reduce((sum, o) => sum + (Number(o.total_amount) || 0), 0)
  const conversionRate = conversations.length > 0
    ? Math.round((orders.filter(o => o.status !== 'cancelled').length / conversations.length) * 100)
    : 0

  const activeProducts = products.filter(p => p.status === 'active').length

  // ── Pedidos por estado ─────────────────────────────────────────────────────
  const ordersByStatus: Record<string, number> = {}
  for (const o of orders) {
    ordersByStatus[o.status] = (ordersByStatus[o.status] ?? 0) + 1
  }

  // ── Productos más vendidos ─────────────────────────────────────────────────
  const itemTotals: Record<string, { quantity: number; revenue: number }> = {}
  for (const item of orderItems) {
    const it = item as { title: string; quantity: number; unit_price: number }
    if (!itemTotals[it.title]) itemTotals[it.title] = { quantity: 0, revenue: 0 }
    itemTotals[it.title].quantity += it.quantity
    itemTotals[it.title].revenue  += it.quantity * Number(it.unit_price)
  }
  const topProducts = Object.entries(itemTotals).sort((a, b) => b[1].quantity - a[1].quantity).slice(0, 5)

  // ── Mensajes por día de semana ─────────────────────────────────────────────
  const msgsPerDay: Record<string, number> = {}
  for (const msg of messages) {
    const label = DAY_LABELS[new Date(msg.created_at).getDay()]
    msgsPerDay[label] = (msgsPerDay[label] ?? 0) + 1
  }
  const barData = DAY_LABELS.map(d => ({ day: d, mensajes: msgsPerDay[d] ?? 0 }))
  const pieData = Object.entries(ordersByStatus).map(([status, count]) => ({ name: status, value: count }))
  const periodLabel = days ? `Últimos ${days} días` : 'Todo el tiempo'

  // ── Reclamos ───────────────────────────────────────────────────────────────
  const REASON_LABELS: Record<string, string> = {
    defective:     'Producto defectuoso',
    wrong_item:    'Ítem incorrecto',
    delayed:       'Envío retrasado',
    missing_parts: 'Partes faltantes',
    other:         'Otro',
  }
  const openClaims      = claims.filter(c => !['resolved', 'refunded', 'rejected'].includes(c.status)).length
  const refundedClaims  = claims.filter(c => c.status === 'refunded')
  const totalRefunded   = refundedClaims.reduce((s, c) => s + (Number(c.requested_amount) || 0), 0)
  const claimRate       = orders.length > 0 ? ((claims.length / orders.length) * 100).toFixed(1) : '0'
  const claimsByReason: Record<string, number> = {}
  for (const c of claims) {
    claimsByReason[c.reason] = (claimsByReason[c.reason] ?? 0) + 1
  }

  // ── UI ─────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <BarChart2 className="h-5 w-5 text-primary" /> Métricas
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">{periodLabel} · {ROLE_LABELS[role] ?? role}</p>
        </div>
        <Suspense>
          <MetricsFilters current={period} />
        </Suspense>
      </div>

      {/* AI Insight — a demanda */}
      {(role === 'owner' || role === 'manager') && (
        <AiInsightPanel module="metrics" label="Analítica y Rendimiento" />
      )}

      {/* ── KPI Cards principales ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {[
          {
            icon: MessageSquare, label: 'Mensajes', value: messages.length, color: 'text-primary',
            sub: `${inboundMessages} recibidos · ${outboundMessages} enviados`,
          },
          {
            icon: Users, label: 'Conversaciones', value: conversations.length, color: 'text-blue-700',
            sub: `${botConversations} bot · ${humanConversations} humano`,
          },
          {
            icon: ShoppingCart, label: 'Pedidos', value: orders.length, color: 'text-emerald-700',
            sub: `$${totalRevenue.toLocaleString('es-CO', { minimumFractionDigits: 0 })} en ventas`,
          },
          {
            icon: Package, label: 'Contactos / Prods.', value: contacts.length, color: 'text-violet-400',
            sub: `${activeProducts} productos activos`,
          },
        ].map(kpi => (
          <div key={kpi.label} className="rounded-xl border border-border bg-card p-4 sm:p-5">
            <div className="flex items-center gap-2 mb-2">
              <kpi.icon className={`h-4 w-4 ${kpi.color}`} />
              <p className="text-xs text-muted-foreground uppercase tracking-wide">{kpi.label}</p>
            </div>
            <p className={`text-2xl sm:text-3xl font-bold ${kpi.color}`}>{kpi.value}</p>
            <p className="text-xs text-muted-foreground mt-1">{kpi.sub}</p>
          </div>
        ))}
      </div>

      {/* ── KPIs derivados ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Tasa conversión', value: `${conversionRate}%`, note: 'Conv. → Pedido', Icon: TrendingUp, color: 'text-primary' },
          { label: 'Ingresos confirmados', value: `$${deliveredRevenue.toLocaleString('es-CO', { minimumFractionDigits: 0 })}`, note: 'Pedidos entregados', Icon: CheckCircle2, color: 'text-emerald-700' },
          { label: '% Inbound', value: messages.length > 0 ? `${Math.round((inboundMessages / messages.length) * 100)}%` : '—', note: 'de los mensajes', Icon: ArrowDownToLine, color: 'text-blue-700' },
          { label: 'Pedidos cancelados', value: (ordersByStatus['cancelled'] ?? 0).toString(), note: 'en el período', Icon: XCircle, color: 'text-red-700' },
        ].map(k => (
          <div key={k.label} className="rounded-xl border border-border bg-card px-4 py-3">
            <div className="flex items-center gap-1.5 mb-1">
              <k.Icon className={`h-3.5 w-3.5 ${k.color}`} />
              <p className="text-xs text-muted-foreground">{k.label}</p>
            </div>
            <p className="text-xl font-bold text-primary">{k.value}</p>
            <p className="text-[11px] text-muted-foreground">{k.note}</p>
          </div>
        ))}
      </div>

      {/* ── Gráficas ── */}
      <div className="grid md:grid-cols-2 gap-5">
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm font-medium mb-4">Mensajes por día de semana</p>
          <MessagesBarChart data={barData} />
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm font-medium mb-4">Pedidos por estado</p>
          {pieData.length > 0
            ? <OrdersPieChart data={pieData} />
            : <p className="text-sm text-muted-foreground py-8 text-center">Sin pedidos en el período.</p>
          }
        </div>
      </div>

      {/* ── Tablas ── */}
      <div className="grid md:grid-cols-2 gap-5">

        {/* Desglose pedidos */}
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm font-medium mb-4">Desglose de pedidos por estado</p>
          {orders.length === 0 ? (
            <p className="text-sm text-muted-foreground">Sin pedidos en el período.</p>
          ) : (
            <div className="space-y-2.5">
              {Object.entries(ordersByStatus).sort((a, b) => b[1] - a[1]).map(([status, count]) => (
                <div key={status} className="flex items-center justify-between">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_COLORS[status] ?? 'bg-muted text-muted-foreground border-border'}`}>
                    {STATUS_LABELS[status] ?? status}
                  </span>
                  <div className="flex items-center gap-3">
                    {/* Progress bar */}
                    <div className="w-20 h-1.5 rounded-full bg-border overflow-hidden hidden sm:block">
                      <div className="h-full bg-primary rounded-full" style={{ width: `${Math.round((count / orders.length) * 100)}%` }} />
                    </div>
                    <span className="font-semibold text-sm w-6 text-right">{count}</span>
                  </div>
                </div>
              ))}
              <div className="pt-2 border-t border-border flex justify-between items-center">
                <span className="text-xs text-muted-foreground">Ingresos confirmados</span>
                <span className="font-bold text-primary text-sm">
                  ${deliveredRevenue.toLocaleString('es-CO', { minimumFractionDigits: 0 })}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Top productos */}
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="h-4 w-4 text-primary" />
            <p className="text-sm font-medium">Top 5 productos vendidos</p>
          </div>
          {topProducts.length === 0 ? (
            <p className="text-sm text-muted-foreground">Sin ventas registradas.</p>
          ) : (
            <div className="space-y-3">
              {topProducts.map(([title, data], i) => (
                <div key={title} className="flex justify-between items-start gap-3">
                  <div className="flex gap-2 items-center min-w-0">
                    <span className={`shrink-0 h-5 w-5 rounded-full flex items-center justify-center text-[11px] font-bold ${
                      i === 0 ? 'bg-yellow-400/20 text-yellow-700' :
                      i === 1 ? 'bg-slate-400/20 text-slate-700' :
                      i === 2 ? 'bg-orange-400/20 text-orange-700' : 'bg-muted text-muted-foreground'
                    }`}>{i + 1}</span>
                    <p className="text-sm font-medium truncate">{title}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-sm font-semibold">{data.quantity} uds.</p>
                    <p className="text-xs text-muted-foreground">${data.revenue.toLocaleString('es-CO', { minimumFractionDigits: 0 })}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Reclamos ── */}
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-center gap-2 mb-4">
          <AlertCircle className="h-4 w-4 text-red-700" />
          <p className="text-sm font-medium">Reclamos</p>
          <span className="ml-auto text-xs text-muted-foreground">{claims.length} en período</span>
        </div>

        {claims.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin reclamos en el período.</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
            {[
              { label: 'Total reclamos',   value: claims.length,         color: 'text-red-700' },
              { label: 'Abiertos',         value: openClaims,            color: 'text-amber-700' },
              { label: 'Reembolsados',     value: refundedClaims.length, color: 'text-emerald-700' },
              { label: 'Tasa reclamo/pedido', value: `${claimRate}%`,   color: 'text-primary' },
            ].map(k => (
              <div key={k.label} className="rounded-lg border border-border p-3 text-center">
                <p className={`text-xl font-bold ${k.color}`}>{k.value}</p>
                <p className="text-[11px] text-muted-foreground mt-0.5">{k.label}</p>
              </div>
            ))}
          </div>
        )}

        {totalRefunded > 0 && (
          <p className="text-xs text-muted-foreground mb-4">
            Total reembolsado:{' '}
            <span className="font-semibold text-emerald-700">
              ${totalRefunded.toLocaleString('es-CO', { minimumFractionDigits: 0 })}
            </span>
          </p>
        )}

        {Object.keys(claimsByReason).length > 0 && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">Por motivo</p>
            {Object.entries(claimsByReason).sort((a, b) => b[1] - a[1]).map(([reason, count]) => (
              <div key={reason} className="flex items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground">{REASON_LABELS[reason] ?? reason}</span>
                <div className="flex items-center gap-2">
                  <div className="w-20 h-1.5 rounded-full bg-border overflow-hidden hidden sm:block">
                    <div className="h-full bg-red-400/60 rounded-full" style={{ width: `${Math.round((count / claims.length) * 100)}%` }} />
                  </div>
                  <span className="text-xs font-semibold w-4 text-right">{count}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
