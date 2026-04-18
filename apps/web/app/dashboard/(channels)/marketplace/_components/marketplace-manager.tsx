'use client'

import { useState } from 'react'
import Image from 'next/image'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import {
  ExternalLink, Pause, Play, Link2, Link2Off, RefreshCw,
  Search, AlertTriangle, CheckCircle2, X,
} from 'lucide-react'
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue
} from '@/components/ui/select'
import {
  linkListing, unlinkListing, changeListingStatus, syncStockFromSupabase, importFromMeli
} from '../actions'

type MeliVariation = {
  id: number
  attributes: { id: string; value_name: string }[]
  available_quantity: number
}

type MeliItem = {
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
  is_linked: boolean
}

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
  name: string
}

type Props = {
  items: MeliItem[]
  paging: { total: number }
  variations: Variation[]
  categories: Category[]
  canWrite: boolean
}

const STATUS_CONFIG = {
  active:  { label: 'Activo',  className: 'bg-green-500/15 text-green-600' },
  paused:  { label: 'Pausado', className: 'bg-yellow-500/15 text-yellow-600' },
  closed:  { label: 'Cerrado', className: 'bg-red-500/15 text-red-500' },
}

export default function MarketplaceManager({ items, paging, variations, categories, canWrite }: Props) {
  const [search, setSearch]                   = useState('')
  const [loadingIds, setLoadingIds]           = useState<Set<string>>(new Set())
  const [sheetItem, setSheetItem]             = useState<MeliItem | null>(null)
  const [sheetMode, setSheetMode]             = useState<'link' | 'import'>('link')
  const [selectedVariationId, setSelectedVariationId]       = useState('')
  const [selectedCategoryId, setSelectedCategoryId]         = useState('')
  const [selectedMeliVariationId, setSelectedMeliVariationId] = useState<number | null>(null)
  const [actionErrors, setActionErrors]       = useState<Record<string, string>>({})
  const [confirmUnlinkId, setConfirmUnlinkId] = useState<string | null>(null)

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
  }

  const filtered = items.filter(i =>
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
    if (resp?.error) setError(item.meli_id, resp.error)
    setLoading(item.meli_id, false)
  }

  const handleSyncStock = async (item: MeliItem) => {
    if (!item.listing_id) return
    clearError(item.meli_id)
    setLoading(item.meli_id, true)
    const resp = await syncStockFromSupabase(item.listing_id)
    if (resp?.error) setError(item.meli_id, resp.error)
    setLoading(item.meli_id, false)
  }

  const handleUnlink = async (item: MeliItem) => {
    if (!item.listing_id) return
    clearError(item.meli_id)
    setLoading(item.meli_id, true)
    const resp = await unlinkListing(item.listing_id)
    if (resp?.error) setError(item.meli_id, resp.error)
    setLoading(item.meli_id, false)
    setConfirmUnlinkId(null)
  }

  const handleLink = async (meliId: string) => {
    if (!selectedVariationId) return
    clearError(meliId)
    setLoading(meliId, true)
    const resp = await linkListing(meliId, selectedVariationId, undefined, selectedMeliVariationId ?? undefined)
    if (resp?.error) setError(meliId, resp.error)
    else closeSheet()
    setLoading(meliId, false)
  }

  const handleImport = async (meliId: string, meliTitle: string) => {
    clearError(meliId)
    setLoading(meliId, true)
    const resp = await importFromMeli(meliId, selectedCategoryId || undefined)
    if (resp?.error) setError(meliId, resp.error)
    else closeSheet()
    setLoading(meliId, false)
  }

  // ── Empty ─────────────────────────────────────────────────────────────────

  if (items.length === 0) {
    return (
      <Card className="border-border/50">
        <CardContent className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <p className="text-muted-foreground">No se encontraron publicaciones en tu cuenta de Mercado Libre.</p>
        </CardContent>
      </Card>
    )
  }

  // ── Main ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Header stats */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
        <div className="flex gap-4 text-sm text-muted-foreground">
          <span><strong className="text-foreground">{paging.total}</strong> publicaciones</span>
          <span><strong className="text-green-600">{items.filter(i => i.status === 'active').length}</strong> activas</span>
          <span><strong className="text-amber-600">{items.filter(i => i.is_linked).length}</strong> vinculadas</span>
        </div>
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por título, ID o SKU..."
            className="pl-9 h-9"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      <Card className="border-border/50 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[860px]">
            <thead>
              <tr className="border-b bg-muted/40 text-muted-foreground">
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

                return (
                  <tr
                    key={item.meli_id}
                    className={`hover:bg-muted/30 transition-colors ${isLoading ? 'opacity-50 pointer-events-none' : ''} ${rowError ? 'bg-red-500/5' : ''}`}
                  >
                    {/* Publicación */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-3">
                        {item.thumbnail && (
                          <Image
                            src={item.thumbnail.replace(/^http:/, 'https:')}
                            alt={item.title ?? ''}
                            width={40}
                            height={40}
                            className="rounded object-cover flex-shrink-0 bg-muted"
                          />
                        )}
                        <div className="min-w-0">
                          <p className="font-medium text-foreground truncate max-w-[240px]">{item.title}</p>
                          <p className="text-xs text-muted-foreground">{item.meli_id}</p>
                          {rowError && (
                            <p className="text-xs text-red-400 flex items-center gap-1 mt-0.5">
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
                          ? 'bg-amber-500/15 text-amber-600'
                          : 'bg-red-500/15 text-red-500'
                      }`}>
                        {item.available_quantity} u.
                      </span>
                    </td>

                    {/* Estado */}
                    <td className="py-3 px-4 text-center">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${STATUS_CONFIG[item.status]?.className ?? 'bg-muted text-muted-foreground'}`}>
                        {STATUS_CONFIG[item.status]?.label ?? item.status}
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
                              <span className="text-[10px] text-yellow-600 flex items-center gap-1">
                                <AlertTriangle className="h-3 w-3" />
                                {item.supabase_stock} u. en catálogo (desincronizado)
                              </span>
                            ) : (
                              <span className="text-[10px] text-green-600 flex items-center gap-1">
                                <CheckCircle2 className="h-3 w-3" />
                                {item.supabase_stock} u. en catálogo (sincronizado)
                              </span>
                            )}
                          </div>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground italic">No vinculado</span>
                      )}
                    </td>

                    {/* Acciones */}
                    <td className="py-3 px-4">
                      <div className="flex items-center justify-end gap-1.5 flex-wrap">
                        {item.permalink && (
                          <Button variant="ghost" size="icon" className="h-8 w-8 text-blue-500 hover:text-blue-600" asChild>
                            <a href={item.permalink} target="_blank" rel="noreferrer" title="Ver en Mercado Libre">
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          </Button>
                        )}

                        {item.is_linked && stockOutOfSync && canWrite && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-8 text-xs gap-1.5 text-blue-600 border-blue-500/30"
                            onClick={() => handleSyncStock(item)}
                            title="Sincronizar stock y precio desde el Catálogo a MeLi"
                          >
                            <RefreshCw className="h-3 w-3" /> Sync
                          </Button>
                        )}

                        {item.is_linked && canWrite && item.status !== 'closed' && (
                          item.status === 'active' ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-8 text-xs gap-1.5 text-yellow-600 border-yellow-500/30"
                              onClick={() => handleStatusChange(item, 'paused')}
                            >
                              <Pause className="h-3 w-3" /> Pausar
                            </Button>
                          ) : item.status === 'paused' ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-8 text-xs gap-1.5 text-green-600 border-green-500/30"
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
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 text-xs gap-1.5 text-muted-foreground hover:text-destructive"
                                onClick={() => setConfirmUnlinkId(item.meli_id)}
                                title="Desvincular"
                              >
                                <Link2Off className="h-3 w-3" />
                              </Button>
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
                    </td>
                  </tr>
                )
              })}

              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-muted-foreground">
                    No hay publicaciones que coincidan con la búsqueda.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {paging.total > items.length && (
        <p className="text-xs text-muted-foreground text-center">
          Mostrando {items.length} de {paging.total} publicaciones. La paginación completa estará disponible próximamente.
        </p>
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
                <Select value={selectedVariationId} onValueChange={setSelectedVariationId}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue placeholder="Categoría → Producto → Variante..." />
                  </SelectTrigger>
                  <SelectContent className="max-h-72">
                    {variations.length === 0 ? (
                      <SelectItem value="_empty" disabled>
                        No hay variantes. Usa &quot;Importar desde MeLi&quot;.
                      </SelectItem>
                    ) : (
                      Object.entries(
                        variations.reduce<Record<string, Variation[]>>((acc, v) => {
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

                <div className="flex gap-2">
                  <Button
                    size="sm"
                    className="flex-1"
                    disabled={!selectedVariationId || selectedVariationId === '_empty'}
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
                  <p className="text-xs text-muted-foreground">Categoría (opcional):</p>
                  <Select value={selectedCategoryId} onValueChange={setSelectedCategoryId}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue placeholder="Sin categoría" />
                    </SelectTrigger>
                    <SelectContent className="max-h-60">
                      <SelectItem value="_none">Sin categoría</SelectItem>
                      {categories.map(c => (
                        <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
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
