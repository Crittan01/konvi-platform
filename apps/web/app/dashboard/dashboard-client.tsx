'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'
import {
  MessageSquare, Package, Users, ShoppingCart,
  Boxes, BarChart2, Plug, ArrowRight,
  AlertTriangle, UserCheck, Clock, Zap, Activity,
  RefreshCw, CheckCircle2, Circle, WifiOff, LayoutDashboard,
} from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, CartesianGrid,
  AreaChart, Area,
} from 'recharts'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { Carousel, CarouselContent, CarouselItem, CarouselDots } from '@/components/ui/carousel'
import { EASE_OUT, FadeIn, Pressable } from '@/components/ui/motion'
import { BentoCard, BentoGrid } from '@/components/ui/bento'
import { useCountUp } from '@/lib/use-count-up'
import { maybeCelebrateFromPayload } from './money-celebration'
import { formatCOP, formatCOPNegative } from './finance/lib/format'

// ─── Tipos ────────────────────────────────────────────────────────────────────

export interface DashboardProps {
  tenantId: string
  tenantName: string
  userEmail: string
  role: string
  stats: {
    conversations: number
    orders: number
    contacts: number
    products: number
  }
  ops: {
    activeConversations: number
    humanTakeovers: number
    pendingOrders: number
    lowStockCount: number
  }
  // BLOQUE G-2: ventas confirmadas (COP) — hoy y este mes. null = no disponible
  // (fallo del RPC) → la card muestra "—", nunca un $0 engañoso.
  revenue: {
    today: number | null
    month: number | null
  }
  lowStockThreshold: number
  messagesPerDay: { day: string; total: number }[]
  ordersByStatus: { status: string; count: number }[]
  quickLinks: { href: string; label: string; icon: string; desc: string }[]
  readError: boolean
  firstRun: boolean
  onboarding: { whatsapp: boolean; catalog: boolean; threshold: boolean }
}

// ─── Maps ─────────────────────────────────────────────────────────────────────

const ICON_MAP: Record<string, React.ElementType> = {
  MessageSquare, Package, Users, ShoppingCart, Boxes, BarChart2, Plug,
}

const ROLE_LABELS: Record<string, string> = {
  owner:    'Administrador',
  manager:  'Supervisor',
  operator: 'Gestor',
}

// Colores del pie de pedidos — tokens --chart-* theme-aware (globals.css);
// antes hex hardcodeados que no adaptaban a dark mode.
const ORDER_STATUS_COLORS: Record<string, string> = {
  pending:    'hsl(var(--chart-pending))',
  pending_payment: 'hsl(var(--chart-pending-payment))',  // F62: ámbar distinto de pending para el chart
  confirmed:  'hsl(var(--chart-confirmed))',
  processing: 'hsl(var(--chart-processing))',
  shipped:    'hsl(var(--chart-shipped))',
  delivered:  'hsl(var(--chart-delivered))',
  cancelled:  'hsl(var(--chart-cancelled))',
}

// Verde de actividad (mensajes) y gris de ticks/leyendas — mismos tokens.
const CHART_MESSAGES = 'hsl(var(--chart-messages))'
const CHART_NEUTRAL = 'hsl(var(--chart-neutral))'

const ORDER_STATUS_LABELS: Record<string, string> = {
  pending:    'Pendiente',
  pending_payment: 'Esperando pago',  // F62: órdenes bot con link Wompi
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

// ─── Tooltip personalizado ────────────────────────────────────────────────────

const CustomTooltip = ({ active, payload, label }: {
  active?: boolean
  payload?: { value: number; name: string }[]
  label?: string
}) => {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-border bg-card px-3 py-2 shadow-xl text-xs">
      <p className="text-muted-foreground mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="font-semibold text-foreground">
          {p.value} <span className="text-muted-foreground font-normal">{p.name}</span>
        </p>
      ))}
    </div>
  )
}

// ─── Componente Principal ─────────────────────────────────────────────────────

const TABS = ['operaciones', 'negocio'] as const
type Tab = (typeof TABS)[number]

export default function DashboardClient({
  tenantId, tenantName, userEmail, role, stats, ops, revenue, lowStockThreshold,
  messagesPerDay, ordersByStatus, quickLinks, readError, firstRun, onboarding,
}: DashboardProps) {
  const [tab, setTab] = useState<Tab>('operaciones')
  const canWrite = role === 'owner' || role === 'manager'
  const router = useRouter()

  // Estado del canal realtime: 'connected' | 'reconnecting' | 'down'. El topbar
  // 'Live' del layout es estático; aquí sí reflejamos el estado real del canal.
  const [rtState, setRtState] = useState<'connected' | 'reconnecting' | 'down'>('connected')

  // router.refresh() re-ejecuta ~22 queries SSR; una ráfaga de N eventos realtime
  // debe coalescerse en un solo refresh (debounce), no N renders consecutivos.
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const debouncedRefresh = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current)
    refreshTimer.current = setTimeout(() => router.refresh(), 700)
  }, [router])

  useEffect(() => {
    if (!tenantId) return
    const supabase = createClient()
    const channel = supabase.channel(`dashboard_ops_${tenantId}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'conversations', filter: `tenant_id=eq.${tenantId}` }, debouncedRefresh)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'orders', filter: `tenant_id=eq.${tenantId}` }, (payload) => {
        // T7.4 — micro-celebración de dinero: transición a confirmed/delivered
        // (dedupe por orden+estado; REPLICA IDENTITY FULL da old.status).
        maybeCelebrateFromPayload(payload as never)
        debouncedRefresh()
      })
      .subscribe((status) => {
        // Sin callback, CHANNEL_ERROR/TIMED_OUT pasaban invisibles y la UI seguía
        // prometiendo tiempo real con el canal caído.
        if (status === 'SUBSCRIBED') setRtState('connected')
        else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') {
          console.warn('[dashboard] canal realtime en fallo:', status)
          setRtState('down')
        } else if (status === 'CLOSED') setRtState('reconnecting')
      })
    return () => {
      if (refreshTimer.current) clearTimeout(refreshTimer.current)
      supabase.removeChannel(channel)
    }
  }, [tenantId, debouncedRefresh])

  // BLOQUE G-1: polling fallback. Si el canal realtime cae ('down'/'reconnecting'),
  // refrescar periódicamente para que el home no se congele (antes rtState='down'
  // solo pintaba un indicador WifiOff; los datos quedaban estáticos hasta recargar).
  // Solo activo mientras el canal NO está sano → sin costo en el camino feliz.
  useEffect(() => {
    if (rtState === 'connected' || !tenantId) return
    const id = setInterval(() => router.refresh(), 30_000)
    return () => clearInterval(id)
  }, [rtState, tenantId, router])

  const totalOpsAlerts = ops.humanTakeovers + ops.pendingOrders + ops.lowStockCount

  // Navegación por flechas entre tabs (accesibilidad WAI-ARIA tabs).
  const onTabKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const idx = TABS.indexOf(tab)
    const next = e.key === 'ArrowRight' ? (idx + 1) % TABS.length : (idx - 1 + TABS.length) % TABS.length
    setTab(TABS[next])
  }

  return (
    <div className="space-y-5 max-w-7xl">

      {/* ── Header — cabecera de módulo con identidad (firma Kaiu, T7.12).
              El saludo "Bienvenido, {tenant}" ES el header del home. ──────── */}
      <PageHeader
        icon={LayoutDashboard}
        title={
          <>
            Bienvenido,{' '}
            <span className="text-gradient">{tenantName}</span>
          </>
        }
        description={`${userEmail} · ${ROLE_LABELS[role] ?? role}`}
        actions={
          <div className="flex items-center gap-2">
            {rtState !== 'connected' && (
              <span className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-muted text-muted-foreground text-xs font-medium" title="El canal de tiempo real se reconecta; los datos pueden tardar en actualizarse.">
                <WifiOff className="h-3.5 w-3.5" />
                {rtState === 'down' ? 'Sin tiempo real' : 'Reconectando…'}
              </span>
            )}
            {totalOpsAlerts > 0 && (
              <button
                type="button"
                onClick={() => setTab('operaciones')}
                className="flex items-center gap-2 px-3 py-2 rounded-xl bg-warning-bg border border-warning-border text-warning-fg text-sm font-medium shadow-xs hover:bg-warning-bg transition-colors"
              >
                <Zap className="h-4 w-4 shrink-0" />
                <span>Ver {totalOpsAlerts} alerta{totalOpsAlerts !== 1 ? 's' : ''} activa{totalOpsAlerts !== 1 ? 's' : ''}</span>
              </button>
            )}
          </div>
        }
      />

      {/* ── Aviso de error de lectura: NO pintar falsos ceros como verdad ──── */}
      {readError && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>Algunos datos no se pudieron cargar</AlertTitle>
          <AlertDescription className="flex flex-col gap-2">
            <span>Las cifras de abajo pueden estar incompletas. No las tomes como definitivas.</span>
            <button
              type="button"
              onClick={() => router.refresh()}
              className="inline-flex items-center gap-1.5 self-start rounded-lg border border-danger-border px-2.5 py-1 text-xs font-medium text-danger-fg hover:bg-danger-bg transition-colors"
            >
              <RefreshCw className="h-3 w-3" /> Reintentar
            </button>
          </AlertDescription>
        </Alert>
      )}

      {/* ── Onboarding de primer uso ──────────────────────────────────────── */}
      {firstRun && (
        <div className="rounded-xl border border-primary/25 bg-primary/5 p-5">
          <div className="flex items-start gap-3">
            <div className="h-9 w-9 rounded-lg bg-primary/15 flex items-center justify-center shrink-0">
              <Zap className="h-5 w-5 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-sm font-semibold text-foreground">Pon tu tienda en marcha</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                Completa estos 3 pasos para que tu bot empiece a vender por WhatsApp.
              </p>
              <ul className="mt-4 space-y-2.5">
                <OnboardingStep
                  done={onboarding.whatsapp}
                  href="/dashboard/integrations"
                  title="Conecta WhatsApp"
                  desc="Vincula tu número oficial para recibir conversaciones."
                />
                <OnboardingStep
                  done={onboarding.catalog}
                  href={canWrite ? '/dashboard/catalog' : undefined}
                  title="Carga tu catálogo"
                  desc="Agrega productos y variantes con stock y precio."
                />
                <OnboardingStep
                  done={onboarding.threshold}
                  href={canWrite ? '/dashboard/catalog' : undefined}
                  title="Configura tu umbral de stock bajo"
                  desc="Define desde qué cantidad una variante se marca como crítica."
                />
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* ── Tabs ──────────────────────────────────────────────────────────── */}
      <div role="tablist" aria-label="Vistas del panel" className="flex gap-0.5 border-b border-border">
        {TABS.map(t => {
          const selected = tab === t
          return (
            <button
              key={t}
              role="tab"
              id={`dash-tab-${t}`}
              aria-selected={selected}
              aria-controls={`dash-panel-${t}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setTab(t)}
              onKeyDown={onTabKeyDown}
              className={`relative px-4 py-2.5 text-sm font-medium capitalize transition-colors border-b-2 -mb-px flex items-center gap-2 ${
                selected
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {t === 'operaciones' ? (
                <><Activity className="h-3.5 w-3.5" /> Operaciones</>
              ) : (
                <><BarChart2 className="h-3.5 w-3.5" /> Negocio</>
              )}
              {t === 'operaciones' && totalOpsAlerts > 0 && (
                <span className="ml-1 h-4 min-w-4 px-1 rounded-full bg-warning-bg text-[10px] font-bold text-warning-fg border border-warning-border flex items-center justify-center">
                  {totalOpsAlerts}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* ── Tab: Operaciones ─────────────────────────────────────────────── */}
      {tab === 'operaciones' && (
        <div
          role="tabpanel"
          id="dash-panel-operaciones"
          aria-labelledby="dash-tab-operaciones"
          className="space-y-6 animate-in fade-in-0 slide-in-from-bottom-2 duration-300"
        >

          {/* BLOQUE G-2: dinero real a la vista en el home operativo.
              BentoGrid: cascada de entrada (§4.1); las cards de dinero llevan
              span=2 (mayor jerarquía del home) → fila completa en ≥lg. */}
          <BentoGrid>
            <MoneyKpiCard label="Ventas hoy" value={revenue.today} />
            <MoneyKpiCard label="Ventas este mes" value={revenue.month} />
          </BentoGrid>

          {/* Alertas operacionales — Spec WOW §4.5: en < lg carrusel horizontal
              con snap + dots (embla); en ≥ lg BentoGrid con cascada (§4.1).
              Mismas cards. */
          }
          {(() => {
            // BLOQUE G-1: cada card deep-linkea con el filtro que la alerta promete
            // → el operador aterriza en la vista ya filtrada (no re-buscar).
            const opsCards = [
              {
                href: '/dashboard/inbox?status=bot_active',
                label: 'Conversaciones activas',
                value: ops.activeConversations,
                icon: MessageSquare,
                color: 'text-primary',
                description: 'Bot respondiendo',
                urgent: false,
              },
              {
                href: '/dashboard/inbox?status=human_takeover',
                label: 'Agente humano',
                value: ops.humanTakeovers,
                icon: UserCheck,
                color: 'text-warning-fg',
                description: 'Requieren atención',
                urgent: ops.humanTakeovers > 0,
              },
              {
                href: '/dashboard/orders?status=pending',
                label: 'Pedidos pendientes',
                value: ops.pendingOrders,
                icon: Clock,
                color: 'text-info-fg',
                description: 'Por confirmar',
                urgent: ops.pendingOrders > 0,
              },
              {
                href: '/dashboard/catalog?filter=low_stock',
                label: 'Productos con poco stock',
                value: ops.lowStockCount,
                icon: AlertTriangle,
                color: 'text-danger-fg',
                description: `Stock entre 1 y ${lowStockThreshold} u.`,
                urgent: ops.lowStockCount > 0,
              },
            ]
            return (
              <>
                <BentoGrid className="hidden lg:grid gap-3 sm:gap-4">
                  {opsCards.map(c => <OpsCard key={c.href} {...c} />)}
                </BentoGrid>
                <div className="lg:hidden">
                  <Carousel opts={{ align: 'start', containScroll: 'trimSnaps', dragFree: true, loop: false }}>
                    <CarouselContent className="-ml-3">
                      {opsCards.map(c => (
                        <CarouselItem key={c.href} className="pl-3 basis-[68%] sm:basis-[42%]">
                          <OpsCard {...c} />
                        </CarouselItem>
                      ))}
                    </CarouselContent>
                    <CarouselDots labels={opsCards.map(c => c.label)} />
                  </Carousel>
                </div>
              </>
            )
          })()}

          {/* Acceso rápido */}
          <div>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-widest mb-3">
              Acceso rápido
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {quickLinks.map(({ href, label, icon, desc }) => {
                const Icon = ICON_MAP[icon] ?? Package
                return (
                  // Pressable (Spec WOW §4.2): lift en hover / compresión en tap
                  // con reduced-motion respetado. Reemplaza al transform de
                  // card-hover (conflicto con framer); borde/sombra quedan en CSS.
                  <Pressable key={href} className="h-full">
                    <Link
                      href={href}
                      className="group relative block h-full rounded-xl border border-border bg-card p-4 shadow-xs hover:shadow-md hover:border-primary/40 transition-[border-color,box-shadow] duration-200"
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                          <Icon className="h-4 w-4 text-primary" />
                        </div>
                        <ArrowRight className="h-3 w-3 text-muted-foreground opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                      </div>
                      <p className="text-sm font-medium text-foreground">{label}</p>
                      <p className="text-xs text-muted-foreground mt-0.5 leading-snug">{desc}</p>
                    </Link>
                  </Pressable>
                )
              })}
            </div>
          </div>

          {/* Actividad reciente — mini gráfica inline. Entra como cola de la
              coreografía del home (KPIs bento → quick links → chart): FadeIn
              con delay en vez de aparecer de golpe. La animación interna de
              recharts queda intacta (corre en paralelo al fade). */}
          {messagesPerDay.some(d => d.total > 0) && (
            <FadeIn transition={{ duration: 0.2, ease: EASE_OUT, delay: 0.25 }}>
              <div className="rounded-xl border border-border bg-card p-5">
              <p className="text-sm font-medium text-foreground mb-4">Actividad de mensajes — últimos 7 días</p>
              <ResponsiveContainer width="100%" height={100}>
                <AreaChart data={messagesPerDay} margin={{ top: 0, right: 0, left: -30, bottom: 0 }}>
                  <defs>
                    <linearGradient id="msgGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={CHART_MESSAGES} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={CHART_MESSAGES} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="day" tick={{ fontSize: 10, fill: CHART_NEUTRAL }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: CHART_NEUTRAL }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="total" stroke={CHART_MESSAGES} fill="url(#msgGrad)" strokeWidth={2} name="Mensajes" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
              </div>
            </FadeIn>
          )}
        </div>
      )}

      {/* ── Tab: Negocio ──────────────────────────────────────────────────── */}
      {tab === 'negocio' && (
        <div
          role="tabpanel"
          id="dash-panel-negocio"
          aria-labelledby="dash-tab-negocio"
          className="space-y-6 animate-in fade-in-0 slide-in-from-bottom-2 duration-300"
        >

          {/* BLOQUE G-2: dinero real — ventas NETAS (confirmadas − reembolsos). Antes
              el tab Negocio no tenía un solo KPI de dinero, solo counts acumulados →
              no era control de negocio real. BentoGrid: cascada + span=2 (§4.1). */}
          <BentoGrid>
            <MoneyKpiCard label="Ventas hoy" value={revenue.today} />
            <MoneyKpiCard label="Ventas este mes" value={revenue.month} />
          </BentoGrid>

          {/* Totales acumulados — mismo patrón §4.5: carrusel < lg, BentoGrid ≥ lg */}
          {(() => {
            const kpiCards = [
              { label: 'Conversaciones', value: stats.conversations },
              { label: 'Pedidos',        value: stats.orders },
              { label: 'Contactos',      value: stats.contacts },
              { label: 'Productos',      value: stats.products },
            ]
            return (
              <>
                <BentoGrid className="hidden lg:grid gap-3 sm:gap-4">
                  {kpiCards.map(c => <KpiCard key={c.label} {...c} />)}
                </BentoGrid>
                <div className="lg:hidden">
                  <Carousel opts={{ align: 'start', containScroll: 'trimSnaps', dragFree: true, loop: false }}>
                    <CarouselContent className="-ml-3">
                      {kpiCards.map(c => (
                        <CarouselItem key={c.label} className="pl-3 basis-[55%] sm:basis-[38%]">
                          <KpiCard {...c} />
                        </CarouselItem>
                      ))}
                    </CarouselContent>
                    <CarouselDots labels={kpiCards.map(c => c.label)} />
                  </Carousel>
                </div>
              </>
            )
          })()}

          {/* Gráficas — entrada coreografiada (cola de la escena del tab:
              KPIs bento → charts). FadeIn con delay; recharts anima sus datos
              en paralelo (isAnimationActive intacto). */}
          <FadeIn transition={{ duration: 0.2, ease: EASE_OUT, delay: 0.25 }}>
          <div className="grid md:grid-cols-2 gap-5">

            {/* Mensajes por día — barras */}
            <div className="rounded-xl border border-border bg-card p-5">
              <p className="text-sm font-medium text-foreground mb-4">Mensajes — últimos 7 días</p>
              {messagesPerDay.some(d => d.total > 0) ? (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={messagesPerDay} barSize={20} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="day" tick={{ fontSize: 11, fill: CHART_NEUTRAL }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: CHART_NEUTRAL }} axisLine={false} tickLine={false} allowDecimals={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="total" fill={CHART_MESSAGES} radius={[4, 4, 0, 0]} name="Mensajes" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart label="Sin mensajes en los últimos 7 días" />
              )}
            </div>

            {/* Pedidos por estado — pie */}
            <div className="rounded-xl border border-border bg-card p-5">
              <p className="text-sm font-medium text-foreground mb-4">Pedidos por estado</p>
              {ordersByStatus.length > 0 ? (
                <ResponsiveContainer width="100%" height={180}>
                  <PieChart>
                    <Pie
                      data={ordersByStatus}
                      dataKey="count"
                      nameKey="status"
                      cx="50%"
                      cy="50%"
                      outerRadius={65}
                      innerRadius={30}
                      strokeWidth={0}
                    >
                      {ordersByStatus.map((entry) => (
                        <Cell key={entry.status} fill={ORDER_STATUS_COLORS[entry.status] ?? CHART_NEUTRAL} />
                      ))}
                    </Pie>
                    <Tooltip
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null
                        const { name, value } = payload[0].payload
                        return (
                          <div className="rounded-xl border border-border bg-card px-3 py-2 shadow-xl text-xs">
                            <p className="font-semibold text-foreground">
                              {ORDER_STATUS_LABELS[String(name)] ?? name}: {String(value)}
                            </p>
                          </div>
                        )
                      }}
                    />
                    <Legend
                      formatter={(value: string) => ORDER_STATUS_LABELS[value] ?? value}
                      iconSize={8}
                      wrapperStyle={{ fontSize: '11px', color: CHART_NEUTRAL }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart label="Sin pedidos registrados" />
              )}
            </div>
          </div>
          </FadeIn>

          {/* Resumen de KPIs acumulados — derivado de cifras ya visibles arriba,
              no protege nada por rol (antes gated tras canWrite sin motivo).
              Cierra la escena del tab tras las gráficas (delay 0.35). */}
          <FadeIn transition={{ duration: 0.2, ease: EASE_OUT, delay: 0.35 }}>
          <div className="rounded-xl border border-border bg-card p-5">
            <p className="text-sm font-medium text-foreground mb-4">Resumen general del negocio</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {[
                { label: 'Tasa de conversión', value: stats.conversations > 0 ? `${Math.round((stats.orders / stats.conversations) * 100)}%` : '0%', note: 'Conv → Pedido' },
                { label: 'Promedio pedidos', value: stats.contacts > 0 ? `${(stats.orders / stats.contacts).toFixed(1)}` : '0', note: 'por contacto' },
                { label: 'Productos activos', value: String(stats.products), note: 'en catálogo' },
                { label: 'Contactos totales', value: String(stats.contacts), note: 'registrados' },
              ].map(item => (
                <div key={item.label} className="text-center">
                  <p className="text-2xl font-bold text-primary">{item.value}</p>
                  <p className="text-xs font-medium text-foreground mt-1">{item.label}</p>
                  <p className="text-xs text-muted-foreground">{item.note}</p>
                </div>
              ))}
            </div>
          </div>
          </FadeIn>
        </div>
      )}
    </div>
  )
}

// ─── Sub-componentes ──────────────────────────────────────────────────────────

function OnboardingStep({
  done, href, title, desc,
}: {
  done: boolean
  href?: string
  title: string
  desc: string
}) {
  const inner = (
    <div className="flex items-start gap-3">
      {done
        ? <CheckCircle2 className="h-5 w-5 text-success-fg shrink-0 mt-0.5" />
        : <Circle className="h-5 w-5 text-muted-foreground shrink-0 mt-0.5" />}
      <div className="min-w-0">
        <p className={`text-sm font-medium ${done ? 'text-muted-foreground line-through' : 'text-foreground'}`}>{title}</p>
        {!done && <p className="text-xs text-muted-foreground leading-snug">{desc}</p>}
      </div>
      {!done && href && <ArrowRight className="h-4 w-4 text-primary shrink-0 ml-auto mt-0.5" />}
    </div>
  )
  if (done || !href) return <li>{inner}</li>
  return (
    <li>
      <Link href={href} className="block rounded-lg -mx-2 px-2 py-1 hover:bg-primary/10 transition-colors">
        {inner}
      </Link>
    </li>
  )
}

function OpsCard({
  href, label, value, icon: Icon, color, description, urgent = false,
}: {
  href: string
  label: string
  value: number
  icon: React.ElementType
  color: string
  description: string
  urgent?: boolean
}) {
  // Count-up (Spec WOW §4.7): rAF con reduced-motion → valor final directo.
  const animated = useCountUp(value)
  return (
    // BentoCard interactive: la card NAVEGA al click (deep-link con filtro) →
    // hover con elevación vía card-hover (F1 — patrón DS para cards
    // interactivas). El chrome (borde/fondo/sombra + tinte urgent) vive en el
    // Card; el Link queda como área clickable. Dentro de BentoGrid entra en
    // cascada (StaggerItem); en el carrusel <lg no hay StaggerList padre →
    // estática.
    <BentoCard
      interactive
      className={`rounded-xl ${urgent ? 'border-primary/40 bg-primary/5' : ''}`}
    >
      <Link
        href={href}
        className="group block h-full rounded-xl p-4 sm:p-5"
      >
        <div className="flex items-center justify-between mb-2">
          <Icon className={`h-4 w-4 ${color}`} />
          {urgent && <span className="h-2 w-2 rounded-full bg-warning-fg animate-pulse" />}
        </div>
        <p className={`text-2xl sm:text-3xl font-bold tabular-nums ${color}`}>{Math.round(animated)}</p>
        <p className="text-xs font-medium text-foreground mt-1 leading-snug">{label}</p>
        <p className="text-xs text-muted-foreground leading-snug">{description}</p>
      </Link>
    </BentoCard>
  )
}

function KpiCard({ label, value }: { label: string; value: number }) {
  const animated = useCountUp(value)
  return (
    // BentoCard estática (no navega → sin card-hover, F1). Mismo chrome de
    // antes (rounded-xl border bg-card p-4 sm:p-5 shadow-xs h-full); dentro
    // de BentoGrid entra en cascada, en el carrusel <lg queda estática.
    <BentoCard className="rounded-xl p-4 sm:p-5">
      <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">{label}</p>
      <p className="text-2xl sm:text-3xl font-bold text-primary tabular-nums">{Math.round(animated)}</p>
      <p className="text-xs mt-1 text-muted-foreground">Total acumulado</p>
    </BentoCard>
  )
}

// BLOQUE G-2: KPI de dinero (ventas NETAS = confirmadas − reembolsos). Verde =
// dinero, coherente con el P&L de Finanzas (netProfit emerald-700). formatCOP para
// moneda COP consistente. Puede ser negativo si los reembolsos superan las ventas.
function MoneyKpiCard({ label, value }: { label: string; value: number | null }) {
  // Neto negativo (reembolsos > ventas en la ventana): rojo + signo explícito
  // (formatCOPNegative → "-$X"), no el verde de dinero con "$-X" malformado.
  const negative = value !== null && value < 0
  const border = negative ? 'border-danger-border bg-danger-bg' : 'border-success-border bg-success-bg'
  const text = negative ? 'text-danger-fg' : 'text-success-fg'
  const animated = useCountUp(value ?? 0)
  return (
    // BentoCard estática (no navega → sin card-hover, F1) con span=2: el
    // dinero es la card de mayor jerarquía del bento → 2 col en ≥lg.
    <BentoCard span={2} className={`rounded-xl p-4 sm:p-5 ${border}`}>
      <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">{label}</p>
      <p className={`text-2xl sm:text-3xl font-bold tabular-nums ${text}`}>
        {value === null ? '—' : negative ? formatCOPNegative(Math.round(animated)) : formatCOP(Math.round(animated))}
      </p>
      <p className="text-xs mt-1 text-muted-foreground">
        {value === null ? 'No disponible' : 'Neto de reembolsos'}
      </p>
    </BentoCard>
  )
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
      {label}
    </div>
  )
}
