'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard, ShoppingCart, MessageSquare, LogOut,
  Package, Users, Settings, Plug, Truck, BarChart2,
  Boxes, BookOpen, Image, ClipboardList, ChevronRight,
  Menu, X,
} from 'lucide-react'

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

interface SidebarProps {
  role: string
  userEmail: string
  tenantName: string | null
  tenantLogoUrl: string | null
  logoutAction: () => Promise<void>
}

export default function SidebarClient({
  role, userEmail, tenantName, tenantLogoUrl, logoutAction,
}: SidebarProps) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const pathname = usePathname()
  const roleBadge = ROLE_BADGE[role] ?? ROLE_BADGE.agent
  const userInitial = userEmail?.charAt(0).toUpperCase() ?? '?'
  const userName = userEmail?.split('@')[0] ?? ''

  // Cerrar sidebar al navegar en mobile
  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  // Bloquear scroll del body cuando overlay está abierto
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [mobileOpen])

  const visibleItems = NAV_ITEMS.filter(item =>
    item.roles.length === 0 || item.roles.includes(role)
  )

  const isActive = (href: string) => {
    if (href === '/dashboard') return pathname === '/dashboard'
    return pathname.startsWith(href)
  }

  const SidebarContent = () => (
    <div className="flex flex-col h-full">
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
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-white tracking-tight truncate">
              {tenantName ?? 'Commerce Ops'}
            </p>
            <p className="text-[10px] text-white/50">Tenant Console</p>
          </div>
          {/* Botón cerrar en mobile */}
          <button
            className="lg:hidden p-1 rounded-md text-white/40 hover:text-white hover:bg-white/10"
            onClick={() => setMobileOpen(false)}
            aria-label="Cerrar menú"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-0.5">
        {visibleItems.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150 ${
              isActive(href)
                ? 'bg-white/15 text-white'
                : 'text-white/60 hover:bg-white/10 hover:text-white'
            }`}
          >
            <Icon
              className={`h-4 w-4 shrink-0 transition-colors ${
                isActive(href) ? 'text-amber-300' : 'group-hover:text-amber-300'
              }`}
            />
            <span className="flex-1">{label}</span>
            <ChevronRight
              className={`h-3 w-3 transition-opacity ${
                isActive(href) ? 'opacity-50' : 'opacity-0 group-hover:opacity-50'
              }`}
            />
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
    </div>
  )

  return (
    <>
      {/* ── Desktop sidebar — siempre visible en lg+ ─────────────────────── */}
      <aside className="hidden lg:flex w-60 flex-shrink-0 flex-col sidebar-gradient border-r border-white/10 h-screen sticky top-0">
        <SidebarContent />
      </aside>

      {/* ── Mobile: hamburger button en topbar ──────────────────────────── */}
      <button
        className="lg:hidden fixed top-3 left-3 z-50 p-2 rounded-lg sidebar-gradient border border-white/10 text-white/70 hover:text-white shadow-lg"
        onClick={() => setMobileOpen(true)}
        aria-label="Abrir menú"
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* ── Mobile: overlay backdrop ─────────────────────────────────────── */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* ── Mobile: sidebar drawer ───────────────────────────────────────── */}
      <aside
        className={`lg:hidden fixed inset-y-0 left-0 z-50 w-72 flex flex-col sidebar-gradient border-r border-white/10 shadow-2xl transition-transform duration-300 ease-in-out ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <SidebarContent />
      </aside>
    </>
  )
}
