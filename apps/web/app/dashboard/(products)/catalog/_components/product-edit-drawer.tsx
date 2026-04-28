'use client'

import { useState } from 'react'
import Image from 'next/image'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { SubmitButton } from '@/components/ui/submit-button'
import { Button } from '@/components/ui/button'
import {
  Info, Package2, ArrowUpDown, Archive,
  Plus, Zap, Edit3, X, ImageOff, ChevronDown, ChevronUp,
} from 'lucide-react'
import { ImageUploadBox } from './image-upload-box'
import { VariantMatrixGenerator } from './variant-matrix'
import type { Product, Variation } from '../types'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtAttrs(attrs: Record<string, string> | null): string {
  if (!attrs || Object.keys(attrs).length === 0) return 'Estándar'
  return Object.entries(attrs).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

function fmtPrice(v: Variation): string {
  return `$${(v.price ?? 0).toLocaleString('es-CO')}`
}

// ── Sección colapsable ────────────────────────────────────────────────────────

function Section({ icon: Icon, title, children, defaultOpen = true }: {
  icon: React.ElementType; title: string; children: React.ReactNode; defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-border/60 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-muted/30 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold text-foreground uppercase tracking-wider">{title}</span>
        </div>
        {open ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />}
      </button>
      {open && <div className="p-4 space-y-4">{children}</div>}
    </div>
  )
}

// ── Variante editable dentro del drawer ───────────────────────────────────────

function VariantEditRow({ v, threshold, tenantId, editVariationAction }: {
  v: Variation; threshold: number; tenantId: string
  editVariationAction: (fd: FormData) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [showDims, setShowDims] = useState(false)

  if (!editing) {
    return (
      <div className="flex items-center gap-3 py-2 border-b border-border/40 last:border-0">
        {v.image_url ? (
          <div className="relative w-8 h-8 rounded border border-border overflow-hidden shrink-0">
            <Image src={v.image_url} alt="" fill className="object-cover" sizes="32px" />
          </div>
        ) : (
          <div className="w-8 h-8 rounded border border-dashed border-border flex items-center justify-center shrink-0 bg-muted/20">
            <ImageOff className="h-3 w-3 text-muted-foreground/40" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium">{fmtAttrs(v.attributes)}</p>
          {v.sku && <p className="text-[10px] text-muted-foreground font-mono">{v.sku}</p>}
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs font-semibold tabular-nums">{fmtPrice(v)}</p>
          <p className={`text-[10px] tabular-nums ${v.stock_quantity === 0 ? 'text-destructive' : v.stock_quantity <= threshold ? 'text-amber-500' : 'text-muted-foreground'}`}>
            {v.stock_quantity} u.
          </p>
        </div>
        <button onClick={() => setEditing(true)}
          className="text-muted-foreground hover:text-primary transition-colors shrink-0">
          <Edit3 className="h-3.5 w-3.5" />
        </button>
      </div>
    )
  }

  return (
    <form action={editVariationAction} onSubmit={() => setEditing(false)}
      className="py-2 border-b border-border/40 last:border-0 space-y-2">
      <input type="hidden" name="variation_id" value={v.id} />
      <p className="text-[10px] text-muted-foreground italic">El stock se gestiona en Inventario ↓</p>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[10px] text-muted-foreground uppercase font-semibold">Precio</label>
          <Input name="price" type="number" defaultValue={v.price} step="50" min="50" className="h-7 text-xs font-mono mt-1" />
        </div>
        <div>
          <label className="text-[10px] text-muted-foreground uppercase font-semibold">Precio anterior</label>
          <Input name="compare_at_price" type="number" defaultValue={v.compare_at_price ?? ''} step="50" className="h-7 text-xs font-mono mt-1" placeholder="Opcional" />
        </div>
        <div>
          <label className="text-[10px] text-amber-600/90 uppercase font-semibold">Costo ($)</label>
          <Input name="cost_price" type="number" defaultValue={v.cost_price ?? ''} step="50" min="0" className="h-7 text-xs font-mono mt-1 border-amber-500/30" placeholder="0" />
        </div>
        <div>
          <label className="text-[10px] text-muted-foreground uppercase font-semibold">SKU</label>
          <Input name="sku" defaultValue={v.sku ?? ''} className="h-7 text-xs font-mono mt-1" placeholder="SKU-001" />
        </div>
      </div>
      {/* Imagen de variante — siempre visible */}
      <ImageUploadBox name="image_url" defaultUrl={v.image_url ?? ''} tenantId={tenantId} size="sm" label="Foto de esta variante (opcional)" />
      <button type="button" onClick={() => setShowDims(d => !d)}
        className="text-[10px] text-primary/70 font-medium hover:text-primary transition-colors">
        {showDims ? '▲ Ocultar dimensiones' : '▼ Dimensiones y peso (Envia)'}
      </button>
      {showDims && (
        <div className="space-y-2 pt-1 border-t border-border/30">
          <div className="grid grid-cols-2 gap-2">
            {[['weight_kg','Peso (kg)','0.1'],['length_cm','Largo (cm)','10'],['width_cm','Ancho (cm)','10'],['height_cm','Alto (cm)','5']].map(([n,l,p]) => (
              <div key={n}>
                <label className="text-[10px] text-muted-foreground uppercase font-semibold">{l}</label>
                <Input name={n} type="number" step="0.01" min="0"
                  defaultValue={v[n as keyof Variation] as number ?? ''}
                  className="h-7 text-xs font-mono mt-1" placeholder={p} />
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex gap-2">
        <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado" className="h-7 text-xs">Guardar</SubmitButton>
        <button type="button" onClick={() => setEditing(false)} className="text-xs text-muted-foreground hover:text-foreground px-2">Cancelar</button>
      </div>
    </form>
  )
}

// ── Drawer principal ──────────────────────────────────────────────────────────

interface Props {
  product: Product
  open: boolean
  onOpenChange: (open: boolean) => void
  catMap: Record<string, string>
  tenantId: string
  threshold: number
  editProductAction:   (fd: FormData) => Promise<void>
  editVariationAction: (fd: FormData) => Promise<void>
  addVariationAction:  (fd: FormData) => Promise<void>
  adjustStockAction:   (fd: FormData) => Promise<void>
  deactivateProductAction: (fd: FormData) => Promise<void>
}

export function ProductEditDrawer({
  product, open, onOpenChange, catMap, tenantId, threshold,
  editProductAction, editVariationAction, addVariationAction,
  adjustStockAction, deactivateProductAction,
}: Props) {
  const vars = product.product_variations ?? []
  const [showAddVar, setShowAddVar] = useState<'manual' | 'matrix' | false>(false)
  const [newVarAttrs, setNewVarAttrs] = useState([{ key: '', value: '' }])

  const addAttr    = () => setNewVarAttrs(a => [...a, { key: '', value: '' }])
  const removeAttr = (i: number) => setNewVarAttrs(a => a.filter((_, idx) => idx !== i))
  const updateAttr = (i: number, field: 'key' | 'value', val: string) =>
    setNewVarAttrs(a => a.map((attr, idx) => idx === i ? { ...attr, [field]: val } : attr))

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto p-0">
        <SheetHeader className="px-6 py-4 border-b border-border sticky top-0 bg-background z-10">
          <SheetTitle className="text-base font-semibold flex items-center gap-2">
            <Package2 className="h-4 w-4 text-primary" />
            {product.title}
          </SheetTitle>
        </SheetHeader>

        <div className="px-6 py-5 space-y-4">

          {/* ① INFORMACIÓN */}
          <Section icon={Info} title="Información del producto">
            <form action={editProductAction} className="space-y-3">
              <input type="hidden" name="product_id" value={product.id} />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Nombre</label>
                  <Input name="title" defaultValue={product.title} className="h-8 text-sm" />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Categoría</label>
                  <select name="platform_category_id" defaultValue={product.platform_category_id ?? ''}
                    className="w-full h-8 rounded-md border border-input bg-background text-sm px-2 text-foreground">
                    <option value="">Sin categoría</option>
                    {Object.entries(catMap).map(([id, name]) => (
                      <option key={id} value={id}>{name}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1 sm:col-span-2">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Descripción</label>
                  <Textarea name="description" defaultValue={product.description ?? ''} className="min-h-[80px] text-sm resize-y" />
                </div>
              </div>
              <ImageUploadBox name="cover_image_url" defaultUrl={product.cover_image_url ?? ''} tenantId={tenantId} size="lg" label="Imagen portada" />
              <div className="flex justify-end pt-1">
                <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado">Guardar información</SubmitButton>
              </div>
            </form>
          </Section>

          {/* ② VARIANTES */}
          <Section icon={Package2} title="Variantes">
            {/* Lista de variantes */}
            <div>
              {vars.map(v => (
                <VariantEditRow key={v.id} v={v} threshold={threshold} tenantId={tenantId} editVariationAction={editVariationAction} />
              ))}
            </div>

            {/* Agregar variante */}
            {!showAddVar ? (
              <div className="flex gap-2 pt-1">
                <button onClick={() => setShowAddVar('manual')}
                  className="inline-flex items-center gap-1.5 h-7 px-3 text-xs font-medium rounded-md border border-primary/30 text-primary bg-primary/5 hover:bg-primary/10 transition-colors">
                  <Plus className="h-3 w-3" /> Agregar variante
                </button>
                <button onClick={() => setShowAddVar('matrix')}
                  className="inline-flex items-center gap-1.5 h-7 px-3 text-xs font-medium rounded-md border border-border text-muted-foreground bg-muted/30 hover:bg-muted hover:text-foreground transition-colors">
                  <Zap className="h-3 w-3" /> Generar variantes
                </button>
              </div>
            ) : showAddVar === 'matrix' ? (
              <div className="space-y-3 p-3 bg-muted/20 rounded-lg border border-border/40">
                <div className="flex items-center justify-between">
                  <p className="text-[11px] font-semibold text-muted-foreground uppercase">Generador de Variantes</p>
                  <button type="button" onClick={() => setShowAddVar(false)}><X className="h-3.5 w-3.5 text-muted-foreground" /></button>
                </div>
                <VariantMatrixGenerator productId={product.id} addVariationAction={addVariationAction} onDone={() => setShowAddVar(false)} />
              </div>
            ) : (
              <form action={addVariationAction} onSubmit={() => setShowAddVar(false as const)}
                className="space-y-3 p-3 bg-muted/20 rounded-lg border border-border/40">
                <input type="hidden" name="product_id" value={product.id} />
                <input type="hidden" name="attrs_json" value={JSON.stringify(
                  Object.fromEntries(newVarAttrs.filter(a => a.key.trim() && a.value.trim()).map(a => [a.key.trim(), a.value.trim()]))
                )} />
                <div className="space-y-1.5">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Atributos</label>
                  {newVarAttrs.map((attr, i) => (
                    <div key={i} className="flex gap-1.5 items-center">
                      <Input value={attr.key} onChange={e => updateAttr(i, 'key', e.target.value)} placeholder="Propiedad" className="h-7 text-xs flex-1" />
                      <Input value={attr.value} onChange={e => updateAttr(i, 'value', e.target.value)} placeholder="Valor" className="h-7 text-xs flex-1" />
                      {newVarAttrs.length > 1 && (
                        <button type="button" onClick={() => removeAttr(i)} className="text-muted-foreground hover:text-destructive"><X className="h-3.5 w-3.5" /></button>
                      )}
                    </div>
                  ))}
                  <button type="button" onClick={addAttr} className="text-[11px] text-primary hover:underline">+ atributo</button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div><label className="text-[10px] text-muted-foreground uppercase font-semibold">SKU</label><Input name="sku" placeholder="PROD-001" className="h-7 text-xs font-mono mt-1" /></div>
                  <div><label className="text-[10px] text-muted-foreground uppercase font-semibold">Precio *</label><Input name="price" type="number" min="50" step="50" placeholder="0" required className="h-7 text-xs font-mono mt-1" /></div>
                  <div><label className="text-[10px] text-muted-foreground uppercase font-semibold">Precio anterior</label><Input name="compare_at_price" type="number" step="50" placeholder="Opcional" className="h-7 text-xs font-mono mt-1 border-dashed" /></div>
                  <div><label className="text-[10px] text-amber-600/90 uppercase font-semibold">Costo ($)</label><Input name="cost_price" type="number" min="0" step="50" placeholder="0" className="h-7 text-xs font-mono mt-1 border-amber-500/30" /></div>
                  <div><label className="text-[10px] text-muted-foreground uppercase font-semibold">Stock *</label><Input name="stock" type="number" min="0" defaultValue={0} required className="h-7 text-xs font-mono mt-1" /></div>
                </div>
                <div className="flex gap-2 justify-end">
                  <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado" className="h-7 text-xs">Guardar variante</SubmitButton>
                  <button type="button" onClick={() => setShowAddVar(false)} className="text-xs text-muted-foreground hover:text-foreground px-2">Cancelar</button>
                </div>
              </form>
            )}
          </Section>

          {/* ③ INVENTARIO */}
          <Section icon={ArrowUpDown} title="Inventario — Registrar movimiento" defaultOpen={false}>
            <p className="text-xs text-muted-foreground">Usa <strong>+</strong> para entradas (compras, devoluciones) y <strong>−</strong> para salidas (mermas, errores). Cada movimiento queda registrado.</p>
            <div className="rounded-lg border border-border/60 divide-y divide-border/40 overflow-hidden">
              <div className="grid grid-cols-[1fr_52px_1fr_56px_44px] gap-2 px-3 py-1.5 bg-muted/30 text-[10px] font-semibold text-muted-foreground uppercase">
                <span>Variante</span><span className="text-right">Actual</span><span>Motivo (obligatorio)</span><span className="text-center">+/−</span><span />
              </div>
              {vars.map(v => (
                <form key={v.id} action={adjustStockAction} className="grid grid-cols-[1fr_52px_1fr_56px_44px] gap-2 items-center px-3 py-2">
                  <input type="hidden" name="variation_id" value={v.id} />
                  <input type="hidden" name="product_id" value={product.id} />
                  <span className="text-xs font-medium truncate">{fmtAttrs(v.attributes)}</span>
                  <span className={`text-xs font-mono text-right tabular-nums ${v.stock_quantity === 0 ? 'text-destructive' : v.stock_quantity <= threshold ? 'text-amber-500' : 'text-muted-foreground'}`}>{v.stock_quantity} u.</span>
                  <Input name="reason" placeholder="Ej: Compra proveedor..." required className="h-7 text-xs" />
                  <Input name="delta" type="number" placeholder="±0" required className="h-7 text-xs font-mono text-center" />
                  <SubmitButton size="sm" pendingText="..." savedText="✓" className="h-7 w-10 p-0 text-xs">OK</SubmitButton>
                </form>
              ))}
            </div>
          </Section>

          {/* Zona de peligro */}
          <div className="border-t border-border/40 pt-4">
            <form action={deactivateProductAction}>
              <input type="hidden" name="product_id" value={product.id} />
              <Button type="submit" variant="ghost" size="sm"
                className="h-7 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/5 border border-transparent hover:border-destructive/20 gap-1.5">
                <Archive className="h-3 w-3" /> Archivar producto
              </Button>
            </form>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
