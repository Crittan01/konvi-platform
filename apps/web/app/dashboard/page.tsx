import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import DashboardClient from './dashboard-client'

export default async function DashboardPage() {
  // Sem 5 perf: getCachedUser/Meta comparten cache con DashboardLayout
  // (mismo render tree). Ahorra 1 round-trip auth.getUser.
  const user = await getCachedUser()
  if (!user) redirect('/login')

  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = createClient()

  let tenantName = 'Tu tienda'
  let stats = { conversations: 0, orders: 0, contacts: 0, products: 0 }
  let ops = { activeConversations: 0, humanTakeovers: 0, pendingOrders: 0, lowStockCount: 0 }
  let messagesPerDay: { day: string; total: number }[] = []
  let ordersByStatus: { status: string; count: number }[] = []

  if (tenantId) {
    // ─── Queries en paralelo ──────────────────────────────────────────────────
    const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()

    // Primero obtenemos el tenant para sacar low_stock_threshold antes de las queries paralelas
    const tenantRes = await supabase
      .from('tenants')
      .select('name, low_stock_threshold')
      .eq('id', tenantId)
      .single()

    const lowStockThreshold = tenantRes.data?.low_stock_threshold ?? 5

    const [
      convRes,
      ordersRes,
      contactsRes,
      productsRes,
      activeConvRes,
      takeoverConvRes,
      pendingOrdersRes,
      lowStockRes,
      messagesRes,
      orderStatusRes,
    ] = await Promise.all([
      supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
      supabase.from('orders').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
      supabase.from('contacts').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
      supabase.from('products').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('status', 'active'),
      // Ops: conversaciones activas con bot
      supabase.from('conversations').select('id', { count: 'exact', head: true })
        .eq('tenant_id', tenantId).eq('status', 'bot_active'),
      // Ops: conversaciones en takeover humano
      supabase.from('conversations').select('id', { count: 'exact', head: true })
        .eq('tenant_id', tenantId).eq('status', 'human_takeover'),
      // Ops: pedidos pendientes
      supabase.from('orders').select('id', { count: 'exact', head: true })
        .eq('tenant_id', tenantId).eq('status', 'pending'),
      // Ops: variantes bajo umbral configurable del tenant (tenants.low_stock_threshold)
      supabase.from('product_variations').select('id', { count: 'exact', head: true })
        .eq('tenant_id', tenantId).lte('stock_quantity', lowStockThreshold),
      // Negocio: mensajes últimos 7 días con fecha
      supabase.from('messages').select('created_at')
        .eq('tenant_id', tenantId)
        .gte('created_at', sevenDaysAgo)
        .order('created_at', { ascending: true }),
      // Negocio: pedidos por estado
      supabase.from('orders').select('status').eq('tenant_id', tenantId),
    ])

    tenantName = tenantRes.data?.name ?? 'Tu tienda'

    stats = {
      conversations: convRes.count ?? 0,
      orders:        ordersRes.count ?? 0,
      contacts:      contactsRes.count ?? 0,
      products:      productsRes.count ?? 0,
    }

    ops = {
      activeConversations: activeConvRes.count ?? 0,
      humanTakeovers:      takeoverConvRes.count ?? 0,
      pendingOrders:       pendingOrdersRes.count ?? 0,
      lowStockCount:       lowStockRes.count ?? 0,
    }

    // Agrupar mensajes por día (formato "Lu", "Ma", etc.)
    const dayLabels = ['Do', 'Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá']
    const dayMap = new Map<string, number>()

    // Inicializar los últimos 7 días
    for (let i = 6; i >= 0; i--) {
      const d = new Date(Date.now() - i * 24 * 60 * 60 * 1000)
      const key = d.toISOString().split('T')[0]
      const label = dayLabels[d.getDay()]
      dayMap.set(key, 0)
    }

    for (const msg of messagesRes.data ?? []) {
      const key = (msg.created_at as string).split('T')[0]
      if (dayMap.has(key)) {
        dayMap.set(key, (dayMap.get(key) ?? 0) + 1)
      }
    }

    messagesPerDay = Array.from(dayMap.entries()).map(([dateStr, total]) => {
      const d = new Date(dateStr + 'T12:00:00')
      return { day: dayLabels[d.getDay()], total }
    })

    // Agrupar pedidos por estado
    const statusMap = new Map<string, number>()
    for (const order of orderStatusRes.data ?? []) {
      const s = (order as { status: string }).status
      statusMap.set(s, (statusMap.get(s) ?? 0) + 1)
    }
    ordersByStatus = Array.from(statusMap.entries()).map(([status, count]) => ({ status, count }))
  }

  const quickLinks = [
    { href: '/dashboard/inbox',         label: 'Inbox AI',      icon: 'MessageSquare', desc: 'Conversaciones WhatsApp', show: true },
    { href: '/dashboard/orders',         label: 'Pedidos',       icon: 'Package',       desc: 'Gestionar pedidos',       show: true },
    { href: '/dashboard/contacts',       label: 'Contactos',     icon: 'Users',         desc: 'Base de clientes',        show: true },
    { href: '/dashboard/catalog',        label: 'Catálogo',      icon: 'ShoppingCart',  desc: 'Productos activos',       show: canWrite },
    { href: '/dashboard/metrics',        label: 'Métricas',      icon: 'BarChart2',     desc: 'KPIs del negocio',        show: canWrite },
    { href: '/dashboard/integrations',   label: 'Integraciones', icon: 'Plug',          desc: 'MeLi · Envia',           show: role === 'owner' },
  ].filter(l => l.show).map(({ show: _show, ...rest }) => rest)

  return (
    <DashboardClient
      tenantId={tenantId ?? ''}
      tenantName={tenantName}
      userEmail={user.email ?? ''}
      role={role}
      stats={stats}
      ops={ops}
      messagesPerDay={messagesPerDay}
      ordersByStatus={ordersByStatus}
      quickLinks={quickLinks}
    />
  )
}
