'use client'

import { useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { SubmitButton } from '@/components/ui/submit-button'
import { Input } from '@/components/ui/input'
import {
  Plus, Boxes, AlertTriangle, XCircle, SlidersHorizontal, Package,
} from 'lucide-react'
import CatalogForm from './catalog-form'
import MassImporter from './mass-importer'
import CatalogTable from './catalog-table'
import type { Product, AttributeDef } from '../types'

type Props = {
  products: Product[]
  archivedProducts: Product[]
  catMap: Record<string, string>
  canWrite: boolean
  productCategories: { id: string; display_label: string }[]  // ADR-0027 categorías operativas
  attributeDefs: AttributeDef[]  // ADR-0029 contrato de atributos por categoría
  tenantId: string
  apiUrl: string
  threshold: number
  editProductAction: (fd: FormData) => Promise<void>
  editVariationAction: (fd: FormData) => Promise<void>
  addVariationAction: (fd: FormData) => Promise<void>
  deactivateProductAction: (fd: FormData) => Promise<void>
  restoreProductAction: (fd: FormData) => Promise<void>
  deleteProductAction: (fd: FormData) => Promise<void>
  adjustStockAction: (fd: FormData) => Promise<void>
  saveThresholdAction: (fd: FormData) => Promise<void>
  linkedVariationIds: string[]
}


export default function ProductsManager({
  products, archivedProducts, catMap, canWrite,
  productCategories, attributeDefs, tenantId, apiUrl,
  threshold,
  editProductAction, editVariationAction, addVariationAction,
  deactivateProductAction, restoreProductAction, deleteProductAction,
  adjustStockAction, saveThresholdAction, linkedVariationIds,
}: Props) {
  const [dialogOpen, setDialogOpen]       = useState(false)
  const [editingThreshold, setEditingThreshold] = useState(false)

  const allVariations  = products.flatMap(p => p.product_variations)
  const totalUnits     = allVariations.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)
  const lowStockCount  = allVariations.filter(v => v.stock_quantity > 0 && v.stock_quantity <= threshold).length
  const zeroStockCount = allVariations.filter(v => v.stock_quantity === 0).length

  return (
    <div className="space-y-5">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Boxes className="h-5 w-5 text-primary" /> Productos
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {products.length} productos · {allVariations.length} variantes
          </p>
        </div>
        {canWrite && (
          <Button onClick={() => setDialogOpen(true)} size="sm" className="gap-1.5 self-start sm:self-auto">
            <Plus className="h-4 w-4" /> Nuevo Producto
          </Button>
        )}
      </div>

      {/* KPI Bar — 4 cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* Total stock */}
        <div className="rounded-xl border border-border bg-card p-3 sm:p-4 flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
            <Package className="h-4 w-4 text-primary" />
          </div>
          <div className="min-w-0">
            <p className="text-xl font-bold text-primary tabular-nums">{totalUnits}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide truncate">Total stock</p>
          </div>
        </div>

        {/* Stock bajo */}
        <div className={`rounded-xl border bg-card p-3 sm:p-4 flex items-center gap-3 ${lowStockCount > 0 ? 'border-yellow-500/30 bg-yellow-500/5' : 'border-border'}`}>
          <div className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${lowStockCount > 0 ? 'bg-yellow-500/15' : 'bg-muted'}`}>
            <AlertTriangle className={`h-4 w-4 ${lowStockCount > 0 ? 'text-yellow-500' : 'text-muted-foreground'}`} />
          </div>
          <div className="min-w-0">
            <p className={`text-xl font-bold tabular-nums ${lowStockCount > 0 ? 'text-yellow-500' : 'text-foreground'}`}>{lowStockCount}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide truncate">Stock bajo</p>
          </div>
        </div>

        {/* Sin stock */}
        <div className={`rounded-xl border bg-card p-3 sm:p-4 flex items-center gap-3 ${zeroStockCount > 0 ? 'border-red-500/30 bg-red-500/5' : 'border-border'}`}>
          <div className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${zeroStockCount > 0 ? 'bg-red-500/15' : 'bg-muted'}`}>
            <XCircle className={`h-4 w-4 ${zeroStockCount > 0 ? 'text-red-500' : 'text-muted-foreground'}`} />
          </div>
          <div className="min-w-0">
            <p className={`text-xl font-bold tabular-nums ${zeroStockCount > 0 ? 'text-red-400' : 'text-foreground'}`}>{zeroStockCount}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide truncate">Sin stock</p>
          </div>
        </div>

        {/* Umbral de alerta — configuración visible */}
        <div className="rounded-xl border border-dashed border-border bg-muted/20 p-3 sm:p-4 space-y-2">
          <div className="flex items-center gap-1.5">
            <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
              Umbral de alerta
            </p>
          </div>
          {editingThreshold && canWrite ? (
            <form action={saveThresholdAction} onSubmit={() => setEditingThreshold(false)}
              className="flex items-center gap-2">
              <Input name="threshold" type="number" min="1" max="999"
                defaultValue={threshold} autoFocus
                className="h-8 w-20 text-sm font-mono" />
              <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado"
                className="h-8 text-xs">
                Guardar
              </SubmitButton>
              <button type="button" onClick={() => setEditingThreshold(false)}
                className="text-xs text-muted-foreground hover:text-foreground">Cancelar</button>
            </form>
          ) : (
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm text-foreground">
                Alerta cuando stock <span className="font-bold">≤ {threshold}</span> u.
              </p>
              {canWrite && (
                <button onClick={() => setEditingThreshold(true)}
                  className="h-7 px-3 text-xs font-medium rounded-md bg-foreground text-background hover:bg-foreground/80 transition-colors shrink-0">
                  Cambiar
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Catalog table — full width */}
      <CatalogTable
        products={products}
        archivedProducts={archivedProducts}
        catMap={catMap}
        productCategories={productCategories}
        canWrite={canWrite}
        threshold={threshold}
        tenantId={tenantId}
        editProductAction={editProductAction}
        editVariationAction={editVariationAction}
        addVariationAction={addVariationAction}
        deactivateProductAction={deactivateProductAction}
        restoreProductAction={restoreProductAction}
        deleteProductAction={deleteProductAction}
        adjustStockAction={adjustStockAction}
        linkedVariationIds={linkedVariationIds}
      />


      {/* New Product Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Plus className="h-4 w-4 text-primary" /> Nuevo Producto
            </DialogTitle>
          </DialogHeader>
          <CatalogForm
            apiUrl={apiUrl}
            productCategories={productCategories}
            attributeDefs={attributeDefs}
            tenantId={tenantId}
            onCreated={() => setDialogOpen(false)}
          />
          <div className="border-t border-border pt-4 mt-2">
            <p className="text-xs font-medium text-muted-foreground mb-3">O importa desde Excel</p>
            <MassImporter productCategories={productCategories} tenantId={tenantId} apiUrl={apiUrl} />
          </div>
        </DialogContent>
      </Dialog>

    </div>
  )
}
