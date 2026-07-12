import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import DashboardClient from './dashboard-client'
import { AlertTriangle } from 'lucide-react'
import { buildQuickLinks, messageDayBuckets, ORDER_STATUSES } from './dashboard-logic'

export default async function DashboardPage() {
  // Sem 5 perf: getCachedUser/Meta comparten cache con DashboardLayout
  // (mismo render tree). Ahorra 1 round-trip auth.getUser.
  const user = await getCachedUser()
  if (!user) redirect('/login')

  const { tenantId, role } = await getCachedTenantMeta()

  // cached-user.ts:59 — un usuario sin tenant_id es malformado; el caller DEBE
  // rechazarlo, no renderizar la consola vacía en ceros (falso "todo en 0").
  if (!tenantId) {
    console.error('[dashboard] usuario sin tenant_id — cuenta malformada', { userId: user.id })
    return (
      <div className="flex items-center justify-center p-12">
        <div className="max-w-md w-full rounded-xl border border-amber-700/25 bg-amber-500/10 p-6 text-center space-y-3">
          <div className="flex justify-center">
            <div className="h-12 w-12 rounded-full bg-amber-500/15 flex items-center justify-center">
              <AlertTriangle className="h-6 w-6 text-amber-700" />
            </div>
          </div>
          <h2 className="text-lg font-semibold text-foreground">Tu cuenta no tiene una tienda asignada</h2>
          <p className="text-sm text-amber-800">
            {user.email} está autenticado pero no está vinculado a ningún tenant.
            Contacta al administrador de la plataforma para completar la asignación.
          </p>
        </div>
      </div>
    )
  }

  const supabase = await createClient()

  // ─── Ronda 0: tenant (threshold + nombre) antes de las queries dependientes ──
  const tenantRes = await supabase
    .from('tenants')
    .select('name, low_stock_threshold')
    .eq('id', tenantId)
    .single()

  if (tenantRes.error) console.error('[dashboard] fallo cargando tenant', tenantRes.error.message)
  const tenantName = tenantRes.data?.name ?? 'Tu tienda'
  const lowStockThreshold = tenantRes.data?.low_stock_threshold ?? 5
  const thresholdConfigured = tenantRes.data?.low_stock_threshold != null

  // Buckets de día (hora Colombia) y estados de pedido: se cuenta POR bucket con
  // head:true (sin traer filas) → exacto y acotado. Evita el fetch-all que
  // PostgREST trunca a 1000 sin avisar (data-fetching.md §1).
  const dayBuckets = messageDayBuckets(7)

  const [
    convRes,
    ordersRes,
    contactsRes,
    productsRes,
    activeConvRes,
    takeoverConvRes,
    pendingOrdersRes,
    lowStockRes,
    whatsappRes,
    messagesDayRes,
    ordersStatusRes,
    revenueRes,
  ] = await Promise.all([
    // BLOQUE G-1: excluir archivadas (`archived_at IS NULL`) — paridad con el inbox
    // (use-conversations.ts). La retención per-tenant archiva conversaciones de
    // CUALQUIER status → sin el filtro el home y el badge sobre-cuentan vs lo que
    // el operador ve en el Inbox.
    supabase.from('conversations').select('id', { count: 'exact', head: true })
      .eq('tenant_id', tenantId).is('archived_at', null),
    supabase.from('orders').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
    supabase.from('contacts').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
    supabase.from('products').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('status', 'active'),
    // Ops: conversaciones activas con bot (excluye archivadas — ver arriba)
    supabase.from('conversations').select('id', { count: 'exact', head: true })
      .eq('tenant_id', tenantId).eq('status', 'bot_active').is('archived_at', null),
    // Ops: conversaciones en takeover humano (excluye archivadas — ver arriba)
    supabase.from('conversations').select('id', { count: 'exact', head: true })
      .eq('tenant_id', tenantId).eq('status', 'human_takeover').is('archived_at', null),
    // Ops: pedidos pendientes (solo 'pending'; ver needs_founder: incluir pending_payment)
    supabase.from('orders').select('id', { count: 'exact', head: true })
      .eq('tenant_id', tenantId).eq('status', 'pending'),
    // Ops: "Bajo stock" — MISMA fórmula que el destino /dashboard/catalog
    // (products-manager.tsx:58: stock>0 && stock<=threshold, sobre productos
    // status='active'). El inner join a products acota a productos activos;
    // .gt('stock_quantity',0) excluye los agotados (que el catálogo cuenta aparte).
    supabase.from('product_variations').select('id, products!inner(status)', { count: 'exact', head: true })
      .eq('tenant_id', tenantId)
      .eq('products.status', 'active')
      .gt('stock_quantity', 0)
      .lte('stock_quantity', lowStockThreshold),
    // First-run: ¿WhatsApp conectado?
    supabase.from('tenant_integrations').select('status')
      .eq('tenant_id', tenantId).eq('provider', 'whatsapp').limit(1).maybeSingle(),
    // Negocio: mensajes por día → un count exacto por bucket Colombia (sin filas)
    Promise.all(dayBuckets.map(b =>
      supabase.from('messages').select('id', { count: 'exact', head: true })
        .eq('tenant_id', tenantId)
        .gte('created_at', b.fromUTC)
        .lt('created_at', b.toUTC),
    )),
    // Negocio: pedidos por estado → un count exacto por estado (sin filas)
    Promise.all(ORDER_STATUSES.map(s =>
      supabase.from('orders').select('id', { count: 'exact', head: true })
        .eq('tenant_id', tenantId).eq('status', s),
    )),
    // BLOQUE G-2: KPI de dinero — ventas NETAS (confirmadas − reembolsos: reclamos +
    // RMA; cancelaciones ya salen por status). Un RPC (SECURITY INVOKER, tenant-scoped
    // por app_current_tenant + RLS) hace el cálculo en DB → evita el fetch-all-and-sum
    // que PostgREST trunca a 1000 filas.
    supabase.rpc('rpc_dashboard_revenue'),
  ])

  // ─── Surfacear errores: un fallo RLS/red NO puede pintar "0" como verdad ─────
  // revenueRes queda FUERA de este array a propósito: un fallo del KPI de dinero
  // (RPC) NO debe blanquear todo el dashboard — se degrada solo (muestra "—", ver
  // abajo), nunca un $0 falso. Los counts sí son all-or-nothing (no pintar 0 como
  // verdad).
  const responses = [
    convRes, ordersRes, contactsRes, productsRes, activeConvRes,
    takeoverConvRes, pendingOrdersRes, lowStockRes, whatsappRes,
    ...messagesDayRes, ...ordersStatusRes,
  ]
  const readError = tenantRes.error != null || responses.some(r => r.error != null)
  for (const r of responses) {
    if (r.error) console.error('[dashboard] fallo de lectura', r.error.message)
  }

  const stats = {
    conversations: convRes.count ?? 0,
    orders: ordersRes.count ?? 0,
    contacts: contactsRes.count ?? 0,
    products: productsRes.count ?? 0,
  }

  const ops = {
    activeConversations: activeConvRes.count ?? 0,
    humanTakeovers: takeoverConvRes.count ?? 0,
    pendingOrders: pendingOrdersRes.count ?? 0,
    lowStockCount: lowStockRes.count ?? 0,
  }

  const messagesPerDay = dayBuckets.map((b, i) => ({ day: b.label, total: messagesDayRes[i].count ?? 0 }))

  const ordersByStatus = ORDER_STATUSES
    .map((status, i) => ({ status, count: ordersStatusRes[i].count ?? 0 }))
    .filter(s => s.count > 0)

  // BLOQUE G-2: ventas netas (hoy + este mes). Number() defensivo (Supabase
  // serializa numeric como string). En error → null (la card muestra "—", no un $0
  // engañoso que parecería "sin ventas").
  if (revenueRes.error) console.error('[dashboard] fallo KPI ventas', revenueRes.error.message)
  const revenueRow = revenueRes.data?.[0]
  const revenue = {
    today: revenueRes.error ? null : Number(revenueRow?.revenue_today ?? 0),
    month: revenueRes.error ? null : Number(revenueRow?.revenue_month ?? 0),
  }

  // ─── Onboarding first-run: sin actividad todavía ────────────────────────────
  const whatsappConnected = whatsappRes.data?.status === 'connected'
  const firstRun = !readError &&
    stats.conversations === 0 && stats.orders === 0 && stats.contacts === 0
  const onboarding = {
    whatsapp: whatsappConnected,
    catalog: stats.products > 0,
    threshold: thresholdConfigured,
  }

  const quickLinks = buildQuickLinks(role)

  return (
    <DashboardClient
      tenantId={tenantId}
      tenantName={tenantName}
      userEmail={user.email ?? ''}
      role={role}
      stats={stats}
      ops={ops}
      revenue={revenue}
      lowStockThreshold={lowStockThreshold}
      messagesPerDay={messagesPerDay}
      ordersByStatus={ordersByStatus}
      quickLinks={quickLinks}
      readError={readError}
      firstRun={firstRun}
      onboarding={onboarding}
    />
  )
}
