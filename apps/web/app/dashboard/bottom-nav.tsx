'use client'

import { BarChart3, Boxes, MessageSquare, ShoppingBag, Users } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

// Navegación inferior móvil — acceso directo a los destinos primarios. El menú
// completo sigue en el drawer del sidebar (hamburguesa). Solo visible < lg.
const ITEMS = [
  { href: '/dashboard/inbox', label: 'Inbox', Icon: MessageSquare },
  { href: '/dashboard/orders', label: 'Pedidos', Icon: ShoppingBag },
  { href: '/dashboard/catalog', label: 'Catálogo', Icon: Boxes },
  { href: '/dashboard/contacts', label: 'Contactos', Icon: Users },
  { href: '/dashboard/metrics', label: 'Métricas', Icon: BarChart3 },
]

export function BottomNav({ inboxBadge = 0 }: { inboxBadge?: number }) {
  const pathname = usePathname()
  return (
    <nav
      aria-label="Navegación principal"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card/90 backdrop-blur-sm supports-backdrop-filter:bg-card/75 lg:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <ul className="flex items-stretch justify-around">
        {ITEMS.map(({ href, label, Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`)
          // Mismo dato que el badge del sidebar desktop (conversaciones en
          // human_takeover, sin archivadas — layout.tsx). En móvil el sidebar
          // queda oculto tras el drawer: sin este badge el operador no ve urgencias.
          const showBadge = href === '/dashboard/inbox' && inboxBadge > 0
          return (
            <li key={href} className="flex-1">
              <Link
                href={href}
                aria-current={active ? 'page' : undefined}
                aria-label={
                  showBadge
                    ? `${label}, ${inboxBadge > 99 ? 'más de 99' : inboxBadge} ${inboxBadge === 1 ? 'conversación necesita' : 'conversaciones necesitan'} atención humana`
                    : undefined
                }
                className={`flex flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium transition-colors ${
                  active ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <span className="relative">
                  <Icon className="h-5 w-5" aria-hidden />
                  {showBadge && (
                    <span
                      aria-hidden
                      className="absolute -top-1.5 -right-2.5 inline-flex items-center justify-center h-4 min-w-4 px-1 rounded-full bg-red-100 text-red-600 border border-red-200 text-[10px] font-bold tabular-nums"
                    >
                      {inboxBadge > 99 ? '99+' : inboxBadge}
                    </span>
                  )}
                </span>
                <span>{label}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
