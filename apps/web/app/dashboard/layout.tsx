import * as React from "react"
import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import SidebarClient from './sidebar-client'

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) redirect('/login')

  const meta = (user?.app_metadata ?? {}) as { role?: string; tenant_id?: string }
  const role = meta.role ?? 'agent'

  // Cargar nombre y logo del tenant
  let tenantName: string | null = null
  let tenantLogoUrl: string | null = null
  if (meta.tenant_id) {
    const { data: tenantData } = await supabase
      .from('tenants')
      .select('name, logo_url')
      .eq('id', meta.tenant_id)
      .single()
    tenantName = tenantData?.name ?? null
    tenantLogoUrl = tenantData?.logo_url ?? null
  }

  const logoutAction = async () => {
    'use server'
    const supabase = createClient()
    await supabase.auth.signOut()
    redirect('/login')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">

      {/* ── Sidebar (responsive: desktop sticky, mobile drawer) ─────────── */}
      <SidebarClient
        role={role}
        userEmail={user?.email ?? ''}
        tenantName={tenantName}
        tenantLogoUrl={tenantLogoUrl}
        logoutAction={logoutAction}
      />

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto min-w-0">
        {/* Top bar */}
        <div className="sticky top-0 z-10 h-12 border-b border-border bg-card/80 backdrop-blur-sm flex items-center px-4 sm:px-8">
          {/* Espacio para el hamburger en mobile */}
          <div className="w-10 lg:hidden" />
          <div className="flex-1" />
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
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
