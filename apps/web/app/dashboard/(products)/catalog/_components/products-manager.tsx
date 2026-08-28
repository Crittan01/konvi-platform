'use client'

import { useState } from 'react'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import ActionResultForm from '@/components/action-result-form'
import { Button } from '@/components/ui/button'
import { SubmitButton } from '@/components/ui/submit-button'
import { Input } from '@/components/ui/input'
import {
  Plus, Boxes, AlertTriangle, XCircle, SlidersHorizontal, Package, Info,
} from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import CatalogForm from './catalog-form'
import MassImporter from './mass-importer'
import CatalogTable from './catalog-table'
import { isLowStockVariation } from '../_lib/stock'
import type { Product, AttributeDef } from '../types'
import type { ActionResult } from '@/lib/action-result'

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
  activeTotal: number   // total real de productos activos (para detectar truncamiento del listado)
  loadError: boolean    // el fetch del listado falló → avisar en vez de mostrar catálogo falso-vacío
  editProductAction: (fd: FormData) => Promise<ActionResult>
  editVariationAction: (fd: FormData) => Promise<ActionResult>
  addVariationAction: (fd: FormData) => Promise<ActionResult>
  deleteVariationAction: (fd: FormData) => Promise<ActionResult>
  deactivateProductAction: (fd: FormData) => Promise<ActionResult>
  restoreProductAction: (fd: FormData) => Promise<ActionResult>
  deleteProductAction: (fd: FormData) => Promise<ActionResult>
  adjustStockAction: (fd: FormData) => Promise<ActionResult>
  saveThresholdAction: (fd: FormData) => Promise<ActionResult>
  linkedVariationIds: string[]
}


export default function ProductsManager({
  products, archivedProducts, catMap, canWrite,
  productCategories, attributeDefs, tenantId, apiUrl,
  threshold, activeTotal, loadError,
  editProductAction, editVariationAction, addVariationAction, deleteVariationAction,
  deactivateProductAction, restoreProductAction, deleteProductAction,
  adjustStockAction, saveThresholdAction, linkedVariationIds,
}: Props) {
  const [dialogOpen, setDialogOpen]       = useState(false)
  const [editingThreshold, setEditingThreshold] = useState(false)

  const allVariations  = products.flatMap(p => p.product_variations)
  const totalUnits     = allVariations.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)
  const lowStockCount  = allVariations.filter(v => isLowStockVariation(v, threshold)).length
  const zeroStockCount = allVariations.filter(v => v.stock_quantity === 0).length

  return (
    <div className="space-y-5">

      {/* Header — cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={Boxes}
        title="Productos"
        description={`${products.length} productos · ${allVariations.length} variantes`}
        actions={canWrite ? (
          <Button onClick={() => setDialogOpen(true)} size="sm" className="gap-1.5 self-start sm:self-auto">
            <Plus className="h-4 w-4" /> Nuevo Producto
          </Button>
        ) : undefined}
      />

      {/* Aviso: el listado no se pudo cargar (no mostrar un catálogo falso-vacío) */}
      {loadError && (
        <div className="flex items-start gap-2 rounded-xl border border-red-700/30 bg-red-500/5 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>No pudimos cargar el catálogo completo. Recarga la página; si persiste, avísanos.</span>
        </div>
      )}

      {/* Aviso: el catálogo excede la ventana mostrada (PostgREST trunca sin avisar) */}
      {activeTotal > products.length && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-700/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-700">
          <Info className="h-4 w-4 shrink-0 mt-0.5" />
          <span>
            Mostrando {products.length} de {activeTotal} productos activos. Usa el buscador para encontrar los que no ves aquí.
          </span>
        </div>
      )}

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
        <div className={`rounded-xl border bg-card p-3 sm:p-4 flex items-center gap-3 ${lowStockCount > 0 ? 'border-amber-700/30 bg-amber-500/5' : 'border-border'}`}>
          <div className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${lowStockCount > 0 ? 'bg-amber-500/15' : 'bg-muted'}`}>
            <AlertTriangle className={`h-4 w-4 ${lowStockCount > 0 ? 'text-amber-700' : 'text-muted-foreground'}`} />
          </div>
          <div className="min-w-0">
            <p className={`text-xl font-bold tabular-nums ${lowStockCount > 0 ? 'text-amber-700' : 'text-foreground'}`}>{lowStockCount}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide truncate">Stock bajo</p>
          </div>
        </div>

        {/* Sin stock */}
        <div className={`rounded-xl border bg-card p-3 sm:p-4 flex items-center gap-3 ${zeroStockCount > 0 ? 'border-red-700/30 bg-red-500/5' : 'border-border'}`}>
          <div className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${zeroStockCount > 0 ? 'bg-red-500/15' : 'bg-muted'}`}>
            <XCircle className={`h-4 w-4 ${zeroStockCount > 0 ? 'text-red-700' : 'text-muted-foreground'}`} />
          </div>
          <div className="min-w-0">
            <p className={`text-xl font-bold tabular-nums ${zeroStockCount > 0 ? 'text-red-700' : 'text-foreground'}`}>{zeroStockCount}</p>
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
            <ActionResultForm action={saveThresholdAction}
              className="flex items-center gap-2">
              <Input name="threshold" type="number" min="1" max="999"
                defaultValue={threshold} autoFocus
                className="h-8 w-20 text-sm font-mono" />
              <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado"
                className="h-8 text-xs">
                Guardar
              </SubmitButton>
              <button type="button" onClick={() => setEditingThreshold(false)}
                className="text-xs text-muted-foreground hover:text-foreground">Cerrar</button>
            </ActionResultForm>
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
        deleteVariationAction={deleteVariationAction}
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
