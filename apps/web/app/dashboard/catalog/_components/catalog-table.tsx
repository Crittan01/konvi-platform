'use client'

import { useState, useMemo, useCallback, memo } from 'react'
import Image from 'next/image'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Search, LayoutGrid, List as ListIcon,
  ChevronRight, ChevronDown, ImageOff, Tag, Package, Edit3, X, Plus, Archive, RotateCcw,
} from 'lucide-react'
import type { Product, Variation } from '../types'

// ── Types ────────────────────────────────────────────────────────────────────

type Props = {
  products: Product[]
  archivedProducts: Product[]
  catMap: Record<string, string>
  canWrite: boolean
  editProductAction: (fd: FormData) => Promise<void>
  editVariationAction: (fd: FormData) => Promise<void>
  addVariationAction: (fd: FormData) => Promise<void>
  deactivateProductAction: (fd: FormData) => Promise<void>
  restoreProductAction: (fd: FormData) => Promise<void>
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
  const locale = (n: number) => n.toLocaleString('es-CO', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
  return min === max ? `$${locale(min)}` : `$${locale(min)} – $${locale(max)}`
}

// ── VariantRow — memoizado para evitar re-renders en edición inline ──────────

const VariantRow = memo(function VariantRow({
  v, canWrite, editVariationAction
}: { v: Variation; canWrite: boolean; editVariationAction: (fd: FormData) => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  return (
    <>
      {/* Desktop table row */}
      <tr className="hidden sm:table-row bg-background hover:bg-muted/10 transition-colors">
        <td className="px-3 py-2">
          <span className="font-medium">{fmtAttrs(v.attributes)}</span>
          {v.sku && <span className="ml-2 text-[10px] font-mono text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{v.sku}</span>}
        </td>
        <td className="px-2 py-2 text-center">
          {editing ? (
            <form action={editVariationAction} onSubmit={() => setEditing(false)} className="flex gap-1 justify-center">
              <input type="hidden" name="variation_id" value={v.id} />
              <input type="hidden" name="stock" value={v.stock_quantity} />
              <Input name="price" type="number" defaultValue={v.price} step="1" min="1" className="h-7 w-24 text-xs text-center font-mono" autoFocus />
              <Button type="submit" size="sm" className="h-7 px-2 text-xs">✓</Button>
              <button type="button" onClick={() => setEditing(false)} className="text-muted-foreground hover:text-foreground px-1"><X className="h-3 w-3" /></button>
            </form>
          ) : (
            <button onClick={() => canWrite && setEditing(true)} className={`font-mono font-semibold text-primary tabular-nums ${canWrite ? 'hover:opacity-70 cursor-pointer' : 'cursor-default'}`}>
              {v.price.toLocaleString('es-CO', { minimumFractionDigits: 0 })}
              {v.compare_at_price && (
                <span className="ml-1 text-[10px] text-muted-foreground line-through">{v.compare_at_price.toLocaleString('es-CO', { minimumFractionDigits: 0 })}</span>
              )}
            </button>
          )}
        </td>
        <td className="px-2 py-2 text-center">
          {editing ? (
            <form action={editVariationAction} onSubmit={() => setEditing(false)} className="flex gap-1 justify-center">
              <input type="hidden" name="variation_id" value={v.id} />
              <input type="hidden" name="price" value={v.price} />
              <Input name="stock" type="number" defaultValue={v.stock_quantity} min="0" className="h-7 w-20 text-xs text-center font-mono" />
              <Button type="submit" size="sm" className="h-7 px-2 text-xs">✓</Button>
            </form>
          ) : (
            <button onClick={() => canWrite && setEditing(true)} className={`font-mono tabular-nums ${v.stock_quantity === 0 ? 'text-destructive font-bold' : v.stock_quantity <= 5 ? 'text-amber-500 font-semibold' : 'text-muted-foreground'} ${canWrite ? 'hover:opacity-70 cursor-pointer' : 'cursor-default'}`}>
              {v.stock_quantity} u.
            </button>
          )}
        </td>
        <td className="px-2 py-2 text-right">
          {canWrite && (
            <button onClick={() => setEditing(!editing)} className="text-muted-foreground hover:text-primary transition-colors p-1 rounded">
              <Edit3 className="h-3 w-3" />
            </button>
          )}
        </td>
      </tr>

      {/* Mobile card row */}
      <div className="sm:hidden flex items-center justify-between py-2 px-3 border-b border-border/20 last:border-0">
        <div>
          <p className="text-xs font-medium">{fmtAttrs(v.attributes)}</p>
          {v.sku && <p className="text-[10px] font-mono text-muted-foreground mt-0.5">{v.sku}</p>}
        </div>
        <div className="text-right flex items-center gap-3">
          <div>
            <p className="text-xs font-bold text-primary tabular-nums">${v.price.toLocaleString('es-CO', { minimumFractionDigits: 0 })}</p>
            <p className={`text-[10px] tabular-nums ${v.stock_quantity === 0 ? 'text-destructive' : v.stock_quantity <= 5 ? 'text-amber-500' : 'text-muted-foreground'}`}>
              {v.stock_quantity} u.
            </p>
          </div>
          {canWrite && (
            <button onClick={() => setEditing(!editing)} className="text-muted-foreground hover:text-primary transition-colors">
              <Edit3 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {editing && (
          <div className="w-full mt-2 p-3 bg-muted/20 rounded-lg border border-border/40">
            <form action={editVariationAction} onSubmit={() => setEditing(false)} className="grid grid-cols-2 gap-2">
              <input type="hidden" name="variation_id" value={v.id} />
              <div>
                <label className="text-[10px] text-muted-foreground uppercase font-semibold">Precio</label>
                <Input name="price" type="number" defaultValue={v.price} step="1" min="1" className="h-8 text-xs font-mono mt-1" />
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground uppercase font-semibold">Stock</label>
                <Input name="stock" type="number" defaultValue={v.stock_quantity} min="0" className="h-8 text-xs font-mono mt-1" />
              </div>
              <div className="col-span-2 flex gap-2 justify-end mt-1">
                <Button type="submit" size="sm" className="h-7 text-xs">Guardar</Button>
                <button type="button" onClick={() => setEditing(false)} className="text-xs text-muted-foreground hover:text-foreground px-3">Cancelar</button>
              </div>
            </form>
          </div>
        )}
      </div>
    </>
  )
})

// ── ExpandedPanel — memoizado ─────────────────────────────────────────────────

const ExpandedPanel = memo(function ExpandedPanel({
  p, canWrite, editProductAction, editVariationAction, addVariationAction, deactivateProductAction
}: {
  p: Product; canWrite: boolean;
  editProductAction: (fd: FormData) => Promise<void>
  editVariationAction: (fd: FormData) => Promise<void>
  addVariationAction: (fd: FormData) => Promise<void>
  deactivateProductAction: (fd: FormData) => Promise<void>
}) {
  const [editingProduct, setEditingProduct] = useState(false)
  const [showAddVar, setShowAddVar] = useState(false)
  const vars = p.product_variations ?? []

  return (
    <div className="px-3 sm:px-5 py-4 space-y-4 border-t border-border/30">

      {/* Variants list */}
      <div className="space-y-2">
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
          Variantes — Editar precio y stock
        </p>

        {/* Desktop: nested table */}
        <div className="rounded-lg border border-border overflow-hidden hidden sm:block">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/30">
                <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Variante / SKU</th>
                <th className="text-center px-2 py-2 font-semibold text-muted-foreground w-32">Precio Normal ($)</th>
                <th className="text-center px-2 py-2 font-semibold text-muted-foreground w-24">Stock (u.)</th>
                <th className="w-12 px-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border/20">
              {vars.map(v => (
                <VariantRow key={v.id} v={v} canWrite={canWrite} editVariationAction={editVariationAction} />
              ))}
            </tbody>
          </table>
        </div>

        {/* Mobile: stacked cards */}
        <div className="sm:hidden rounded-lg border border-border overflow-hidden divide-y divide-border/20 bg-background">
          {vars.map(v => (
            <VariantRow key={v.id} v={v} canWrite={canWrite} editVariationAction={editVariationAction} />
          ))}
        </div>
      </div>

      {/* Add variant form */}
      {canWrite && (
        <div className="space-y-2">
          {!showAddVar ? (
            <button
              onClick={() => setShowAddVar(true)}
              className="flex items-center gap-1.5 text-xs text-primary hover:underline font-medium"
            >
              <Plus className="h-3.5 w-3.5" /> Agregar variante
            </button>
          ) : (
            <form action={addVariationAction} onSubmit={() => setShowAddVar(false)} className="p-3 bg-muted/20 rounded-lg border border-border/40 space-y-3">
              <input type="hidden" name="product_id" value={p.id} />
              <p className="text-[11px] font-semibold text-muted-foreground uppercase">Nueva Variante</p>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Tipo</label>
                  <Input name="attr_key" placeholder="Propiedad (Ej: Color)" className="h-8 text-xs" />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Valor</label>
                  <Input name="attr_val" placeholder="Ej: L" className="h-8 text-xs" />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">SKU</label>
                  <Input name="sku" placeholder="PROD-001" className="h-8 text-xs font-mono" />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Precio *</label>
                  <Input name="price" type="number" min="1" step="1" placeholder="0" className="h-8 text-xs font-mono" required />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Stock *</label>
                  <Input name="stock" type="number" min="0" defaultValue={0} className="h-8 text-xs font-mono" required />
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <Button type="submit" size="sm" className="h-7 text-xs">Guardar Variante</Button>
                <button type="button" onClick={() => setShowAddVar(false)} className="text-xs text-muted-foreground hover:text-foreground px-3">Cancelar</button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* Edit product info */}
      {canWrite && (
        <div className="pt-2 border-t border-border/20 space-y-2">
          {!editingProduct ? (
            <button
              onClick={() => setEditingProduct(true)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary font-medium transition-colors"
            >
              <Edit3 className="h-3 w-3" /> Editar nombre / descripción
            </button>
          ) : (
            <form action={editProductAction} onSubmit={() => setEditingProduct(false)} className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-3 bg-muted/20 rounded-lg border border-border/40">
              <input type="hidden" name="product_id" value={p.id} />
              <div className="space-y-1">
                <label className="text-[10px] font-semibold text-muted-foreground uppercase">Nombre</label>
                <Input name="title" defaultValue={p.title} className="h-8 text-xs" />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] font-semibold text-muted-foreground uppercase">Descripción</label>
                <Input name="description" defaultValue={p.description ?? ''} className="h-8 text-xs" />
              </div>
              <div className="col-span-1 sm:col-span-2 flex gap-2 justify-end">
                <Button type="submit" size="sm" className="h-7 text-xs">Guardar</Button>
                <button type="button" onClick={() => setEditingProduct(false)} className="text-xs text-muted-foreground hover:text-foreground px-3">Cancelar</button>
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
  )
})

// ── ProductMobileCard — tarjeta para vista móvil en lista ─────────────────────

const ProductMobileCard = memo(function ProductMobileCard({
  p, catName, isExpanded, onToggle, canWrite,
  editProductAction, editVariationAction, addVariationAction, deactivateProductAction
}: {
  p: Product; catName: string | null; isExpanded: boolean; onToggle: () => void; canWrite: boolean;
  editProductAction: (fd: FormData) => Promise<void>
  editVariationAction: (fd: FormData) => Promise<void>
  addVariationAction: (fd: FormData) => Promise<void>
  deactivateProductAction: (fd: FormData) => Promise<void>
}) {
  const vars = p.product_variations ?? []
  const totalStock = vars.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)
  const hasZero = vars.some(v => v.stock_quantity === 0)

  return (
    <div className={`rounded-xl border ${isExpanded ? 'border-primary/30 bg-primary/5' : 'border-border bg-card'} overflow-hidden transition-colors`}>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 p-3 text-left hover:bg-muted/20 transition-colors"
      >
        {/* thumbnail */}
        <div className="relative w-12 h-12 rounded-lg overflow-hidden bg-muted border border-border flex-shrink-0">
          {p.cover_image_url ? (
            <Image src={p.cover_image_url} alt={p.title} fill className="object-cover" sizes="48px" />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <ImageOff className="h-4 w-4 text-muted-foreground/40" />
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <p className="font-semibold text-sm leading-tight truncate">{p.title}</p>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            {catName && (
              <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 font-medium">
                <Tag className="h-2 w-2" />{catName}
              </span>
            )}
            <span className="text-[10px] text-muted-foreground">{vars.length} var.</span>
          </div>
        </div>

        <div className="text-right flex-shrink-0 mr-1">
          <p className="font-bold text-sm text-primary">{fmtPrice(vars)}</p>
          <p className={`text-[10px] tabular-nums ${hasZero ? 'text-destructive' : totalStock <= 5 ? 'text-amber-500' : 'text-muted-foreground'}`}>
            {totalStock} u.
          </p>
        </div>
        {isExpanded ? <ChevronDown className="h-4 w-4 text-muted-foreground flex-shrink-0" /> : <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />}
      </button>

      {isExpanded && (
        <ExpandedPanel
          p={p} canWrite={canWrite}
          editProductAction={editProductAction}
          editVariationAction={editVariationAction}
          addVariationAction={addVariationAction}
          deactivateProductAction={deactivateProductAction}
        />
      )}
    </div>
  )
})

// ── ArchivedSection — muestra productos inactivos con opción de restaurar ────

const ArchivedSection = memo(function ArchivedSection({
  archivedProducts, catMap, restoreProductAction
}: {
  archivedProducts: Product[]
  catMap: Record<string, string>
  restoreProductAction: (fd: FormData) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  if (archivedProducts.length === 0) return null

  return (
    <div className="mt-4 border border-border/40 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-muted/30 hover:bg-muted/50 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <Archive className="h-4 w-4" />
          Archivados ({archivedProducts.length})
        </span>
        {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
      </button>
      {open && (
        <div className="divide-y divide-border/30">
          {archivedProducts.map(p => (
            <div key={p.id} className="flex items-center gap-3 px-4 py-3 bg-muted/10 hover:bg-muted/20 transition-colors">
              <div className="relative w-9 h-9 rounded-lg overflow-hidden bg-muted border border-border flex-shrink-0 opacity-60">
                {p.cover_image_url ? (
                  <Image src={p.cover_image_url} alt={p.title} fill className="object-cover grayscale" sizes="36px" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <ImageOff className="h-3 w-3 text-muted-foreground/40" />
                  </div>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-muted-foreground line-through line-clamp-1">{p.title}</p>
                {p.platform_category_id && catMap[p.platform_category_id] && (
                  <p className="text-[10px] text-muted-foreground/60">{catMap[p.platform_category_id]}</p>
                )}
              </div>
              <form action={restoreProductAction}>
                <input type="hidden" name="product_id" value={p.id} />
                <Button type="submit" size="sm" variant="outline" className="h-7 text-xs gap-1.5 border-primary/30 text-primary hover:bg-primary/10">
                  <RotateCcw className="h-3 w-3" /> Restaurar
                </Button>
              </form>
            </div>
          ))}
        </div>
      )}
    </div>
  )
})

// ── Main Component ────────────────────────────────────────────────────────────

export default function CatalogTable({
  products, archivedProducts, catMap, canWrite,
  editProductAction, editVariationAction, addVariationAction, deactivateProductAction, restoreProductAction,
}: Props) {
  const [search, setSearch]           = useState('')
  const [viewMode, setViewMode]       = useState<'list' | 'grid'>('list')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const toggle = useCallback((id: string) =>
    setExpandedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n }), [])

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
    <div className="flex items-center gap-2 sm:gap-3">
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

        {/* Mobile: stacked cards */}
        <div className="sm:hidden space-y-2">
          {filtered.length === 0 ? (
            <div className="text-center py-10 text-muted-foreground text-sm">
              No hay productos que coincidan con &quot;<span className="font-medium text-foreground">{search}</span>&quot;
            </div>
          ) : filtered.map(p => (
            <ProductMobileCard
              key={p.id}
              p={p}
              catName={p.platform_category_id ? catMap[p.platform_category_id] : null}
              isExpanded={expandedIds.has(p.id)}
              onToggle={() => toggle(p.id)}
              canWrite={canWrite}
              editProductAction={editProductAction}
              editVariationAction={editVariationAction}
              addVariationAction={addVariationAction}
              deactivateProductAction={deactivateProductAction}
            />
          ))}
        </div>

        {/* Desktop: table */}
        <div className="hidden sm:block rounded-xl border border-border overflow-hidden bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40">
                <th className="w-14 px-3 py-3" />
                <th className="text-left px-3 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Producto</th>
                <th className="hidden md:table-cell text-left px-3 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Categoría</th>
                <th className="text-right px-3 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Precio</th>
                <th className="text-right px-3 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Stock</th>
                <th className="w-8 px-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {filtered.map(p => {
                const vars        = p.product_variations ?? []
                const totalStock  = vars.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)
                const hasZero     = vars.some(v => v.stock_quantity === 0)
                const isExpanded  = expandedIds.has(p.id)
                const catName     = p.platform_category_id ? catMap[p.platform_category_id] : null

                return [
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
                    <td className="px-3 py-3 text-right">
                      <span className={`text-sm font-semibold tabular-nums ${
                        hasZero ? 'text-destructive' : totalStock <= 5 ? 'text-amber-500' : 'text-muted-foreground'
                      }`}>{totalStock} u.</span>
                    </td>
                    <td className="px-2 py-3 text-muted-foreground">
                      {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </td>
                  </tr>,

                  isExpanded && (
                    <tr key={`${p.id}-exp`}>
                      <td colSpan={6} className="bg-muted/10" onClick={e => e.stopPropagation()}>
                        <ExpandedPanel
                          p={p} canWrite={canWrite}
                          editProductAction={editProductAction}
                          editVariationAction={editVariationAction}
                          addVariationAction={addVariationAction}
                          deactivateProductAction={deactivateProductAction}
                        />
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
        <ArchivedSection
          archivedProducts={archivedProducts}
          catMap={catMap}
          restoreProductAction={restoreProductAction}
        />
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
            const vars       = p.product_variations ?? []
            const totalStock = vars.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)
            const hasZero    = vars.some(v => v.stock_quantity === 0)
            const isExpanded = expandedIds.has(p.id)
            const catName    = p.platform_category_id ? catMap[p.platform_category_id] : null

            return (
              <div
                key={p.id}
                className={`rounded-2xl border ${isExpanded ? 'border-primary/40' : 'border-border'} bg-card shadow-sm overflow-hidden transition-all duration-200 hover:shadow-md`}
              >
                {/* Card image */}
                <div
                  className="relative aspect-[4/3] bg-muted cursor-pointer overflow-hidden"
                  onClick={() => toggle(p.id)}
                >
                  {p.cover_image_url ? (
                    <Image src={p.cover_image_url} alt={p.title} fill className="object-cover transition-transform duration-300 hover:scale-105" sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw" />
                  ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center gap-2">
                      <ImageOff className="h-8 w-8 text-muted-foreground/30" />
                      <span className="text-[10px] text-muted-foreground/50">Sin imagen</span>
                    </div>
                  )}
                  {/* Click hint overlay — visible on mobile, hover on desktop */}
                  <div className="absolute bottom-2 right-2 bg-black/30 text-white text-[10px] px-2 py-1 rounded-full backdrop-blur-sm opacity-100 md:opacity-0 md:hover:opacity-100 transition-opacity">
                    {isExpanded ? 'Cerrar' : 'Ver detalle'}
                  </div>
                </div>

                {/* Card content */}
                <div className="p-4">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="min-w-0">
                      <p className="font-semibold text-sm leading-tight line-clamp-2">{p.title}</p>
                      {catName && (
                        <span className="inline-flex items-center gap-1 text-[10px] mt-1 px-1.5 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 font-medium">
                          <Tag className="h-2 w-2" />{catName}
                        </span>
                      )}
                    </div>
                    <div className="text-right flex-shrink-0">
                      <p className="font-bold text-primary text-sm">{fmtPrice(vars)}</p>
                      <p className={`text-[11px] tabular-nums font-medium ${hasZero ? 'text-destructive' : totalStock <= 5 ? 'text-amber-500' : 'text-muted-foreground'}`}>
                        {totalStock} u.
                      </p>
                    </div>
                  </div>

                  {p.description && (
                    <p className="text-xs text-muted-foreground line-clamp-2 mb-3">{p.description}</p>
                  )}

                  <div className="flex items-center justify-between mt-2">
                    <span className="text-[11px] text-muted-foreground/70">{vars.length} variante{vars.length !== 1 ? 's' : ''}</span>
                    <button
                      onClick={() => toggle(p.id)}
                      className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                    >
                      {isExpanded ? <><ChevronDown className="h-3.5 w-3.5" /> Cerrar</> : <><ChevronRight className="h-3.5 w-3.5" /> Detalle</>}
                    </button>
                  </div>
                </div>

                {/* Expandable panel */}
                {isExpanded && (
                  <div className="border-t border-border/40">
                    <ExpandedPanel
                      p={p} canWrite={canWrite}
                      editProductAction={editProductAction}
                      editVariationAction={editVariationAction}
                      addVariationAction={addVariationAction}
                      deactivateProductAction={deactivateProductAction}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
      <ArchivedSection
        archivedProducts={archivedProducts}
        catMap={catMap}
        restoreProductAction={restoreProductAction}
      />
    </div>
  )
}
