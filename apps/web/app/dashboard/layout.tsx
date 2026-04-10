import * as React from "react"
import Link from 'next/link'
import { redirect } from 'next/navigation'
import {
  LayoutDashboard, ShoppingCart, MessageSquare, LogOut,
  Package, Users, Settings, Plug, Truck, BarChart2,
  Boxes, BookOpen, Image, ClipboardList, ChevronRight,
} from 'lucide-react'
import { createClient } from '@/utils/supabase/server'

type NavItem = {
  href: string
  label: string
  icon: React.ElementType
  roles: string[]
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard',                label: 'Resumen',        icon: LayoutDashboard, roles: [] },
  { href: '/dashboard/inbox',          label: 'Inbox AI',       icon: MessageSquare,   roles: [] },
  { href: '/dashboard/orders',         label: 'Pedidos',        icon: Package,         roles: [] },
  { href: '/dashboard/contacts',       label: 'Contactos',      icon: Users,           roles: [] },
  { href: '/dashboard/catalog',        label: 'Catálogo',       icon: ShoppingCart,    roles: ['owner', 'manager'] },
  { href: '/dashboard/inventory',      label: 'Inventario',     icon: Boxes,           roles: ['owner', 'manager'] },
  { href: '/dashboard/knowledge-base', label: 'Knowledge Base', icon: BookOpen,        roles: ['owner', 'manager'] },
  { href: '/dashboard/media',          label: 'Media',          icon: Image,           roles: ['owner', 'manager'] },
  { href: '/dashboard/shipping',       label: 'Envíos',         icon: Truck,           roles: [] },
  { href: '/dashboard/integrations',   label: 'Integraciones',  icon: Plug,            roles: ['owner'] },
  { href: '/dashboard/metrics',        label: 'Métricas',       icon: BarChart2,       roles: ['owner', 'manager'] },
  { href: '/dashboard/audit',          label: 'Auditoría',      icon: ClipboardList,   roles: ['owner'] },
  { href: '/dashboard/settings',       label: 'Configuración',  icon: Settings,        roles: ['owner'] },
]

const ROLE_BADGE: Record<string, { label: string; color: string }> = {
  owner:   { label: 'Owner',   color: 'bg-amber-400/20 text-amber-200 border border-amber-400/30' },
  manager: { label: 'Manager', color: 'bg-white/15 text-white/80 border border-white/20' },
  agent:   { label: 'Agent',   color: 'bg-white/10 text-white/60 border border-white/15' },
}

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { role?: string; tenant_id?: string }
  const role = meta.role ?? 'agent'
  const roleBadge = ROLE_BADGE[role] ?? ROLE_BADGE.agent

  // Cargar nombre y logo del tenant para el sidebar
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

  const visibleItems = NAV_ITEMS.filter(item =>
    item.roles.length === 0 || item.roles.includes(role)
  )

  const logoutAction = async () => {
    'use server'
    const supabase = createClient()
    await supabase.auth.signOut()
    redirect('/login')
  }

  const userInitial = user?.email?.charAt(0).toUpperCase() ?? '?'
  const userName = user?.email?.split('@')[0] ?? ''

  return (
    <div className="flex h-screen overflow-hidden bg-background">

      {/* ── Sidebar — verde bosque ──────────────────────────────────────── */}
      <aside className="w-60 flex-shrink-0 flex flex-col sidebar-gradient border-r border-white/10">

        {/* Logo */}
        <div className="px-5 py-5 border-b border-white/10">
          <div className="flex items-center gap-2.5">
            {tenantLogoUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={tenantLogoUrl}
                alt="Logo"
                className="h-7 w-7 rounded-lg object-cover border border-white/20"
              />
            ) : (
              <div className="h-7 w-7 rounded-lg bg-white/15 border border-white/20 flex items-center justify-center glow-primary">
                <span className="text-white text-xs font-bold">
                  {tenantName ? tenantName.charAt(0).toUpperCase() : 'CO'}
                </span>
              </div>
            )}
            <div>
              <p className="text-sm font-semibold text-white tracking-tight">
                {tenantName ?? 'Commerce Ops'}
              </p>
              <p className="text-[10px] text-white/50">Tenant Console</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-0.5">
          {visibleItems.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-white/60 transition-all duration-150 hover:bg-white/10 hover:text-white"
            >
              <Icon className="h-4 w-4 shrink-0 transition-colors group-hover:text-amber-300" />
              <span className="flex-1">{label}</span>
              <ChevronRight className="h-3 w-3 opacity-0 group-hover:opacity-50 transition-opacity" />
            </Link>
          ))}
        </nav>

        {/* User footer */}
        <div className="border-t border-white/10 p-3">
          <div className="flex items-center gap-3 rounded-lg px-2 py-2">
            <div className="h-8 w-8 shrink-0 rounded-full bg-amber-400/20 border border-amber-400/30 flex items-center justify-center">
              <span className="text-xs font-semibold text-amber-300">{userInitial}</span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-white/80 truncate">{userName}</p>
              <span className={`inline-block text-[10px] font-medium px-1.5 py-0.5 rounded-full ${roleBadge.color}`}>
                {roleBadge.label}
              </span>
            </div>
            <form action={logoutAction}>
              <button
                type="submit"
                title="Cerrar sesión"
                className="p-1.5 rounded-md text-white/40 hover:text-white hover:bg-white/10 transition-colors"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </form>
          </div>
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto">
        {/* Top bar */}
        <div className="sticky top-0 z-10 h-12 border-b border-border bg-card/80 backdrop-blur-sm flex items-center px-8">
          <div className="flex-1" />
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span>Live</span>
          </div>
        </div>

        {/* Page content */}
        <div className="p-8">
          {children}
        </div>
      </main>
    </div>
  )
}
