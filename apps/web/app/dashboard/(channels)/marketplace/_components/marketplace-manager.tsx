'use client'

import { useMemo, useState } from 'react'
import Image from 'next/image'
import Link from 'next/link'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import {
  Tooltip, TooltipTrigger, TooltipContent, TooltipProvider,
} from '@/components/ui/tooltip'
import { Checkbox } from '@/components/ui/checkbox'
import { useConfirm } from '@/components/ui/confirm-dialog'
import {
  ExternalLink, Pause, Play, Link2, Link2Off, RefreshCw,
  Search, AlertTriangle, CheckCircle2, X, Store,
  ChevronLeft, ChevronRight, PackagePlus, Loader2,
} from 'lucide-react'
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue
} from '@/components/ui/select'
import {
  linkListing, unlinkListing, changeListingStatus, syncStockFromSupabase,
  importFromMeli, importBulkFromMeli,
} from '../actions'

type MeliVariation = {
  id: number
  attributes: { id: string; value_name: string }[]
  available_quantity: number
}

export type MeliItem = {
  meli_id: string
  title: string
  status: 'active' | 'paused' | 'closed'
  price: number
  available_quantity: number
  thumbnail: string | null
  permalink: string | null
  meli_variations: MeliVariation[]   // lista vacía si item sin variaciones propias
  listing_id: string | null
  variation_id: string | null
  meli_variation_id: number | null   // ID de variación MeLi ya mapeada
  sku: string | null
  product_name: string | null
  supabase_stock: number | null
  supabase_price: number | null      // precio de catálogo (para drift vs precio MeLi)
  is_linked: boolean
  meli_condition: string | null      // 'new' | 'used' | 'not_specified'
  synced_at: string | null
}

type StatusFilter = 'all' | 'active' | 'paused' | 'closed' | 'unlinked'

type Variation = {
  id: string
  sku: string
  stock_quantity: number
  price: number
  attributes: Record<string, string>
  product_id: string
  product_title: string
  category_id: string | null
  category_name: string
}

type Category = {
  id: string
  display_label: string   // categoría OPERATIVA (product_categories) — la que administra Categorías y usa el bot
}

type Props = {
  items: MeliItem[]
  paging: { total: number; limit?: number; offset?: number }
  variations: Variation[]
  categories: Category[]
  canWrite: boolean
}

const STATUS_CONFIG = {
  active:  { label: 'Activo',  className: 'bg-success-bg text-success-fg' },
  paused:  { label: 'Pausado', className: 'bg-warning-bg text-warning-fg' },
  closed:  { label: 'Cerrado', className: 'bg-danger-bg text-danger-fg' },
}

const CONDITION_LABEL: Record<string, string> = {
  new: 'Nuevo',
  used: 'Usado',
}

// Estados MeLi que pueden llegar fuera del trío active/paused/closed. Sin este
// mapa se mostraban crudos en inglés (ej. 'under_review').
const MELI_STATUS_LABEL: Record<string, string> = {
  under_review:      'En revisión',
  payment_required:  'Pago requerido',
  inactive:          'Inactivo',
  pending:           'Pendiente',
  not_yet_active:    'Por activar',
}

const meliStatusLabel = (status: string) =>
  STATUS_CONFIG[status as keyof typeof STATUS_CONFIG]?.label
    ?? MELI_STATUS_LABEL[status]
    ?? status.replace(/_/g, ' ')

export default function MarketplaceManager({ items, paging, variations, categories, canWrite }: Props) {
  const [search, setSearch]                   = useState('')
  const [statusFilter, setStatusFilter]       = useState<StatusFilter>('all')
  const [loadingIds, setLoadingIds]           = useState<Set<string>>(new Set())
  const [sheetItem, setSheetItem]             = useState<MeliItem | null>(null)
  const [sheetMode, setSheetMode]             = useState<'link' | 'import'>('link')
  const [selectedVariationId, setSelectedVariationId]       = useState('')
  const [selectedCategoryId, setSelectedCategoryId]         = useState('')
  const [selectedMeliVariationId, setSelectedMeliVariationId] = useState<number | null>(null)
  const [variantQuery, setVariantQuery]       = useState('')
  const [actionErrors, setActionErrors]       = useState<Record<string, string>>({})
  const [confirmUnlinkId, setConfirmUnlinkId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds]         = useState<Set<string>>(new Set())
  const [bulkCategoryId, setBulkCategoryId]   = useState('')
  const [bulkLoading, setBulkLoading]         = useState(false)
  const confirm = useConfirm()

  // ── Paginación server-side (F3) ─────────────────────────────────────────────
  const pageLimit  = paging.limit ?? (items.length || 50)
  const pageOffset = paging.offset ?? 0
  const total      = paging.total ?? items.length
  const hasPrev    = pageOffset > 0
  const hasNext    = pageOffset + items.length < total
  const prevHref   = `/dashboard/marketplace?offset=${Math.max(0, pageOffset - pageLimit)}`
  const nextHref   = `/dashboard/marketplace?offset=${pageOffset + pageLimit}`

  const setLoading = (id: string, on: boolean) =>
    setLoadingIds(prev => { const n = new Set(prev); if (on) { n.add(id) } else { n.delete(id) } return n })

  const setError = (id: string, msg: string) =>
    setActionErrors(prev => ({ ...prev, [id]: msg }))

  const clearError = (id: string) =>
    setActionErrors(prev => { const n = { ...prev }; delete n[id]; return n })

  const closeSheet = () => {
    setSheetItem(null)
    setSelectedVariationId('')
    setSelectedCategoryId('')
    setSelectedMeliVariationId(null)
    setVariantQuery('')
  }

  const meliVariationRequired = (sheetItem?.meli_variations?.length ?? 0) > 0

  // Filtro type-ahead sobre las variantes del catálogo: con catálogos grandes el
  // Select plano agrupado era inusable (scroll manual). El operador escribe SKU /
  // producto / atributo y el Select solo muestra las coincidencias.
  const filteredVariations = useMemo(() => {
    const q = variantQuery.trim().toLowerCase()
    if (!q) return variations
    return variations.filter(v =>
      v.sku?.toLowerCase().includes(q) ||
      v.product_title?.toLowerCase().includes(q) ||
      Object.values(v.attributes).some(val => String(val).toLowerCase().includes(q))
    )
  }, [variations, variantQuery])

  const STATUS_FILTERS: { key: StatusFilter; label: string; count: number }[] = [
    { key: 'all',      label: 'Todos',        count: items.length },
    { key: 'active',   label: 'Activos',      count: items.filter(i => i.status === 'active').length },
    { key: 'paused',   label: 'Pausados',     count: items.filter(i => i.status === 'paused').length },
    { key: 'closed',   label: 'Cerrados',     count: items.filter(i => i.status === 'closed').length },
    { key: 'unlinked', label: 'Sin vincular', count: items.filter(i => !i.is_linked).length },
  ]

  const filtered = items
    .filter(i => {
      if (statusFilter === 'active')   return i.status === 'active'
      if (statusFilter === 'paused')   return i.status === 'paused'
      if (statusFilter === 'closed')   return i.status === 'closed'
      if (statusFilter === 'unlinked') return !i.is_linked
      return true
    })
    .filter(i =>
      i.title?.toLowerCase().includes(search.toLowerCase()) ||
      i.meli_id?.toLowerCase().includes(search.toLowerCase()) ||
      i.sku?.toLowerCase().includes(search.toLowerCase())
    )

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleStatusChange = async (item: MeliItem, newStatus: 'active' | 'paused') => {
    if (!item.listing_id) return
    clearError(item.meli_id)
    setLoading(item.meli_id, true)
    const resp = await changeListingStatus(item.listing_id, newStatus)
    handleStatusResult(item, resp, newStatus === 'paused' ? 'pausada' : 'activada')
    setLoading(item.meli_id, false)
  }

  const handleSyncStock = async (item: MeliItem) => {
    if (!item.listing_id) return
    clearError(item.meli_id)
    setLoading(item.meli_id, true)
    const resp = await syncStockFromSupabase(item.listing_id)
    if (resp?.error) { setError(item.meli_id, resp.error); toast.error(resp.error) }
    else toast.success('Stock y precio sincronizados con Mercado Libre.')
    setLoading(item.meli_id, false)
  }

  const handleUnlink = async (item: MeliItem) => {
    if (!item.listing_id) return
    clearError(item.meli_id)
    setLoading(item.meli_id, true)
    const resp = await unlinkListing(item.listing_id)
    if (resp?.error) { setError(item.meli_id, resp.error); toast.error(resp.error) }
    else toast.success('Publicación desvinculada del catálogo.')
    setLoading(item.meli_id, false)
    setConfirmUnlinkId(null)
  }

  const handleStatusResult = (item: MeliItem, resp: { error?: string }, verb: string) => {
    if (resp?.error) { setError(item.meli_id, resp.error); toast.error(resp.error) }
    else toast.success(`Publicación ${verb} en Mercado Libre.`)
  }

  const handleLink = async (meliId: string) => {
    // Enforcement de variación MeLi: si la publicación tiene variaciones propias,
    // el operador DEBE elegir a cuál mapea el stock (evita el fallback silencioso
    // que asigna el qty a la primera variación, potencialmente la equivocada).
    if (!selectedVariationId) return
    if (meliVariationRequired && selectedMeliVariationId == null) {
      setError(meliId, 'Selecciona la variación de Mercado Libre a la que se sincronizará el stock.')
      return
    }
    clearError(meliId)
    setLoading(meliId, true)
    const resp = await linkListing(meliId, selectedVariationId, undefined, selectedMeliVariationId ?? undefined)
    if (resp?.error) { setError(meliId, resp.error); toast.error(resp.error) }
    else { toast.success('Publicación vinculada al catálogo. El stock se sincronizará automáticamente.'); closeSheet() }
    setLoading(meliId, false)
  }

  const handleImport = async (meliId: string, _meliTitle: string) => {
    clearError(meliId)
    setLoading(meliId, true)
    // '_none' es el centinela del SelectItem "Sin categoría"; el backend espera
    // null/undefined, NO el literal '_none' (rompía el .eq sobre columna UUID → 500).
    const categoryId = selectedCategoryId && selectedCategoryId !== '_none' ? selectedCategoryId : undefined
    const resp = await importFromMeli(meliId, categoryId)
    if (resp?.error) { setError(meliId, resp.error); toast.error(resp.error) }
    else {
      const sku = (resp?.data as { sku?: string } | null)?.sku
      toast.success(
        sku
          ? `Producto importado al Catálogo (SKU ${sku}) y vinculado.`
          : 'Producto importado al Catálogo y vinculado.',
        { description: 'Edita descripción e imágenes desde Productos.' }
      )
      closeSheet()
    }
    setLoading(meliId, false)
  }

  // ── Selección masiva (F3: importar todo lo no vinculado) ────────────────────
  const unlinkedIds = useMemo(
    () => items.filter(i => !i.is_linked).map(i => i.meli_id),
    [items]
  )
  const allUnlinkedSelected = unlinkedIds.length > 0 && unlinkedIds.every(id => selectedIds.has(id))

  const toggleSelect = (meliId: string) =>
    setSelectedIds(prev => {
      const n = new Set(prev)
      if (n.has(meliId)) { n.delete(meliId) } else { n.add(meliId) }
      return n
    })

  const toggleSelectAllUnlinked = () =>
    setSelectedIds(prev => (allUnlinkedSelected ? new Set() : new Set(unlinkedIds)))

  const clearSelection = () => setSelectedIds(new Set())

  const handleBulkImport = async () => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0) return
    const ok = await confirm({
      title: `Importar ${ids.length} ${ids.length === 1 ? 'publicación' : 'publicaciones'} al Catálogo`,
      description: 'Se creará un producto por cada publicación seleccionada y se vinculará automáticamente. Podrás editar descripción e imágenes desde Productos.',
      confirmLabel: 'Importar todo',
    })
    if (!ok) return
    setBulkLoading(true)
    const categoryId = bulkCategoryId && bulkCategoryId !== '_none' ? bulkCategoryId : undefined
    const resp = await importBulkFromMeli(ids, categoryId)
    setBulkLoading(false)
    if (resp?.error) { toast.error(resp.error); return }
    const summary = (resp?.data as { summary?: { imported: number; skipped: number; errors: number } } | null)?.summary
    if (summary) {
      const parts = [`${summary.imported} ${summary.imported === 1 ? 'importada' : 'importadas'}`]
      if (summary.skipped) parts.push(`${summary.skipped} omitidas (ya vinculadas)`)
      if (summary.errors)  parts.push(`${summary.errors} con error`)
      if (summary.errors) {
        toast.warning(parts.join(' · '), { description: 'Revisa las publicaciones con error e inténtalo de nuevo.' })
      } else {
        toast.success(parts.join(' · '), { description: 'Edita descripción e imágenes desde Productos.' })
      }
    } else {
      toast.success('Publicaciones importadas al Catálogo.')
    }
    clearSelection()
  }

  // ── Empty ─────────────────────────────────────────────────────────────────

  if (items.length === 0) {
    return (
      <Card className="border-border/50">
        <CardContent>
          <EmptyState
            variant="plain"
            icon={Store}
            className="py-16 max-w-md mx-auto"
            title="Aún no hay publicaciones para gestionar"
            description={
              <>
                No encontramos publicaciones activas en la cuenta de Mercado Libre conectada.
                Verifica que conectaste la cuenta vendedor correcta y crea publicaciones en Mercado Libre;
                aparecerán aquí para vincularlas a tu catálogo.
              </>
            }
            action={
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button variant="outline" size="sm" asChild>
                  <a href="https://www.mercadolibre.com.co/publicaciones/listado" target="_blank" rel="noreferrer">
                    <ExternalLink className="h-3.5 w-3.5 mr-1.5" /> Ir a mis publicaciones en MeLi
                  </a>
                </Button>
                <Button variant="ghost" size="sm" asChild>
                  <Link href="/dashboard/integrations">Revisar la cuenta conectada</Link>
                </Button>
              </div>
            }
          />
        </CardContent>
      </Card>
    )
  }

  // ── Main ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Filtros por estado */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
        <div className="flex gap-1 flex-wrap">
          {STATUS_FILTERS.map(f => (
            <button
              key={f.key}
              onClick={() => setStatusFilter(f.key)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 ${
                statusFilter === f.key
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
            >
              {f.label}
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                statusFilter === f.key ? 'bg-primary-foreground/20 text-primary-foreground' : 'bg-muted text-muted-foreground'
              }`}>
                {f.count}
              </span>
            </button>
          ))}
        </div>
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por título, ID o SKU..."
            aria-label="Buscar publicaciones por título, ID o SKU"
            className="pl-9 h-9"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Barra de acción masiva — aparece al seleccionar publicaciones sin vincular */}
      {canWrite && selectedIds.size > 0 && (
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 rounded-lg border border-primary/25 bg-primary/5 px-4 py-2.5">
          <p className="text-sm font-medium text-foreground flex items-center gap-2">
            <PackagePlus className="h-4 w-4 text-primary" />
            {selectedIds.size} sin vincular {selectedIds.size === 1 ? 'seleccionada' : 'seleccionadas'}
          </p>
          <div className="flex flex-1 items-center gap-2 flex-wrap sm:justify-end">
            <div className="w-full sm:w-52">
              <Select value={bulkCategoryId} onValueChange={setBulkCategoryId}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Categoría de catálogo (opcional)" />
                </SelectTrigger>
                <SelectContent className="max-h-60">
                  <SelectItem value="_none">Sin categoría</SelectItem>
                  {categories.map(c => (
                    <SelectItem key={c.id} value={c.id}>{c.display_label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button size="sm" className="h-8 text-xs gap-1.5" onClick={handleBulkImport} disabled={bulkLoading}>
              {bulkLoading
                ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Importando…</>
                : <><PackagePlus className="h-3.5 w-3.5" /> Importar {selectedIds.size} al Catálogo</>}
            </Button>
            <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={clearSelection} disabled={bulkLoading}>
              Limpiar
            </Button>
          </div>
        </div>
      )}

      <Card className="border-border/50 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[860px]">
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
                {canWrite && (
                  <th className="py-3 pl-4 pr-1 w-9">
                    <Tooltip>
                      <TooltipProvider delayDuration={200}>
                        <TooltipTrigger asChild>
                          <span className="inline-flex">
                            <Checkbox
                              checked={allUnlinkedSelected}
                              onCheckedChange={toggleSelectAllUnlinked}
                              disabled={unlinkedIds.length === 0}
                              aria-label="Seleccionar todas las publicaciones sin vincular"
                            />
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>Seleccionar todas las publicaciones sin vincular de esta página</TooltipContent>
                      </TooltipProvider>
                    </Tooltip>
                  </th>
                )}
                <th className="py-3 px-4 font-medium text-left">Publicación MeLi</th>
                <th className="py-3 px-4 font-medium text-right">Precio MeLi</th>
                <th className="py-3 px-4 font-medium text-center">Stock MeLi</th>
                <th className="py-3 px-4 font-medium text-center">Estado</th>
                <th className="py-3 px-4 font-medium text-left">Vinculado a Catálogo</th>
                <th className="py-3 px-4 font-medium text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {filtered.map(item => {
                const isLoading     = loadingIds.has(item.meli_id)
                const rowError      = actionErrors[item.meli_id]
                const stockDiff     = item.is_linked && item.supabase_stock !== null
                  ? item.supabase_stock - item.available_quantity
                  : null
                const stockOutOfSync = stockDiff !== null && stockDiff !== 0
                // F3: drift de precio (catálogo vs MeLi). El sync es manual — nunca
                // pisamos promos nativas de MeLi automáticamente; solo lo señalamos.
                const priceOutOfSync = item.is_linked && item.supabase_price !== null
                  && Math.abs(item.supabase_price - item.price) >= 0.01
                const outOfSync = stockOutOfSync || priceOutOfSync
                const isSelected = selectedIds.has(item.meli_id)

                return (
                  <tr
                    key={item.meli_id}
                    className={`hover:bg-muted/30 transition-colors ${isLoading ? 'opacity-50 pointer-events-none' : ''} ${rowError ? 'bg-danger-bg' : ''} ${isSelected ? 'bg-primary/5' : ''}`}
                  >
                    {/* Selección masiva — solo publicaciones sin vincular */}
                    {canWrite && (
                      <td className="py-3 pl-4 pr-1 align-top">
                        {!item.is_linked ? (
                          <Checkbox
                            checked={isSelected}
                            onCheckedChange={() => toggleSelect(item.meli_id)}
                            aria-label={`Seleccionar ${item.title ?? item.meli_id} para importar`}
                          />
                        ) : (
                          <span className="block h-4 w-4" aria-hidden="true" />
                        )}
                      </td>
                    )}
                    {/* Publicación */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-3">
                        {item.thumbnail && (
                          <Image
                            src={item.thumbnail.replace(/^http:/, 'https:')}
                            alt={item.title ?? ''}
                            width={40}
                            height={40}
                            className="rounded object-cover shrink-0 bg-muted"
                          />
                        )}
                        <div className="min-w-0">
                          <p className="font-medium text-foreground truncate max-w-[240px]">{item.title}</p>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <p className="text-xs text-muted-foreground">{item.meli_id}</p>
                            {item.meli_condition && item.meli_condition !== 'not_specified' && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                                {CONDITION_LABEL[item.meli_condition] ?? item.meli_condition}
                              </span>
                            )}
                          </div>
                          {rowError && (
                            <p className="text-xs text-danger-fg flex items-center gap-1 mt-0.5">
                              <AlertTriangle className="h-3 w-3 shrink-0" /> {rowError}
                              <button onClick={() => clearError(item.meli_id)} className="ml-1 text-muted-foreground hover:text-foreground">
                                <X className="h-3 w-3" />
                              </button>
                            </p>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Precio MeLi */}
                    <td className="py-3 px-4 text-right whitespace-nowrap">
                      <span className="font-semibold">${item.price?.toLocaleString('es-CO')}</span>
                    </td>

                    {/* Stock MeLi */}
                    <td className="py-3 px-4 text-center">
                      <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                        item.available_quantity > 0
                          ? 'bg-warning-bg text-warning-fg'
                          : 'bg-danger-bg text-danger-fg'
                      }`}>
                        {item.available_quantity} u.
                      </span>
                    </td>

                    {/* Estado */}
                    <td className="py-3 px-4 text-center">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${STATUS_CONFIG[item.status]?.className ?? 'bg-muted text-muted-foreground'}`}>
                        {meliStatusLabel(item.status)}
                      </span>
                    </td>

                    {/* Vinculación */}
                    <td className="py-3 px-4">
                      {item.is_linked ? (
                        <div className="flex flex-col gap-0.5">
                          <p className="text-xs font-medium text-foreground">{item.product_name}</p>
                          <p className="text-[10px] text-muted-foreground">SKU: {item.sku}</p>
                          <div className="flex items-center gap-1 mt-0.5">
                            {stockOutOfSync ? (
                              <span className="text-[10px] text-warning-fg flex items-center gap-1">
                                <AlertTriangle className="h-3 w-3" />
                                {item.supabase_stock} u. en catálogo (desincronizado)
                              </span>
                            ) : (
                              <span className="text-[10px] text-success-fg flex items-center gap-1">
                                <CheckCircle2 className="h-3 w-3" />
                                {item.supabase_stock} u. en catálogo (sincronizado)
                              </span>
                            )}
                          </div>
                          {priceOutOfSync && (
                            <div className="flex items-center gap-1 mt-0.5">
                              <span className="text-[10px] text-warning-fg flex items-center gap-1">
                                <AlertTriangle className="h-3 w-3" />
                                Catálogo ${item.supabase_price?.toLocaleString('es-CO')} vs MeLi ${item.price?.toLocaleString('es-CO')} (precio desincronizado)
                              </span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground italic">No vinculado</span>
                      )}
                    </td>

                    {/* Acciones */}
                    <td className="py-3 px-4">
                      <TooltipProvider delayDuration={200}>
                      <div className="flex items-center justify-end gap-1.5 flex-wrap">
                        {item.permalink && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button variant="ghost" size="icon" className="h-8 w-8 text-info-fg hover:text-info-fg" asChild>
                                <a href={item.permalink} target="_blank" rel="noreferrer" aria-label="Ver en Mercado Libre">
                                  <ExternalLink className="h-3.5 w-3.5" />
                                </a>
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Ver en Mercado Libre</TooltipContent>
                          </Tooltip>
                        )}

                        {item.is_linked && outOfSync && canWrite && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-8 text-xs gap-1.5 text-info-fg border-info-border"
                                onClick={() => handleSyncStock(item)}
                                aria-label="Sincronizar stock y precio desde el Catálogo a Mercado Libre"
                              >
                                <RefreshCw className="h-3 w-3" /> Sync
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Sincronizar stock y precio desde el Catálogo a Mercado Libre</TooltipContent>
                          </Tooltip>
                        )}

                        {item.is_linked && canWrite && item.status !== 'closed' && (
                          item.status === 'active' ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-8 text-xs gap-1.5 text-warning-fg border-warning-border"
                              onClick={() => handleStatusChange(item, 'paused')}
                            >
                              <Pause className="h-3 w-3" /> Pausar
                            </Button>
                          ) : item.status === 'paused' ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-8 text-xs gap-1.5 text-success-fg border-success-border"
                              onClick={() => handleStatusChange(item, 'active')}
                            >
                              <Play className="h-3 w-3" /> Activar
                            </Button>
                          ) : null
                        )}

                        {canWrite && (
                          item.is_linked ? (
                            confirmUnlinkId === item.meli_id ? (
                              <div className="flex items-center gap-1">
                                <Button size="sm" variant="destructive" className="h-7 text-xs"
                                  onClick={() => handleUnlink(item)}>Confirmar</Button>
                                <Button size="sm" variant="ghost" className="h-7 text-xs"
                                  onClick={() => setConfirmUnlinkId(null)}>Cancelar</Button>
                              </div>
                            ) : (
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 text-xs gap-1.5 text-muted-foreground hover:text-destructive"
                                    onClick={() => setConfirmUnlinkId(item.meli_id)}
                                    aria-label="Desvincular del catálogo"
                                  >
                                    <Link2Off className="h-3 w-3" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Desvincular del catálogo</TooltipContent>
                              </Tooltip>
                            )
                          ) : (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-8 text-xs gap-1.5"
                              onClick={() => { setSheetItem(item); setSheetMode('link') }}
                            >
                              <Link2 className="h-3 w-3" /> Vincular
                            </Button>
                          )
                        )}
                      </div>
                      </TooltipProvider>
                    </td>
                  </tr>
                )
              })}

              {filtered.length === 0 && (
                <tr>
                  <td colSpan={canWrite ? 7 : 6}>
                    <EmptyState
                      variant="plain"
                      className="py-12"
                      description="No hay publicaciones que coincidan con la búsqueda."
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Pager server-side — navega por query param (?offset=). Búsqueda y filtros
          operan sobre la página actual. */}
      {(hasPrev || hasNext) && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-xs text-muted-foreground">
            Mostrando <strong>{pageOffset + 1}</strong>–<strong>{pageOffset + items.length}</strong> de <strong>{total}</strong> publicaciones
          </p>
          <div className="flex items-center gap-2">
            {hasPrev ? (
              <Button variant="outline" size="sm" className="h-8 text-xs gap-1" asChild>
                <Link href={prevHref}><ChevronLeft className="h-3.5 w-3.5" /> Anteriores</Link>
              </Button>
            ) : (
              <Button variant="outline" size="sm" className="h-8 text-xs gap-1" disabled>
                <ChevronLeft className="h-3.5 w-3.5" /> Anteriores
              </Button>
            )}
            {hasNext ? (
              <Button variant="outline" size="sm" className="h-8 text-xs gap-1" asChild>
                <Link href={nextHref}>Siguientes <ChevronRight className="h-3.5 w-3.5" /></Link>
              </Button>
            ) : (
              <Button variant="outline" size="sm" className="h-8 text-xs gap-1" disabled>
                Siguientes <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      )}

      {/* ── Sheet: Vincular / Importar ──────────────────────────────────────── */}
      <Sheet open={!!sheetItem} onOpenChange={open => !open && closeSheet()}>
        <SheetContent side="right" className="w-full sm:max-w-lg flex flex-col overflow-y-auto">
          <SheetHeader className="shrink-0">
            <SheetTitle className="text-base line-clamp-2">{sheetItem?.title}</SheetTitle>
            <SheetDescription className="text-xs">
              {sheetItem?.meli_id} · ${sheetItem?.price?.toLocaleString('es-CO')} · {sheetItem?.available_quantity} u.
            </SheetDescription>
          </SheetHeader>

          {/* Mode tabs */}
          <div className="flex gap-1 mt-4 shrink-0">
            <button
              className={`px-3 py-1.5 text-xs rounded font-medium transition-colors ${sheetMode === 'link' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
              onClick={() => setSheetMode('link')}
            >
              Vincular a producto existente
            </button>
            <button
              className={`px-3 py-1.5 text-xs rounded font-medium transition-colors ${sheetMode === 'import' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'}`}
              onClick={() => setSheetMode('import')}
            >
              Importar desde MeLi
            </button>
          </div>

          <div className="flex-1 mt-4 space-y-4">
            {/* Vincular */}
            {sheetMode === 'link' && (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Selecciona la variante del catálogo que representa esta publicación. Solo se sincronizará el stock de variantes vinculadas.
                </p>

                {/* Selector variación MeLi — solo si el item tiene variaciones propias */}
                {(sheetItem?.meli_variations?.length ?? 0) > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-foreground">
                      Variación de Mercado Libre
                      <span className="ml-1 text-muted-foreground font-normal">(requerido — este item tiene variaciones)</span>
                    </p>
                    <Select
                      value={selectedMeliVariationId?.toString() ?? ''}
                      onValueChange={v => setSelectedMeliVariationId(Number(v))}
                    >
                      <SelectTrigger className="h-9 text-sm">
                        <SelectValue placeholder="Selecciona la variación de MeLi..." />
                      </SelectTrigger>
                      <SelectContent className="max-h-60">
                        {sheetItem?.meli_variations.map(mv => {
                          const label = mv.attributes.map(a => a.value_name).join(' / ') || `ID ${mv.id}`
                          return (
                            <SelectItem key={mv.id} value={mv.id.toString()}>
                              {label}
                              <span className="text-muted-foreground text-xs ml-1">· {mv.available_quantity} u.</span>
                            </SelectItem>
                          )
                        })}
                      </SelectContent>
                    </Select>
                    <p className="text-[11px] text-muted-foreground">
                      El stock se sincronizará exactamente a esta variación. Las demás quedarán en 0.
                    </p>
                  </div>
                )}

                <p className="text-xs text-muted-foreground">Variante del catálogo interno:</p>
                {variations.length > 0 && (
                  <div className="relative">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input
                      value={variantQuery}
                      onChange={e => setVariantQuery(e.target.value)}
                      placeholder="Filtrar por SKU, producto o atributo..."
                      aria-label="Filtrar variantes del catálogo"
                      className="pl-9 h-9 text-sm"
                    />
                  </div>
                )}
                <Select value={selectedVariationId} onValueChange={setSelectedVariationId}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue placeholder="Categoría → Producto → Variante..." />
                  </SelectTrigger>
                  <SelectContent className="max-h-72">
                    {variations.length === 0 ? (
                      <SelectItem value="_empty" disabled>
                        No hay variantes. Usa &quot;Importar desde MeLi&quot;.
                      </SelectItem>
                    ) : filteredVariations.length === 0 ? (
                      <SelectItem value="_nomatch" disabled>
                        Ninguna variante coincide con &quot;{variantQuery}&quot;.
                      </SelectItem>
                    ) : (
                      Object.entries(
                        filteredVariations.reduce<Record<string, Variation[]>>((acc, v) => {
                          const key = v.category_name
                          ;(acc[key] ??= []).push(v)
                          return acc
                        }, {})
                      ).sort(([a], [b]) => a.localeCompare(b)).map(([catName, vars]) => (
                        <SelectGroup key={catName}>
                          <SelectLabel className="text-xs font-semibold text-primary/80 uppercase tracking-wide">
                            {catName}
                          </SelectLabel>
                          {vars.map(v => {
                            const attrs = Object.entries(v.attributes)
                              .filter(([k]) => k !== 'default')
                              .map(([, val]) => val)
                              .join(' / ')
                            return (
                              <SelectItem key={v.id} value={v.id}>
                                <span className="font-medium">{v.product_title}</span>
                                {attrs && <span className="text-muted-foreground"> — {attrs}</span>}
                                <span className="text-muted-foreground text-xs ml-1">
                                  · {v.sku} · Stock: {v.stock_quantity}
                                </span>
                              </SelectItem>
                            )
                          })}
                        </SelectGroup>
                      ))
                    )}
                  </SelectContent>
                </Select>

                {meliVariationRequired && selectedMeliVariationId == null && (
                  <p className="text-[11px] text-warning-fg flex items-center gap-1">
                    <AlertTriangle className="h-3 w-3 shrink-0" />
                    Selecciona la variación de Mercado Libre antes de vincular.
                  </p>
                )}
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    className="flex-1"
                    disabled={
                      !selectedVariationId ||
                      selectedVariationId === '_empty' ||
                      selectedVariationId === '_nomatch' ||
                      (meliVariationRequired && selectedMeliVariationId == null)
                    }
                    onClick={() => sheetItem && handleLink(sheetItem.meli_id)}
                  >
                    Confirmar vinculación
                  </Button>
                  <Button variant="ghost" size="sm" onClick={closeSheet}>Cancelar</Button>
                </div>
              </div>
            )}

            {/* Importar */}
            {sheetMode === 'import' && (
              <div className="space-y-3">
                <div className="rounded-md border border-border/50 bg-muted/30 p-3 text-sm space-y-1">
                  <p className="font-medium">{sheetItem?.title}</p>
                  <div className="flex gap-4 text-xs text-muted-foreground flex-wrap">
                    <span>Precio: <strong className="text-foreground">${sheetItem?.price?.toLocaleString('es-CO')}</strong></span>
                    <span>Stock: <strong className="text-foreground">{sheetItem?.available_quantity} u.</strong></span>
                  </div>
                  <p className="text-xs text-muted-foreground pt-1">
                    Se creará un producto en el Catálogo con estos datos. Podrás editar descripción e imágenes desde Productos.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <p className="text-xs text-muted-foreground">Categoría de catálogo (opcional):</p>
                  <Select value={selectedCategoryId} onValueChange={setSelectedCategoryId}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue placeholder="Sin categoría" />
                    </SelectTrigger>
                    <SelectContent className="max-h-60">
                      <SelectItem value="_none">Sin categoría</SelectItem>
                      {categories.map(c => (
                        <SelectItem key={c.id} value={c.id}>{c.display_label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex gap-2">
                  <Button
                    size="sm"
                    className="flex-1"
                    onClick={() => sheetItem && handleImport(sheetItem.meli_id, sheetItem.title)}
                  >
                    Importar y Vincular
                  </Button>
                  <Button variant="ghost" size="sm" onClick={closeSheet}>Cancelar</Button>
                </div>
              </div>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
