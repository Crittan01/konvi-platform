'use client'

import { useState, useMemo } from 'react'
import Image from 'next/image'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Search, LayoutGrid, List as ListIcon,
  ChevronRight, ChevronDown, ImageOff, Tag, Package, Edit3, X,
} from 'lucide-react'

// ── Types ────────────────────────────────────────────────────────────────────

type Variation = {
  id: string
  price: number
  stock_quantity: number
  attributes: Record<string, string> | null
  sku: string | null
}

type Product = {
  id: string
  title: string
  description: string | null
  cover_image_url: string | null
  platform_category_id: string | null
  product_variations: Variation[]
}

type Props = {
  products: Product[]
  catMap: Record<string, string>
  canWrite: boolean
  editProductAction: (fd: FormData) => Promise<void>
  editVariationAction: (fd: FormData) => Promise<void>
  addVariationAction: (fd: FormData) => Promise<void>
  deactivateProductAction: (fd: FormData) => Promise<void>
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtAttrs(attrs: Record<string, string> | null): string {
  if (!attrs || Object.keys(attrs).length === 0) return 'Estándar'
  return Object.entries(attrs).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

function fmtPrice(vars: Variation[]): string {
  if (!vars.length) return '—'
  const prices = vars.map(v => v.price)
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  const locale = (n: number) => n.toLocaleString('es-MX', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
  return min === max ? `$${locale(min)}` : `$${locale(min)} – $${locale(max)}`
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function CatalogTable({
  products, catMap, canWrite,
  editProductAction, editVariationAction, addVariationAction, deactivateProductAction,
}: Props) {
  const [search, setSearch]           = useState('')
  const [viewMode, setViewMode]       = useState<'list' | 'grid'>('list')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [editingId, setEditingId]     = useState<string | null>(null)

  const toggle = (id: string) =>
    setExpandedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim()
    if (!q) return products
    return products.filter(p =>
      p.title.toLowerCase().includes(q) ||
      p.description?.toLowerCase().includes(q) ||
      p.product_variations.some(v => v.sku?.toLowerCase().includes(q))
    )
  }, [products, search])

  // ── Empty State ─────────────────────────────────────────────────────────────
  if (products.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[420px] rounded-2xl border-2 border-dashed border-border/50 bg-muted/5 text-center px-10 py-16 gap-5">
        <div className="w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center shadow-inner">
          <Package className="h-10 w-10 text-primary/50" />
        </div>
        <div className="space-y-2">
          <p className="text-lg font-semibold text-foreground">Tu catálogo está listo para crecer</p>
          <p className="text-sm text-muted-foreground max-w-sm mx-auto leading-relaxed">
            {canWrite
              ? 'Crea tu primer producto con el formulario, o carga una lista completa desde Excel en segundos.'
              : 'Aún no hay productos activos en este catálogo.'}
          </p>
        </div>
        {canWrite && (
          <div className="flex flex-col sm:flex-row gap-2.5 text-xs text-muted-foreground mt-1">
            {['Agrega manualmente', 'Importa desde Excel'].map((label, i) => (
              <span key={i} className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border border-border shadow-sm">
                <span className="w-5 h-5 rounded-full bg-primary text-white font-bold flex items-center justify-center text-[10px]">{i + 1}</span>
                {label}
              </span>
            ))}
          </div>
        )}
      </div>
    )
  }

  // ── Toolbar ─────────────────────────────────────────────────────────────────
  const toolbar = (
    <div className="flex items-center gap-3">
      <div className="relative flex-1">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
        <Input
          placeholder="Buscar producto o SKU…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="pl-9 h-9 text-sm bg-card"
        />
        {search && (
          <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* View toggle */}
      <div className="flex items-center gap-0.5 p-1 rounded-lg border border-border bg-muted/30">
        {(['list', 'grid'] as const).map(mode => (
          <button
            key={mode}
            onClick={() => setViewMode(mode)}
            title={mode === 'list' ? 'Vista Lista' : 'Vista Cuadrícula'}
            className={`p-1.5 rounded-md transition-colors ${
              viewMode === mode
                ? 'bg-background shadow-sm text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {mode === 'list' ? <ListIcon className="h-4 w-4" /> : <LayoutGrid className="h-4 w-4" />}
          </button>
        ))}
      </div>

      <span className="text-xs text-muted-foreground whitespace-nowrap hidden sm:inline">
        {filtered.length} producto{filtered.length !== 1 ? 's' : ''}
      </span>
    </div>
  )

  // ── List View ────────────────────────────────────────────────────────────────
  if (viewMode === 'list') {
    return (
      <div className="space-y-3">
        {toolbar}
        <div className="rounded-xl border border-border overflow-hidden bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40">
                <th className="w-14 px-3 py-3" />
                <th className="text-left px-3 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Producto</th>
                <th className="hidden md:table-cell text-left px-3 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Categoría</th>
                <th className="text-right px-3 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Precio</th>
                <th className="hidden sm:table-cell text-right px-3 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Stock</th>
                <th className="w-8 px-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {filtered.map(p => {
                const vars        = p.product_variations ?? []
                const totalStock  = vars.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)
                const hasZero     = vars.some(v => v.stock_quantity === 0)
                const isExpanded  = expandedIds.has(p.id)
                const isEditing   = editingId === p.id
                const catName     = p.platform_category_id ? catMap[p.platform_category_id] : null

                return [
                  // ── Product Row ──────────────────────────────────────────
                  <tr
                    key={p.id}
                    className="cursor-pointer hover:bg-muted/30 transition-colors"
                    onClick={() => toggle(p.id)}
                  >
                    <td className="px-3 py-3">
                      <div className="relative w-10 h-10 rounded-lg overflow-hidden bg-muted border border-border flex-shrink-0">
                        {p.cover_image_url ? (
                          <Image src={p.cover_image_url} alt={p.title} fill className="object-cover" sizes="40px" />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center">
                            <ImageOff className="h-3.5 w-3.5 text-muted-foreground/40" />
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <p className="font-semibold leading-tight line-clamp-1">{p.title}</p>
                      {p.description && (
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">{p.description}</p>
                      )}
                      <p className="text-xs text-muted-foreground/70 mt-0.5">{vars.length} variante{vars.length !== 1 ? 's' : ''}</p>
                    </td>
                    <td className="hidden md:table-cell px-3 py-3">
                      {catName && (
                        <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 font-medium">
                          <Tag className="h-2.5 w-2.5" />
                          {catName}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <span className="font-bold text-primary tabular-nums">{fmtPrice(vars)}</span>
                    </td>
                    <td className="hidden sm:table-cell px-3 py-3 text-right">
                      <span className={`text-sm font-semibold tabular-nums ${
                        hasZero ? 'text-destructive' : totalStock <= 5 ? 'text-amber-500' : 'text-muted-foreground'
                      }`}>{totalStock} u.</span>
                    </td>
                    <td className="px-2 py-3 text-muted-foreground">
                      {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </td>
                  </tr>,

                  // ── Expanded Panel ───────────────────────────────────────
                  isExpanded && (
                    <tr key={`${p.id}-exp`}>
                      <td colSpan={6} className="bg-muted/10" onClick={e => e.stopPropagation()}>
                        <div className="px-5 py-4 space-y-4 border-t border-border/30">

                          {/* Variants table */}
                          <div className="space-y-2">
                            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                              Variantes — Editar precio y stock
                            </p>
                            <div className="rounded-lg border border-border overflow-hidden">
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="border-b border-border bg-muted/30">
                                    <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Variante / SKU</th>
                                    <th className="text-center px-2 py-2 font-semibold text-muted-foreground w-32">Precio ($)</th>
                                    <th className="text-center px-2 py-2 font-semibold text-muted-foreground w-24">Stock (u.)</th>
                                    <th className="w-20 px-2" />
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-border/20">
                                  {vars.map(v => (
                                    <tr key={v.id} className="bg-background hover:bg-muted/10 transition-colors">
                                      <td className="px-3 py-2">
                                        <span className="font-medium">{fmtAttrs(v.attributes)}</span>
                                        {v.sku && (
                                          <span className="ml-2 font-mono text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                            {v.sku}
                                          </span>
                                        )}
                                      </td>
                                      <td className="px-2 py-1.5 text-center">
                                        <form
                                          action={editVariationAction}
                                          key={`${v.id}-${v.price}-${v.stock_quantity}`}
                                          className="flex items-center justify-center gap-1.5"
                                        >
                                          <input type="hidden" name="variation_id" value={v.id} />
                                          <Input name="price" type="number" step="0.01" min="0.01"
                                            defaultValue={v.price}
                                            className="h-7 text-xs w-24 text-center"
                                            required
                                          />
                                          {/* Stock hidden — will be the second form's real value */}
                                        </form>
                                      </td>
                                      <td className="px-2 py-1.5 text-center">
                                        <Input name="stock_display" type="number" min="0"
                                          readOnly
                                          tabIndex={-1}
                                          value={v.stock_quantity}
                                          className={`h-7 text-xs w-16 text-center pointer-events-none opacity-70 ${
                                            v.stock_quantity === 0 ? 'border-destructive/50 text-destructive' : ''
                                          }`}
                                        />
                                      </td>
                                      <td className="px-2 py-1.5">
                                        {/* One proper form per variant with BOTH fields */}
                                        <form action={editVariationAction} key={`save-${v.id}`} className="flex items-center gap-1">
                                          <input type="hidden" name="variation_id" value={v.id} />
                                          <input type="hidden" name="price" value={v.price} />
                                          <input type="hidden" name="stock" value={v.stock_quantity} />
                                          <Button type="submit" size="sm" variant="secondary" className="h-7 text-xs px-3">
                                            Guardar
                                          </Button>
                                        </form>
                                      </td>
                                    </tr>
                                  ))}
                                  {canWrite && (
                                    <tr className="bg-muted/5">
                                      <td colSpan={4} className="px-3 py-2">
                                        <form action={addVariationAction} className="flex items-center gap-2">
                                          <input type="hidden" name="product_id" value={p.id} />
                                          <div className="flex-1 flex gap-2">
                                            <Input name="attr_key" placeholder="Atr. (ej: Tamaño)" className="h-7 text-xs flex-1" required />
                                            <Input name="attr_val" placeholder="Valor (ej: 50ml)" className="h-7 text-xs flex-1" required />
                                            <Input name="sku" placeholder="SKU (opcional)" className="h-7 text-xs w-24" />
                                          </div>
                                          <Input name="price" type="number" step="0.01" min="0.01" placeholder="Precio ($)" className="h-7 text-xs w-24 text-center" required />
                                          <Input name="stock" type="number" min="0" placeholder="Stock (u.)" className="h-7 text-xs w-16 text-center" required />
                                          <Button type="submit" size="sm" variant="outline" className="h-7 text-xs px-3">Añadir</Button>
                                        </form>
                                      </td>
                                    </tr>
                                  )}
                                </tbody>
                              </table>
                            </div>
                          </div>

                          {/* Edit name/desc */}
                          {canWrite && (
                            <div className="border-t border-border/30 pt-3">
                              {!isEditing ? (
                                <button
                                  onClick={() => setEditingId(p.id)}
                                  className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary transition-colors"
                                >
                                  <Edit3 className="h-3.5 w-3.5" />
                                  Editar nombre / descripción
                                </button>
                              ) : (
                                <form action={editProductAction} className="space-y-3">
                                  <input type="hidden" name="product_id" value={p.id} />
                                  <div className="grid sm:grid-cols-2 gap-3">
                                    <div className="space-y-1">
                                      <Label className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Nombre</Label>
                                      <Input name="title" defaultValue={p.title} required className="h-8 text-sm" />
                                    </div>
                                    <div className="space-y-1">
                                      <Label className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Descripción</Label>
                                      <Input name="description" defaultValue={p.description ?? ''} className="h-8 text-sm" placeholder="Descripción…" />
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <Button type="submit" size="sm" variant="secondary" className="h-7 text-xs">
                                      Guardar cambios
                                    </Button>
                                    <button
                                      type="button"
                                      onClick={() => setEditingId(null)}
                                      className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                                    >
                                      Cancelar
                                    </button>
                                  </div>
                                </form>
                              )}
                            </div>
                          )}

                          {/* Archive */}
                          {canWrite && (
                            <form action={deactivateProductAction}>
                              <input type="hidden" name="product_id" value={p.id} />
                              <Button
                                type="submit"
                                size="sm"
                                variant="ghost"
                                className="h-7 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/5 border border-transparent hover:border-destructive/20 transition-all"
                              >
                                Archivar producto
                              </Button>
                            </form>
                          )}
                        </div>
                      </td>
                    </tr>
                  ),
                ]
              })}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="text-center py-10 text-muted-foreground text-sm">
              No hay productos que coincidan con &quot;<span className="font-medium text-foreground">{search}</span>&quot;
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── Grid View ────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-3">
      {toolbar}
      {filtered.length === 0 ? (
        <div className="text-center py-10 text-muted-foreground text-sm">
          No hay productos que coincidan con &quot;<span className="font-medium text-foreground">{search}</span>&quot;
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(p => {
            const vars        = p.product_variations ?? []
            const totalStock  = vars.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)
            const hasZero     = vars.some(v => v.stock_quantity === 0)
            const hasLow      = !hasZero && totalStock <= 5
            const isExpanded  = expandedIds.has(p.id)
            const catName     = p.platform_category_id ? catMap[p.platform_category_id] : null

            return (
              <div
                key={p.id}
                className={`group flex flex-col rounded-2xl border bg-card overflow-hidden shadow-sm transition-all hover:shadow-md ${
                  hasZero ? 'border-destructive/30' : hasLow ? 'border-amber-500/30' : 'border-border'
                }`}
              >
                {/* Photo */}
                <div
                  className="relative w-full h-44 bg-muted/40 flex-shrink-0 overflow-hidden cursor-pointer"
                  onClick={() => toggle(p.id)}
                >
                  {p.cover_image_url ? (
                    <Image
                      src={p.cover_image_url}
                      alt={p.title}
                      fill
                      className="object-cover transition-transform duration-300 group-hover:scale-105"
                      sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
                    />
                  ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-muted-foreground/25">
                      <ImageOff className="h-9 w-9" />
                      <span className="text-[10px] uppercase tracking-wider font-medium">Sin imagen</span>
                    </div>
                  )}

                  {/* Hover overlay */}
                  <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                    <span className="bg-white/90 text-black px-3 py-1.5 rounded-full font-medium text-xs flex items-center gap-1.5">
                      {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      {isExpanded ? 'Cerrar variantes' : `Gestionar ${vars.length} variante${vars.length !== 1 ? 's' : ''}`}
                    </span>
                  </div>

                  {/* Badges */}
                  <div className="absolute top-2.5 right-2.5 flex flex-col gap-1 items-end">
                    {hasZero && (
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-destructive/90 text-white shadow-sm">
                        Sin stock
                      </span>
                    )}
                    {hasLow && !hasZero && (
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/90 text-white shadow-sm">
                        Stock bajo
                      </span>
                    )}
                  </div>
                  {catName && (
                    <div className="absolute bottom-2.5 left-2.5">
                      <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-black/60 text-white backdrop-blur-sm">
                        {catName}
                      </span>
                    </div>
                  )}
                </div>

                {/* Body */}
                <div className="flex flex-col flex-1 p-4 gap-3">
                  <div>
                    <h3 className="font-semibold text-sm line-clamp-1 leading-tight">{p.title}</h3>
                    {p.description && (
                      <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2 leading-relaxed">{p.description}</p>
                    )}
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-lg font-bold text-primary tabular-nums">{fmtPrice(vars)}</span>
                    <span className="text-xs text-muted-foreground">
                      {totalStock} u. · {vars.length} var{vars.length !== 1 ? 's' : ''}
                    </span>
                  </div>

                  {/* Expanded variants */}
                  {isExpanded ? (
                    <div className="space-y-2 pt-2 border-t border-border/40" onClick={e => e.stopPropagation()}>
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Variantes</p>
                      {vars.map(v => (
                        <form
                          key={v.id}
                          action={editVariationAction}
                          className="flex items-center gap-1.5 bg-muted/30 rounded-lg px-2.5 py-1.5 hover:bg-muted/50 transition-colors"
                        >
                          <input type="hidden" name="variation_id" value={v.id} />
                          <span className="text-xs flex-1 truncate font-medium">{fmtAttrs(v.attributes)}</span>
                          <span className="text-[10px] text-muted-foreground">$</span>
                          <Input name="price" type="number" step="0.01" defaultValue={v.price}
                            className="h-6 text-[11px] w-16 text-center px-1" required />
                          <Input name="stock" type="number" defaultValue={v.stock_quantity}
                            className={`h-6 text-[11px] w-12 text-center px-1 ${v.stock_quantity === 0 ? 'border-destructive/50' : ''}`} />
                          <Button type="submit" size="sm" className="h-6 text-[10px] px-2 shrink-0">✓</Button>
                        </form>
                      ))}
                      {canWrite && (
                        <form action={addVariationAction} className="flex flex-col gap-1.5 pt-1 mt-1 border-t border-border/40">
                          <input type="hidden" name="product_id" value={p.id} />
                          <div className="flex items-center gap-1.5">
                            <Input name="attr_key" placeholder="Atr. (ej: Tam)" className="h-6 text-[10px] flex-1 px-1.5" required />
                            <Input name="attr_val" placeholder="Val (ej: 50ml)" className="h-6 text-[10px] flex-1 px-1.5" required />
                          </div>
                          <div className="flex items-center gap-1.5">
                            <Input name="sku" placeholder="SKU (opc)" className="h-6 text-[10px] flex-1 px-1.5" />
                            <Input name="price" type="number" step="0.01" min="0.01" placeholder="Precio" className="h-6 text-[10px] w-14 text-center px-1" required />
                            <Input name="stock" type="number" min="0" placeholder="Stock" className="h-6 text-[10px] w-14 text-center px-1" required />
                            <Button type="submit" size="sm" variant="secondary" className="h-6 text-[10px] px-2 shrink-0">+</Button>
                          </div>
                        </form>
                      )}
                      {canWrite && (
                        <form action={deactivateProductAction} className="pt-1">
                          <input type="hidden" name="product_id" value={p.id} />
                          <Button type="submit" size="sm" variant="ghost"
                            className="w-full h-7 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/5">
                            Archivar producto
                          </Button>
                        </form>
                      )}
                    </div>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full h-8 text-xs mt-auto"
                      onClick={() => toggle(p.id)}
                    >
                      Gestionar variantes ({vars.length})
                    </Button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
