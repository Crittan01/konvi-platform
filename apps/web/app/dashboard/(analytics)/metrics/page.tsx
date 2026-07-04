import { Suspense } from 'react'
import Link from 'next/link'
import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import {
  BarChart2, MessageSquare, ShoppingCart, Users, Package, TrendingUp,
  CheckCircle2, XCircle, ArrowDownToLine, AlertCircle, Info, AlertTriangle,
} from 'lucide-react'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import MetricsFilters from './metrics-filters'
import MetricsRetry from './metrics-retry'
import { MessagesBarChart, OrdersPieChart } from './metrics-charts'
import AiInsightPanel from '@/components/ai-insight-panel'
import { bogotaWindowUTC } from '@/lib/date-window'
import {
  MAX_ROWS, ORDER_STATUS_LABELS, ORDER_STATUS_CHIP, CLAIM_REASON_LABELS,
  aggregateOrders, conversionRate, topProducts, aggregateClaims, claimRatePct,
  messagesByWeekday,
  type OrderRow, type OrderItemRow, type ClaimRow,
} from './_lib/metrics'

const VALID_PERIODS = ['7', '30', '90', 'all'] as const

const cop = (n: number) => `$${n.toLocaleString('es-CO', { minimumFractionDigits: 0 })}`

export default async function MetricsPage(
  props: { searchParams: Promise<{ period?: string }> }
) {
  const searchParams = await props.searchParams
  // period inválido en URL → cae al default '30' (evita el estado sin filtro activo).
  const rawPeriod = searchParams?.period ?? '30'
  const period = (VALID_PERIODS as readonly string[]).includes(rawPeriod) ? rawPeriod : '30'
  const days = period === 'all' ? null : Number(period)

  const ROLE_LABELS: Record<string, string> = { owner: 'Administrador', manager: 'Supervisor', operator: 'Gestor' }

  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  // Guard server-side (matriz 2026-07-02): Métricas = owner/manager.
  if (role !== 'owner' && role !== 'manager') redirect('/dashboard')

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  // Ventana en hora Colombia (UTC-5): los días de calendario cierran a la hora
  // correcta, no a medianoche UTC (date-window.ts).
  const since = days ? bogotaWindowUTC(days).fromUTC : null
  const win = <T extends { gte: (c: string, v: string) => T }>(q: T): T => (since ? q.gte('created_at', since) : q)

  // ── Queries: conteos con count:'exact',head:true (NO traer filas);
  //    agregados (revenue, ranking, weekday) acotados por ventana + flag de
  //    truncamiento contra MAX_ROWS. Todo con .eq('tenant_id') (RLS + ADR-0025).
  const [
    msgRowsRes, inboundRes, ordersRowsRes, orderItemsRes,
    convTotalRes, convBotRes, convHumanRes, contactsRes, productsRes, claimsRowsRes,
  ] = await Promise.all([
    win(supabase.from('messages').select('created_at', { count: 'exact' }).eq('tenant_id', tenantId)),
    win(supabase.from('messages').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('direction', 'inbound')),
    win(supabase.from('orders').select('id, status, total_amount', { count: 'exact' }).eq('tenant_id', tenantId)),
    win(supabase.from('order_items').select('title, quantity, unit_price, orders!inner(status)', { count: 'exact' }).eq('tenant_id', tenantId)),
    win(supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId)),
    win(supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('status', 'bot_active')),
    win(supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('status', 'human_takeover')),
    supabase.from('contacts').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
    supabase.from('products').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('status', 'active'),
    win(supabase.from('claims').select('id, status, reason, requested_amount', { count: 'exact' }).eq('tenant_id', tenantId)),
  ])

  // ── Errores de lectura: se SURFACEAN, nunca se caen a 0 silencioso (F1) ─────
  const sources: { key: string; label: string; error: unknown }[] = [
    { key: 'messages', label: 'Mensajes', error: msgRowsRes.error || inboundRes.error },
    { key: 'orders', label: 'Pedidos', error: ordersRowsRes.error },
    { key: 'orderItems', label: 'Productos vendidos', error: orderItemsRes.error },
    { key: 'conversations', label: 'Conversaciones', error: convTotalRes.error || convBotRes.error || convHumanRes.error },
    { key: 'contacts', label: 'Contactos', error: contactsRes.error },
    { key: 'products', label: 'Productos', error: productsRes.error },
    { key: 'claims', label: 'Reclamos', error: claimsRowsRes.error },
  ]
  const failed = sources.filter(s => s.error)
  const err = (k: string) => failed.some(f => f.key === k)
  const DASH = '—'

  // ── Agregación (sobre filas acotadas) ───────────────────────────────────────
  const messageRows = (msgRowsRes.data ?? []) as { created_at: string }[]
  const orderRows   = (ordersRowsRes.data ?? []) as OrderRow[]
  const itemRows    = (orderItemsRes.data ?? []) as unknown as OrderItemRow[]
  const claimRows   = (claimsRowsRes.data ?? []) as ClaimRow[]

  const messagesTotal = msgRowsRes.count ?? messageRows.length
  const inboundTotal  = inboundRes.count ?? 0
  const outboundTotal = Math.max(messagesTotal - inboundTotal, 0)
  const conversationsTotal = convTotalRes.count ?? 0
  const botCount   = convBotRes.count ?? 0
  const humanCount = convHumanRes.count ?? 0
  const ordersTotal = ordersRowsRes.count ?? orderRows.length
  const contactsTotal = contactsRes.count ?? 0
  const activeProducts = productsRes.count ?? 0

  const ordersAgg = aggregateOrders(orderRows)
  const nonCancelledOrders = ordersTotal - ordersAgg.cancelledCount
  const convRate = conversionRate(nonCancelledOrders, conversationsTotal)
  const top = topProducts(itemRows)
  const claimsAgg = aggregateClaims(claimRows)
  const claimRate = claimRatePct(claimsAgg.total, ordersTotal)
  const barData = messagesByWeekday(messageRows)
  const pieData = Object.entries(ordersAgg.byStatus).map(([status, count]) => ({ name: status, value: count }))
  const periodLabel = days ? `Últimos ${days} días` : 'Todo el tiempo'

  // ── Truncamiento: agregados calculados sobre filas → si topan MAX_ROWS el
  //    resultado es aproximado (revenue, ranking, distribución semanal).
  const truncated = [
    { c: ordersRowsRes.count, n: orderRows.length, what: 'ingresos y estados de pedidos' },
    { c: orderItemsRes.count, n: itemRows.length, what: 'ranking de productos' },
    { c: msgRowsRes.count, n: messageRows.length, what: 'distribución semanal de mensajes' },
    { c: claimsRowsRes.count, n: claimRows.length, what: 'desglose de reclamos' },
  ].filter(x => (x.c ?? 0) > x.n && x.n >= MAX_ROWS)

  // ── UI ──────────────────────────────────────────────────────────────────────
  return (
    <TooltipProvider delayDuration={150}>
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

      {/* Estado de error: datos que no se pudieron cargar (no se pintan como 0) */}
      {failed.length > 0 && (
        <Alert variant="destructive" className="flex items-start justify-between gap-3">
          <div className="flex gap-2">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <div>
              <AlertTitle>No se pudieron cargar algunos datos</AlertTitle>
              <AlertDescription>
                {failed.map(f => f.label).join(', ')}. Los indicadores afectados muestran «{DASH}» en vez de 0.
              </AlertDescription>
            </div>
          </div>
          <MetricsRetry />
        </Alert>
      )}

      {/* Aviso de aproximación por truncamiento PostgREST (max_rows) */}
      {truncated.length > 0 && (
        <Alert variant="warning">
          <Info className="h-4 w-4" />
          <AlertTitle>Cifras aproximadas en este rango</AlertTitle>
          <AlertDescription>
            {`El período supera ${MAX_ROWS} registros; ${truncated.map(t => t.what).join(', ')} se calculan sobre una muestra. Reduce el rango para valores exactos.`}
          </AlertDescription>
        </Alert>
      )}

      {/* AI Insight — a demanda */}
      {(role === 'owner' || role === 'manager') && (
        <AiInsightPanel module="metrics" label="Analítica y Rendimiento" />
      )}

      {/* ── KPI Cards principales ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {[
          {
            icon: MessageSquare, label: 'Mensajes', color: 'text-primary',
            value: err('messages') ? DASH : messagesTotal,
            sub: err('messages') ? 'No disponible' : `${inboundTotal} recibidos · ${outboundTotal} enviados`,
          },
          {
            icon: Users, label: 'Conversaciones', color: 'text-blue-700',
            value: err('conversations') ? DASH : conversationsTotal,
            sub: err('conversations') ? 'No disponible' : `${botCount} bot · ${humanCount} humano`,
          },
          {
            icon: ShoppingCart, label: 'Pedidos', color: 'text-emerald-700',
            value: err('orders') ? DASH : ordersTotal,
            sub: err('orders') ? 'No disponible' : `${cop(ordersAgg.revenue)} en ventas`,
            tip: 'Ventas = suma de todos los pedidos no cancelados (incluye pendientes y en espera de pago). Distinto de «Ingresos confirmados».',
          },
          {
            icon: Users, label: 'Contactos', color: 'text-violet-700',
            value: err('contacts') ? DASH : contactsTotal,
            sub: 'Base total de clientes',
            tip: 'Total histórico de clientes registrados del tenant (no depende del período seleccionado).',
          },
        ].map(kpi => (
          <div key={kpi.label} className="rounded-xl border border-border bg-card p-4 sm:p-5">
            <div className="flex items-center gap-2 mb-2">
              <kpi.icon className={`h-4 w-4 ${kpi.color}`} />
              <p className="text-xs text-muted-foreground uppercase tracking-wide">{kpi.label}</p>
              {kpi.tip && (
                <Tooltip>
                  <TooltipTrigger aria-label={`Qué significa ${kpi.label}`} className="ml-auto text-muted-foreground/60 hover:text-muted-foreground">
                    <Info className="h-3.5 w-3.5" />
                  </TooltipTrigger>
                  <TooltipContent>{kpi.tip}</TooltipContent>
                </Tooltip>
              )}
            </div>
            <p className={`text-2xl sm:text-3xl font-bold ${kpi.color}`}>{kpi.value}</p>
            <p className="text-xs text-muted-foreground mt-1">{kpi.sub}</p>
          </div>
        ))}
      </div>

      {/* ── KPIs derivados ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-3">
        {[
          { label: 'Tasa conversión', value: (err('orders') || err('conversations')) ? DASH : `${convRate}%`, note: 'Pedidos ÷ conversaciones', Icon: TrendingUp, color: 'text-primary', tip: 'Pedidos no cancelados dividido entre conversaciones, ambos dentro del período seleccionado.' },
          { label: 'Ingresos confirmados', value: err('orders') ? DASH : cop(ordersAgg.deliveredRevenue), note: 'Solo pedidos entregados', Icon: CheckCircle2, color: 'text-emerald-700', tip: 'Dinero realizado: suma de pedidos en estado «Entregado» únicamente.' },
          { label: '% Inbound', value: err('messages') ? DASH : (messagesTotal > 0 ? `${Math.round((inboundTotal / messagesTotal) * 100)}%` : '—'), note: 'de los mensajes', Icon: ArrowDownToLine, color: 'text-blue-700' },
          { label: 'Pedidos cancelados', value: err('orders') ? DASH : ordersAgg.cancelledCount.toString(), note: 'en el período', Icon: XCircle, color: 'text-red-700' },
          { label: 'Productos activos', value: err('products') ? DASH : activeProducts.toString(), note: 'en catálogo', Icon: Package, color: 'text-violet-700' },
        ].map(k => (
          <div key={k.label} className="rounded-xl border border-border bg-card px-4 py-3">
            <div className="flex items-center gap-1.5 mb-1">
              <k.Icon className={`h-3.5 w-3.5 ${k.color}`} />
              <p className="text-xs text-muted-foreground">{k.label}</p>
              {k.tip && (
                <Tooltip>
                  <TooltipTrigger aria-label={`Qué significa ${k.label}`} className="ml-auto text-muted-foreground/60 hover:text-muted-foreground">
                    <Info className="h-3 w-3" />
                  </TooltipTrigger>
                  <TooltipContent>{k.tip}</TooltipContent>
                </Tooltip>
              )}
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
          {err('messages') ? (
            <p className="text-sm text-muted-foreground py-8 text-center">No se pudo cargar la actividad de mensajes.</p>
          ) : messagesTotal === 0 ? (
            <div className="py-8 text-center space-y-1">
              <p className="text-sm text-muted-foreground">Sin mensajes en el período.</p>
              <Link href="/dashboard/inbox" className="text-xs text-primary hover:underline">Ir al Inbox →</Link>
            </div>
          ) : (
            <MessagesBarChart data={barData} />
          )}
        </div>
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm font-medium mb-4">Pedidos por estado</p>
          {err('orders') ? (
            <p className="text-sm text-muted-foreground py-8 text-center">No se pudieron cargar los pedidos.</p>
          ) : pieData.length > 0 ? (
            <OrdersPieChart data={pieData} />
          ) : (
            <div className="py-8 text-center space-y-1">
              <p className="text-sm text-muted-foreground">Sin pedidos en el período.</p>
              <Link href="/dashboard/orders" className="text-xs text-primary hover:underline">Ver pedidos →</Link>
            </div>
          )}
        </div>
      </div>

      {/* ── Tablas ── */}
      <div className="grid md:grid-cols-2 gap-5">

        {/* Desglose pedidos */}
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-sm font-medium mb-4">Desglose de pedidos por estado</p>
          {err('orders') ? (
            <p className="text-sm text-muted-foreground">No se pudieron cargar los pedidos.</p>
          ) : orderRows.length === 0 ? (
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Sin pedidos en el período.</p>
              <Link href="/dashboard/orders" className="text-xs text-primary hover:underline">Ver pedidos →</Link>
            </div>
          ) : (
            <div className="space-y-2.5">
              {Object.entries(ordersAgg.byStatus).sort((a, b) => b[1] - a[1]).map(([status, count]) => (
                <div key={status} className="flex items-center justify-between">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${ORDER_STATUS_CHIP[status] ?? 'bg-muted text-muted-foreground border border-border'}`}>
                    {ORDER_STATUS_LABELS[status] ?? status}
                  </span>
                  <div className="flex items-center gap-3">
                    <div className="w-20 h-1.5 rounded-full bg-border overflow-hidden hidden sm:block">
                      <div className="h-full bg-primary rounded-full" style={{ width: `${Math.round((count / orderRows.length) * 100)}%` }} />
                    </div>
                    <span className="font-semibold text-sm w-6 text-right">{count}</span>
                  </div>
                </div>
              ))}
              <div className="pt-2 border-t border-border flex justify-between items-center">
                <span className="text-xs text-muted-foreground">Ingresos confirmados</span>
                <span className="font-bold text-primary text-sm">{cop(ordersAgg.deliveredRevenue)}</span>
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
          {err('orderItems') ? (
            <p className="text-sm text-muted-foreground">No se pudieron cargar los ítems vendidos.</p>
          ) : top.length === 0 ? (
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Sin ventas registradas en el período.</p>
              <Link href="/dashboard/orders" className="text-xs text-primary hover:underline">Ver pedidos →</Link>
            </div>
          ) : (
            <div className="space-y-3">
              {top.map((p, i) => (
                <div key={p.title} className="flex justify-between items-start gap-3">
                  <div className="flex gap-2 items-center min-w-0">
                    <span className={`shrink-0 h-5 w-5 rounded-full flex items-center justify-center text-[11px] font-bold ${
                      i === 0 ? 'bg-amber-500/20 text-amber-700' :
                      i === 1 ? 'bg-slate-500/20 text-slate-700' :
                      i === 2 ? 'bg-orange-500/20 text-orange-700' : 'bg-muted text-muted-foreground'
                    }`}>{i + 1}</span>
                    <p className="text-sm font-medium truncate">{p.title}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-sm font-semibold">{p.quantity} uds.</p>
                    <p className="text-xs text-muted-foreground">{cop(p.revenue)}</p>
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
          <span className="ml-auto text-xs text-muted-foreground">{err('claims') ? DASH : `${claimsAgg.total} en período`}</span>
        </div>

        {err('claims') ? (
          <p className="text-sm text-muted-foreground">No se pudieron cargar los reclamos.</p>
        ) : claimsAgg.total === 0 ? (
          <p className="text-sm text-muted-foreground">Sin reclamos en el período.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
              {[
                { label: 'Total reclamos',      value: claimsAgg.total,         color: 'text-red-700' },
                { label: 'Abiertos',            value: claimsAgg.open,          color: 'text-amber-700' },
                { label: 'Reembolsados',        value: claimsAgg.refundedCount, color: 'text-emerald-700' },
                { label: 'Tasa reclamo/pedido', value: `${claimRate}%`,         color: 'text-primary' },
              ].map(k => (
                <div key={k.label} className="rounded-lg border border-border p-3 text-center">
                  <p className={`text-xl font-bold ${k.color}`}>{k.value}</p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">{k.label}</p>
                </div>
              ))}
            </div>

            {claimsAgg.totalRefunded > 0 && (
              <p className="text-xs text-muted-foreground mb-4">
                Total reembolsado:{' '}
                <span className="font-semibold text-emerald-700">{cop(claimsAgg.totalRefunded)}</span>
              </p>
            )}

            {Object.keys(claimsAgg.byReason).length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">Por motivo</p>
                {Object.entries(claimsAgg.byReason).sort((a, b) => b[1] - a[1]).map(([reason, count]) => (
                  <div key={reason} className="flex items-center justify-between gap-3">
                    <span className="text-xs text-muted-foreground">{CLAIM_REASON_LABELS[reason] ?? reason}</span>
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 rounded-full bg-border overflow-hidden hidden sm:block">
                        <div className="h-full bg-red-700/50 rounded-full" style={{ width: `${Math.round((count / claimsAgg.total) * 100)}%` }} />
                      </div>
                      <span className="text-xs font-semibold w-4 text-right">{count}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
    </TooltipProvider>
  )
}
