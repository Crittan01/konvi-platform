'use client'

import { useState } from 'react'
import { useFormStatus } from 'react-dom'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Plus, Boxes, AlertTriangle, XCircle, SlidersHorizontal, History, Loader2, Package,
} from 'lucide-react'
import CatalogForm from './catalog-form'
import MassImporter from './mass-importer'
import CatalogTable from './catalog-table'
import type { Product } from '../types'

type Movement = {
  id: string
  delta: number
  new_stock: number
  reason: string | null
  created_at: string
}

type Category = { id: string; name: string }

type Props = {
  products: Product[]
  archivedProducts: Product[]
  catMap: Record<string, string>
  canWrite: boolean
  categories: Category[]
  tenantId: string
  apiUrl: string
  movements: Movement[]
  threshold: number
  editProductAction: (fd: FormData) => Promise<void>
  editVariationAction: (fd: FormData) => Promise<void>
  addVariationAction: (fd: FormData) => Promise<void>
  deactivateProductAction: (fd: FormData) => Promise<void>
  restoreProductAction: (fd: FormData) => Promise<void>
  deleteProductAction: (fd: FormData) => Promise<void>
  adjustStockAction: (fd: FormData) => Promise<void>
  saveThresholdAction: (fd: FormData) => Promise<void>
}

function SaveThresholdButton() {
  const { pending } = useFormStatus()
  return (
    <Button type="submit" size="sm" className="h-8 shrink-0" disabled={pending}>
      {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Guardar'}
    </Button>
  )
}

export default function ProductsManager({
  products, archivedProducts, catMap, canWrite,
  categories, tenantId, apiUrl,
  movements, threshold,
  editProductAction, editVariationAction, addVariationAction,
  deactivateProductAction, restoreProductAction, deleteProductAction,
  adjustStockAction, saveThresholdAction,
}: Props) {
  const [dialogOpen, setDialogOpen]   = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)

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

      {/* KPI Bar */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-xl border border-border bg-card p-3 sm:p-4 flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
            <Package className="h-4 w-4 text-primary" />
          </div>
          <div className="min-w-0">
            <p className="text-xl font-bold text-primary tabular-nums">{totalUnits}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide truncate">Total stock</p>
          </div>
        </div>

        <div className={`rounded-xl border bg-card p-3 sm:p-4 flex items-center gap-3 ${lowStockCount > 0 ? 'border-yellow-500/30 bg-yellow-500/5' : 'border-border'}`}>
          <div className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${lowStockCount > 0 ? 'bg-yellow-500/15' : 'bg-muted'}`}>
            <AlertTriangle className={`h-4 w-4 ${lowStockCount > 0 ? 'text-yellow-500' : 'text-muted-foreground'}`} />
          </div>
          <div className="min-w-0">
            <p className={`text-xl font-bold tabular-nums ${lowStockCount > 0 ? 'text-yellow-500' : 'text-foreground'}`}>{lowStockCount}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide truncate">Stock bajo</p>
          </div>
        </div>

        <div className={`rounded-xl border bg-card p-3 sm:p-4 flex items-center gap-3 ${zeroStockCount > 0 ? 'border-red-500/30 bg-red-500/5' : 'border-border'}`}>
          <div className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${zeroStockCount > 0 ? 'bg-red-500/15' : 'bg-muted'}`}>
            <XCircle className={`h-4 w-4 ${zeroStockCount > 0 ? 'text-red-500' : 'text-muted-foreground'}`} />
          </div>
          <div className="min-w-0">
            <p className={`text-xl font-bold tabular-nums ${zeroStockCount > 0 ? 'text-red-400' : 'text-foreground'}`}>{zeroStockCount}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide truncate">Sin stock</p>
          </div>
        </div>
      </div>

      {/* Catalog table — full width */}
      <CatalogTable
        products={products}
        archivedProducts={archivedProducts}
        catMap={catMap}
        canWrite={canWrite}
        editProductAction={editProductAction}
        editVariationAction={editVariationAction}
        addVariationAction={addVariationAction}
        deactivateProductAction={deactivateProductAction}
        restoreProductAction={restoreProductAction}
        deleteProductAction={deleteProductAction}
        adjustStockAction={adjustStockAction}
      />

      {/* Bottom: Threshold + Movements */}
      {canWrite && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 pt-2 border-t border-border/40">

          {/* Threshold */}
          <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
            <p className="font-semibold text-sm mb-3 text-foreground flex items-center gap-1.5">
              <SlidersHorizontal className="h-3.5 w-3.5" /> Umbral de alerta
            </p>
            <form action={saveThresholdAction} className="flex gap-2 items-end">
              <div className="flex-1 space-y-1.5">
                <Label className="text-[11px] text-muted-foreground uppercase">Unidades mínimas</Label>
                <Input
                  name="threshold"
                  type="number"
                  min="0"
                  defaultValue={threshold}
                  className="h-8 text-sm bg-background font-mono"
                  required
                />
              </div>
              <SaveThresholdButton />
            </form>
            <p className="text-[11px] text-muted-foreground leading-snug mt-3">
              Stock ≤ {threshold} u. aparece como &quot;bajo&quot;.
            </p>
          </div>

          {/* Movements history */}
          <div className="sm:col-span-1 lg:col-span-2 rounded-xl border border-border bg-card p-4 shadow-sm">
            <button
              onClick={() => setHistoryOpen(o => !o)}
              className="w-full flex items-center justify-between"
            >
              <p className="font-semibold text-sm text-foreground flex items-center gap-1.5">
                <History className="h-3.5 w-3.5" /> Últimos movimientos
              </p>
              <span className="text-xs text-muted-foreground">{historyOpen ? 'Ocultar' : 'Mostrar'}</span>
            </button>

            {historyOpen && (
              movements.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center border-t border-border/40 mt-3">
                  Sin historial reciente.
                </p>
              ) : (
                <div className="space-y-2 max-h-60 overflow-y-auto pr-1 pt-3 border-t border-border/40 mt-3">
                  {movements.map(m => (
                    <div key={m.id} className="text-xs pb-2 border-b border-border/30 last:border-0">
                      <div className="flex justify-between items-center">
                        <span className={`font-bold px-1.5 py-0.5 rounded-sm ${m.delta > 0 ? 'text-emerald-500 bg-emerald-500/10' : 'text-red-500 bg-red-500/10'}`}>
                          {m.delta > 0 ? `+${m.delta}` : m.delta} u.
                        </span>
                        <span className="text-muted-foreground font-mono text-[10px]">→ {m.new_stock} u.</span>
                      </div>
                      <p className="text-foreground mt-1 leading-tight">{m.reason ?? 'Ajuste manual'}</p>
                      <p className="text-muted-foreground/60 text-[10px] mt-0.5">
                        {new Date(m.created_at).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                  ))}
                </div>
              )
            )}
          </div>
        </div>
      )}

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
            categories={categories}
            tenantId={tenantId}
            onCreated={() => setDialogOpen(false)}
          />
          <div className="border-t border-border pt-4 mt-2">
            <p className="text-xs font-medium text-muted-foreground mb-3">O importa desde Excel</p>
            <MassImporter categories={categories} tenantId={tenantId} />
          </div>
        </DialogContent>
      </Dialog>

    </div>
  )
}
