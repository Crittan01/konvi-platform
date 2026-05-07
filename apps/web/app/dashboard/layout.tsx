import * as React from "react"
import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { getMarketplaceBadgeCount } from '@/lib/marketplace-badges'
import SidebarClient from './sidebar-client'

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  // Sem 5 perf: getCachedUser comparte resultado con page server
  // components anidados via React.cache. Ahorra 1 round-trip por
  // navegación (~640ms en VM Colombia → Supabase US-East).
  const user = await getCachedUser()

  if (!user) redirect('/login')

  const { role, tenantId } = await getCachedTenantMeta()
  const supabase = createClient()

  const logoutAction = async () => {
    'use server'
    const supabase = createClient()
    await supabase.auth.signOut()
    redirect('/login')
  }

  // ── Ronda 2: todas las queries del tenant en paralelo ─────────────────────
  let tenantName: string | null = null
  let tenantLogoUrl: string | null = null
  let inboxBadge = 0
  let meliBadge = 0
  let planCode = 'enterprise'
  const planCapabilities: Record<string, boolean> = {}
  const integrations = { whatsapp: false, envia: false, mercadolibre: false }

  if (tenantId) {
    const [tenantRes, inboxRes, meliRes, integRes, subRes] = await Promise.all([
      supabase.from('tenants').select('name, logo_url').eq('id', tenantId).single(),
      supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('status', 'human_takeover'),
      supabase.from('marketplace_listings').select('status').eq('tenant_id', tenantId).eq('provider', 'mercadolibre'),
      supabase.from('tenant_integrations').select('provider, status').eq('tenant_id', tenantId).in('provider', ['whatsapp', 'envia', 'mercadolibre']),
      supabase.from('tenant_subscriptions').select('plan_code').eq('tenant_id', tenantId).maybeSingle(),
    ])

    tenantName    = tenantRes.data?.name ?? null
    tenantLogoUrl = tenantRes.data?.logo_url ?? null
    inboxBadge    = inboxRes.count ?? 0
    meliBadge     = getMarketplaceBadgeCount(meliRes.data ?? [])
    planCode      = subRes.data?.plan_code ?? 'enterprise'

    for (const row of integRes.data ?? []) {
      const provider  = (row as { provider?: string }).provider
      const connected = (row as { status?: string }).status === 'connected'
      if (provider === 'whatsapp')     integrations.whatsapp     = connected
      if (provider === 'envia')        integrations.envia        = connected
      if (provider === 'mercadolibre') integrations.mercadolibre = connected
    }

    // ── Ronda 3: capabilities depende del planCode anterior ─────────────────
    try {
      const { data: caps } = await supabase
        .from('plan_capabilities')
        .select('capability_key, enabled')
        .eq('plan_code', planCode)

      for (const row of caps ?? []) {
        const key = (row as { capability_key?: string }).capability_key
        if (!key) continue
        planCapabilities[key] = (row as { enabled?: boolean }).enabled !== false
      }
    } catch {
      // Fail-open: si plan_capabilities no está disponible, no bloquear navegación.
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">

      {/* ── Sidebar (responsive: desktop sticky, mobile drawer) ─────────── */}
      <SidebarClient
        role={role}
        userEmail={user?.email ?? ''}
        tenantName={tenantName}
        tenantLogoUrl={tenantLogoUrl}
        inboxBadge={inboxBadge}
        meliBadge={meliBadge}
        integrations={integrations}
        planCode={planCode}
        planCapabilities={planCapabilities}
        logoutAction={logoutAction}
      />

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto min-w-0">
        {/* Top bar */}
        <div className="sticky top-0 z-10 h-12 border-b topbar-bg flex items-center px-4 sm:px-8">
          {/* Espacio para el hamburger en mobile */}
          <div className="w-10 lg:hidden" />
          <div className="flex-1" />
          <div className="flex items-center gap-2 text-xs opacity-90">
            <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span className="hidden sm:inline">Live</span>
          </div>
        </div>

        {/* Page content */}
        <div className="p-4 sm:p-6 lg:p-8">
          {children}
        </div>
      </main>
    </div>
  )
}
