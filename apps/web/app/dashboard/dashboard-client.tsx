'use client'

import { useState } from 'react'
import Link from 'next/link'
import {
  MessageSquare, Package, Users, ShoppingCart,
  Boxes, BarChart2, Plug, ArrowRight,
  AlertTriangle, UserCheck, Clock, TrendingUp,
  TrendingDown, Minus, Zap, Activity,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, LineChart, Line, CartesianGrid,
  AreaChart, Area,
} from 'recharts'

// ─── Tipos ────────────────────────────────────────────────────────────────────

export interface DashboardProps {
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
  messagesPerDay: { day: string; total: number }[]
  ordersByStatus: { status: string; count: number }[]
  quickLinks: { href: string; label: string; icon: string; desc: string }[]
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

const ORDER_STATUS_COLORS: Record<string, string> = {
  pending:    '#D4A843',
  confirmed:  '#38A875',
  processing: '#60a5fa',
  shipped:    '#a78bfa',
  delivered:  '#34d399',
  cancelled:  '#f87171',
}

const ORDER_STATUS_LABELS: Record<string, string> = {
  pending:    'Pendiente',
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

export default function DashboardClient({
  tenantName, userEmail, role, stats, ops,
  messagesPerDay, ordersByStatus, quickLinks,
}: DashboardProps) {
  const [tab, setTab] = useState<'operaciones' | 'negocio'>('operaciones')
  const canWrite = role === 'owner' || role === 'manager'

  const totalOpsAlerts = ops.humanTakeovers + ops.pendingOrders + ops.lowStockCount

  return (
    <div className="space-y-5 max-w-7xl">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-foreground tracking-tight">
            Bienvenido,{' '}
            <span className="text-gradient">{tenantName}</span>
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {userEmail} · {ROLE_LABELS[role] ?? role}
          </p>
        </div>
        {totalOpsAlerts > 0 && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-400/10 border border-amber-400/30 text-amber-300 text-sm font-medium">
            <Zap className="h-4 w-4 shrink-0" />
            <span>{totalOpsAlerts} alerta{totalOpsAlerts !== 1 ? 's' : ''} activa{totalOpsAlerts !== 1 ? 's' : ''}</span>
          </div>
        )}
      </div>

      {/* ── Tabs ──────────────────────────────────────────────────────────── */}
      <div className="flex gap-0.5 border-b border-border">
        {(['operaciones', 'negocio'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`relative px-4 py-2.5 text-sm font-medium capitalize transition-colors border-b-2 -mb-px flex items-center gap-2 ${
              tab === t
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
              <span className="ml-1 h-4 w-4 rounded-full bg-amber-400 text-[10px] font-bold text-black flex items-center justify-center">
                {totalOpsAlerts}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Tab: Operaciones ─────────────────────────────────────────────── */}
      {tab === 'operaciones' && (
        <div className="space-y-6 animate-in fade-in-0 slide-in-from-bottom-2 duration-300">

          {/* Alertas operacionales */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
            <OpsCard
              href="/dashboard/inbox"
              label="Conversaciones activas"
              value={ops.activeConversations}
              icon={MessageSquare}
              color="text-primary"
              description="Bot respondiendo"
            />
            <OpsCard
              href="/dashboard/inbox"
              label="Agente humano"
              value={ops.humanTakeovers}
              icon={UserCheck}
              color="text-amber-400"
              description="Requieren atención"
              urgent={ops.humanTakeovers > 0}
            />
            <OpsCard
              href="/dashboard/orders"
              label="Pedidos pendientes"
              value={ops.pendingOrders}
              icon={Clock}
              color="text-blue-400"
              description="Por confirmar"
              urgent={ops.pendingOrders > 0}
            />
            <OpsCard
              href="/dashboard/inventory"
              label="Bajo stock"
              value={ops.lowStockCount}
              icon={AlertTriangle}
              color="text-red-400"
              description="Variantes críticas"
              urgent={ops.lowStockCount > 0}
            />
          </div>

          {/* Acceso rápido */}
          <div>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-widest mb-3">
              Acceso rápido
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {quickLinks.map(({ href, label, icon, desc }) => {
                const Icon = ICON_MAP[icon] ?? Package
                return (
                  <Link
                    key={href}
                    href={href}
                    className="group relative rounded-xl border border-border bg-card p-4 shadow-sm hover:shadow-md hover:border-primary/40 transition-all duration-200 card-hover"
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
                )
              })}
            </div>
          </div>

          {/* Actividad reciente — mini gráfica inline */}
          {messagesPerDay.length > 0 && (
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between mb-4">
                <p className="text-sm font-medium text-foreground">Actividad de mensajes — 7 días</p>
                <span className="text-xs text-muted-foreground">Últimos 7 días</span>
              </div>
              <ResponsiveContainer width="100%" height={100}>
                <AreaChart data={messagesPerDay} margin={{ top: 0, right: 0, left: -30, bottom: 0 }}>
                  <defs>
                    <linearGradient id="msgGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#38A875" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#38A875" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="day" tick={{ fontSize: 10, fill: '#7A9490' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#7A9490' }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="total" stroke="#38A875" fill="url(#msgGrad)" strokeWidth={2} name="Mensajes" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* ── Tab: Negocio ──────────────────────────────────────────────────── */}
      {tab === 'negocio' && (
        <div className="space-y-6 animate-in fade-in-0 slide-in-from-bottom-2 duration-300">

          {/* KPI Cards con comparativa */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
            <KpiCard label="Conversaciones" value={stats.conversations} trend="neutral" />
            <KpiCard label="Pedidos"        value={stats.orders}        trend="neutral" />
            <KpiCard label="Contactos"      value={stats.contacts}      trend="neutral" />
            <KpiCard label="Productos"      value={stats.products}      trend="neutral" />
          </div>

          {/* Gráficas */}
          <div className="grid md:grid-cols-2 gap-5">

            {/* Mensajes por día — área */}
            <div className="rounded-xl border border-border bg-card p-5">
              <p className="text-sm font-medium text-foreground mb-4">Mensajes — últimos 7 días</p>
              {messagesPerDay.length > 0 ? (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={messagesPerDay} barSize={20} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="day" tick={{ fontSize: 11, fill: '#7A9490' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: '#7A9490' }} axisLine={false} tickLine={false} allowDecimals={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="total" fill="#38A875" radius={[4, 4, 0, 0]} name="Mensajes" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart label="Sin datos en los últimos 7 días" />
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
                        <Cell key={entry.status} fill={ORDER_STATUS_COLORS[entry.status] ?? '#7A9490'} />
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
                      wrapperStyle={{ fontSize: '11px', color: '#7A9490' }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <EmptyChart label="Sin pedidos registrados" />
              )}
            </div>
          </div>

          {/* Resumen de KPIs acumulados */}
          {canWrite && (
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
          )}
        </div>
      )}
    </div>
  )
}

// ─── Sub-componentes ──────────────────────────────────────────────────────────

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
  return (
    <Link
      href={href}
      className={`group rounded-xl border bg-card p-4 sm:p-5 shadow-sm hover:shadow-md transition-all duration-200 card-hover ${
        urgent ? 'border-primary/40 bg-primary/5' : 'border-border'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <Icon className={`h-4 w-4 ${color}`} />
        {urgent && <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />}
      </div>
      <p className={`text-2xl sm:text-3xl font-bold ${color}`}>{value}</p>
      <p className="text-xs font-medium text-foreground mt-1 leading-snug">{label}</p>
      <p className="text-xs text-muted-foreground leading-snug">{description}</p>
    </Link>
  )
}

function KpiCard({
  label, value, trend, trendValue,
}: {
  label: string
  value: number
  trend: 'up' | 'down' | 'neutral'
  trendValue?: string
}) {
  const TrendIcon = trend === 'up' ? TrendingUp : trend === 'down' ? TrendingDown : Minus
  const trendColor = trend === 'up' ? 'text-emerald-400' : trend === 'down' ? 'text-red-400' : 'text-muted-foreground'

  return (
    <div className="rounded-xl border border-border bg-card p-4 sm:p-5 shadow-sm">
      <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">{label}</p>
      <p className="text-2xl sm:text-3xl font-bold text-primary">{value}</p>
      <p className={`text-xs mt-1 flex items-center gap-1 ${trendColor}`}>
        <TrendIcon className="h-3 w-3" />
        {trendValue ?? 'Total acumulado'}
      </p>
    </div>
  )
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
      {label}
    </div>
  )
}
