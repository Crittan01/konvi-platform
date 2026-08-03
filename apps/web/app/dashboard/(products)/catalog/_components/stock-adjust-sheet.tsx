'use client'

/**
 * StockAdjustSheet — ajuste rápido de stock de UNA variante (Spec WOW §4.4).
 *
 * El ajuste completo vive en la sección ③ Inventario del ProductEditDrawer;
 * este es el atajo operativo desde la fila de variante del ExpandedPanel
 * (compartido por las 3 vistas del catálogo: cards móvil, tabla y grid).
 *
 * Presentación: ResponsiveDialog — bottom-sheet (vaul) en < lg, Dialog del DS
 * en ≥ lg. La acción es la MISMA server action `adjustStock` del drawer
 * (ledger stock_movements + audit_log + revalidate /dashboard/catalog), sin
 * endpoints nuevos.
 */
import { useEffect } from 'react'
import ActionResultForm, { useActionResultStatus } from '@/components/action-result-form'
import { ResponsiveDialog } from '@/components/ui/responsive-dialog'
import { Input } from '@/components/ui/input'
import { SubmitButton } from '@/components/ui/submit-button'
import type { Product, Variation } from '../types'
import type { ActionResult } from '@/lib/action-result'

type Action = (fd: FormData) => Promise<ActionResult>

function fmtAttrs(attrs: Record<string, string> | null): string {
  if (!attrs || Object.keys(attrs).length === 0) return 'Estándar'
  return Object.entries(attrs).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

/** Cierra el sheet cuando la server action termina OK (el toast lo da el form). */
function CloseOnSuccess({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  const status = useActionResultStatus()
  useEffect(() => {
    if (status === 'ok') onOpenChange(false)
  }, [status, onOpenChange])
  return null
}

export function StockAdjustSheet({
  product, variation, open, onOpenChange, adjustStockAction, threshold,
}: {
  product: Product
  variation: Variation
  open: boolean
  onOpenChange: (open: boolean) => void
  adjustStockAction: Action
  threshold: number
}) {
  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Ajustar stock"
      description={
        <>
          {product.title} · {fmtAttrs(variation.attributes)} — stock actual:{' '}
          <span className={`font-semibold tabular-nums ${variation.stock_quantity === 0 ? 'text-destructive' : variation.stock_quantity <= threshold ? 'text-amber-700' : ''}`}>
            {variation.stock_quantity} u.
          </span>
        </>
      }
    >
      <ActionResultForm action={adjustStockAction} className="space-y-3">
        <CloseOnSuccess onOpenChange={onOpenChange} />
        <input type="hidden" name="variation_id" value={variation.id} />
        <input type="hidden" name="product_id" value={product.id} />
        <p className="text-xs text-muted-foreground">
          Usa <strong>+</strong> para entradas (compras, devoluciones) y <strong>−</strong> para
          salidas (mermas, errores). Cada movimiento queda registrado en el historial.
        </p>
        <div className="space-y-1">
          <label htmlFor="stock-adjust-reason" className="text-[10px] font-semibold text-muted-foreground uppercase">
            Motivo (obligatorio)
          </label>
          <Input id="stock-adjust-reason" name="reason" placeholder="Ej: Compra proveedor..." required className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <label htmlFor="stock-adjust-delta" className="text-[10px] font-semibold text-muted-foreground uppercase">
            Cantidad (+/−)
          </label>
          <Input id="stock-adjust-delta" name="delta" type="number" placeholder="±0" required className="h-9 text-sm font-mono" />
        </div>
        <div className="flex justify-end pt-1">
          <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado">
            Aplicar ajuste
          </SubmitButton>
        </div>
      </ActionResultForm>
    </ResponsiveDialog>
  )
}
