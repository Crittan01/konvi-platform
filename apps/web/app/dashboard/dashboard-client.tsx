'use client'

import { useState } from 'react'
import Link from 'next/link'
import {
  MessageSquare, Package, Users, ShoppingCart,
  Boxes, BarChart2, Plug, ArrowRight,
  AlertTriangle, UserCheck, Clock, TrendingUp,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'

// ─── Tipos ────────────────────────────────────────────────────────────────────

export interface DashboardProps {
  tenantName: string
  userEmail: string
  role: string
  // Datos tab Negocio
  stats: {
    conversations: number
    orders: number
    contacts: number
    products: number
  }
  // Datos tab Operaciones
  ops: {
    activeConversations: number
    humanTakeovers: number
    pendingOrders: number
    lowStockCount: number
  }
  // Gráfica: mensajes por día (últimos 7 días)
  messagesPerDay: { day: string; total: number }[]
  // Gráfica: pedidos por estado
  ordersByStatus: { status: string; count: number }[]
  // Quick links config
  quickLinks: { href: string; label: string; icon: string; desc: string }[]
}

// ─── Icon map para quick links (pasar el nombre como string desde Server Component) ─

const ICON_MAP: Record<string, React.ElementType> = {
  MessageSquare,
  Package,
  Users,
  ShoppingCart,
  Boxes,
  BarChart2,
  Plug,
}

// ─── Colores por estado de pedido ─────────────────────────────────────────────

const ORDER_STATUS_COLORS: Record<string, string> = {
  pending:    '#D4A843',   // ámbar
  confirmed:  '#38A875',   // verde
  processing: '#60a5fa',   // azul
  shipped:    '#a78bfa',   // morado
  delivered:  '#34d399',   // verde claro
  cancelled:  '#f87171',   // rojo
}

const ORDER_STATUS_LABELS: Record<string, string> = {
  pending:    'Pendiente',
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

// ─── Componente Principal ─────────────────────────────────────────────────────

export default function DashboardClient({
  tenantName, userEmail, role, stats, ops,
  messagesPerDay, ordersByStatus, quickLinks,
}: DashboardProps) {
  const [tab, setTab] = useState<'operaciones' | 'negocio'>('operaciones')

  const canWrite = role === 'owner' || role === 'manager'

  return (
    <div className="space-y-6 max-w-5xl">

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground tracking-tight">
          Bienvenido a{' '}
          <span className="text-gradient">{tenantName}</span>
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {userEmail} · <span className="capitalize">{role}</span>
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {(['operaciones', 'negocio'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize transition-colors border-b-2 -mb-px ${
              tab === t
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
          >
            {t === 'operaciones' ? '⚡ Operaciones' : '📊 Negocio'}
          </button>
        ))}
      </div>

      {/* ── Tab: Operaciones ────────────────────────────────────────────────── */}
      {tab === 'operaciones' && (
        <div className="space-y-6">

          {/* Alertas operacionales */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <OpsCard
              href="/dashboard/inbox"
              label="Conversaciones activas"
              value={ops.activeConversations}
              icon={MessageSquare}
              color="text-primary"
              description="Con bot respondiendo"
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

          {/* Quick links */}
          <div>
            <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-3">
              Acceso rápido
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {quickLinks.map(({ href, label, icon, desc }) => {
                const Icon = ICON_MAP[icon] ?? Package
                return (
                  <Link
                    key={href}
                    href={href}
                    className="group relative rounded-xl border border-border bg-card p-4 shadow-sm hover:shadow-md hover:border-primary/30 transition-all duration-200 card-hover"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                        <Icon className="h-4 w-4 text-primary" />
                      </div>
                      <ArrowRight className="h-3 w-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                    <p className="text-sm font-medium text-foreground">{label}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
                  </Link>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab: Negocio ────────────────────────────────────────────────────── */}
      {tab === 'negocio' && (
        <div className="space-y-6">

          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Conversaciones',    value: stats.conversations },
              { label: 'Pedidos',           value: stats.orders },
              { label: 'Contactos',         value: stats.contacts },
              { label: 'Productos activos', value: stats.products },
            ].map(kpi => (
              <div key={kpi.label} className="rounded-xl border border-border bg-card p-5 shadow-sm">
                <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">{kpi.label}</p>
                <p className="text-3xl font-bold text-primary">{kpi.value}</p>
                <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                  <TrendingUp className="h-3 w-3" />
                  Total acumulado
                </p>
              </div>
            ))}
          </div>

          {/* Gráficas */}
          <div className="grid md:grid-cols-2 gap-6">

            {/* Mensajes por día — últimos 7 días */}
            <div className="rounded-xl border border-border bg-card p-5">
              <p className="text-sm font-medium text-foreground mb-4">Mensajes — últimos 7 días</p>
              {messagesPerDay.length > 0 ? (
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={messagesPerDay} barSize={24}>
                    <XAxis
                      dataKey="day"
                      tick={{ fontSize: 11, fill: '#7A9490' }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: '#7A9490' }}
                      axisLine={false}
                      tickLine={false}
                      allowDecimals={false}
                    />
                    <Tooltip
                      contentStyle={{
                        background: '#1E2624',
                        border: '1px solid #2A3533',
                        borderRadius: '8px',
                        fontSize: '12px',
                      }}
                      labelStyle={{ color: '#F0EDE8' }}
                      itemStyle={{ color: '#38A875' }}
                    />
                    <Bar dataKey="total" fill="#38A875" radius={[4, 4, 0, 0]} name="Mensajes" />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
                  Sin datos en los últimos 7 días
                </div>
              )}
            </div>

            {/* Pedidos por estado — pie chart */}
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
                      labelLine={false}
                    >
                      {ordersByStatus.map((entry) => (
                        <Cell
                          key={entry.status}
                          fill={ORDER_STATUS_COLORS[entry.status] ?? '#7A9490'}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        background: '#1E2624',
                        border: '1px solid #2A3533',
                        borderRadius: '8px',
                        fontSize: '12px',
                      }}
                      formatter={(value, name) => [
                        value,
                        ORDER_STATUS_LABELS[String(name)] ?? name,
                      ]}
                    />
                    <Legend
                      formatter={(value: string) => ORDER_STATUS_LABELS[value] ?? value}
                      iconSize={10}
                      wrapperStyle={{ fontSize: '11px' }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
                  Sin pedidos registrados
                </div>
              )}
            </div>

          </div>
        </div>
      )}

    </div>
  )
}

// ─── OpsCard ──────────────────────────────────────────────────────────────────

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
      className={`group rounded-xl border bg-card p-5 shadow-sm hover:shadow-md transition-all duration-200 card-hover ${
        urgent ? 'border-primary/40 bg-primary/5' : 'border-border'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <Icon className={`h-4 w-4 ${color}`} />
        {urgent && (
          <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" />
        )}
      </div>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
      <p className="text-xs font-medium text-foreground mt-1">{label}</p>
      <p className="text-xs text-muted-foreground">{description}</p>
    </Link>
  )
}
