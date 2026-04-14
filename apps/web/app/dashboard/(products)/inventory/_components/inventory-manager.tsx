'use client'

import { useState, useMemo, useEffect, useTransition } from 'react'
import { useFormStatus } from 'react-dom'
import { Boxes, AlertTriangle, Package, Search, X, Loader2, ChevronLeft, ChevronRight } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import AiInsightPanel from '@/components/ai-insight-panel'
import type { Product, Movement } from '../types'

type Props = {
  products: Product[]
  movements: Movement[]
  threshold: number
  canWrite: boolean
  role: string
  adjustStockAction: (fd: FormData) => Promise<void>
  saveThresholdAction: (fd: FormData) => Promise<void>
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatAttributes(attrs: Record<string, string> | null): string {
  if (!attrs || Object.keys(attrs).length === 0) return 'Estándar'
  return Object.entries(attrs).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

// ── Sub-components ───────────────────────────────────────────────────────────

function SubmitButton() {
  const { pending } = useFormStatus()
  return (
    <Button type="submit" size="sm" className="h-7 text-xs w-full sm:w-auto" disabled={pending}>
      {pending ? <Loader2 className="h-3 w-3 animate-spin mx-2" /> : 'Aplicar'}
    </Button>
  )
}

function AdjustForm({
  variationId, productId, adjustStockAction
}: { variationId: string; productId: string; adjustStockAction: (fd: FormData) => Promise<void> }) {
  // Opcional: limpiar la form o manejar reset, aunque el action provoca revalida
  return (
    <form action={adjustStockAction} className="grid grid-cols-1 xs:grid-cols-2 sm:grid-cols-3 gap-2 pt-2 border-t border-border mt-3">
      <input type="hidden" name="variation_id" value={variationId} />
      <input type="hidden" name="product_id"   value={productId} />
      <div className="space-y-1">
        <Label className="text-[11px]">Ajuste (±)</Label>
        <Input name="delta" type="number" placeholder="10 o -3" className="h-7 text-xs" required />
      </div>
      <div className="space-y-1">
        <Label className="text-[11px]">Motivo</Label>
        <Input name="reason" placeholder="Compra..." className="h-7 text-xs" />
      </div>
      <div className="flex items-end mt-1 sm:mt-0">
        <SubmitButton />
      </div>
    </form>
  )
}

function SaveThresholdButton() {
  const { pending } = useFormStatus()
  return (
    <Button type="submit" size="sm" className="h-8" disabled={pending}>
      {pending ? <Loader2 className="h-4 w-4 animate-spin mx-2" /> : 'Guardar'}
    </Button>
  )
}

// ── Main Component ───────────────────────────────────────────────────────────

const ITEMS_PER_PAGE = 20

export default function InventoryManager({
  products, movements, threshold, canWrite, role, adjustStockAction, saveThresholdAction
}: Props) {
  const [search, setSearch] = useState('')
  const [currentPage, setCurrentPage] = useState(1)

  const allVariations  = products.flatMap(p => p.product_variations)
  const totalUnits     = allVariations.reduce((s, v) => s + v.stock_quantity, 0)
  const lowStockCount  = allVariations.filter(v => v.stock_quantity > 0 && v.stock_quantity <= threshold).length
  const zeroStockCount = allVariations.filter(v => v.stock_quantity === 0).length

  // Filter products locally
  const filteredProducts = useMemo(() => {
    const q = search.toLowerCase().trim()
    if (!q) return products
    
    return products.filter(p => {
      // Coincide el título
      if (p.title.toLowerCase().includes(q)) return true
      // Coincide algún SKU
      if (p.product_variations.some(v => v.sku?.toLowerCase().includes(q))) return true
      // Coincide algún atributo
      if (p.product_variations.some(v => formatAttributes(v.attributes).toLowerCase().includes(q))) return true
      return false
    })
  }, [products, search])

  // Pagination
  const totalPages = Math.ceil(filteredProducts.length / ITEMS_PER_PAGE) || 1
  const paginatedProducts = useMemo(() => {
    const start = (currentPage - 1) * ITEMS_PER_PAGE
    return filteredProducts.slice(start, start + ITEMS_PER_PAGE)
  }, [filteredProducts, currentPage])

  // Reset page to 1 when search changes
  useEffect(() => {
    setCurrentPage(1)
  }, [search])

  return (
    <div className="space-y-5 max-w-7xl">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Boxes className="h-5 w-5 text-primary" /> Inventario
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {products.length} productos activos · {allVariations.length} variantes
          </p>
        </div>
        <div className="relative w-full md:w-80">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Buscar por nombre, SKU o atributo..."
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
      </div>

      {/* AI Insight */}
      {(role === 'owner' || role === 'manager') && (
        <AiInsightPanel module="inventory" label="Inventario" />
      )}

      {/* KPIs - Mobile optimized grid */}
      <div className="grid grid-cols-1 xs:grid-cols-3 gap-3 sm:gap-4">
        <div className="rounded-xl border border-border bg-card p-4 sm:p-5 xs:col-span-3 sm:col-span-1">
          <p className="text-[10px] sm:text-xs text-muted-foreground uppercase tracking-wide">Total stock</p>
          <p className="text-2xl sm:text-3xl font-bold text-primary mt-1">{totalUnits}</p>
          <p className="text-xs text-muted-foreground mt-1">{allVariations.length} variantes</p>
        </div>
        <div className={`rounded-xl border bg-card p-4 sm:p-5 xs:col-span-1.5 sm:col-span-1 ${lowStockCount > 0 ? 'border-yellow-500/30 bg-yellow-500/5' : 'border-border'}`}>
          <div className="flex items-center gap-1.5 mb-1">
            {lowStockCount > 0 && <AlertTriangle className="h-3.5 w-3.5 text-yellow-400" />}
            <p className="text-[10px] sm:text-xs text-muted-foreground uppercase tracking-wide truncate">Stock bajo</p>
          </div>
          <p className={`text-2xl sm:text-3xl font-bold mt-1 ${lowStockCount > 0 ? 'text-yellow-400' : 'text-primary'}`}>
            {lowStockCount}
          </p>
          <p className="text-[10px] sm:text-xs text-muted-foreground mt-1">≤ {threshold} unid.</p>
        </div>
        <div className={`rounded-xl border bg-card p-4 sm:p-5 xs:col-span-1.5 sm:col-span-1 ${zeroStockCount > 0 ? 'border-red-500/30 bg-red-500/5' : 'border-border'}`}>
          <p className="text-[10px] sm:text-xs text-muted-foreground uppercase tracking-wide truncate">Sin stock</p>
          <p className={`text-2xl sm:text-3xl font-bold mt-1 ${zeroStockCount > 0 ? 'text-red-400' : 'text-primary'}`}>
            {zeroStockCount}
          </p>
          <p className="text-[10px] sm:text-xs text-muted-foreground mt-1">en cero</p>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-5 items-start">
        {/* Lista de productos */}
        <div className="lg:col-span-2 space-y-4">
          {paginatedProducts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 rounded-xl border-2 border-dashed border-border/50 bg-muted/5 text-center">
              <Package className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground text-sm">
                {search ? 'No se encontraron resultados para tu búsqueda.' : 'No hay productos activos en inventario.'}
              </p>
              {search && (
                <Button variant="link" onClick={() => setSearch('')} className="mt-2 text-xs">Limpiar filtros</Button>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              {paginatedProducts.map(product => (
                <div key={product.id} className="rounded-xl border border-border bg-card overflow-hidden shadow-sm">
                  <div className="px-4 py-3 border-b border-border bg-muted/20">
                    <p className="font-semibold text-sm line-clamp-1">{product.title}</p>
                  </div>
                  <div className="p-3 space-y-3">
                    {product.product_variations.map(variation => {
                      const isLow  = variation.stock_quantity > 0 && variation.stock_quantity <= threshold
                      const isZero = variation.stock_quantity === 0
                      return (
                        <div key={variation.id} className={`rounded-lg border p-3 ${isZero ? 'border-red-500/30 bg-red-500/5' : isLow ? 'border-yellow-500/30 bg-yellow-500/5' : 'border-border/60 bg-background'}`}>
                          <div className="flex justify-between items-start gap-2">
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-foreground">{formatAttributes(variation.attributes)}</p>
                              {variation.sku && <p className="text-[10px] font-mono text-muted-foreground mt-0.5">{variation.sku}</p>}
                              <p className="text-[11px] text-muted-foreground mt-1 font-medium">${variation.price.toLocaleString('es-CO')} c/u</p>
                            </div>
                            <div className="text-right flex-shrink-0">
                              <p className={`text-2xl font-bold tracking-tight ${isZero ? 'text-red-400' : isLow ? 'text-yellow-400' : 'text-primary'}`}>
                                {variation.stock_quantity}
                              </p>
                              <p className="text-[10px] font-semibold mt-0.5">
                                {isZero ? <span className="text-red-400">❌ CERO</span>
                                  : isLow ? <span className="text-yellow-500">⚠️ BAJO</span>
                                  : <span className="text-emerald-500">✓ OK</span>}
                              </p>
                            </div>
                          </div>

                          {canWrite && (
                            <AdjustForm variationId={variation.id} productId={product.id} adjustStockAction={adjustStockAction} />
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}

              {/* Pagination controls */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between py-2 px-1 text-sm text-muted-foreground">
                  <span>Mostrando {(currentPage - 1) * ITEMS_PER_PAGE + 1} - {Math.min(currentPage * ITEMS_PER_PAGE, filteredProducts.length)} de {filteredProducts.length}</span>
                  <div className="flex items-center gap-1">
                    <Button variant="outline" size="sm" className="w-8 h-8 p-0" disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}>
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="text-xs font-medium w-8 text-center">{currentPage}</span>
                    <Button variant="outline" size="sm" className="w-8 h-8 p-0" disabled={currentPage === totalPages} onClick={() => setCurrentPage(p => p + 1)}>
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Panel lateral */}
        <div className="space-y-4">
          {/* Umbral configurable */}
          {canWrite && (
            <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
              <p className="font-semibold text-sm mb-3 text-foreground">⚙️ Umbral de alerta</p>
              <form action={saveThresholdAction} className="flex gap-2 items-end">
                <div className="flex-1 space-y-1.5">
                  <Label className="text-[11px] text-muted-foreground uppercase">Unidades mínimas</Label>
                  <Input name="threshold" type="number" min="0" defaultValue={threshold} className="h-8 text-sm bg-background font-mono" required />
                </div>
                <SaveThresholdButton />
              </form>
              <p className="text-[11px] text-muted-foreground leading-snug mt-3">
                Si quedan {threshold} unidades o menos, se alertará de &quot;stock bajo&quot;.
              </p>
            </div>
          )}

          {/* Historial de movimientos */}
          <div className="rounded-xl border border-border bg-card p-4 shadow-sm flex flex-col h-[500px]">
            <p className="font-semibold text-sm mb-3 flex-shrink-0 text-foreground">📋 Últimos movimientos</p>
            {movements.length === 0 ? (
              <p className="text-sm text-muted-foreground flex-1 flex items-center justify-center border-t border-border/40 mt-1">Sin historial reciente.</p>
            ) : (
              <div className="space-y-3 overflow-y-auto pr-1 flex-1 border-t border-border/40 pt-3">
                {movements.map(m => (
                  <div key={m.id} className="text-xs pb-3 border-b border-border/40 last:border-0 last:pb-0">
                    <div className="flex justify-between items-center mb-1">
                      <span className={`font-bold px-1.5 py-0.5 rounded-sm ${m.delta > 0 ? 'text-emerald-500 bg-emerald-500/10' : 'text-red-500 bg-red-500/10'}`}>
                        {m.delta > 0 ? `+${m.delta}` : m.delta} u.
                      </span>
                      <span className="text-muted-foreground font-mono bg-muted/40 px-1.5 py-0.5 rounded-sm">→ {m.new_stock} u.</span>
                    </div>
                    <p className="text-foreground leading-tight">{m.reason ?? 'Ajuste manual'}</p>
                    <p className="text-muted-foreground/60 text-[10px] mt-1 line-clamp-1">
                      {new Date(m.created_at).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}
