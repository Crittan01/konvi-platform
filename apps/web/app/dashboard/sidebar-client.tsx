'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard, MessageSquare, LogOut, ShoppingCart,
  Package, Users, Settings, Plug, Truck, BarChart2,
  Boxes, BookOpen, ClipboardList, BrainCircuit,
  Menu, X, ChevronDown, TrendingUp, Building2,
  Tag, Wallet, DollarSign, AlertCircle, Bot,
  Store, Crown, Briefcase, Headphones,
} from 'lucide-react'

// ── Tipos ─────────────────────────────────────────────────────────────────────

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

// ── Estructura oficial de navegación — Rev. 4 ─────────────────────────────────
//
//  2026-04-14 (Vuelta 4 — Cierre semántico del tenant)
//  Fuente de verdad: .context/00-product.md
//
//  Decisiones de cierre:
//  • Despachos dentro de Ventas — es paso del ciclo comercial PYME, no dominio independiente
//  • Canales restaurado como grupo — Mercado Libre no debe flotar sin familia conceptual
//  • Media oculta del menú — biblioteca de assets del catálogo, no operativa independiente
//  • "IA y Conocimiento" — no existe Automatizaciones live; nombre honesto con lo que hay
//  • Configuración: Equipo/RBAC ya implementado in-page (settings); Reglas de Negocio pendiente

const NAV_ITEMS: NavItem[] = [
  // ── Inicio ───────────────────────────────────────────────────────────────
  { kind: 'leaf', href: '/dashboard',       label: 'Dashboard', icon: LayoutDashboard, roles: [] },
  { kind: 'leaf', href: '/dashboard/inbox', label: 'Inbox',     icon: MessageSquare,   roles: [] },

  // ── Ventas ✅ ─────────────────────────────────────────────────────────────
  {
    kind: 'group', id: 'ventas', label: 'Ventas', icon: ShoppingCart, roles: [],
    children: [
      { kind: 'leaf', href: '/dashboard/orders',   label: 'Pedidos',   icon: Package,     roles: [] },
      { kind: 'leaf', href: '/dashboard/contacts', label: 'Contactos', icon: Users,       roles: [] },
      { kind: 'leaf', href: '/dashboard/shipping', label: 'Despachos', icon: Truck,       roles: [] },
      { kind: 'leaf', href: '/dashboard/claims',   label: 'Reclamos',  icon: AlertCircle, roles: [] },
    ],
  },

  // ── Productos ✅ ──────────────────────────────────────────────────────────
  { kind: 'leaf', href: '/dashboard/catalog', label: 'Productos', icon: Boxes, roles: ['owner', 'manager'] },

  // ── Canales ✅ ────────────────────────────────────────────────────────────
  // Restaurado como grupo — Shopify, tienda custom entrarán aquí en fases futuras
  {
    kind: 'group', id: 'canales', label: 'Canales', icon: Store, roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/marketplace', label: 'Mercado Libre', icon: Store, roles: ['owner', 'manager'] },
    ],
  },

  // ── Compras ✅ ────────────────────────────────────────────────────────────
  { kind: 'leaf', href: '/dashboard/purchases', label: 'Compras', icon: Wallet, roles: ['owner'] },

  // ── Finanzas ✅ ───────────────────────────────────────────────────────────
  { kind: 'leaf', href: '/dashboard/finance', label: 'Finanzas', icon: DollarSign, roles: ['owner'] },

  // ── IA y Conocimiento ✅ ──────────────────────────────────────────────────
  // Renombrado: no existe Automatizaciones live — el nombre refleja lo que realmente hay
  {
    kind: 'group', id: 'ia', label: 'IA y Conocimiento', icon: BrainCircuit, roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/knowledge-base', label: 'Base de Conocimiento', icon: BookOpen, roles: ['owner', 'manager'] },
      { kind: 'leaf', href: '/dashboard/ai-agents',      label: 'Agentes IA',           icon: Bot,      roles: ['owner'] },
    ],
  },

  // ── Analítica ✅ ──────────────────────────────────────────────────────────
  {
    kind: 'group', id: 'analitica', label: 'Analítica', icon: BarChart2, roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/metrics', label: 'Métricas',  icon: TrendingUp,    roles: ['owner', 'manager'] },
      { kind: 'leaf', href: '/dashboard/audit',   label: 'Auditoría', icon: ClipboardList, roles: ['owner'] },
    ],
  },

  // ── Configuración ✅ ──────────────────────────────────────────────────────
  //  Rev. 5 — 2026-04-14 (Vuelta 5 — Cierre dominio Configuración)
  //
  //  General         → /settings   — datos del negocio, logo, WABA, dirección de envío, Telegram
  //  Usuarios y Acceso → /team     — equipo RBAC: listado, changeRole, removeMember (extraído)
  //  Integraciones   → /integrations — MeLi OAuth, Envia API key (ruta existente)
  //
  //  Reglas de Negocio: pendiente funcional — no existe base real. No se expone.
  {
    kind: 'group', id: 'configuracion', label: 'Configuración', icon: Settings, roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/settings',     label: 'General',            icon: Building2, roles: ['owner'] },
      { kind: 'leaf', href: '/dashboard/team',         label: 'Usuarios y Acceso',  icon: Users,     roles: ['owner'] },
      { kind: 'leaf', href: '/dashboard/integrations', label: 'Integraciones',      icon: Plug,      roles: ['owner'] },
    ],
  },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function hasAccess(roles: string[], role: string): boolean {
  return roles.length === 0 || roles.includes(role)
}

const ROLE_BADGE: Record<string, { label: string; icon: React.ElementType; color: string }> = {
  owner:    { label: 'Administrador', icon: Crown,      color: 'bg-amber-400/20 text-amber-200 border border-amber-400/30' },
  manager:  { label: 'Supervisor',    icon: Briefcase,  color: 'bg-white/15 text-white/80 border border-white/20' },
  operator: { label: 'Gestor',        icon: Headphones, color: 'bg-white/10 text-white/60 border border-white/15' },
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface SidebarProps {
  role: string
  userEmail: string
  tenantName: string | null
  tenantLogoUrl: string | null
  inboxBadge: number
  logoutAction: () => Promise<void>
}

// ── Componente Principal ──────────────────────────────────────────────────────

export default function SidebarClient({
  role, userEmail, tenantName, tenantLogoUrl, inboxBadge, logoutAction,
}: SidebarProps) {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)

  // Grupos abiertos por defecto — auto-expand si una ruta hija está activa
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => {
    const initial = new Set<string>()
    NAV_ITEMS.forEach(item => {
      if (item.kind === 'group') {
        const hasActive = item.children.some(child => pathname === child.href || pathname.startsWith(child.href + '/'))
        if (hasActive) initial.add(item.id)
      }
    })
    return initial
  })

  // Cerrar el drawer mobile al navegar
  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  const toggleGroup = (id: string) => {
    setOpenGroups(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const badge = ROLE_BADGE[role] ?? ROLE_BADGE.operator

  return (
    <>
      {/* ── Botón hamburger (mobile) ────────────────────────────────────────── */}
      <button
        onClick={() => setMobileOpen(true)}
        className="lg:hidden fixed top-3 left-3 z-50 h-9 w-9 rounded-lg bg-card border border-border flex items-center justify-center shadow-md"
        aria-label="Abrir menú"
      >
        <Menu className="h-4 w-4 text-foreground" />
      </button>

      {/* ── Overlay mobile ─────────────────────────────────────────────────── */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* ── Sidebar panel ──────────────────────────────────────────────────── */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-50 flex flex-col w-64 sidebar-gradient border-r border-border/50
          transition-transform duration-300 ease-in-out
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}
          lg:relative lg:translate-x-0 lg:z-auto lg:flex-shrink-0
        `}
      >
        {/* ── Header: logo + nombre tenant ───────────────────────────────── */}
        <div className="flex items-center justify-between h-14 px-4 border-b border-border/40 shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            {tenantLogoUrl ? (
              <img
                src={tenantLogoUrl}
                alt="Logo"
                className="h-7 w-7 rounded-md object-cover shrink-0 glow-primary"
              />
            ) : (
              <div className="h-7 w-7 rounded-md bg-primary/20 border border-primary/30 flex items-center justify-center shrink-0 glow-primary">
                <span className="text-primary text-xs font-bold">
                  {(tenantName ?? 'C').charAt(0).toUpperCase()}
                </span>
              </div>
            )}
            <span className="font-semibold text-sm text-foreground truncate">
              {tenantName ?? 'Commerce Ops'}
            </span>
          </div>

          {/* Cerrar en mobile */}
          <button
            onClick={() => setMobileOpen(false)}
            className="lg:hidden h-7 w-7 rounded-md hover:bg-white/10 flex items-center justify-center shrink-0"
            aria-label="Cerrar menú"
          >
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>

        {/* ── Nav items ──────────────────────────────────────────────────── */}
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {NAV_ITEMS.map((item) => {
            if (!hasAccess(item.roles, role)) return null

            if (item.kind === 'leaf') {
              const isActive = item.href === '/dashboard'
                ? pathname === '/dashboard'
                : pathname === item.href || pathname.startsWith(item.href + '/')
              const isInbox = item.href === '/dashboard/inbox'
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`
                    flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors
                    ${isActive
                      ? 'bg-primary/15 text-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-white/5'
                    }
                  `}
                >
                  <item.icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1">{item.label}</span>
                  {isInbox && inboxBadge > 0 && (
                    <span className="inline-flex items-center justify-center h-4 min-w-4 px-1 rounded-full bg-red-500 text-white text-[10px] font-bold tabular-nums">
                      {inboxBadge > 99 ? '99+' : inboxBadge}
                    </span>
                  )}
                </Link>
              )
            }

            // NavGroup
            const isOpen = openGroups.has(item.id)
            const hasActiveChild = item.children.some(child =>
              pathname === child.href || pathname.startsWith(child.href + '/')
            )
            const visibleChildren = item.children.filter(c => hasAccess(c.roles, role))
            if (visibleChildren.length === 0) return null

            return (
              <div key={item.id}>
                <button
                  onClick={() => toggleGroup(item.id)}
                  className={`
                    w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors
                    ${hasActiveChild
                      ? 'text-foreground bg-white/5'
                      : 'text-muted-foreground hover:text-foreground hover:bg-white/5'
                    }
                  `}
                >
                  <item.icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1 text-left">{item.label}</span>
                  <ChevronDown
                    className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
                  />
                </button>

                {isOpen && (
                  <div className="mt-0.5 ml-4 pl-2.5 border-l border-border/40 space-y-0.5 pb-1">
                    {visibleChildren.map(child => {
                      const isActive = pathname === child.href || pathname.startsWith(child.href + '/')
                      return (
                        <Link
                          key={child.href}
                          href={child.href}
                          className={`
                            flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm transition-colors
                            ${isActive
                              ? 'bg-primary/15 text-primary font-medium'
                              : 'text-muted-foreground hover:text-foreground hover:bg-white/5'
                            }
                          `}
                        >
                          <child.icon className="h-3.5 w-3.5 shrink-0" />
                          {child.label}
                        </Link>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </nav>

        {/* ── Footer: usuario + rol + logout ─────────────────────────────── */}
        <div className="shrink-0 border-t border-border/40 p-3 space-y-2">
          <div className="px-1">
            <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full ${badge.color}`}>
              <badge.icon className="h-3 w-3 shrink-0" />
              {badge.label}
            </span>
          </div>
          <div className="px-1">
            <p className="text-xs text-muted-foreground truncate">{userEmail}</p>
          </div>
          <form action={logoutAction}>
            <button
              type="submit"
              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
            >
              <LogOut className="h-4 w-4 shrink-0" />
              Cerrar sesión
            </button>
          </form>
        </div>
      </aside>
    </>
  )
}
