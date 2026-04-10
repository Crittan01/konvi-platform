import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import Link from 'next/link'
import {
  MessageSquare, Package, Users, ShoppingCart,
  Boxes, BarChart2, Plug, ArrowRight,
} from 'lucide-react'

export default async function DashboardPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const meta = (user.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  let tenantName = 'Commerce Ops'
  let stats = { conversations: 0, orders: 0, contacts: 0, products: 0 }

  if (tenantId) {
    const [tenantRes, convRes, ordersRes, contactsRes, productsRes] = await Promise.all([
      supabase.from('tenants').select('name').eq('id', tenantId).single(),
      supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
      supabase.from('orders').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
      supabase.from('contacts').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
      supabase.from('products').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('status', 'active'),
    ])
    tenantName = tenantRes.data?.name ?? 'Commerce Ops'
    stats = {
      conversations: convRes.count ?? 0,
      orders:        ordersRes.count ?? 0,
      contacts:      contactsRes.count ?? 0,
      products:      productsRes.count ?? 0,
    }
  }

  const quickLinks = [
    { href: '/dashboard/inbox',    label: 'Inbox AI',     icon: MessageSquare, desc: 'Conversaciones WhatsApp', show: true },
    { href: '/dashboard/orders',   label: 'Pedidos',      icon: Package,       desc: 'Gestionar pedidos',       show: true },
    { href: '/dashboard/contacts', label: 'Contactos',    icon: Users,         desc: 'Base de clientes',        show: true },
    { href: '/dashboard/catalog',  label: 'Catálogo',     icon: ShoppingCart,  desc: 'Productos activos',       show: canWrite },
    { href: '/dashboard/inventory',label: 'Inventario',   icon: Boxes,         desc: 'Control de stock',        show: canWrite },
    { href: '/dashboard/metrics',  label: 'Métricas',     icon: BarChart2,     desc: 'KPIs del negocio',        show: canWrite },
    { href: '/dashboard/integrations', label: 'Integraciones', icon: Plug,     desc: 'MeLi · Envia',           show: role === 'owner' },
  ].filter(l => l.show)

  return (
    <div className="space-y-8 max-w-5xl">

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground tracking-tight">
          Bienvenido a{' '}
          <span className="text-gradient">{tenantName}</span>
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {user.email} · <span className="capitalize">{role}</span>
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Conversaciones',    value: stats.conversations, color: 'text-primary' },
          { label: 'Pedidos',           value: stats.orders,        color: 'text-primary' },
          { label: 'Contactos',         value: stats.contacts,      color: 'text-primary' },
          { label: 'Productos activos', value: stats.products,      color: 'text-primary' },
        ].map(kpi => (
          <div key={kpi.label} className="rounded-xl border border-border bg-card p-5 shadow-sm">
            <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">{kpi.label}</p>
            <p className={`text-3xl font-bold ${kpi.color}`}>{kpi.value}</p>
          </div>
        ))}
      </div>

      {/* Quick access */}
      <div>
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wide mb-3">
          Acceso rápido
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {quickLinks.map(({ href, label, icon: Icon, desc }) => (
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
          ))}
        </div>
      </div>

    </div>
  )
}
