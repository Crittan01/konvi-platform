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
//
//  Extraído de sidebar-client.tsx (2026-08-02, Spec WOW §4.3): el sidebar y la
//  command palette consumen la MISMA fuente → los gates RBAC/integración/plan no
//  se duplican ni se desalinean. Módulo client-safe (sin imports de servidor).

import {
  LayoutDashboard, MessageSquare, ShoppingCart,
  Package, Users, Settings, Plug, Truck, BarChart2,
  Boxes, BookOpen, ClipboardList, BrainCircuit,
  TrendingUp, Building2,
  Wallet, DollarSign, AlertCircle, Bot,
  Store, Tag, Tags,
  Shield, Activity, Scale, Archive, Trash2, Receipt,
} from 'lucide-react'

// ── Tipos ─────────────────────────────────────────────────────────────────────

export type NavLeaf = {
  kind: 'leaf'
  href: string
  label: string
  icon: React.ElementType
  roles: string[]
  // 'shipping' = integración logística del tenant (Aveonline, provider
  // shipping soportado). Rev. 107 ADR-0019.
  integration?: 'whatsapp' | 'shipping' | 'mercadolibre'
  capability?: string
}

export type NavGroup = {
  kind: 'group'
  id: string
  label: string
  icon: React.ElementType
  roles: string[]
  children: NavLeaf[]
}

export type NavItem = NavLeaf | NavGroup

export const NAV_ITEMS: NavItem[] = [
  // ── Inicio ───────────────────────────────────────────────────────────────
  { kind: 'leaf', href: '/dashboard',       label: 'Dashboard', icon: LayoutDashboard, roles: [] },
  { kind: 'leaf', href: '/dashboard/inbox', label: 'Inbox',     icon: MessageSquare,   roles: [], integration: 'whatsapp' },

  // ── Ventas ─────────────────────────────────────────────────────────────
  {
    kind: 'group', id: 'ventas', label: 'Ventas', icon: ShoppingCart, roles: [],
    children: [
      { kind: 'leaf', href: '/dashboard/orders',     label: 'Pedidos',     icon: Package,     roles: [] },
      { kind: 'leaf', href: '/dashboard/contacts',   label: 'Contactos',   icon: Users,       roles: [] },
      { kind: 'leaf', href: '/dashboard/shipping',   label: 'Cotizador',   icon: Truck,       roles: [], integration: 'shipping' },
      { kind: 'leaf', href: '/dashboard/promotions', label: 'Promociones', icon: Tag,         roles: ['owner', 'manager'] },
      { kind: 'leaf', href: '/dashboard/claims',     label: 'Reclamos',    icon: AlertCircle, roles: [] },
      { kind: 'leaf', href: '/dashboard/receipts',   label: 'Comprobantes', icon: Receipt,    roles: [] },
    ],
  },

  // ── Productos ──────────────────────────────────────────────────────────
  { kind: 'leaf', href: '/dashboard/catalog', label: 'Productos', icon: Boxes, roles: ['owner', 'manager'] },
  { kind: 'leaf', href: '/dashboard/categories', label: 'Categorías', icon: Tags, roles: ['owner', 'manager'] },

  // ── Canales ────────────────────────────────────────────────────────────
  // Restaurado como grupo — Shopify, tienda custom entrarán aquí en fases futuras
  {
    kind: 'group', id: 'canales', label: 'Canales', icon: Store, roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/marketplace', label: 'Mercado Libre', icon: Store, roles: ['owner', 'manager'], integration: 'mercadolibre', capability: 'integrations.mercadolibre' },
    ],
  },

  // ── Compras ────────────────────────────────────────────────────────────
  { kind: 'leaf', href: '/dashboard/purchases', label: 'Compras', icon: Wallet, roles: ['owner'] },

  // ── Finanzas ───────────────────────────────────────────────────────────
  { kind: 'leaf', href: '/dashboard/finance', label: 'Finanzas', icon: DollarSign, roles: ['owner'] },

  // ── IA y Conocimiento ──────────────────────────────────────────────────
  // Renombrado: no existe Automatizaciones live — el nombre refleja lo que realmente hay
  {
    kind: 'group', id: 'ia', label: 'IA y Conocimiento', icon: BrainCircuit, roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/knowledge-base', label: 'Base de Conocimiento', icon: BookOpen, roles: ['owner', 'manager'] },
      { kind: 'leaf', href: '/dashboard/ai-agents',      label: 'Agentes IA',           icon: Bot,      roles: ['owner'], capability: 'ai.agents.configure' },
    ],
  },

  // ── Analítica ──────────────────────────────────────────────────────────
  {
    kind: 'group', id: 'analitica', label: 'Analítica', icon: BarChart2, roles: ['owner', 'manager'],
    children: [
      { kind: 'leaf', href: '/dashboard/metrics', label: 'Métricas',  icon: TrendingUp,    roles: ['owner', 'manager'] },
      { kind: 'leaf', href: '/dashboard/audit',   label: 'Auditoría', icon: ClipboardList, roles: ['owner'], capability: 'analytics.audit.export' },
    ],
  },

  // ── Configuración ──────────────────────────────────────────────────────
  //  Rev. 5 — 2026-04-14 (Vuelta 5 — Cierre dominio Configuración)
  //
  //  General         → /settings   — datos del negocio, logo, WABA, dirección de envío, Telegram
  //  Usuarios y Acceso → /team     — equipo RBAC: listado, changeRole, removeMember (extraído)
  //  Integraciones   → /integrations — MeLi OAuth, Envia API key (ruta existente)
  //
  //  Reglas de Negocio: pendiente funcional — no existe base real. No se expone.
  {
    kind: 'group', id: 'configuracion', label: 'Configuración', icon: Settings, roles: ['owner', 'manager', 'operator'],
    children: [
      { kind: 'leaf', href: '/dashboard/settings',                  label: 'General',           icon: Building2, roles: ['owner'] },
      { kind: 'leaf', href: '/dashboard/team',                      label: 'Usuarios y Acceso', icon: Users,     roles: ['owner'] },
      { kind: 'leaf', href: '/dashboard/integrations',              label: 'Integraciones',     icon: Plug,      roles: ['owner', 'manager'] },
      // Rev. 109 J.2.4.3 — Seguridad per-user (MFA TOTP + recovery codes).
      // Accesible para TODOS los roles porque MFA es de la cuenta personal.
      { kind: 'leaf', href: '/dashboard/settings/security',         label: 'Seguridad',         icon: Shield,    roles: ['owner', 'manager', 'operator'] },
      // Rev. 109 J.2.11 — Salud integraciones per-tenant.
      { kind: 'leaf', href: '/dashboard/settings/health',           label: 'Salud integraciones', icon: Activity, roles: ['owner', 'manager'] },
      // Rev. 102 — Habeas Data per-tenant. F6: visible a owner+manager, coherente
      // con la RLS (retention_policies / tenant_legal_acceptance permiten
      // modify a owner+manager) y con el gate de las páginas. El sidebar owner-only
      // solo ocultaba funcionalidad ya accesible al manager.
      { kind: 'leaf', href: '/dashboard/settings/legal',            label: 'Legal',             icon: Scale,     roles: ['owner', 'manager'] },
      { kind: 'leaf', href: '/dashboard/settings/retention',        label: 'Retención datos',   icon: Archive,   roles: ['owner', 'manager'] },
      // Rev. 109 J.2.4.4 — Cerrar cuenta (owner-only, destructive).
      { kind: 'leaf', href: '/dashboard/settings/account-closure',  label: 'Cerrar cuenta',     icon: Trash2,    roles: ['owner'] },
    ],
  },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

export function hasAccess(roles: string[], role: string): boolean {
  return roles.length === 0 || roles.includes(role)
}

/** Hojas navegables del árbol, en orden de aparición (para command palette). */
export function flattenNavLeaves(items: NavItem[]): NavLeaf[] {
  return items.flatMap(item => (item.kind === 'leaf' ? [item] : item.children))
}
