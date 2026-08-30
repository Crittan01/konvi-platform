'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { shouldRenderMarketplaceBadge } from '@/lib/marketplace-badges'
import {
  LogOut,
  Menu, X, ChevronDown,
  Lock,
  Crown, Briefcase, Headphones,
  Shield } from 'lucide-react'
// NAV_ITEMS (estructura oficial de navegación, Rev. 4/5) vive en ./nav-items —
// fuente única compartida con la command palette (Spec WOW §4.3).
import { NAV_ITEMS, hasAccess, type NavLeaf } from './nav-items'

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
  meliBadge: number
  planCode: string
  planCapabilities: Record<string, boolean>
  integrations: {
    whatsapp: boolean
    shipping: boolean  // true si Aveonline está connected (Rev. 107)
    mercadolibre: boolean
  }
}

// ── Componente Principal ──────────────────────────────────────────────────────

export default function SidebarClient({
  role, userEmail, tenantName, tenantLogoUrl, inboxBadge, meliBadge, planCode, planCapabilities, integrations,
}: SidebarProps) {
  const pathname = usePathname()
  const [mobileOpen,   setMobileOpen]   = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)

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
  const isIntegrationEnabled = (integration?: NavLeaf['integration']) =>
    !integration || integrations[integration] === true
  const isCapabilityEnabled = (capability?: string) =>
    !capability || planCapabilities[capability] !== false
  const planLabel =
    planCode === 'basic' ? 'Basic' :
    planCode === 'pro' ? 'Pro' :
    planCode === 'enterprise' ? 'Enterprise' :
    planCode

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
          className="lg:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-xs"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* ── Sidebar panel ──────────────────────────────────────────────────── */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-50 flex flex-col w-64 sidebar-gradient border-r border-border/50
          transition-transform duration-300 ease-in-out
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}
          lg:relative lg:translate-x-0 lg:z-auto lg:shrink-0
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
              {tenantName ?? 'Tu tienda'}
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
              const integrationOk = isIntegrationEnabled(item.integration)
              const capabilityOk = isCapabilityEnabled(item.capability)
              const isEnabled = integrationOk && capabilityOk
              const isActive = item.href === '/dashboard'
                ? pathname === '/dashboard'
                : pathname === item.href || pathname.startsWith(item.href + '/')
              const isInbox = item.href === '/dashboard/inbox'
              if (!isEnabled) {
                const lockReason = !capabilityOk
                  ? `Requiere upgrade de plan (${planLabel})`
                  : 'Requiere integración activa en Configuración → Integraciones'
                return (
                  <div
                    key={item.href}
                    title={lockReason}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium text-muted-foreground/50 bg-white/2 cursor-not-allowed"
                  >
                    <item.icon className="h-4 w-4 shrink-0" />
                    <span className="flex-1">{item.label}</span>
                    <Lock className="h-3.5 w-3.5 shrink-0" />
                  </div>
                )
              }
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
                    <span className="inline-flex items-center justify-center h-4 min-w-4 px-1.5 rounded-full bg-danger-bg text-danger-fg border border-danger-border text-[10px] font-bold tabular-nums">
                      {inboxBadge > 99 ? '99+' : inboxBadge}
                    </span>
                  )}
                    {shouldRenderMarketplaceBadge(item.href, meliBadge) && (
                    <span className="inline-flex items-center justify-center h-4 min-w-4 px-1.5 rounded-full bg-warning-bg text-warning-fg border border-warning-border text-[10px] font-bold tabular-nums">
                      {meliBadge > 99 ? '99+' : meliBadge}
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
                      const integrationOk = isIntegrationEnabled(child.integration)
                      const capabilityOk = isCapabilityEnabled(child.capability)
                      const isEnabled = integrationOk && capabilityOk
                      const isActive = pathname === child.href || pathname.startsWith(child.href + '/')
                      if (!isEnabled) {
                        const lockReason = !capabilityOk
                          ? `Requiere upgrade de plan (${planLabel})`
                          : 'Requiere integración activa en Configuración → Integraciones'
                        return (
                          <div
                            key={child.href}
                            title={lockReason}
                            className="flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm text-muted-foreground/50 bg-white/2 cursor-not-allowed"
                          >
                            <child.icon className="h-3.5 w-3.5 shrink-0" />
                            <span className="flex-1">{child.label}</span>
                            <Lock className="h-3 w-3 shrink-0" />
                          </div>
                        )
                      }
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
                          <span className="flex-1">{child.label}</span>
                          {shouldRenderMarketplaceBadge(child.href, meliBadge) && (
                            <span className="inline-flex items-center justify-center h-4 min-w-4 px-1.5 rounded-full bg-warning-bg text-warning-fg border border-warning-border text-[10px] font-bold tabular-nums">
                              {meliBadge > 99 ? '99+' : meliBadge}
                            </span>
                          )}
                        </Link>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </nav>

        {/* ── Footer: usuario + menú desplegable ──────────────────────────── */}
        <div className="shrink-0 border-t border-border/40 p-3">
          <div className="relative">
            {/* Trigger */}
            <button
              type="button"
              onClick={() => setUserMenuOpen(v => !v)}
              className={`w-full flex items-center gap-2.5 px-2 py-2 rounded-lg transition-colors text-left ${
                userMenuOpen ? 'bg-white/8' : 'hover:bg-white/5'
              }`}
            >
              {/* Avatar */}
              <div className="h-7 w-7 rounded-full bg-primary/25 border border-primary/40 flex items-center justify-center shrink-0 text-[11px] font-bold text-primary">
                {userEmail.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[11px] text-foreground/75 truncate">{userEmail}</p>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className={`inline-flex items-center gap-0.5 text-[10px] font-medium px-1.5 rounded-full ${badge.color}`}>
                    <badge.icon className="h-2.5 w-2.5 shrink-0" />
                    {badge.label}
                  </span>
                  <span className="inline-flex items-center text-[10px] font-semibold uppercase tracking-wide px-1.5 rounded-full bg-primary/20 text-primary border border-primary/30">
                    {planLabel}
                  </span>
                </div>
              </div>
              <ChevronDown className={`h-3 w-3 shrink-0 text-muted-foreground/60 transition-transform duration-200 ${userMenuOpen ? 'rotate-180' : ''}`} />
            </button>

            {/* Menú — aparece ARRIBA, colores del propio sidebar para coherencia */}
            {userMenuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setUserMenuOpen(false)} />
                <div
                  className="absolute bottom-full left-0 right-0 mb-2 z-50 rounded-xl overflow-hidden shadow-2xl"
                  style={{ background: 'hsl(168 14% 10%)', border: '1px solid hsl(156 30% 20%)' }}
                >
                  <div className="p-1">
                    <Link
                      href="/dashboard/settings/security"
                      onClick={() => setUserMenuOpen(false)}
                      className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm transition-colors"
                      style={{ color: 'hsl(156 20% 70%)' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'hsl(168 14% 16%)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                    >
                      <Shield className="h-3.5 w-3.5 shrink-0 opacity-70" />
                      Seguridad y contraseña
                    </Link>
                    <div className="my-1 mx-2" style={{ borderTop: '1px solid hsl(156 30% 18%)' }} />
                    {/* T7.10 — el logout va a `/logout` (despedida de marca con
                        la escena de auth); el signOut + limpieza G7 ocurren allí. */}
                    <Link
                      href="/logout"
                      className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm transition-colors"
                      style={{ color: 'hsl(0 70% 65%)' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'hsl(0 30% 14%)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                    >
                      <LogOut className="h-3.5 w-3.5 shrink-0 opacity-80" />
                      Cerrar sesión
                    </Link>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </aside>
    </>
  )
}
