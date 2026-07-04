'use client'

import { useState, useMemo, useEffect, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Package, Clock, ChevronRight, Hourglass, CheckCircle2, Settings2, MapPin, X, LayoutList, Search, Loader2, Truck } from 'lucide-react'
import Link from 'next/link'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useConfirm } from '@/components/ui/confirm-dialog'
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
  canWrite: boolean
  updateStatusAction: (fd: FormData) => Promise<void>
  generateShippingGuideAction?: (fd: FormData) => Promise<{
    ok: boolean
    message?: string
    tracking?: string
  }>
}

// ─── Constantes ───────────────────────────────────────────────────────────────
// F62: 'pending_payment' es el estado con que el backend crea TODA orden bot con link Wompi
// (VALID_STATUSES en orders.py). Faltaba en el enum → el operador veía el string crudo, no podía
// avanzar (sin STATUS_NEXT) ni filtrar esas órdenes.
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
  pending_payment: 'confirmed',   // F62: la API permite pending_payment→confirmed (orders.py)
  confirmed:  'processing',
  processing: 'shipped',
  shipped:    'delivered',
}

const STATUS_COLORS: Record<string, string> = {
  pending:         'bg-yellow-500/15 text-yellow-700 border-yellow-700/30',
  pending_payment: 'bg-amber-500/15 text-amber-600 border-amber-700/30',
  confirmed:  'bg-blue-500/15 text-blue-700 border-blue-700/30',
  processing: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  shipped:    'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  delivered:  'bg-green-500/15 text-green-700 border-green-700/30',
  cancelled:  'bg-red-500/15 text-red-700 border-red-700/30',
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
const ITEMS_PER_PAGE = 20

// ─── Sub-componentes ──────────────────────────────────────────────────────────

function GenerateGuideButton({
  orderId,
  action,
}: {
  orderId: string
  action: (fd: FormData) => Promise<{
    ok: boolean
    message?: string
    tracking?: string
  }>
}) {
  const [isPending, startTransition] = useTransition()
  const confirmar = useConfirm()
  const [result, setResult] = useState<{
    ok: boolean
    message?: string
  } | null>(null)

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
        className="inline-flex items-center gap-1.5 text-xs text-emerald-700 hover:text-emerald-800 border border-emerald-700/40 hover:border-emerald-700/60 bg-emerald-50 rounded-lg px-3 py-1.5 transition-all disabled:opacity-50"
        title="Genera guía Aveonline con contraentrega — el courier recauda al entregar"
      >
        {isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Truck className="h-3 w-3" />}
        {isPending ? 'Generando…' : 'Generar guía COD'}
      </button>
      {result && (
        <span
          className={`text-xs ${result.ok ? 'text-emerald-700' : 'text-red-700'}`}
        >
          {result.message}
        </span>
      )}
    </div>
  )
}


function ActionButton({
  orderId, nextStatus, originalStatus, updateStatusAction 
}: { 
  orderId: string, nextStatus: string, originalStatus: string, updateStatusAction: (fd: FormData) => Promise<void> 
}) {
  const [isPending, startTransition] = useTransition()
  
  const handleNext = () => {
    startTransition(async () => {
      const fd = new FormData()
      fd.append('order_id', orderId)
      fd.append('next_status', nextStatus)
      await updateStatusAction(fd)
    })
  }
  
  const handleCancel = () => {
    startTransition(async () => {
      const fd = new FormData()
      fd.append('order_id', orderId)
      fd.append('cancel', 'true')
      await updateStatusAction(fd)
    })
  }

  return (
    <div className="flex flex-col sm:flex-row gap-2 mt-4 pt-3 border-t border-border">
      <Button 
        onClick={handleNext} 
        disabled={isPending} 
        size="sm" 
        className="w-full sm:w-auto h-8 text-xs font-semibold"
      >
        {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <>Avanzar a {STATUS_LABELS[nextStatus]} <ChevronRight className="h-3 w-3 ml-1" /></>}
      </Button>
      {originalStatus === 'pending' && (
        <Button 
          variant="ghost" 
          onClick={handleCancel} 
          disabled={isPending} 
          size="sm" 
          className="w-full sm:w-auto h-8 text-xs text-muted-foreground hover:text-red-700 hover:bg-red-400/10"
        >
          {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Cancelar pedido'}
        </Button>
      )}
    </div>
  )
}

// ─── Componente Principal ─────────────────────────────────────────────────────

export default function OrdersManager({ initialOrders, products, contacts, role, canWrite, updateStatusAction, generateShippingGuideAction }: Props) {
  const router = useRouter()
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState('all')
  const [currentPage, setCurrentPage] = useState(1)

  // 1. Filtrado de órdenes local en memoria
  const filteredOrders = useMemo(() => {
    let result = initialOrders

    // Filtrar por status
    if (filterStatus !== 'all') {
      result = result.filter(o => o.status === filterStatus)
    }

    // Buscar texto (ID, contacto, items)
    const q = search.toLowerCase().trim()
    if (q) {
      result = result.filter(o => {
        if (o.id.toLowerCase().includes(q)) return true
        
        const contact = Array.isArray(o.contacts) ? o.contacts[0] : o.contacts
        if (contact) {
          if (contact.name?.toLowerCase().includes(q) || contact.phone.toLowerCase().includes(q)) return true
        }

        if (o.order_items.some(i => i.title.toLowerCase().includes(q))) return true
        
        return false
      })
    }
    
    return result
  }, [initialOrders, filterStatus, search])

  // Reset pagination on filter changes
  useEffect(() => { setCurrentPage(1) }, [search, filterStatus])

  // 2. Paginación
  const totalPages = Math.ceil(filteredOrders.length / ITEMS_PER_PAGE) || 1
  const paginatedOrders = useMemo(() => {
    const start = (currentPage - 1) * ITEMS_PER_PAGE
    return filteredOrders.slice(start, start + ITEMS_PER_PAGE)
  }, [filteredOrders, currentPage])

  // Contadores para pestañas
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: initialOrders.length }
    initialOrders.forEach(o => {
      c[o.status] = (c[o.status] || 0) + 1
    })
    return c
  }, [initialOrders])

  return (
    <div className="space-y-5 max-w-7xl">
      {/* Header & Search */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Package className="h-5 w-5 text-primary" /> Pedidos
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {counts['all'] ?? 0} pedidos totales
          </p>
        </div>
        
        <div className="flex flex-col sm:flex-row items-center gap-3 w-full md:w-auto">
          <div className="relative w-full md:w-80">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
            <Input
              placeholder="Buscar por ID, nombre, teléfono o ítem..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-9 h-9 text-sm bg-card w-full"
            />
            {search && (
              <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <Badge variant="outline" className="text-xs self-start sm:self-auto h-9">
            {ROLE_LABELS[role] ?? role}
          </Badge>
        </div>
      </div>

      {/* AI Insight */}
      {(role === 'owner' || role === 'manager') && (
        <AiInsightPanel module="orders" label="Pedidos" />
      )}

      {/* Filtros de estado — scrollable horizontal en mobile */}
      <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1">
        {TAB_FILTERS.map(s => {
          const Icon = STATUS_ICONS[s] ?? LayoutList
          return (
            <button
              key={s}
              onClick={() => setFilterStatus(s)}
              className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                filterStatus === s
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'border-border text-muted-foreground hover:text-foreground hover:bg-accent'
              }`}
            >
              <Icon className="h-4 w-4 mr-1.5 opacity-70 shrink-0" />
              <span>{s === 'all' ? 'Todos' : STATUS_LABELS[s]}</span>
              {counts[s] !== undefined && counts[s] > 0 && (
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold ${
                  filterStatus === s ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground'
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
          {paginatedOrders.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 rounded-xl border border-dashed border-border text-center">
              <Package className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground text-sm">
                {search ? 'No se encontraron resultados para la búsqueda.' : filterStatus === 'all' ? 'No hay pedidos aún.' : `No hay pedidos con estado "${STATUS_LABELS[filterStatus]}".`}
              </p>
              {(filterStatus !== 'all' || search) && (
                <button onClick={() => { setFilterStatus('all'); setSearch('') }} className="mt-2 text-xs text-primary hover:underline">
                  Limpiar filtros
                </button>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              {paginatedOrders.map((o) => {
                const nextStatus = STATUS_NEXT[o.status]
                const colorClass = STATUS_COLORS[o.status] || 'bg-gray-500/15 text-gray-700'
                const contact = Array.isArray(o.contacts) ? o.contacts[0] : o.contacts
                const subtotal  = o.order_items.reduce((acc, i) => acc + i.unit_price * i.quantity, 0)
                const shipping  = o.shipping_cost ?? 0
                const revenue   = o.total_amount ?? (subtotal + shipping)
                
                return (
                  <div key={o.id} className="rounded-xl border border-border bg-card p-4 hover:border-primary/30 hover:shadow-sm transition-all focus-within:border-primary/50">
                    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 mb-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${colorClass}`}>
                            {STATUS_LABELS[o.status] ?? o.status}
                          </span>
                          {o.payment_method === 'cod' && (
                            <span
                              className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-emerald-500/15 text-emerald-700 border-emerald-700/30"
                              title="Pago contraentrega — el courier recauda al entregar"
                            >
                              💵 COD
                            </span>
                          )}
                          <span className="text-[10px] text-muted-foreground font-mono truncate max-w-[120px]">
                            {o.id.split('-')[0].toUpperCase()}
                          </span>
                          <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {new Date(o.created_at).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
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
                      {o.notes && (
                        <div className="pt-2 mt-2 border-t border-border/50 text-muted-foreground italic line-clamp-2">
                          &quot;{o.notes}&quot;
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2 mt-3 flex-wrap">
                      {canWrite && nextStatus && (
                        <ActionButton orderId={o.id} originalStatus={o.status} nextStatus={nextStatus} updateStatusAction={updateStatusAction} />
                      )}
                      {['confirmed', 'processing', 'shipped'].includes(o.status) && (
                        <Link
                          href={`/dashboard/shipping?order=${o.id}`}
                          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary border border-border hover:border-primary/40 rounded-lg px-3 py-1.5 transition-all"
                        >
                          <Truck className="h-3 w-3" /> Cotizar envío
                        </Link>
                      )}
                      {canWrite
                        && o.payment_method === 'cod'
                        && o.status === 'confirmed'
                        && generateShippingGuideAction && (
                        <GenerateGuideButton
                          orderId={o.id}
                          action={generateShippingGuideAction}
                        />
                      )}
                    </div>
                  </div>
                )
              })}

              {/* Controles de Paginación */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between py-2 px-1 text-sm text-muted-foreground">
                  <span>Mostrando {(currentPage - 1) * ITEMS_PER_PAGE + 1} - {Math.min(currentPage * ITEMS_PER_PAGE, filteredOrders.length)} de {filteredOrders.length}</span>
                  <div className="flex items-center gap-1">
                    <Button variant="outline" size="sm" className="w-8 h-8 p-0" disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}>
                       <span>{'<'}</span>
                    </Button>
                    <span className="text-xs font-medium w-8 text-center">{currentPage}</span>
                    <Button variant="outline" size="sm" className="w-8 h-8 p-0" disabled={currentPage === totalPages} onClick={() => setCurrentPage(p => p + 1)}>
                       <span>{'>'}</span>
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
