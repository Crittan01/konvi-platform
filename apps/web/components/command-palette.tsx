'use client'

/**
 * CommandPalette — búsqueda federada + navegación global (Spec WOW §4.3).
 *
 * - Atajo global ⌘K / Ctrl+K + trigger en la topbar (input fake en desktop,
 *   icono en móvil — la topbar móvil estaba casi vacía, gap §6.2).
 * - Acciones de navegación: MISMA fuente NAV_ITEMS del sidebar (./dashboard/
 *   nav-items) con los mismos gates RBAC / integración / capability de plan.
 * - Búsqueda de entidades (pedidos, contactos, productos) con debounce 300ms
 *   via el cliente Supabase del browser — el mecanismo de acceso a datos ya
 *   establecido en el frontend (inbox hooks, product-edit-drawer): la sesión
 *   del usuario + RLS acotan al tenant. NO se crearon endpoints nuevos.
 * - Superficie bg-popover + border-border (tokens Kaiu) → dark mode intacto.
 *   En móvil abre como panel full-width bajo la topbar (no modal diminuto).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Search, Package, Users, Boxes, Loader2, AlertCircle, RefreshCw,
} from 'lucide-react'
import { createClient } from '@/utils/supabase/client'
import { NAV_ITEMS, flattenNavLeaves, hasAccess } from '@/app/dashboard/nav-items'
import {
  Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem,
} from '@/components/ui/command'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'

// ── Tipos ─────────────────────────────────────────────────────────────────────

type ContactHit = { id: string; name: string | null; phone: string }
type ProductHit = { id: string; title: string }
type OrderHit = {
  id: string
  status: string
  total_amount: number
  created_at: string
  contactLabel: string
}

type EntityResults = {
  orders: OrderHit[]
  contacts: ContactHit[]
  products: ProductHit[]
}

const EMPTY_RESULTS: EntityResults = { orders: [], contacts: [], products: [] }

interface Props {
  role: string
  integrations: { whatsapp: boolean; shipping: boolean; mercadolibre: boolean }
  planCapabilities: Record<string, boolean>
}

// Sanitiza como la búsqueda server-side de pedidos (D7): sin comodines LIKE.
const sanitize = (q: string) => q.replace(/[%_]/g, '').trim().slice(0, 60)

export default function CommandPalette({ role, integrations, planCapabilities }: Props) {
  const router = useRouter()
  const supabase = useMemo(() => createClient(), [])
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<EntityResults>(EMPTY_RESULTS)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState(false)
  // Guard contra respuestas fuera de orden (debounce + latencia variable).
  const searchSeq = useRef(0)

  // Reset al cerrar: cada apertura empieza limpia. Event-driven (no effect):
  // todos los caminos de cierre pasan por aquí (Esc/overlay vía onOpenChange,
  // selección de ítem vía go(), atajo ⌘K).
  const closePalette = useCallback(() => {
    setOpen(false)
    setQuery('')
    setResults(EMPTY_RESULTS)
    setSearching(false)
    setSearchError(false)
    searchSeq.current++
  }, [])

  // ── Atajo global ⌘K / Ctrl+K ──────────────────────────────────────────────
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        if (open) closePalette()
        else setOpen(true)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, closePalette])

  // ── Navegación: hojas visibles con los mismos gates del sidebar ───────────
  const navActions = useMemo(() => {
    const isIntegrationEnabled = (integration?: 'whatsapp' | 'shipping' | 'mercadolibre') =>
      !integration || integrations[integration] === true
    const isCapabilityEnabled = (capability?: string) =>
      !capability || planCapabilities[capability] !== false
    return flattenNavLeaves(NAV_ITEMS).filter(
      leaf => hasAccess(leaf.roles, role)
        && isIntegrationEnabled(leaf.integration)
        && isCapabilityEnabled(leaf.capability),
    )
  }, [role, integrations, planCapabilities])

  const filteredNav = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return navActions
    return navActions.filter(a => a.label.toLowerCase().includes(q))
  }, [navActions, query])

  // ── Búsqueda de entidades (debounce 300ms) ────────────────────────────────
  const runSearch = useCallback(async (raw: string) => {
    const q = sanitize(raw)
    if (q.length < 2) {
      setResults(EMPTY_RESULTS)
      setSearching(false)
      setSearchError(false)
      return
    }
    const seq = ++searchSeq.current
    setSearching(true)
    setSearchError(false)
    const like = `%${q}%`
    try {
      // Contactos por nombre/teléfono + productos por título/SKU, en paralelo
      // (dos ilike por campo en lugar de .or() — patrón del repo, D7).
      const [byName, byPhone, byTitle, bySku] = await Promise.all([
        supabase.from('contacts').select('id, name, phone').ilike('name', like).limit(4),
        supabase.from('contacts').select('id, name, phone').ilike('phone', like).limit(4),
        supabase.from('products').select('id, title').eq('status', 'active').ilike('title', like).limit(4),
        supabase.from('product_variations').select('product_id').ilike('sku', like).limit(8),
      ])
      if (seq !== searchSeq.current) return // respuesta stale

      const firstErr = byName.error ?? byPhone.error ?? byTitle.error ?? bySku.error
      if (firstErr) throw new Error(firstErr.message)

      const contacts = new Map<string, ContactHit>()
      for (const c of [...(byName.data ?? []), ...(byPhone.data ?? [])] as ContactHit[]) {
        contacts.set(c.id, c)
      }

      const products = new Map<string, ProductHit>()
      for (const p of (byTitle.data ?? []) as ProductHit[]) products.set(p.id, p)
      const skuProductIds = Array.from(new Set(
        ((bySku.data ?? []) as { product_id: string }[]).map(r => r.product_id),
      )).filter(id => !products.has(id))
      if (skuProductIds.length > 0) {
        const { data: extra, error: extraErr } = await supabase
          .from('products').select('id, title').eq('status', 'active').in('id', skuProductIds).limit(4)
        if (seq !== searchSeq.current) return
        if (extraErr) throw new Error(extraErr.message)
        for (const p of (extra ?? []) as ProductHit[]) products.set(p.id, p)
      }

      // Pedidos: mismas semánticas que la lista (D7) — por contacto (nombre/teléfono).
      let orders: OrderHit[] = []
      const contactIds = Array.from(contacts.keys())
      if (contactIds.length > 0) {
        const { data: orderRows, error: orderErr } = await supabase
          .from('orders')
          .select('id, status, total_amount, created_at, contacts(name, phone)')
          .in('contact_id', contactIds)
          .order('created_at', { ascending: false })
          .limit(5)
        if (seq !== searchSeq.current) return
        if (orderErr) throw new Error(orderErr.message)
        type RawOrder = {
          id: string; status: string; total_amount: number; created_at: string
          contacts: { name: string | null; phone: string } | { name: string | null; phone: string }[] | null
        }
        orders = ((orderRows ?? []) as unknown as RawOrder[]).map(o => {
          const c = Array.isArray(o.contacts) ? o.contacts[0] : o.contacts
          return {
            id: o.id, status: o.status, total_amount: o.total_amount, created_at: o.created_at,
            contactLabel: c ? (c.name || c.phone) : 'Cliente anónimo',
          }
        })
      }

      setResults({
        orders,
        contacts: Array.from(contacts.values()).slice(0, 5),
        products: Array.from(products.values()).slice(0, 5),
      })
      setSearching(false)
    } catch {
      if (seq !== searchSeq.current) return
      // Anti-falso-0 (§3.2): un error de búsqueda NO se pinta como "sin resultados".
      setResults(EMPTY_RESULTS)
      setSearching(false)
      setSearchError(true)
    }
  }, [supabase])

  useEffect(() => {
    const t = setTimeout(() => { void runSearch(query) }, 300)
    return () => clearTimeout(t)
  }, [query, runSearch])

  const go = useCallback((href: string) => {
    closePalette()
    router.push(href)
  }, [router, closePalette])

  const hasEntityResults =
    results.orders.length + results.contacts.length + results.products.length > 0
  const showEmpty =
    sanitize(query).length >= 2 && !searching && !searchError && !hasEntityResults && filteredNav.length === 0

  return (
    <>
      {/* Trigger desktop — input fake con hint ⌘K */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Buscar y navegar (Comando K)"
        className="hidden sm:flex items-center gap-2 h-8 w-52 lg:w-64 rounded-lg border border-white/15 bg-white/5 px-3 text-xs text-white/60 hover:bg-white/10 hover:text-white/80 transition-colors"
      >
        <Search className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="flex-1 text-left truncate">Buscar pedidos, contactos…</span>
        <kbd className="pointer-events-none inline-flex h-5 select-none items-center rounded border border-white/20 bg-white/5 px-1.5 font-mono text-[10px] font-medium text-white/70">
          ⌘K
        </kbd>
      </button>
      {/* Trigger móvil — icono (la topbar móvil estaba casi vacía) */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Buscar y navegar"
        className="sm:hidden h-8 w-8 inline-flex items-center justify-center rounded-lg border border-white/15 bg-white/5 text-white/70 hover:bg-white/10 transition-colors"
      >
        <Search className="h-4 w-4" aria-hidden />
      </button>

      <Dialog open={open} onOpenChange={(o) => { if (o) setOpen(true); else closePalette() }}>
        <DialogContent
          className="top-3 translate-y-0 sm:top-[50%] sm:translate-y-[-50%] w-[calc(100%-1.5rem)] max-w-lg overflow-hidden p-0 gap-0 bg-popover"
          aria-describedby={undefined}
        >
          <DialogTitle className="sr-only">Buscar y navegar</DialogTitle>
          <Command shouldFilter={false} label="Buscar y navegar">
            <CommandInput
              className="pr-8"
              placeholder="Buscar módulos, pedidos, contactos, productos…"
              value={query}
              onValueChange={setQuery}
            />
            <CommandList className="max-h-[min(24rem,60vh)]">
              {searching && (
                <div className="flex items-center gap-2 px-3 py-3 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  Buscando…
                </div>
              )}
              {searchError && (
                <div className="flex items-center justify-between gap-3 px-3 py-3 text-xs text-muted-foreground">
                  <span className="flex items-center gap-2">
                    <AlertCircle className="h-3.5 w-3.5 text-destructive" aria-hidden />
                    No se pudo completar la búsqueda.
                  </span>
                  <button
                    type="button"
                    onClick={() => void runSearch(query)}
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    <RefreshCw className="h-3 w-3" aria-hidden /> Reintentar
                  </button>
                </div>
              )}
              {showEmpty && (
                <CommandEmpty>
                  <EmptyState
                    variant="plain"
                    icon={Search}
                    className="py-2"
                    description={<>Sin resultados para &ldquo;{sanitize(query)}&rdquo;.</>}
                  />
                </CommandEmpty>
              )}

              {filteredNav.length > 0 && (
                <CommandGroup heading="Navegación">
                  {filteredNav.map(action => (
                    <CommandItem
                      key={action.href}
                      value={`nav:${action.href}`}
                      onSelect={() => go(action.href)}
                    >
                      <action.icon className="text-muted-foreground" aria-hidden />
                      <span>{action.label}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}

              {results.orders.length > 0 && (
                <CommandGroup heading="Pedidos">
                  {results.orders.map(o => (
                    <CommandItem
                      key={o.id}
                      value={`order:${o.id}`}
                      onSelect={() => go(`/dashboard/orders/${o.id}`)}
                    >
                      <Package className="text-muted-foreground" aria-hidden />
                      <span className="flex-1 truncate">
                        <span className="font-mono text-xs">{o.id.split('-')[0].toUpperCase()}</span>
                        {' · '}{o.contactLabel}
                      </span>
                      <span className="text-xs text-muted-foreground tabular-nums">
                        ${o.total_amount.toLocaleString('es-CO')}
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}

              {results.contacts.length > 0 && (
                <CommandGroup heading="Contactos">
                  {results.contacts.map(c => (
                    <CommandItem
                      key={c.id}
                      value={`contact:${c.id}`}
                      onSelect={() => go(`/dashboard/contacts?q=${encodeURIComponent(c.phone)}`)}
                    >
                      <Users className="text-muted-foreground" aria-hidden />
                      <span className="flex-1 truncate">{c.name || c.phone}</span>
                      {c.name && <span className="text-xs text-muted-foreground">{c.phone}</span>}
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}

              {results.products.length > 0 && (
                <CommandGroup heading="Productos">
                  {results.products.map(p => (
                    <CommandItem
                      key={p.id}
                      value={`product:${p.id}`}
                      onSelect={() => go(`/dashboard/catalog?q=${encodeURIComponent(p.title)}`)}
                    >
                      <Boxes className="text-muted-foreground" aria-hidden />
                      <span className="flex-1 truncate">{p.title}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
            </CommandList>
          </Command>
        </DialogContent>
      </Dialog>
    </>
  )
}
