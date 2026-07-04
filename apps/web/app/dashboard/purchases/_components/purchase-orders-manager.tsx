'use client'

import { useMemo, useState, useTransition } from 'react'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useConfirm } from '@/components/ui/confirm-dialog'
import {
  Plus, PackageSearch, Trash2, Check, XCircle, Search, Loader2, Info, CalendarClock, Truck,
} from 'lucide-react'
import { createPurchaseOrder, receivePurchaseOrder, cancelPurchaseOrder } from '../actions'
import {
  statusMeta, isOpenStatus, buildItemsPayload, validateDraftItems, draftTotal,
  formatCOP, formatBogotaDate, type DraftItem,
} from '../_lib/purchase-orders'
import type { Supplier } from './suppliers-manager'

export type PurchaseProductVariation = {
  id: string
  sku?: string | null
  cost_price?: number | null
  stock_quantity?: number | null
}

export type PurchaseProduct = {
  id: string
  title: string
  product_variations?: PurchaseProductVariation[] | null
}

export type PurchaseOrder = {
  id: string
  status: string
  total_amount: number
  created_at: string
  expected_date?: string | null
  suppliers?: { name: string } | null
  purchase_order_items: {
    quantity: number
    unit_cost: number
    product_variations?: {
      sku?: string | null
      products?: { title?: string | null } | null
    } | null
  }[]
}

type Props = {
  orders: PurchaseOrder[]
  suppliers: Supplier[]
  products: PurchaseProduct[]
  canWrite: boolean
  totalOrders: number
}

type StatusFilter = 'all' | 'open' | 'received' | 'cancelled'

const FILTERS: { key: StatusFilter; label: string; match: (s: string) => boolean }[] = [
  { key: 'all', label: 'Todas', match: () => true },
  { key: 'open', label: 'Pendientes', match: (s) => isOpenStatus(s) },
  { key: 'received', label: 'Recibidas', match: (s) => s === 'received' },
  { key: 'cancelled', label: 'Canceladas', match: (s) => s === 'cancelled' },
]

export default function PurchaseOrdersManager({ orders, suppliers, products, canWrite, totalOrders }: Props) {
  const confirm = useConfirm()
  const [showAdd, setShowAdd] = useState(false)
  const [selectedSupplier, setSelectedSupplier] = useState('')
  const [expectedDate, setExpectedDate] = useState('')
  const [items, setItems] = useState<DraftItem[]>([])
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [isPending, startTransition] = useTransition()

  const variations = useMemo(() => {
    const list: (PurchaseProductVariation & { product_title: string })[] = []
    for (const p of products) {
      for (const v of p.product_variations || []) {
        list.push({ ...v, product_title: p.title })
      }
    }
    return list
  }, [products])

  const filteredVariations = useMemo(() => {
    const q = search.trim().toLowerCase()
    const base = q
      ? variations.filter(
          (v) =>
            v.product_title.toLowerCase().includes(q) ||
            (v.sku || '').toLowerCase().includes(q),
        )
      : variations
    return base.slice(0, 40)
  }, [variations, search])

  const visibleOrders = useMemo(() => {
    const f = FILTERS.find((x) => x.key === filter)!
    return orders.filter((o) => f.match(o.status))
  }, [orders, filter])

  const filterCount = (key: StatusFilter) => {
    const f = FILTERS.find((x) => x.key === key)!
    return orders.filter((o) => f.match(o.status)).length
  }

  const addItem = (vid: string) => {
    const v = variations.find((x) => x.id === vid)
    if (!v) return
    if (items.some((i) => i.variation_id === vid)) {
      toast.info('Ese producto ya está en la orden.')
      return
    }
    setItems((prev) => [
      ...prev,
      { variation_id: v.id, product_title: v.product_title, sku: v.sku, qty: 1, cost: v.cost_price || 0 },
    ])
    setSearch('')
  }

  const resetForm = () => {
    setShowAdd(false)
    setItems([])
    setSelectedSupplier('')
    setExpectedDate('')
    setSearch('')
  }

  const estimatedTotal = draftTotal(items)
  const validationError = validateDraftItems(selectedSupplier, items)

  const completePO = () => {
    const err = validateDraftItems(selectedSupplier, items)
    if (err) {
      toast.error(err)
      return
    }
    const fd = new FormData()
    fd.append('supplier_id', selectedSupplier)
    if (expectedDate) fd.append('expected_date', expectedDate)
    fd.append('items', JSON.stringify(buildItemsPayload(items)))
    startTransition(async () => {
      const res = await createPurchaseOrder(fd)
      if (!res.ok) {
        toast.error(res.error || 'No se pudo crear la orden de compra.')
        return
      }
      toast.success(res.message || 'Orden de compra creada.')
      resetForm()
    })
  }

  const handleCancel = (o: PurchaseOrder) => {
    startTransition(async () => {
      const okToCancel = await confirm({
        title: '¿Cancelar esta orden de compra?',
        description:
          'Esta acción es irreversible: una OC cancelada no se puede reactivar y tendrías que crear una nueva. No afecta el inventario.',
        confirmLabel: 'Sí, cancelar orden',
        cancelLabel: 'Volver',
        destructive: true,
      })
      if (!okToCancel) return
      const res = await cancelPurchaseOrder(o.id)
      if (!res.ok) {
        toast.error(res.error || 'No se pudo cancelar la orden.')
        return
      }
      toast.success(res.message || 'Orden cancelada.')
    })
  }

  const handleReceive = (o: PurchaseOrder) => {
    startTransition(async () => {
      const okToReceive = await confirm({
        title: '¿Marcar como recibida?',
        description:
          'Se sumará la cantidad de cada ítem al inventario y se recalculará el costo promedio (WAC) de cada variante — esto cambia tus márgenes en Finanzas. La acción no se puede deshacer.',
        confirmLabel: 'Sí, ingresar al inventario',
        cancelLabel: 'Volver',
      })
      if (!okToReceive) return
      const res = await receivePurchaseOrder(o.id)
      if (!res.ok) {
        toast.error(res.error || 'No se pudo recibir la orden.')
        return
      }
      toast.success(res.message || 'Orden recibida — inventario y costos actualizados.')
    })
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-4">
        <div className="flex justify-between items-center bg-muted/20 p-3 rounded-lg border border-border/50">
          <div>
            <h2 className="text-lg font-semibold flex items-center gap-2">Órdenes a Proveedores</h2>
            <p className="text-xs text-muted-foreground">
              Historial de reabastecimiento
              {totalOrders > orders.length && ` · mostrando las ${orders.length} más recientes de ${totalOrders}`}
            </p>
          </div>
          {canWrite && !showAdd && suppliers.length > 0 && (
            <Button onClick={() => setShowAdd(true)} size="sm" className="h-8 text-xs gap-1.5">
              <Plus className="h-3.5 w-3.5" /> Nueva Orden
            </Button>
          )}
        </div>

        {showAdd && (
          <Card className="border-primary/50 shadow-md">
            <CardContent className="pt-6 space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label htmlFor="po-supplier" className="text-xs font-semibold text-muted-foreground uppercase">
                    Proveedor *
                  </label>
                  <select
                    id="po-supplier"
                    aria-label="Proveedor de la orden"
                    value={selectedSupplier}
                    onChange={(e) => setSelectedSupplier(e.target.value)}
                    className="w-full h-9 px-3 rounded-md border text-sm bg-background"
                  >
                    <option value="">Selecciona...</option>
                    {suppliers.map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <label htmlFor="po-expected" className="text-xs font-semibold text-muted-foreground uppercase flex items-center gap-1">
                    <CalendarClock className="h-3 w-3" /> Fecha estimada de llegada
                  </label>
                  <input
                    id="po-expected"
                    type="date"
                    aria-label="Fecha estimada de llegada"
                    value={expectedDate}
                    onChange={(e) => setExpectedDate(e.target.value)}
                    className="w-full h-9 px-3 rounded-md border text-sm bg-background"
                  />
                </div>
              </div>

              <div className="pt-4 border-t">
                <label htmlFor="po-item-search" className="text-xs font-semibold text-muted-foreground uppercase">
                  Añadir ítems a la orden
                </label>
                <div className="relative mt-2">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    id="po-item-search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Buscar producto o SKU..."
                    className="h-9 pl-8 text-sm"
                    autoComplete="off"
                  />
                </div>
                {search.trim() !== '' && (
                  <div className="mt-1 border rounded-md max-h-52 overflow-y-auto bg-background shadow-sm divide-y">
                    {filteredVariations.length === 0 && (
                      <p className="p-3 text-xs text-muted-foreground">Sin coincidencias en el catálogo activo.</p>
                    )}
                    {filteredVariations.map((v) => (
                      <button
                        key={v.id}
                        type="button"
                        onClick={() => addItem(v.id)}
                        className="w-full text-left px-3 py-2 text-xs hover:bg-muted/60 flex justify-between items-center gap-2"
                      >
                        <span className="truncate">
                          <span className="font-medium">{v.product_title}</span>
                          <span className="text-muted-foreground"> · {v.sku || 'Sin SKU'}</span>
                        </span>
                        <span className="text-muted-foreground shrink-0 tabular-nums">
                          Stock: {v.stock_quantity ?? 0}
                        </span>
                      </button>
                    ))}
                    {!search && variations.length > 40 && (
                      <p className="p-2 text-[11px] text-muted-foreground">
                        Escribe para filtrar entre {variations.length} variantes.
                      </p>
                    )}
                  </div>
                )}

                {items.length > 0 && (
                  <div className="border rounded-md overflow-x-auto bg-muted/10 mt-3">
                    <Table className="text-xs">
                      <TableHeader>
                        <TableRow>
                          <TableHead>Producto</TableHead>
                          <TableHead className="w-24">Cantidad</TableHead>
                          <TableHead className="w-28">Costo unitario</TableHead>
                          <TableHead className="w-8 sr-only">Quitar</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {items.map((it, idx) => (
                          <TableRow key={it.variation_id}>
                            <TableCell className="font-medium max-w-[220px]">
                              <span className="truncate block">{it.product_title}</span>
                              {it.sku && <span className="text-muted-foreground">{it.sku}</span>}
                            </TableCell>
                            <TableCell>
                              <Input
                                type="number"
                                min={1}
                                step={1}
                                aria-label={`Cantidad de ${it.product_title}`}
                                value={it.qty}
                                onChange={(e) =>
                                  setItems((cur) =>
                                    cur.map((x, i) =>
                                      i === idx ? { ...x, qty: Math.max(1, Math.floor(Number(e.target.value) || 0)) } : x,
                                    ),
                                  )
                                }
                                className="h-8 w-20"
                              />
                            </TableCell>
                            <TableCell>
                              <Input
                                type="number"
                                min={0}
                                step="0.01"
                                aria-label={`Costo unitario de ${it.product_title}`}
                                value={it.cost}
                                onChange={(e) =>
                                  setItems((cur) =>
                                    cur.map((x, i) =>
                                      i === idx ? { ...x, cost: Math.max(0, Number(e.target.value) || 0) } : x,
                                    ),
                                  )
                                }
                                className="h-8 w-24"
                              />
                            </TableCell>
                            <TableCell className="text-center">
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <button
                                    type="button"
                                    aria-label={`Quitar ${it.product_title} de la orden`}
                                    onClick={() => setItems((cur) => cur.filter((_, i) => i !== idx))}
                                    className="text-red-700 hover:text-red-800"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                </TooltipTrigger>
                                <TooltipContent>Quitar ítem</TooltipContent>
                              </Tooltip>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    <div className="flex justify-between items-center px-3 py-2 border-t bg-muted/30 text-xs">
                      <span className="text-muted-foreground">{items.length} ítem(s)</span>
                      <span className="font-semibold">Total estimado: {formatCOP(estimatedTotal)}</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="ghost" size="sm" onClick={resetForm} className="text-xs" disabled={isPending}>
                  Cancelar
                </Button>
                <Button onClick={completePO} disabled={!!validationError || isPending} size="sm" className="text-xs">
                  {isPending ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Creando...</> : 'Crear orden de compra'}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {suppliers.length === 0 && !showAdd && canWrite && (
          <div className="border border-amber-700/25 bg-amber-500/10 p-4 rounded-lg">
            <p className="text-xs text-amber-800 font-medium">
              Aún no hay proveedores registrados. Registra un proveedor en la pestaña <strong>Proveedores</strong> antes de crear una orden de compra.
            </p>
          </div>
        )}

        {orders.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                aria-pressed={filter === f.key}
                className={`px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
                  filter === f.key
                    ? 'bg-primary/10 border-primary/40 text-primary'
                    : 'border-border text-muted-foreground hover:bg-muted/50'
                }`}
              >
                {f.label} <span className="tabular-nums">({filterCount(f.key)})</span>
              </button>
            ))}
          </div>
        )}

        <div className="space-y-3">
          {visibleOrders.map((o) => {
            const meta = statusMeta(o.status)
            return (
              <div key={o.id} className="border border-border/50 bg-card rounded-lg p-4">
                <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-2 mb-3">
                  <div>
                    <p className="font-semibold text-sm flex items-center gap-2">
                      <PackageSearch className="h-4 w-4 text-primary" /> {o.suppliers?.name || 'Proveedor sin nombre'}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="font-mono cursor-help">OC {o.id.split('-')[0].toUpperCase()}</span>
                        </TooltipTrigger>
                        <TooltipContent>ID completo: {o.id}</TooltipContent>
                      </Tooltip>
                      <span>· Pedido el {formatBogotaDate(o.created_at)}</span>
                      {o.expected_date && (
                        <span className="inline-flex items-center gap-1">
                          <Truck className="h-3 w-3" /> Llega aprox. {formatBogotaDate(o.expected_date)}
                        </span>
                      )}
                    </p>
                  </div>
                  <div className="text-left sm:text-right">
                    <Badge variant={meta.variant}>{meta.label}</Badge>
                    <p className="font-bold text-sm mt-1">{formatCOP(o.total_amount)}</p>
                  </div>
                </div>

                <div className="bg-muted/30 p-2 rounded text-xs space-y-1 mt-2">
                  {o.purchase_order_items.map((i, k) => (
                    <div key={k} className="flex justify-between w-full">
                      <span className="truncate">
                        {i.quantity}x {i.product_variations?.products?.title || 'Producto'}{' '}
                        ({i.product_variations?.sku || 'Sin SKU'})
                      </span>
                      <span className="font-mono tabular-nums text-muted-foreground ml-2">{formatCOP(i.unit_cost)}/u.</span>
                    </div>
                  ))}
                </div>

                {isOpenStatus(o.status) && canWrite && (
                  <div className="mt-3 flex flex-wrap gap-2 justify-end pt-3 border-t">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={isPending}
                      onClick={() => handleCancel(o)}
                      className="h-8 text-xs text-red-700 hover:text-red-800 hover:bg-red-500/10 gap-2 border-red-700/25"
                    >
                      <XCircle className="h-3.5 w-3.5" /> Cancelar orden
                    </Button>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          type="button"
                          size="sm"
                          disabled={isPending}
                          onClick={() => handleReceive(o)}
                          className="h-8 text-xs bg-emerald-700 hover:bg-emerald-800 text-white gap-2"
                        >
                          <Check className="h-3.5 w-3.5" /> Marcar como recibida
                          <Info className="h-3 w-3 opacity-80" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        Suma el stock al inventario y recalcula el costo promedio (WAC) de cada variante.
                      </TooltipContent>
                    </Tooltip>
                  </div>
                )}
              </div>
            )
          })}

          {orders.length === 0 && !showAdd && (
            <div className="p-8 text-center border border-dashed rounded-xl space-y-3">
              <PackageSearch className="h-8 w-8 mx-auto text-muted-foreground/60" />
              <div>
                <p className="font-medium text-sm text-foreground">Aún no tienes órdenes de compra</p>
                <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">
                  Una orden de compra registra lo que le pides a un proveedor. Al recibirla, el stock entra al inventario y se actualiza tu costo promedio.
                </p>
              </div>
              {canWrite && suppliers.length > 0 && (
                <Button onClick={() => setShowAdd(true)} size="sm" className="gap-1.5">
                  <Plus className="h-3.5 w-3.5" /> Crear primera orden
                </Button>
              )}
            </div>
          )}

          {orders.length > 0 && visibleOrders.length === 0 && (
            <div className="p-6 text-center text-xs text-muted-foreground border border-dashed rounded-xl">
              No hay órdenes en este estado.
            </div>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}
