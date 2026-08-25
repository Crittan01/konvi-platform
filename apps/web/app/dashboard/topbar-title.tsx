'use client'

// T7.5 — identidad de página en la topbar (móvil y desktop).
//
// En móvil la topbar no decía dónde estás (gap §6.2 de UX-UI.md); la directiva
// founder (2026-08-25) pide la firma diferencial en TODO el front. El título se
// resuelve de la fuente ÚNICA `NAV_ITEMS` (la misma del sidebar y de la command
// palette — cero duplicación de labels/gates) con match por prefijo más largo,
// más overrides de las rutas huérfanas conocidas (media, integraciones por
// proveedor). Entra con FadeIn keyeado por destino (firma de motion Track 7;
// reduced-motion lo neutraliza vía el wrapper del DS).

import { usePathname } from 'next/navigation'
import { FadeIn } from '@/components/ui/motion'
import { NAV_ITEMS, flattenNavLeaves } from './nav-items'

// Rutas reales que NO están en NAV_ITEMS (huérfanas ◊ del inventario §5) o cuya
// etiqueta pide más precisión que el prefijo genérico "Integraciones".
const ROUTE_OVERRIDES: Record<string, { label: string; group?: string }> = {
  '/dashboard/media': { label: 'Media', group: 'Productos' },
  '/dashboard/integrations/whatsapp': { label: 'WhatsApp', group: 'Integraciones' },
  '/dashboard/integrations/wompi': { label: 'Wompi', group: 'Integraciones' },
  '/dashboard/integrations/aveonline': { label: 'Aveonline', group: 'Integraciones' },
  '/dashboard/integrations/telegram': { label: 'Telegram', group: 'Integraciones' },
  '/dashboard/integrations/mercadolibre': { label: 'Mercado Libre', group: 'Integraciones' },
}

export function resolveTopbarTitle(pathname: string): { label: string; group?: string } {
  if (ROUTE_OVERRIDES[pathname]) return ROUTE_OVERRIDES[pathname]

  const leaves = flattenNavLeaves(NAV_ITEMS)
  // Match por prefijo MÁS LARGO (detalles tipo /orders/[id] heredan su módulo;
  // '/dashboard' solo por igualdad exacta para no prefijar todo el árbol).
  let best: { href: string; label: string } | null = null
  for (const leaf of leaves) {
    const matches =
      pathname === leaf.href ||
      (leaf.href !== '/dashboard' && pathname.startsWith(`${leaf.href}/`))
    if (matches && (!best || leaf.href.length > best.href.length)) {
      best = leaf
    }
  }
  if (best) {
    for (const item of NAV_ITEMS) {
      if (item.kind === 'group' && item.children.some(c => c.href === best!.href)) {
        return { label: best.label, group: item.label }
      }
    }
    return { label: best.label }
  }
  // '/dashboard' y cualquier ruta sin módulo (redirects de compatibilidad
  // nunca pintan título: salen por redirect antes de renderizar).
  return { label: 'Dashboard' }
}

export default function TopbarTitle() {
  const pathname = usePathname() ?? '/dashboard'
  const { label, group } = resolveTopbarTitle(pathname)
  return (
    <FadeIn key={`${group ?? ''}:${label}`} className="min-w-0">
      <p className="truncate text-sm font-medium" aria-current="page">
        {group && <span className="opacity-60 hidden sm:inline">{group} · </span>}
        {label}
      </p>
    </FadeIn>
  )
}
