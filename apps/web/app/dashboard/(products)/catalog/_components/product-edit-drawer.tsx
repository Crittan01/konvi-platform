'use client'

import { useState, useRef, useEffect, useTransition } from 'react'
import Image from 'next/image'
import { toast } from 'sonner'
import { createClient } from '@/utils/supabase/client'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet'
import ActionResultForm from '@/components/action-result-form'
import { useConfirm } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { SubmitButton } from '@/components/ui/submit-button'
import { Button } from '@/components/ui/button'
import {
  Info, Package2, ArrowUpDown, Archive, History,
  Plus, Zap, Edit3, Trash2, X, ImageOff, ChevronDown, ChevronUp, Sparkles, Loader2,
} from 'lucide-react'
import { ImageUploadBox } from './image-upload-box'
import { VariantMatrixGenerator } from './variant-matrix'
import type { Product, Variation, AttributeDef } from '../types'
import type { ActionResult } from '@/lib/action-result'
import { buildCategoryPicker } from '../_lib/category-tree'
import { optionOf } from '../_lib/attribute-contract'

type Action = (fd: FormData) => Promise<ActionResult>

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

function VariantEditRow({ v, productId, threshold, tenantId, variantCount, editVariationAction, deleteVariationAction }: {
  v: Variation; productId: string; threshold: number; tenantId: string; variantCount: number
  editVariationAction: Action
  deleteVariationAction: Action
}) {
  const [editing, setEditing] = useState(false)
  const [showDims, setShowDims] = useState(false)
  const confirmar = useConfirm()
  const [deleting, startDelete] = useTransition()

  const onDelete = async () => {
    // El backend rechaza borrar la única variante; se anticipa con un mensaje claro sin pegarle a la API.
    if (variantCount <= 1) {
      toast.error('No puedes eliminar la única variante. Archiva el producto si deseas retirarlo.')
      return
    }
    const okConfirm = await confirmar({
      title: '¿Eliminar esta variante?',
      description: `${fmtAttrs(v.attributes)}${v.sku ? ` · ${v.sku}` : ''}. Esta acción no se puede deshacer.`,
      confirmLabel: 'Eliminar', destructive: true,
    })
    if (!okConfirm) return
    startDelete(async () => {
      const fd = new FormData()
      fd.append('product_id', productId)
      fd.append('variation_id', v.id)
      const r = await deleteVariationAction(fd)
      if (!r.ok) toast.error(r.error || 'No se pudo eliminar la variante.')
      else toast.success(r.message || 'Variante eliminada.')
    })
  }

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
          <p className={`text-[10px] tabular-nums ${v.stock_quantity === 0 ? 'text-destructive' : v.stock_quantity <= threshold ? 'text-amber-700' : 'text-muted-foreground'}`}>
            {v.stock_quantity} u.
          </p>
        </div>
        <button onClick={() => setEditing(true)} aria-label={`Editar variante ${fmtAttrs(v.attributes)}`}
          className="text-muted-foreground hover:text-primary transition-colors shrink-0">
          <Edit3 className="h-3.5 w-3.5" />
        </button>
        <button onClick={onDelete} disabled={deleting} aria-label={`Eliminar variante ${fmtAttrs(v.attributes)}`}
          className="text-muted-foreground hover:text-destructive transition-colors shrink-0 disabled:opacity-50">
          {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
        </button>
      </div>
    )
  }

  return (
    <ActionResultForm action={editVariationAction}
      className="py-2 border-b border-border/40 last:border-0 space-y-2">
      <input type="hidden" name="variation_id" value={v.id} />
      <input type="hidden" name="product_id" value={productId} />
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
          <Input name="cost_price" type="number" defaultValue={v.cost_price ?? ''} step="50" min="0" className="h-7 text-xs font-mono mt-1 border-amber-700/30" placeholder="0" />
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
        <button type="button" onClick={() => setEditing(false)} className="text-xs text-muted-foreground hover:text-foreground px-2">Cerrar</button>
      </div>
    </ActionResultForm>
  )
}

// ── Historial de movimientos de stock (colapsable) ───────────────────────────
// Árbol funcional (00-product.md): "historial de movimientos colapsable". Hasta ahora stock_movements
// solo se ESCRIBÍA; aquí se LEE (RLS por tenant vía JWT) para que el operador vea/audite cada ajuste.

type StockMovement = {
  id: string
  variation_id: string
  delta: number
  new_stock: number
  reason: string | null
  created_at: string
}

function StockMovementHistory({ product, tenantId }: { product: Product; tenantId: string }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<StockMovement[] | null>(null)

  // Map variation_id → etiqueta legible (las variantes ya están en el producto).
  const varLabel = (id: string) => {
    const v = (product.product_variations ?? []).find(x => x.id === id)
    return v ? fmtAttrs(v.attributes) : 'Variante eliminada'
  }

  const load = async () => {
    setLoading(true); setError(null)
    try {
      const sb = createClient()
      const { data, error: err } = await sb
        .from('stock_movements')
        .select('id, variation_id, delta, new_stock, reason, created_at')
        .eq('tenant_id', tenantId)
        .eq('product_id', product.id)
        .order('created_at', { ascending: false })
        .limit(50)
      if (err) throw new Error(err.message)
      setRows((data as StockMovement[]) ?? [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo cargar el historial')
    } finally {
      setLoading(false)
    }
  }

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (next && rows === null && !loading) void load()
  }

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleString('es-CO', {
      timeZone: 'America/Bogota', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    })

  return (
    <div className="pt-3 border-t border-border/30">
      <button type="button" onClick={toggle} aria-expanded={open}
        className="flex items-center gap-1.5 text-[11px] font-medium text-primary/80 hover:text-primary transition-colors">
        <History className="h-3.5 w-3.5" />
        {open ? 'Ocultar historial de movimientos' : 'Ver historial de movimientos'}
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>
      {open && (
        <div className="mt-2">
          {loading && (
            <div className="flex items-center gap-2 py-3 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Cargando historial…
            </div>
          )}
          {error && (
            <div className="flex items-center justify-between gap-2 rounded-md border border-red-700/30 bg-red-500/5 px-3 py-2 text-xs text-red-700">
              <span>{error}</span>
              <button type="button" onClick={load} className="underline underline-offset-2 hover:no-underline">Reintentar</button>
            </div>
          )}
          {!loading && !error && rows && rows.length === 0 && (
            <p className="py-3 text-xs text-muted-foreground">Aún no hay movimientos registrados para este producto.</p>
          )}
          {!loading && !error && rows && rows.length > 0 && (
            <div className="rounded-lg border border-border/60 overflow-hidden">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="bg-muted/30 text-muted-foreground">
                    <th className="text-left px-2.5 py-1.5 font-semibold">Fecha</th>
                    <th className="text-left px-2.5 py-1.5 font-semibold">Variante</th>
                    <th className="text-left px-2.5 py-1.5 font-semibold">Motivo</th>
                    <th className="text-right px-2.5 py-1.5 font-semibold">Cambio</th>
                    <th className="text-right px-2.5 py-1.5 font-semibold">Resultante</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30">
                  {rows.map(mv => (
                    <tr key={mv.id}>
                      <td className="px-2.5 py-1.5 text-muted-foreground whitespace-nowrap">{fmtDate(mv.created_at)}</td>
                      <td className="px-2.5 py-1.5 truncate max-w-[120px]" title={varLabel(mv.variation_id)}>{varLabel(mv.variation_id)}</td>
                      <td className="px-2.5 py-1.5 text-muted-foreground truncate max-w-[140px]" title={mv.reason ?? ''}>{mv.reason || '—'}</td>
                      <td className={`px-2.5 py-1.5 text-right font-mono tabular-nums font-semibold ${mv.delta > 0 ? 'text-emerald-700' : mv.delta < 0 ? 'text-destructive' : 'text-muted-foreground'}`}>
                        {mv.delta > 0 ? '+' : ''}{mv.delta}
                      </td>
                      <td className="px-2.5 py-1.5 text-right font-mono tabular-nums">{mv.new_stock}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Drawer principal ──────────────────────────────────────────────────────────

interface Props {
  product: Product
  open: boolean
  onOpenChange: (open: boolean) => void
  productCategories: { id: string; display_label: string; parent_id?: string | null }[]
  tenantId: string
  threshold: number
  editProductAction:   Action
  editVariationAction: Action
  addVariationAction:  Action
  deleteVariationAction: Action
  adjustStockAction:   Action
  deactivateProductAction: Action
}

export function ProductEditDrawer({
  product, open, onOpenChange, productCategories, tenantId, threshold,
  editProductAction, editVariationAction, addVariationAction, deleteVariationAction,
  adjustStockAction, deactivateProductAction,
}: Props) {
  const vars = product.product_variations ?? []
  const [showAddVar, setShowAddVar] = useState<'manual' | 'matrix' | false>(false)
  const [newVarAttrs, setNewVarAttrs] = useState([{ key: '', value: '' }])

  // ADR-0029 D4: editor de atributos PRODUCT-LEVEL guiado por el contrato de la categoría. Auto-consulta las
  // definiciones no-variante al abrir (RLS via JWT) → inputs guiados; el save va por el PATCH validado (page.tsx).
  const [contractDefs, setContractDefs] = useState<AttributeDef[]>([])
  const [prodAttrs, setProdAttrs] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries((product.attributes ?? {}) as Record<string, unknown>)) {
      out[k] = String(v ?? '')
    }
    return out
  })
  useEffect(() => {
    if (!open || !product.category_id) { setContractDefs([]); return }
    let cancelled = false
    ;(async () => {
      const sb = createClient()
      const { data } = await sb
        .from('product_attribute_definitions')
        .select('product_category_id, code, label, type, unit, allowed_values, is_variant_axis, sort_order')
        .eq('tenant_id', tenantId)
        .eq('product_category_id', product.category_id)
        .eq('is_variant_axis', false)
        .order('sort_order')
      if (!cancelled) setContractDefs((data as AttributeDef[]) ?? [])
    })()
    return () => { cancelled = true }
  }, [open, product.category_id, tenantId])

  const setProdAttr = (label: string, value: string) => setProdAttrs(p => ({ ...p, [label]: value }))
  // Solo se envían atributos DEFINIDOS en el contrato y no vacíos (coherente con la validación HARD;
  // los legacy fuera de contrato no se reenvían para no disparar 422). Sin contrato → no se toca attributes.
  const contractLabels = new Set(contractDefs.map(d => d.label))
  const attrsPayload = Object.fromEntries(
    Object.entries(prodAttrs).filter(([k, v]) => contractLabels.has(k) && v.trim())
  )

  // "Sugerir con IA" — refs a los textareas (form no-controlado) + draft.
  const descRef = useRef<HTMLTextAreaElement>(null)
  const safetyRef = useRef<HTMLTextAreaElement>(null)
  const [suggesting, setSuggesting] = useState(false)
  const [aiNotice, setAiNotice] = useState('')

  async function onSuggest() {
    setSuggesting(true); setAiNotice('')
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      if (!session?.access_token) { setAiNotice('Sesión expirada.'); return }
      const categoryName = product.category_id
        ? productCategories.find(c => c.id === product.category_id)?.display_label : undefined
      const resp = await fetch('/api/catalog/suggest-content', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${session.access_token}` },
        body: JSON.stringify({
          title: product.title,
          category_name: categoryName ?? null,
          current_description: descRef.current?.value?.trim() || null,
        }),
      })
      if (!resp.ok) { const b = await resp.json().catch(() => ({})); setAiNotice(b.detail || 'No se pudo generar.'); return }
      const data = await resp.json()
      if (descRef.current && data.description) descRef.current.value = data.description
      if (safetyRef.current && data.safety_note) safetyRef.current.value = data.safety_note
      setAiNotice(data.disclaimer || 'Borrador generado por IA. Revísalo y edítalo antes de guardar.')
    } catch {
      setAiNotice('Error al sugerir con IA.')
    } finally {
      setSuggesting(false)
    }
  }

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
            <ActionResultForm action={editProductAction} className="space-y-3">
              <input type="hidden" name="product_id" value={product.id} />
              <div className="flex items-center justify-end">
                <Button type="button" variant="outline" size="sm" disabled={suggesting}
                  onClick={onSuggest} className="gap-1.5 h-7 text-xs">
                  {suggesting
                    ? <><Loader2 className="h-3 w-3 animate-spin" /> Generando...</>
                    : <><Sparkles className="h-3 w-3" /> Sugerir con IA</>}
                </Button>
              </div>
              {aiNotice && (
                <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-700/30 rounded px-2 py-1">{aiNotice}</p>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Nombre</label>
                  <Input name="title" defaultValue={product.title} className="h-8 text-sm" />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Categoría (catálogo)</label>
                  <select name="category_id" defaultValue={product.category_id ?? ''}
                    className="w-full h-8 rounded-md border border-input bg-background text-sm px-2 text-foreground">
                    <option value="">Sin categoría</option>
                    {/* F2: picker agrupado — verticales como <optgroup>, subcategorías/hojas como opciones. */}
                    {buildCategoryPicker(productCategories).map((g, gi) =>
                      g.label === null
                        ? g.options.map(o => <option key={o.id} value={o.id}>{o.display_label}</option>)
                        : <optgroup key={`g-${gi}-${g.label}`} label={g.label}>
                            {g.options.map(o => <option key={o.id} value={o.id}>{o.display_label}</option>)}
                          </optgroup>
                    )}
                  </select>
                </div>
                <div className="space-y-1 sm:col-span-2">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">Descripción</label>
                  <Textarea ref={descRef} name="description" defaultValue={product.description ?? ''} className="min-h-[80px] text-sm resize-y" />
                </div>
                <div className="space-y-1 sm:col-span-2">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">⚠️ Nota de seguridad (opcional — la IA SIEMPRE la menciona)</label>
                  <Textarea ref={safetyRef} name="safety_note" defaultValue={product.safety_note ?? ''} placeholder="Ej.: Diluir antes de usar, no aplicar directo en la piel." className="min-h-[44px] text-sm resize-y" />
                </div>
              </div>
              <ImageUploadBox name="cover_image_url" defaultUrl={product.cover_image_url ?? ''} tenantId={tenantId} size="lg" label="Imagen portada" />

              {/* ADR-0029 D4: atributos PRODUCT-LEVEL guiados por el contrato (solo si la categoría lo tiene).
                  El save va por el PATCH validado; el hidden field serializa solo los del contrato no vacíos. */}
              {contractDefs.length > 0 && (
                <div className="space-y-2 pt-3 border-t border-border/40">
                  <input type="hidden" name="attributes" value={JSON.stringify(attrsPayload)} />
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">
                    Atributos de esta categoría <span className="normal-case font-normal text-muted-foreground/70">— el bot los cita como hechos</span>
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {contractDefs.map(d => {
                      const opts = (d.allowed_values ?? []).map(v => optionOf(d, String(v)))
                      const cur = prodAttrs[d.label] ?? ''
                      const orphan = cur && !opts.includes(cur) ? cur : null
                      return (
                        <div key={d.code || d.label} className="space-y-1">
                          <label className="text-[10px] text-muted-foreground">{d.label}{d.unit ? ` (${d.unit})` : ''}</label>
                          {opts.length > 0 ? (
                            <select value={cur} onChange={e => setProdAttr(d.label, e.target.value)}
                              className="w-full h-8 rounded-md border border-input bg-background text-sm px-2 text-foreground">
                              <option value="">— sin definir —</option>
                              {opts.map(o => <option key={o} value={o}>{o}</option>)}
                              {orphan && <option value={orphan}>{orphan} (fuera de contrato)</option>}
                            </select>
                          ) : (
                            <Input value={cur} onChange={e => setProdAttr(d.label, e.target.value)}
                              placeholder={d.type === 'boolean' ? 'Sí / No' : d.type === 'number' ? 'Número' : ''}
                              className="h-8 text-sm" />
                          )}
                        </div>
                      )
                    })}
                  </div>
                  <p className="text-[10px] text-muted-foreground/70">
                    Los de lista o número con unidad se validan contra sus opciones al guardar (anti-alucinación).
                  </p>
                </div>
              )}

              {/* Rev. 109 backlog #1 — Retracto categories multi-tenant.
                  Tenant marca productos excluidos del Art. 47 Ley 1480
                  parágrafo (cosmética abierta, software descargable,
                  perecederos, etc.). Multi-vertical agnóstico. */}
              <div className="space-y-2 pt-3 border-t border-border/40">
                <label className="flex items-start gap-2 text-xs font-medium cursor-pointer">
                  <input
                    type="checkbox"
                    name="retracto_excluded"
                    defaultChecked={product.retracto_excluded ?? false}
                    className="mt-0.5 accent-primary"
                  />
                  <span>
                    <span className="text-foreground">Excluir del retracto</span>
                    <span className="block text-[10px] text-muted-foreground font-normal mt-0.5">
                      Ley 1480 Art. 47 parágrafo (cosmética uso íntimo,
                      software descargable, perecederos, personalizados, etc.)
                    </span>
                  </span>
                </label>
                <div className="space-y-1 pl-6">
                  <label className="text-[10px] font-semibold text-muted-foreground uppercase">
                    Razón legal (visible al cliente si solicita retracto)
                  </label>
                  <Textarea
                    name="retracto_excluded_reason"
                    defaultValue={product.retracto_excluded_reason ?? ''}
                    placeholder="Ej. cosmética uso íntimo (Art. 47 parágrafo)"
                    className="min-h-[50px] text-xs resize-y"
                  />
                </div>
              </div>

              <div className="flex justify-end pt-1">
                <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado">Guardar información</SubmitButton>
              </div>
            </ActionResultForm>
          </Section>

          {/* ② VARIANTES */}
          <Section icon={Package2} title="Variantes">
            {/* Lista de variantes */}
            <div>
              {vars.map(v => (
                <VariantEditRow key={v.id} v={v} productId={product.id} threshold={threshold} tenantId={tenantId}
                  variantCount={vars.length}
                  editVariationAction={editVariationAction} deleteVariationAction={deleteVariationAction} />
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
              <ActionResultForm action={addVariationAction}
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
                  <div><label className="text-[10px] text-amber-600/90 uppercase font-semibold">Costo ($)</label><Input name="cost_price" type="number" min="0" step="50" placeholder="0" className="h-7 text-xs font-mono mt-1 border-amber-700/30" /></div>
                  <div><label className="text-[10px] text-muted-foreground uppercase font-semibold">Stock *</label><Input name="stock" type="number" min="0" defaultValue={0} required className="h-7 text-xs font-mono mt-1" /></div>
                </div>
                <div className="flex gap-2 justify-end">
                  <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado" className="h-7 text-xs">Guardar variante</SubmitButton>
                  <button type="button" onClick={() => setShowAddVar(false)} className="text-xs text-muted-foreground hover:text-foreground px-2">Cerrar</button>
                </div>
              </ActionResultForm>
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
                <ActionResultForm key={v.id} action={adjustStockAction} className="grid grid-cols-[1fr_52px_1fr_56px_44px] gap-2 items-center px-3 py-2">
                  <input type="hidden" name="variation_id" value={v.id} />
                  <input type="hidden" name="product_id" value={product.id} />
                  <span className="text-xs font-medium truncate">{fmtAttrs(v.attributes)}</span>
                  <span className={`text-xs font-mono text-right tabular-nums ${v.stock_quantity === 0 ? 'text-destructive' : v.stock_quantity <= threshold ? 'text-amber-700' : 'text-muted-foreground'}`}>{v.stock_quantity} u.</span>
                  <Input name="reason" placeholder="Ej: Compra proveedor..." required className="h-7 text-xs" />
                  <Input name="delta" type="number" placeholder="±0" required className="h-7 text-xs font-mono text-center" />
                  <SubmitButton size="sm" pendingText="..." savedText="✓" className="h-7 w-10 p-0 text-xs">OK</SubmitButton>
                </ActionResultForm>
              ))}
            </div>
            {/* Historial de movimientos — cierra la promesa del árbol funcional */}
            <StockMovementHistory product={product} tenantId={tenantId} />
          </Section>

          {/* Zona de peligro */}
          <div className="border-t border-border/40 pt-4">
            <ActionResultForm action={deactivateProductAction}>
              <input type="hidden" name="product_id" value={product.id} />
              <Button type="submit" variant="ghost" size="sm"
                className="h-7 text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/5 border border-transparent hover:border-destructive/20 gap-1.5">
                <Archive className="h-3 w-3" /> Archivar producto
              </Button>
            </ActionResultForm>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
