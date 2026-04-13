'use client'

import { useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  ExternalLink, Pause, Play, Link2, Link2Off, RefreshCw,
  Search, AlertTriangle, CheckCircle2, WifiOff
} from 'lucide-react'
import {
  linkListing, unlinkListing, changeListingStatus, syncStockFromSupabase
} from '../actions'

type MeliItem = {
  meli_id: string
  title: string
  status: 'active' | 'paused' | 'closed'
  price: number
  available_quantity: number
  thumbnail: string | null
  permalink: string | null
  // Vinculación Supabase
  listing_id: string | null
  variation_id: string | null
  sku: string | null
  product_name: string | null
  supabase_stock: number | null
  is_linked: boolean
}

type Variation = {
  id: string
  label: string
  sku: string
  stock_quantity: number
  product_title: string
}

type Props = {
  connected: boolean
  items: MeliItem[]
  paging: { total: number }
  variations: Variation[]
  canWrite: boolean
}

const STATUS_CONFIG = {
  active:  { label: 'Activo',  className: 'bg-green-500/15 text-green-600' },
  paused:  { label: 'Pausado', className: 'bg-yellow-500/15 text-yellow-600' },
  closed:  { label: 'Cerrado', className: 'bg-red-500/15 text-red-500' },
}

export default function MarketplaceManager({ connected, items, paging, variations, canWrite }: Props) {
  const [search, setSearch] = useState('')
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set())
  // Estado para el panel de vinculación
  const [linkingMeliId, setLinkingMeliId] = useState<string | null>(null)
  const [selectedVariationId, setSelectedVariationId] = useState('')

  const setLoading = (id: string, on: boolean) => {
    setLoadingIds(prev => {
      const next = new Set(prev)
      on ? next.add(id) : next.delete(id)
      return next
    })
  }

  const filtered = items.filter(i =>
    i.title?.toLowerCase().includes(search.toLowerCase()) ||
    i.meli_id?.toLowerCase().includes(search.toLowerCase()) ||
    i.sku?.toLowerCase().includes(search.toLowerCase())
  )

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleStatusChange = async (item: MeliItem, newStatus: 'active' | 'paused') => {
    if (!item.listing_id) return
    setLoading(item.meli_id, true)
    const resp = await changeListingStatus(item.listing_id, newStatus)
    if (resp?.error) alert(`Error: ${resp.error}`)
    setLoading(item.meli_id, false)
  }

  const handleSyncStock = async (item: MeliItem) => {
    if (!item.listing_id) return
    setLoading(item.meli_id, true)
    const resp = await syncStockFromSupabase(item.listing_id)
    if (resp?.error) alert(`Error: ${resp.error}`)
    setLoading(item.meli_id, false)
  }

  const handleUnlink = async (item: MeliItem) => {
    if (!item.listing_id) return
    if (!confirm(`¿Desvincular "${item.title}" de Supabase? El item en MeLi quedará intacto pero el stock dejará de sincronizarse.`)) return
    setLoading(item.meli_id, true)
    const resp = await unlinkListing(item.listing_id)
    if (resp?.error) alert(`Error: ${resp.error}`)
    setLoading(item.meli_id, false)
  }

  const handleLink = async (meliId: string) => {
    if (!selectedVariationId) return
    setLoading(meliId, true)
    const resp = await linkListing(meliId, selectedVariationId)
    if (resp?.error) {
      alert(`Error: ${resp.error}`)
    } else {
      setLinkingMeliId(null)
      setSelectedVariationId('')
    }
    setLoading(meliId, false)
  }

  // ── Sin conexión ──────────────────────────────────────────────────────────

  if (!connected) {
    return (
      <Card className="border-border/50">
        <CardContent className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <WifiOff className="h-10 w-10 text-muted-foreground" />
          <p className="text-muted-foreground max-w-sm">
            Tu cuenta de Mercado Libre no está conectada.
            Ve a <strong>Configuración → Integraciones</strong> para vincularla.
          </p>
        </CardContent>
      </Card>
    )
  }

  // ── Sin publicaciones ─────────────────────────────────────────────────────

  if (items.length === 0) {
    return (
      <Card className="border-border/50">
        <CardContent className="flex flex-col items-center justify-center py-16 gap-4 text-center">
          <p className="text-muted-foreground">No se encontraron publicaciones en tu cuenta de Mercado Libre.</p>
        </CardContent>
      </Card>
    )
  }

  // ── Tabla principal ───────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Header stats */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
        <div className="flex gap-4 text-sm text-muted-foreground">
          <span><strong className="text-foreground">{paging.total}</strong> publicaciones totales</span>
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
                <th className="py-3 px-4 font-medium text-left">Vinculado a Supabase</th>
                <th className="py-3 px-4 font-medium text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {filtered.map(item => {
                const isLoading = loadingIds.has(item.meli_id)
                const isLinking = linkingMeliId === item.meli_id
                const stockDiff = item.is_linked && item.supabase_stock !== null
                  ? item.supabase_stock - item.available_quantity
                  : null
                const stockOutOfSync = stockDiff !== null && stockDiff !== 0

                return (
                  <>
                    <tr
                      key={item.meli_id}
                      className={`hover:bg-muted/30 transition-colors ${isLoading ? 'opacity-50 pointer-events-none' : ''}`}
                    >
                      {/* Publicación */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-3">
                          {item.thumbnail && (
                            <img
                              src={item.thumbnail}
                              alt=""
                              className="h-10 w-10 rounded object-cover flex-shrink-0 bg-muted"
                            />
                          )}
                          <div className="min-w-0">
                            <p className="font-medium text-foreground truncate max-w-[240px]">{item.title}</p>
                            <p className="text-xs text-muted-foreground">{item.meli_id}</p>
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

                      {/* Vinculación Supabase */}
                      <td className="py-3 px-4">
                        {item.is_linked ? (
                          <div className="flex flex-col gap-0.5">
                            <p className="text-xs font-medium text-foreground">{item.product_name}</p>
                            <p className="text-[10px] text-muted-foreground">SKU: {item.sku}</p>
                            <div className="flex items-center gap-1 mt-0.5">
                              {stockOutOfSync ? (
                                <span className="text-[10px] text-yellow-600 flex items-center gap-1">
                                  <AlertTriangle className="h-3 w-3" />
                                  Supabase: {item.supabase_stock} u. (desincronizado)
                                </span>
                              ) : (
                                <span className="text-[10px] text-green-600 flex items-center gap-1">
                                  <CheckCircle2 className="h-3 w-3" />
                                  Supabase: {item.supabase_stock} u. (sincronizado)
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
                          {/* Ver en MeLi */}
                          {item.permalink && (
                            <Button variant="ghost" size="icon" className="h-8 w-8 text-blue-500 hover:text-blue-600" asChild>
                              <a href={item.permalink} target="_blank" rel="noreferrer" title="Ver en Mercado Libre">
                                <ExternalLink className="h-3.5 w-3.5" />
                              </a>
                            </Button>
                          )}

                          {/* Sync stock (solo si vinculado y desincronizado) */}
                          {item.is_linked && stockOutOfSync && canWrite && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-8 text-xs gap-1.5 text-blue-600 border-blue-500/30"
                              onClick={() => handleSyncStock(item)}
                              title="Sincronizar stock de Supabase a MeLi"
                            >
                              <RefreshCw className="h-3 w-3" /> Sync
                            </Button>
                          )}

                          {/* Pausar / Activar (solo si vinculado) */}
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

                          {/* Vincular / Desvincular */}
                          {canWrite && (
                            item.is_linked ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 text-xs gap-1.5 text-muted-foreground hover:text-destructive"
                                onClick={() => handleUnlink(item)}
                                title="Desvincular de Supabase"
                              >
                                <Link2Off className="h-3 w-3" />
                              </Button>
                            ) : (
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-8 text-xs gap-1.5"
                                onClick={() => setLinkingMeliId(isLinking ? null : item.meli_id)}
                              >
                                <Link2 className="h-3 w-3" /> Vincular
                              </Button>
                            )
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* Panel de vinculación inline */}
                    {isLinking && (
                      <tr key={`link-${item.meli_id}`} className="bg-muted/20">
                        <td colSpan={6} className="px-4 py-3">
                          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
                            <p className="text-xs text-muted-foreground whitespace-nowrap">
                              Vincular <strong>{item.title}</strong> a:
                            </p>
                            <select
                              className="flex-1 h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                              value={selectedVariationId}
                              onChange={e => setSelectedVariationId(e.target.value)}
                            >
                              <option value="">Seleccionar variante de Supabase...</option>
                              {variations.map(v => (
                                <option key={v.id} value={v.id}>{v.label}</option>
                              ))}
                            </select>
                            <div className="flex gap-2">
                              <Button
                                size="sm"
                                className="h-8 text-xs"
                                disabled={!selectedVariationId}
                                onClick={() => handleLink(item.meli_id)}
                              >
                                Confirmar
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 text-xs"
                                onClick={() => { setLinkingMeliId(null); setSelectedVariationId('') }}
                              >
                                Cancelar
                              </Button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
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
    </div>
  )
}
