'use client'

import { useState, useEffect, useTransition, useRef, useCallback } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import { Package, Clock, ChevronRight, ChevronLeft, Hourglass, CheckCircle2, Settings2, MapPin, X, LayoutList, Search, Loader2, Truck, RefreshCw, AlertCircle, Link2, Copy, Send, User } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import Link from 'next/link'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'
import { useConfirm } from '@/components/ui/confirm-dialog'
import { ResponsiveDialog } from '@/components/ui/responsive-dialog'
import { StaggerList, StaggerItem, LayoutItem } from '@/components/ui/motion'
import AiInsightPanel from '@/components/ai-insight-panel'
import OrdersNewForm from '../orders-new-form'

// ─── Tipos ────────────────────────────────────────────────────────────────────
type Variation = { id: string; price: number | null; attributes: Record<string, string> | null }
type Product   = { id: string; title: string; product_variations: Variation[] }
type Contact   = { id: string; phone: string; name: string | null }
type OrderItem = { title: string; quantity: number; unit_price: number }
type Order = {
  id: string
  status: string
  total_amount: number
  discount_amount?: number | null
  shipping_cost: number | null
  notes: string | null
  created_at: string
  contacts: Contact | Contact[] | null
  order_items: OrderItem[]
  payment_method?: string | null  // 'credit' | 'cod' (rev. 108 Fase B)
}

type Props = {
  initialOrders: Order[]
  products: Product[]
  contacts: Contact[]
  role: string
  canWrite: boolean          // owner|manager|operator — crear/avanzar (opera el módulo)
  canManageMoney: boolean    // owner|manager — cancelar, link de pago, guía (mueven dinero)
  counts: Record<string, number>
  filteredCount: number      // total del filtro server-side actual (para paginación)
  currentPage: number
  totalPages: number
  perPage: number
  status: string
  query: string
  contactId?: string | null
  contactName?: string | null
  loadError?: string | null
  updateStatusAction: (fd: FormData) => Promise<void>
  generateShippingGuideAction?: (fd: FormData) => Promise<{
    ok: boolean
    message?: string
    tracking?: string
  }>
}

// ─── Constantes ───────────────────────────────────────────────────────────────
const STATUS_LABELS: Record<string, string> = {
  pending:         'Pendiente',
  pending_payment: 'Esperando pago',
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

const STATUS_NEXT: Record<string, string> = {
  pending:         'confirmed',
  pending_payment: 'confirmed',
  confirmed:  'processing',
  processing: 'shipped',
  shipped:    'delivered',
}

const STATUS_COLORS: Record<string, string> = {
  pending:         'bg-warning-bg text-warning-fg border-warning-border',
  pending_payment: 'bg-warning-bg text-warning-fg border-warning-border',
  confirmed:  'bg-info-bg text-info-fg border-info-border',
  processing: 'bg-ai-bg text-ai-fg border-ai-border',
  shipped:    'bg-ai-bg text-ai-fg border-ai-border',
  delivered:  'bg-success-bg text-success-fg border-success-border',
  cancelled:  'bg-danger-bg text-danger-fg border-danger-border',
}

const STATUS_ADVANCE_HELP: Record<string, string> = {
  confirmed:  'Al confirmar se descuenta el inventario de los productos del pedido.',
  processing: 'Marca el pedido como en preparación para su despacho.',
  shipped:    'Marca el pedido como despachado al cliente.',
  delivered:  'Cierra el pedido como entregado. Es un estado final: no se puede reabrir.',
}

const STATUS_ICONS: Record<string, React.ElementType> = {
  all:        LayoutList,
  pending:    Hourglass,
  pending_payment: Hourglass,
  confirmed:  CheckCircle2,
  processing: Settings2,
  shipped:    Package,
  delivered:  MapPin,
  cancelled:  X,
}

const ROLE_LABELS: Record<string, string> = {
  owner:    'Administrador',
  manager:  'Supervisor',
  operator: 'Gestor',
}

const TAB_FILTERS = ['all', 'pending', 'pending_payment', 'confirmed', 'processing', 'shipped', 'delivered', 'cancelled']

// ─── Sub-componentes ──────────────────────────────────────────────────────────

// D2 — Link de pago Wompi desde la consola. Genera (o regenera) el link vía el
// proxy web y cierra el ciclo de cobro: copiar al portapapeles + reenviar por
// WhatsApp (deep-link wa.me pre-poblado) sin depender de que el cliente reescriba.
function PaymentLinkButton({ orderId, phone }: { orderId: string; phone?: string | null }) {
  const [isPending, startTransition] = useTransition()
  const [url, setUrl] = useState<string | null>(null)

  const generate = () => {
    startTransition(async () => {
      try {
        const res = await fetch(`/api/orders/${orderId}/payment-link`, {
          method: 'POST',
          signal: AbortSignal.timeout(27000),
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          toast.error(data.detail || `No se pudo generar el link (HTTP ${res.status}).`)
          return
        }
        const checkout = data.checkout_url as string | undefined
        if (!checkout) { toast.error('El servidor no devolvió un link válido.'); return }
        setUrl(checkout)
        try { await navigator.clipboard.writeText(checkout); toast.success('Link de pago generado y copiado.') }
        catch { toast.success('Link de pago generado.') }
      } catch {
        toast.error('Error de red al generar el link.')
      }
    })
  }

  const copy = async () => {
    if (!url) return
    try { await navigator.clipboard.writeText(url); toast.success('Link copiado.') }
    catch { toast.error('No se pudo copiar. Selecciónalo manualmente.') }
  }

  const waHref = () => {
    const digits = (phone || '').replace(/\D/g, '')
    const msg = encodeURIComponent(`Hola 👋 Aquí está tu link de pago seguro para completar tu pedido:\n${url}`)
    return digits ? `https://wa.me/${digits}?text=${msg}` : `https://wa.me/?text=${msg}`
  }

  if (!url) {
    return (
      <button
        type="button"
        onClick={generate}
        disabled={isPending}
        className="inline-flex items-center gap-1.5 text-xs text-primary hover:text-primary/80 border border-primary/40 hover:border-primary/60 bg-primary/5 rounded-lg px-3 py-1.5 transition-all disabled:opacity-50"
        title="Genera un link de pago Wompi para cobrar este pedido"
      >
        {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Link2 className="h-3 w-3" />}
        {isPending ? 'Generando…' : 'Generar link de pago'}
      </button>
    )
  }

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <button type="button" onClick={() => void copy()} className="inline-flex items-center gap-1.5 text-xs text-foreground border border-border hover:bg-accent rounded-lg px-2.5 py-1.5 transition-all">
        <Copy className="h-3 w-3" /> Copiar link
      </button>
      <a href={waHref()} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs text-success-fg border border-success-border hover:border-success-fg bg-success-bg rounded-lg px-2.5 py-1.5 transition-all">
        <Send className="h-3 w-3" /> Reenviar por WhatsApp
      </a>
    </div>
  )
}

function GenerateGuideButton({
  orderId,
  action,
}: {
  orderId: string
  action: (fd: FormData) => Promise<{ ok: boolean; message?: string; tracking?: string }>
}) {
  const [isPending, startTransition] = useTransition()
  const confirmar = useConfirm()
  const [result, setResult] = useState<{ ok: boolean; message?: string } | null>(null)

  const handle = async () => {
    if (!(await confirmar({
      title: '¿Generar guía COD para este pedido?',
      description: 'Se creará la guía de envío en Aveonline con recaudo contraentrega. '
        + 'Tarda entre 10 y 15 segundos y, si tu cuenta genera guías reales, será facturable.',
      confirmLabel: 'Generar guía',
    }))) return
    setResult(null)
    startTransition(async () => {
      const fd = new FormData()
      fd.append('order_id', orderId)
      const r = await action(fd)
      setResult(r)
    })
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => void handle()}
        disabled={isPending}
        className="inline-flex items-center gap-1.5 text-xs text-success-fg hover:text-success-fg border border-success-border hover:border-success-fg bg-success-bg rounded-lg px-3 py-1.5 transition-all disabled:opacity-50"
        title="Genera guía Aveonline con contraentrega — el courier recauda al entregar"
      >
        {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Truck className="h-3 w-3" />}
        {isPending ? 'Generando…' : 'Generar guía COD'}
      </button>
      {result && (
        <span className={`text-xs ${result.ok ? 'text-success-fg' : 'text-danger-fg'}`}>
          {result.message}
        </span>
      )}
    </div>
  )
}

function ActionButton({
  orderId, nextStatus, originalStatus, canManageMoney, updateStatusAction,
}: {
  orderId: string, nextStatus: string, originalStatus: string, canManageMoney: boolean, updateStatusAction: (fd: FormData) => Promise<void>
}) {
  const [isPending, startTransition] = useTransition()
  // Spec WOW §4.4: la confirmación del cambio de estado es bottom-sheet (vaul)
  // en < lg y el Dialog del DS en ≥ lg — mismo contenido, dos presentaciones.
  // Acotado a ESTE flujo: el ConfirmDialog global (21 consumidores) no se toca.
  const [confirmAction, setConfirmAction] = useState<'next' | 'cancel' | null>(null)

  const run = (fd: FormData, successMsg: string) => {
    startTransition(async () => {
      try {
        await updateStatusAction(fd)
        toast.success(successMsg)
      } catch (e) {
        toast.error(e instanceof Error && e.message ? e.message : 'No se pudo actualizar el pedido.')
      }
    })
  }

  const handleConfirm = () => {
    if (!confirmAction) return
    const fd = new FormData()
    fd.append('order_id', orderId)
    if (confirmAction === 'cancel') {
      fd.append('cancel', 'true')
      run(fd, 'Pedido cancelado.')
    } else {
      fd.append('next_status', nextStatus)
      run(fd, `Pedido actualizado a ${STATUS_LABELS[nextStatus]}.`)
    }
    setConfirmAction(null)
  }

  const isCancel = confirmAction === 'cancel'

  return (
    <div className="flex flex-col sm:flex-row gap-2 mt-4 pt-3 border-t border-border">
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              onClick={() => setConfirmAction('next')}
              disabled={isPending}
              size="sm"
              className="w-full sm:w-auto h-8 text-xs font-semibold"
            >
              {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Avanzar a {STATUS_LABELS[nextStatus]} <ChevronRight className="h-3 w-3 ml-1" /></>}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{STATUS_ADVANCE_HELP[nextStatus] ?? `Pasar a "${STATUS_LABELS[nextStatus]}".`}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      {/* D1: cancelar mueve dinero (refund) → solo owner/manager. Se mantiene sobre
          'pending' (cancelar post-confirmación con restock/refund queda pendiente). */}
      {originalStatus === 'pending' && canManageMoney && (
        <Button
          variant="ghost"
          onClick={() => setConfirmAction('cancel')}
          disabled={isPending}
          size="sm"
          className="w-full sm:w-auto h-8 text-xs text-muted-foreground hover:text-danger-fg hover:bg-destructive/10"
        >
          {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Cancelar pedido'}
        </Button>
      )}

      <ResponsiveDialog
        open={confirmAction !== null}
        onOpenChange={(o) => { if (!o) setConfirmAction(null) }}
        title={isCancel ? '¿Cancelar este pedido?' : `¿Avanzar a ${STATUS_LABELS[nextStatus]}?`}
        description={
          isCancel
            ? 'El pedido quedará cancelado de forma definitiva. Esta acción no se puede revertir.'
            : (STATUS_ADVANCE_HELP[nextStatus] ?? `El pedido pasará a "${STATUS_LABELS[nextStatus]}".`)
        }
        footer={
          <>
            <Button type="button" variant="outline" size="sm" onClick={() => setConfirmAction(null)}>
              Volver
            </Button>
            <Button
              type="button"
              size="sm"
              variant={isCancel ? 'destructive' : 'default'}
              disabled={isPending}
              onClick={handleConfirm}
            >
              {isPending
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : isCancel ? 'Cancelar pedido' : `Avanzar a ${STATUS_LABELS[nextStatus]}`}
            </Button>
          </>
        }
      />
    </div>
  )
}

// ─── Componente Principal ─────────────────────────────────────────────────────

/**
 * OrderStatusBadge — badge de estado con micro-transición al CAMBIAR de valor
 * (Spec WOW §4.2: fade/scale sutil, ~200ms). Solo en cambios reales: ni en el
 * primer render ni en refetches con el mismo estado (patrón oficial de estado
 * derivado durante el render). motion-reduce:animate-none cubre reduced-motion.
 */
function OrderStatusBadge({ status, colorClass }: { status: string; colorClass: string }) {
  const [prevStatus, setPrevStatus] = useState(status)
  const changed = prevStatus !== status
  if (changed) setPrevStatus(status)
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${colorClass} ${
      changed ? 'animate-in fade-in-0 zoom-in-95 duration-200 motion-reduce:animate-none' : ''
    }`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}

export default function OrdersManager({
  initialOrders, products, contacts, role, canWrite, canManageMoney, counts,
  filteredCount, currentPage, totalPages, perPage, status, query, contactId,
  contactName, loadError, updateStatusAction, generateShippingGuideAction,
}: Props) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [isNavPending, startNav] = useTransition()

  // Búsqueda local con debounce → empuja ?q al server (D7: search server-side).
  const [searchInput, setSearchInput] = useState(query)
  useEffect(() => { setSearchInput(query) }, [query])
  const firstRender = useRef(true)

  // Construye una URL nueva mutando searchParams; al cambiar filtros resetea page.
  const buildUrl = useCallback((updates: Record<string, string | null>, resetPage = true) => {
    const params = new URLSearchParams(searchParams.toString())
    for (const [k, v] of Object.entries(updates)) {
      if (v === null || v === '') params.delete(k)
      else params.set(k, v)
    }
    if (resetPage && !('page' in updates)) params.delete('page')
    const qs = params.toString()
    return qs ? `${pathname}?${qs}` : pathname
  }, [searchParams, pathname])

  const navigate = useCallback((url: string) => {
    startNav(() => router.push(url, { scroll: false }))
  }, [router])

  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return }
    const t = setTimeout(() => {
      if (searchInput.trim() === query) return
      navigate(buildUrl({ q: searchInput.trim() || null }))
    }, 400)
    return () => clearTimeout(t)
  }, [searchInput, query, buildUrl, navigate])

  const setStatus = (s: string) => navigate(buildUrl({ status: s === 'all' ? null : s }))
  const goToPage = (p: number) => navigate(buildUrl({ page: String(p) }, false))
  const clearAll = () => navigate(pathname)

  const from = filteredCount === 0 ? 0 : (currentPage - 1) * perPage + 1
  const to = Math.min(currentPage * perPage, filteredCount)

  return (
    <div className="space-y-5 max-w-7xl">
      {/* Header & Search — cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={Package}
        title="Pedidos"
        description={`${counts['all'] ?? 0} pedidos totales`}
        actions={
          <div className="flex flex-col sm:flex-row items-center gap-3 w-full md:w-auto">
            <div className="relative w-full md:w-80">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              <Input
                placeholder="Buscar por nombre, teléfono o nota..."
                value={searchInput}
                onChange={e => setSearchInput(e.target.value)}
                aria-label="Buscar pedidos"
                className="pl-9 pr-8 h-9 text-sm bg-card w-full"
              />
              {(searchInput || isNavPending) && (
                <span className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center">
                  {isNavPending
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                    : <button type="button" onClick={() => { setSearchInput(''); navigate(buildUrl({ q: null })) }} aria-label="Limpiar búsqueda" className="text-muted-foreground hover:text-foreground"><X className="h-3.5 w-3.5" /></button>}
                </span>
              )}
            </div>
            <Badge variant="outline" className="text-xs self-start sm:self-auto h-9">
              {ROLE_LABELS[role] ?? role}
            </Badge>
          </div>
        }
      />

      {/* Error de lectura */}
      {loadError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription className="flex items-center justify-between gap-3">
            <span>{loadError}</span>
            <Button type="button" variant="outline" size="sm" className="h-7 text-xs gap-1.5 shrink-0" onClick={() => router.refresh()}>
              <RefreshCw className="h-3 w-3" /> Reintentar
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* D9 — filtro por contacto (deep-link desde Contactos/Reclamos) */}
      {contactId && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
          <span className="flex items-center gap-1.5 text-foreground min-w-0">
            <User className="h-4 w-4 text-primary shrink-0" />
            <span className="truncate">Pedidos de <span className="font-medium">{contactName || 'este contacto'}</span></span>
          </span>
          <button type="button" onClick={() => navigate(buildUrl({ contact_id: null }))} className="inline-flex items-center gap-1 text-xs text-primary hover:underline shrink-0">
            <X className="h-3 w-3" /> Quitar filtro
          </button>
        </div>
      )}

      {/* AI Insight */}
      {(role === 'owner' || role === 'manager') && (
        <AiInsightPanel module="orders" label="Pedidos" />
      )}

      {/* Filtros de estado */}
      <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1">
        {TAB_FILTERS.map(s => {
          const Icon = STATUS_ICONS[s] ?? LayoutList
          const active = (s === 'all' && status === 'all') || status === s
          return (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              aria-pressed={active}
              aria-label={`Filtrar por ${s === 'all' ? 'todos' : STATUS_LABELS[s]}${counts[s] ? ` (${counts[s]})` : ''}`}
              className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                active
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'border-border text-muted-foreground hover:text-foreground hover:bg-accent'
              }`}
            >
              <Icon className="h-4 w-4 mr-1.5 opacity-70 shrink-0" />
              <span>{s === 'all' ? 'Todos' : STATUS_LABELS[s]}</span>
              {counts[s] !== undefined && counts[s] > 0 && (
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${
                  active ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground'
                }`}>
                  {counts[s]}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Grid principal */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

        {/* Formulario nuevo pedido */}
        {canWrite && (
          <div className="xl:col-span-1">
            <OrdersNewForm products={products} contacts={contacts} onCreated={() => router.refresh()} />
          </div>
        )}

        {/* Lista de pedidos */}
        <div className={canWrite ? 'xl:col-span-2' : 'xl:col-span-3'}>
          {initialOrders.length === 0 ? (
            <EmptyState
              icon={Package}
              className="py-16"
              description={
                query
                  ? 'No se encontraron resultados para la búsqueda.'
                  : (status === 'all' && !contactId)
                    ? (canWrite
                        ? 'Aún no tienes pedidos. Llegan automáticamente cuando un cliente compra por el bot de WhatsApp, o puedes crear uno a mano con el formulario “Nuevo Pedido” de la izquierda.'
                        : 'Aún no hay pedidos. Llegan automáticamente cuando un cliente compra por el bot de WhatsApp.')
                    : `No hay pedidos${status !== 'all' ? ` con estado "${STATUS_LABELS[status]}"` : ''}${contactId ? ' para este contacto' : ''}.`
              }
              action={
                (status !== 'all' || query || contactId) ? (
                  <button type="button" onClick={clearAll} className="text-xs text-primary hover:underline">
                    Limpiar filtros
                  </button>
                ) : undefined
              }
            />
          ) : (
            /* Spec WOW §4.2: entrada escalonada sutil (stagger 25ms) solo en los
               primeros 6 ítems (sin cascada infinita). Las keys estables (o.id)
               evitan re-animar en refreshes con la misma data.
               T7.3: LayoutItem envuelve TODA card — al cambiar de filtro/página
               las que sobreviven se REUBICAN suave (layout animation) en vez de
               saltar; la entrada de las nuevas sigue siendo del StaggerItem. */
            <StaggerList stagger={0.025} className={`space-y-4 transition-opacity ${isNavPending ? 'opacity-60' : ''}`}>
              {initialOrders.map((o, orderIdx) => {
                const nextStatus = STATUS_NEXT[o.status]
                const colorClass = STATUS_COLORS[o.status] || 'bg-muted text-muted-foreground'
                const contact = Array.isArray(o.contacts) ? o.contacts[0] : o.contacts
                const subtotal  = o.order_items.reduce((acc, i) => acc + i.unit_price * i.quantity, 0)
                const shipping  = o.shipping_cost ?? 0
                const discount  = o.discount_amount ?? 0
                const revenue   = o.total_amount ?? (subtotal + shipping - discount)

                // La key de lista vive en el LayoutItem (wrapper exterior).
                const card = (
                  <div className="rounded-xl border border-border bg-card p-4 hover:border-primary/30 hover:shadow-xs transition-all focus-within:border-primary/50">
                    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 mb-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <OrderStatusBadge status={o.status} colorClass={colorClass} />
                          {o.payment_method === 'cod' && (
                            <TooltipProvider delayDuration={200}>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-success-bg text-success-fg border-success-border cursor-default">
                                    💵 COD
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent>Pago contraentrega — el courier recauda al entregar.</TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          )}
                          {/* D6/D8 — el id enlaza a la vista de detalle */}
                          <Link href={`/dashboard/orders/${o.id}`} className="text-[10px] text-muted-foreground hover:text-primary font-mono truncate max-w-[120px] underline-offset-2 hover:underline">
                            {o.id.split('-')[0].toUpperCase()}
                          </Link>
                          <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {new Date(o.created_at).toLocaleString('es-CO', { timeZone: 'America/Bogota', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                        <p className="font-semibold text-sm truncate">
                          {contact ? (contact.name || contact.phone) : 'Cliente anónimo'}
                        </p>
                        {contact?.name && <p className="text-xs text-muted-foreground">{contact.phone}</p>}
                      </div>
                      <div className="text-left sm:text-right">
                        <p className="text-lg font-bold text-primary tabular-nums tracking-tight">
                          ${revenue.toLocaleString('es-CO', { minimumFractionDigits: 0 })}
                        </p>
                        <p className="text-[10px] text-muted-foreground">{o.order_items.reduce((s, i) => s + i.quantity, 0)} ítems</p>
                      </div>
                    </div>

                    <div className="bg-muted/30 rounded-lg p-3 text-xs space-y-1.5">
                      {o.order_items.map((it, idx) => (
                        <div key={idx} className="flex justify-between items-center gap-2">
                          <span className="text-muted-foreground truncate">{it.quantity}x {it.title}</span>
                          <span className="font-mono tabular-nums shrink-0">${it.unit_price.toLocaleString('es-CO')}</span>
                        </div>
                      ))}
                      {shipping > 0 && (
                        <div className="flex justify-between items-center gap-2 pt-1.5 mt-1 border-t border-border/40">
                          <span className="text-muted-foreground flex items-center gap-1"><MapPin className="h-3 w-3" /> Envío</span>
                          <span className="font-mono tabular-nums shrink-0">${shipping.toLocaleString('es-CO')}</span>
                        </div>
                      )}
                      {discount > 0 && (
                        <div className="flex justify-between items-center gap-2">
                          <span className="text-success-fg flex items-center gap-1">Descuento</span>
                          <span className="font-mono tabular-nums shrink-0 text-success-fg">−${discount.toLocaleString('es-CO')}</span>
                        </div>
                      )}
                      {(shipping > 0 || discount > 0) && (
                        <div className="flex justify-between items-center gap-2 pt-1.5 mt-1 border-t border-border/60 font-semibold text-foreground">
                          <span>Total</span>
                          <span className="font-mono tabular-nums shrink-0">${revenue.toLocaleString('es-CO')}</span>
                        </div>
                      )}
                      {o.notes && (
                        <div className="pt-2 mt-2 border-t border-border/50 text-muted-foreground italic line-clamp-2">
                          &quot;{o.notes}&quot;
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2 mt-3 flex-wrap">
                      {canWrite && nextStatus && (
                        <ActionButton orderId={o.id} originalStatus={o.status} nextStatus={nextStatus} canManageMoney={canManageMoney} updateStatusAction={updateStatusAction} />
                      )}
                      {/* D2 — cobro Wompi para pedidos aún sin pagar */}
                      {canManageMoney && ['pending', 'pending_payment'].includes(o.status) && (
                        <PaymentLinkButton orderId={o.id} phone={contact?.phone} />
                      )}
                      {['confirmed', 'processing', 'shipped'].includes(o.status) && (
                        <Link
                          href={`/dashboard/shipping?order=${o.id}`}
                          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary border border-border hover:border-primary/40 rounded-lg px-3 py-1.5 transition-all"
                        >
                          <Truck className="h-3 w-3" /> Cotizar envío
                        </Link>
                      )}
                      {canManageMoney
                        && o.payment_method === 'cod'
                        && o.status === 'confirmed'
                        && generateShippingGuideAction && (
                        <GenerateGuideButton orderId={o.id} action={generateShippingGuideAction} />
                      )}
                      <Link href={`/dashboard/orders/${o.id}`} className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary ml-auto">
                        Ver detalle <ChevronRight className="h-3 w-3" />
                      </Link>
                    </div>
                  </div>
                )

                return (
                  <LayoutItem key={o.id}>
                    {orderIdx < 6
                      ? <StaggerItem>{card}</StaggerItem>
                      : card}
                  </LayoutItem>
                )
              })}

              {/* D7 — Paginación server-side */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between py-2 px-1 text-sm text-muted-foreground">
                  <span>Mostrando {from} - {to} de {filteredCount}</span>
                  <div className="flex items-center gap-1">
                    <Button type="button" variant="outline" size="sm" aria-label="Página anterior" className="w-8 h-8 p-0" disabled={currentPage === 1 || isNavPending} onClick={() => goToPage(currentPage - 1)}>
                       <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="text-xs font-medium px-2 text-center" aria-current="page">{currentPage} / {totalPages}</span>
                    <Button type="button" variant="outline" size="sm" aria-label="Página siguiente" className="w-8 h-8 p-0" disabled={currentPage === totalPages || isNavPending} onClick={() => goToPage(currentPage + 1)}>
                       <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </StaggerList>
          )}
        </div>
      </div>
    </div>
  )
}
