'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard, MessageSquare, LogOut, ShoppingCart,
  Package, Users, Settings, Plug, Truck, BarChart2,
  Boxes, BookOpen, Image, ClipboardList, BrainCircuit,
  Menu, X, ChevronDown, TrendingUp, Building2, ShoppingBag,
} from 'lucide-react'

// ── Tipos ────────────────────────────────────────────────────────────────────

type NavLeaf = {
  kind: 'leaf'
  href: string
  label: string
  icon: React.ElementType
  roles: string[]
}

type NavGroup = {
  kind: 'group'
  id: string
  label: string
  icon: React.ElementType
  roles: string[]
  children: NavLeaf[]
}

type NavItem = NavLeaf | NavGroup

// ── Estructura de navegación ──────────────────────────────────────────────────
//
// Arquitectura aprobada 2026-04-10:
//   Dashboard  → raíz, sin sub-items (tabs internas = Operaciones/Negocio)
//   Inbox      → raíz (uso diario crítico)
//   Ventas     → grupo: Pedidos, Contactos, Envíos
//   Productos  → grupo: Catálogo, Inventario
//   IA & Contenido → grupo: Base de Conocimiento, Media
//   Analítica  → grupo: Métricas, Auditoría
//   Configuración → grupo: General, Integraciones
//
// Regla: sub-item en sidebar = módulo con URL propia.
//        Tabs dentro de una página = vistas alternativas del mismo dato.

const NAV_ITEMS: NavItem[] = [
  {
    kind: 'leaf',
    href: '/dashboard',
    label: 'Dashboard',
    icon: LayoutDashboard,
    roles: [],
  },
  {
    kind: 'leaf',
    href: '/dashboard/inbox',
    label: 'Inbox',
    icon: MessageSquare,
    roles: [],
  },
  {
    kind: 'group',
    id: 'ventas',
    label: 'Ventas',
    icon: ShoppingCart,
    roles: [],
    children: [
      { kind: 'leaf', href: '/dashboard/orders',   label: 'Pedidos',   icon: Package,        roles: [] },
      { kind: 'leaf', href: '/dashboard/contacts', label: 'Contactos', icon: Users,          roles: [] },
      { kind: 'leaf', href: '/dashboard/shipping', label: 'Envíos',    icon: Truck,          roles: [] },
    ],
  },
  {
    kind: 'group',
    id: 'productos',
    label: 'Productos',
    icon: ShoppingBag,
    roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/catalog',   label: 'Catálogo',   icon: ShoppingBag, roles: ['owner', 'manager'] },
      { kind: 'leaf', href: '/dashboard/inventory', label: 'Inventario', icon: Boxes,       roles: ['owner', 'manager'] },
    ],
  },
  {
    kind: 'group',
    id: 'ia-contenido',
    label: 'IA & Contenido',
    icon: BrainCircuit,
    roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/knowledge-base', label: 'Base de Conocimiento', icon: BookOpen, roles: ['owner', 'manager'] },
      { kind: 'leaf', href: '/dashboard/media',          label: 'Media',                icon: Image,    roles: ['owner', 'manager'] },
    ],
  },
  {
    kind: 'group',
    id: 'analitica',
    label: 'Analítica',
    icon: BarChart2,
    roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/metrics', label: 'Métricas',  icon: TrendingUp,    roles: ['owner', 'manager'] },
      { kind: 'leaf', href: '/dashboard/audit',   label: 'Auditoría', icon: ClipboardList, roles: ['owner'] },
    ],
  },
  {
    kind: 'group',
    id: 'configuracion',
    label: 'Configuración',
    icon: Settings,
    roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/settings',     label: 'General',        icon: Building2, roles: ['owner'] },
      { kind: 'leaf', href: '/dashboard/integrations', label: 'Integraciones',  icon: Plug,      roles: ['owner'] },
    ],
  },
]

// ── RBAC helpers ──────────────────────────────────────────────────────────────

function hasAccess(roles: string[], role: string): boolean {
  return roles.length === 0 || roles.includes(role)
}

// ── Role badge ────────────────────────────────────────────────────────────────

const ROLE_BADGE: Record<string, { label: string; color: string }> = {
  owner:   { label: '👑 Owner',   color: 'bg-amber-400/20 text-amber-200 border border-amber-400/30' },
  manager: { label: '🛠️ Manager', color: 'bg-white/15 text-white/80 border border-white/20' },
  agent:   { label: '🎧 Agente',  color: 'bg-white/10 text-white/60 border border-white/15' },
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface SidebarProps {
  role: string
  userEmail: string
  tenantName: string | null
  tenantLogoUrl: string | null
  logoutAction: () => Promise<void>
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function SidebarClient({
  role, userEmail, tenantName, tenantLogoUrl, logoutAction,
}: SidebarProps) {
  const [mobileOpen, setMobileOpen]   = useState(false)
  const [openGroups, setOpenGroups]   = useState<Set<string>>(new Set())
  const pathname = usePathname()
  const roleBadge   = ROLE_BADGE[role] ?? ROLE_BADGE.agent
  const userInitial = userEmail?.charAt(0).toUpperCase() ?? '?'
  const userName    = userEmail?.split('@')[0] ?? ''

  // Auto-expand el grupo que contiene la ruta activa
  useEffect(() => {
    const groups = NAV_ITEMS.filter((i): i is NavGroup => i.kind === 'group')
    const activeGroup = groups.find(g =>
      g.children.some(c => pathname.startsWith(c.href))
    )
    if (activeGroup) {
      setOpenGroups(prev => new Set(Array.from(prev).concat(activeGroup.id)))
    }
  }, [pathname])

  // Cerrar sidebar mobile al navegar
  useEffect(() => { setMobileOpen(false) }, [pathname])

  // Bloquear scroll body en mobile con overlay abierto
  useEffect(() => {
    document.body.style.overflow = mobileOpen ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [mobileOpen])

  const isActive = (href: string) =>
    href === '/dashboard' ? pathname === '/dashboard' : pathname.startsWith(href)

  const isGroupActive = (group: NavGroup) =>
    group.children.some(c => isActive(c.href))

  const toggleGroup = (id: string) =>
    setOpenGroups(prev => {
      const next = new Set(Array.from(prev))
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  // Filtrar por RBAC
  const visibleItems = NAV_ITEMS.filter(item => hasAccess(item.roles, role))

  // ── Inner content ───────────────────────────────────────────────────────────
  const SidebarContent = () => (
    <div className="flex flex-col h-full">

      {/* Logo / Tenant header */}
      <div className="px-4 py-4 border-b border-white/10">
        <div className="flex items-center gap-2.5">
          {tenantLogoUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={tenantLogoUrl} alt="Logo"
              className="h-7 w-7 rounded-lg object-cover border border-white/20" />
          ) : (
            <div className="h-7 w-7 rounded-lg bg-white/15 border border-white/20 flex items-center justify-center">
              <span className="text-white text-xs font-bold">
                {tenantName ? tenantName.charAt(0).toUpperCase() : 'CO'}
              </span>
            </div>
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-white tracking-tight truncate">
              {tenantName ?? 'Commerce Ops'}
            </p>
            <p className="text-[10px] text-white/40">Tenant Console</p>
          </div>
          <button
            className="lg:hidden p-1 rounded-md text-white/40 hover:text-white hover:bg-white/10 transition-colors"
            onClick={() => setMobileOpen(false)}
            aria-label="Cerrar menú"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-0.5">
        {visibleItems.map(item => {

          // ── Leaf item ────────────────────────────────────────────────────
          if (item.kind === 'leaf') {
            const active = isActive(item.href)
            const Icon = item.icon
            return (
              <Link key={item.href} href={item.href}
                className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150 ${
                  active ? 'bg-white/15 text-white' : 'text-white/60 hover:bg-white/10 hover:text-white'
                }`}
              >
                <Icon className={`h-4 w-4 shrink-0 transition-colors ${
                  active ? 'text-amber-300' : 'group-hover:text-amber-300'
                }`} />
                <span className="flex-1">{item.label}</span>
              </Link>
            )
          }

          // ── Group item ───────────────────────────────────────────────────
          const group = item
          const visibleChildren = group.children.filter(c => hasAccess(c.roles, role))
          if (visibleChildren.length === 0) return null

          const groupActive = isGroupActive(group)
          const isOpen      = openGroups.has(group.id)
          const GroupIcon   = group.icon

          return (
            <div key={group.id}>
              {/* Group header — clickable toggle */}
              <button
                onClick={() => toggleGroup(group.id)}
                className={`w-full group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150 ${
                  groupActive && !isOpen
                    ? 'bg-white/15 text-white'
                    : 'text-white/60 hover:bg-white/10 hover:text-white'
                }`}
              >
                <GroupIcon className={`h-4 w-4 shrink-0 transition-colors ${
                  groupActive ? 'text-amber-300' : 'group-hover:text-amber-300'
                }`} />
                <span className="flex-1 text-left">{group.label}</span>
                {/* Indicador de ítem activo inside group */}
                {groupActive && !isOpen && (
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400 shrink-0" />
                )}
                <ChevronDown className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${
                  isOpen ? 'rotate-180' : ''
                }`} />
              </button>

              {/* Children — collapsible con animación CSS */}
              <div className={`overflow-hidden transition-all duration-200 ${
                isOpen ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'
              }`}>
                <div className="ml-3 pl-3 border-l border-white/10 mt-0.5 space-y-0.5 pb-1">
                  {visibleChildren.map(child => {
                    const childActive = isActive(child.href)
                    const ChildIcon   = child.icon
                    return (
                      <Link key={child.href} href={child.href}
                        className={`group flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm transition-all duration-150 ${
                          childActive
                            ? 'bg-white/15 text-white font-medium'
                            : 'text-white/50 hover:bg-white/10 hover:text-white'
                        }`}
                      >
                        <ChildIcon className={`h-3.5 w-3.5 shrink-0 transition-colors ${
                          childActive ? 'text-amber-300' : 'group-hover:text-amber-300'
                        }`} />
                        <span className="flex-1 text-[13px]">{child.label}</span>
                        {childActive && <span className="h-1.5 w-1.5 rounded-full bg-amber-400 shrink-0" />}
                      </Link>
                    )
                  })}
                </div>
              </div>
            </div>
          )
        })}
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
            <button type="submit" title="Cerrar sesión"
              className="p-1.5 rounded-md text-white/40 hover:text-white hover:bg-white/10 transition-colors">
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </form>
        </div>
      </div>
    </div>
  )

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex w-60 flex-shrink-0 flex-col sidebar-gradient border-r border-white/10 h-screen sticky top-0">
        <SidebarContent />
      </aside>

      {/* Mobile: hamburger */}
      <button
        className="lg:hidden fixed top-3 left-3 z-50 p-2 rounded-lg sidebar-gradient border border-white/10 text-white/70 hover:text-white shadow-lg"
        onClick={() => setMobileOpen(true)}
        aria-label="Abrir menú"
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* Mobile: overlay */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)} />
      )}

      {/* Mobile: drawer */}
      <aside className={`lg:hidden fixed inset-y-0 left-0 z-50 w-72 flex flex-col sidebar-gradient border-r border-white/10 shadow-2xl transition-transform duration-300 ease-in-out ${
        mobileOpen ? 'translate-x-0' : '-translate-x-full'
      }`}>
        <SidebarContent />
      </aside>
    </>
  )
}
