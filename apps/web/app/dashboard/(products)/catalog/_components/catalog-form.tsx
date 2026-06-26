'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Loader2, Zap, X, ChevronDown, ChevronUp } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { createClient } from '@/utils/supabase/client'
import { ImageUploadBox } from './image-upload-box'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface Attr { key: string; value: string }
interface VariantDraft {
  sku: string; attrs: Attr[]; price: number; compare_at_price: number | ''
  stock: number; cost_price: number | ''
  weight_kg: number | ''; length_cm: number | ''; width_cm: number | ''; height_cm: number | ''
  image_url: string
}
interface Props { apiUrl: string; onCreated?: () => void; categories?: {id: string, name: string}[]; tenantId: string }

const DEFAULT_VARIANT: VariantDraft = {
  sku: '', attrs: [{ key: '', value: '' }], price: 0, compare_at_price: '',
  stock: 0, cost_price: '', weight_kg: '', length_cm: '', width_cm: '', height_cm: '', image_url: '',
}

function attrsToObj(attrs: Attr[]): Record<string, string> {
  const obj: Record<string, string> = {}
  for (const a of attrs) if (a.key.trim() && a.value.trim()) obj[a.key.trim()] = a.value.trim()
  return obj
}

// ─── Generador de combinaciones (trabaja con estado local, sin product_id) ────

function cartesian(defs: { name: string; values: string[] }[]): Record<string, string>[] {
  return defs.reduce<Record<string, string>[]>((acc, def) => {
    if (!def.values.length) return acc
    if (!acc.length) return def.values.map(v => ({ [def.name]: v }))
    return acc.flatMap(combo => def.values.map(v => ({ ...combo, [def.name]: v })))
  }, [])
}

function normalize(s: string): string {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^A-Z0-9]/gi, '').toUpperCase()
}

function suggestPrefix(title: string): string {
  const stop = new Set(['de', 'del', 'la', 'el', 'los', 'las', 'y', 'e', 'o', 'u', 'con', 'en', 'a'])
  const words = title.trim().split(/\s+/).filter(w => !stop.has(w.toLowerCase()))
  return words.slice(0, 3).map(w => normalize(w).slice(0, 3)).join('-')
}

function InlineMatrixBuilder({ onGenerate, onClose, productTitle }: {
  onGenerate: (variants: VariantDraft[]) => void
  onClose: () => void
  productTitle: string
}) {
  const [defs, setDefs] = useState([{ name: '', values: [''] }])
  const [skuPrefix, setSkuPrefix] = useState(() => suggestPrefix(productTitle))
  const [prefixEdited, setPrefixEdited] = useState(false)
  const [bulkPrice, setBulkPrice] = useState('')
  const [bulkStock, setBulkStock] = useState('0')
  const [preview, setPreview] = useState<Record<string, string>[] | null>(null)

  const addDef = () => setDefs(d => [...d, { name: '', values: [''] }])
  const updateName = (i: number, name: string) => setDefs(d => d.map((def, idx) => idx === i ? { ...def, name } : def))
  const addValue = (i: number) => setDefs(d => d.map((def, idx) => idx === i ? { ...def, values: [...def.values, ''] } : def))
  const updateValue = (di: number, vi: number, val: string) =>
    setDefs(d => d.map((def, idx) => idx === di ? { ...def, values: def.values.map((v, j) => j === vi ? val : v) } : def))
  const removeValue = (di: number, vi: number) =>
    setDefs(d => d.map((def, idx) => idx === di ? { ...def, values: def.values.filter((_, j) => j !== vi) } : def))

  const handleGenerate = () => {
    const valid = defs.map(d => ({ name: d.name.trim(), values: d.values.map(v => v.trim()).filter(Boolean) })).filter(d => d.name && d.values.length)
    const combos = cartesian(valid)
    if (!combos.length) return
    setPreview(combos)
  }

  const handleConfirm = () => {
    if (!preview) return
    const price = parseFloat(bulkPrice) || 0
    const stock = parseInt(bulkStock) || 0
    const generated: VariantDraft[] = preview.map(attrs => {
      const suffix = Object.values(attrs).map(v => normalize(v).slice(0, 6)).join('-')
      const rawSku = skuPrefix ? `${skuPrefix}-${suffix}` : suffix
      return {
        ...DEFAULT_VARIANT,
        attrs: Object.entries(attrs).map(([key, value]) => ({ key, value })),
        sku: rawSku.slice(0, 50),
        price, stock,
      }
    })
    onGenerate(generated)
  }

  return (
    <div className="rounded-xl border border-border/40 bg-muted/10 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 bg-muted/30 border-b border-border/40">
        <p className="text-[11px] font-semibold text-foreground uppercase tracking-wider">Generador de variantes</p>
        <button type="button" onClick={onClose}><X className="h-3.5 w-3.5 text-muted-foreground" /></button>
      </div>
      <div className="p-4 space-y-4">
        <p className="text-xs text-muted-foreground">
          Define los atributos y sus opciones. El sistema crea todas las combinaciones automáticamente.
        </p>

        {/* Atributos */}
        {defs.map((def, di) => (
          <div key={di} className="space-y-2">
            <div className="flex items-center gap-2">
              <Input value={def.name} onChange={e => updateName(di, e.target.value)}
                placeholder="Atributo (Ej: Volumen, Color, Talla)" className="h-8 text-xs font-semibold" />
            </div>
            <div className="flex flex-wrap gap-1.5 pl-2">
              {def.values.map((val, vi) => (
                <div key={vi} className="flex items-center gap-1">
                  <Input value={val} onChange={e => updateValue(di, vi, e.target.value)}
                    placeholder={`Opción ${vi + 1}`} className="h-7 text-xs w-24" />
                  {def.values.length > 1 && (
                    <button type="button" onClick={() => removeValue(di, vi)}
                      className="text-muted-foreground hover:text-destructive"><X className="h-3 w-3" /></button>
                  )}
                </div>
              ))}
              <button type="button" onClick={() => addValue(di)}
                className="h-7 px-2 text-[11px] text-primary border border-primary/30 rounded-md hover:bg-primary/10">
                + opción
              </button>
            </div>
          </div>
        ))}

        <button type="button" onClick={addDef}
          className="text-[11px] text-primary hover:underline flex items-center gap-1">
          <Plus className="h-3 w-3" /> Otro atributo
        </button>

        {/* Prefijo SKU + Precio + Stock */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-border/30">
          <div className="sm:col-span-2">
            <label className="text-[10px] text-muted-foreground uppercase font-semibold">
              Prefijo SKU
              <span className="ml-1 normal-case font-normal text-muted-foreground/70">— se añade antes de cada variante</span>
            </label>
            <div className="flex items-center gap-1.5 mt-1">
              <Input value={skuPrefix}
                onChange={e => { setSkuPrefix(normalize(e.target.value).slice(0, 20)); setPrefixEdited(true) }}
                className="h-8 text-xs font-mono" placeholder="Ej: ACE-LAV" maxLength={20} />
              <span className="text-[10px] text-muted-foreground shrink-0">-[variante]</span>
              {productTitle && (
                <button type="button"
                  onClick={() => { setSkuPrefix(suggestPrefix(productTitle)); setPrefixEdited(false) }}
                  className="text-[10px] text-primary/70 hover:text-primary shrink-0 underline underline-offset-2">
                  ↺ del título
                </button>
              )}
            </div>
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground uppercase font-semibold">Precio para todas</label>
            <Input type="number" step="50" min="50" value={bulkPrice}
              onChange={e => setBulkPrice(e.target.value)} className="h-8 text-xs font-mono mt-1" placeholder="0" />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground uppercase font-semibold">Stock para todas</label>
            <Input type="number" min="0" value={bulkStock}
              onChange={e => setBulkStock(e.target.value)} className="h-8 text-xs font-mono mt-1" />
          </div>
        </div>

        {!preview ? (
          <button type="button" onClick={handleGenerate}
            className="inline-flex items-center gap-1.5 h-8 px-4 text-xs font-medium rounded-lg bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors">
            <Zap className="h-3.5 w-3.5" /> Vista previa de combinaciones
          </button>
        ) : (
          <div className="space-y-2">
            <p className="text-xs font-medium text-foreground">{preview.length} variantes que se crearán:</p>
            <div className="rounded-lg border border-border/40 divide-y divide-border/30 max-h-40 overflow-y-auto text-xs">
              <div className="grid grid-cols-2 px-3 py-1.5 bg-muted/30 font-semibold text-muted-foreground uppercase text-[10px]">
                <span>Variante</span><span>SKU generado</span>
              </div>
              {preview.map((combo, i) => {
                const suffix = Object.values(combo).map(v => normalize(v).slice(0, 6)).join('-')
                const sku = (skuPrefix ? `${skuPrefix}-${suffix}` : suffix).slice(0, 50)
                return (
                  <div key={i} className="grid grid-cols-2 px-3 py-1.5 text-muted-foreground">
                    <span>{Object.entries(combo).map(([k, v]) => `${k}: ${v}`).join(' · ')}</span>
                    <span className="font-mono text-foreground">{sku}</span>
                  </div>
                )
              })}
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={handleConfirm}
                className="inline-flex items-center gap-1.5 h-8 px-4 text-xs font-medium rounded-lg bg-foreground text-background hover:bg-foreground/80 transition-colors">
                Agregar {preview.length} variantes
              </button>
              <button type="button" onClick={() => setPreview(null)}
                className="text-xs text-muted-foreground hover:text-foreground px-3">Volver</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Variante individual ──────────────────────────────────────────────────────

function VariantForm({ v, idx, total, onChange, onRemove, tenantId }: {
  v: VariantDraft; idx: number; total: number; tenantId: string
  onChange: (field: keyof VariantDraft, val: unknown) => void
  onRemove: () => void
}) {
  const [showDims, setShowDims] = useState(false)

  const addAttr = () => onChange('attrs', [...v.attrs, { key: '', value: '' }])
  const removeAttr = (i: number) => onChange('attrs', v.attrs.filter((_, j) => j !== i))
  const updateAttr = (i: number, field: 'key' | 'value', val: string) =>
    onChange('attrs', v.attrs.map((a, j) => j === i ? { ...a, [field]: val } : a))

  return (
    <div className="rounded-xl border border-border/60 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-muted/30 border-b border-border/40">
        <span className="text-xs font-semibold text-foreground">
          {v.sku || `Variante ${idx + 1}`}
          {v.attrs.filter(a => a.key && a.value).length > 0 && (
            <span className="font-normal text-muted-foreground ml-1.5">
              — {v.attrs.filter(a => a.key && a.value).map(a => `${a.key}: ${a.value}`).join(', ')}
            </span>
          )}
        </span>
        {total > 1 && (
          <button type="button" onClick={onRemove}
            className="text-muted-foreground hover:text-destructive transition-colors">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      <div className="p-4 space-y-3">
        {/* Atributos */}
        <div className="space-y-1.5">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase">Atributos (tamaño, color, aroma…)</label>
          {v.attrs.map((attr, i) => (
            <div key={i} className="flex gap-1.5 items-center">
              <Input value={attr.key} onChange={e => updateAttr(i, 'key', e.target.value)}
                placeholder="Propiedad (Ej: Volumen)" className="h-7 text-xs flex-1" />
              <Input value={attr.value} onChange={e => updateAttr(i, 'value', e.target.value)}
                placeholder="Valor (Ej: 100ml)" className="h-7 text-xs flex-1" />
              {v.attrs.length > 1 && (
                <button type="button" onClick={() => removeAttr(i)}
                  className="text-muted-foreground hover:text-destructive"><X className="h-3 w-3" /></button>
              )}
            </div>
          ))}
          <button type="button" onClick={addAttr} className="text-[11px] text-primary hover:underline">+ atributo</button>
        </div>

        {/* Precio, stock, SKU */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <div>
            <label className="text-[10px] text-muted-foreground uppercase font-semibold">Precio *</label>
            <Input type="number" step="50" min="50" value={v.price || ''}
              onChange={e => onChange('price', parseFloat(e.target.value) || 0)}
              className="h-8 text-xs font-mono mt-1" placeholder="0" />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground uppercase font-semibold">Precio anterior</label>
            <Input type="number" step="50" value={v.compare_at_price}
              onChange={e => onChange('compare_at_price', parseFloat(e.target.value) || '')}
              className="h-8 text-xs font-mono mt-1 border-dashed bg-muted/20" placeholder="Opcional" />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground uppercase font-semibold">Stock *</label>
            <Input type="number" min="0" value={v.stock}
              onChange={e => onChange('stock', parseInt(e.target.value) || 0)}
              className="h-8 text-xs font-mono mt-1" />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground uppercase font-semibold">SKU *</label>
            <Input value={v.sku} onChange={e => onChange('sku', e.target.value.toUpperCase())}
              className="h-8 text-xs font-mono mt-1" placeholder="PROD-001" maxLength={50} />
          </div>
          <div>
            <label className="text-[10px] text-amber-600/90 uppercase font-semibold">Costo ($)</label>
            <Input type="number" step="50" min="0" value={v.cost_price}
              onChange={e => onChange('cost_price', parseFloat(e.target.value) || '')}
              className="h-8 text-xs font-mono mt-1 border-amber-500/30" placeholder="Para margen" />
          </div>
        </div>

        {/* Foto de la variante */}
        <ImageUploadBox name={`image_url_${idx}`} defaultUrl={v.image_url}
          tenantId={tenantId} size="sm" label="Foto de esta variante (opcional)"
          onUrlChange={url => onChange('image_url', url)} key={`img-${idx}`} />

        {/* Dimensiones */}
        <button type="button" onClick={() => setShowDims(d => !d)}
          className="flex items-center gap-1 text-[10px] text-primary/70 font-medium hover:text-primary transition-colors">
          {showDims ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {showDims ? 'Ocultar dimensiones' : 'Dimensiones y peso (Envia)'}
        </button>
        {showDims && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 border-t border-border/30">
            {([['weight_kg','Peso (kg)','0.1'],['length_cm','Largo (cm)','10'],['width_cm','Ancho (cm)','10'],['height_cm','Alto (cm)','5']] as const).map(([f,l,p]) => (
              <div key={f}>
                <label className="text-[10px] text-muted-foreground uppercase">{l}</label>
                <Input type="number" step="0.01" min="0" value={v[f]}
                  onChange={e => onChange(f, parseFloat(e.target.value) || '')}
                  className="h-7 text-xs font-mono mt-1" placeholder={p} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Formulario principal ─────────────────────────────────────────────────────

export default function CatalogForm({ onCreated = () => {}, categories = [], tenantId }: Props) {
  const router = useRouter()
  const [title, setTitle]           = useState('')
  const [description, setDescription] = useState('')
  const [safetyNote, setSafetyNote] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [coverUrl, setCoverUrl]     = useState('')
  const [variants, setVariants]     = useState<VariantDraft[]>([{ ...DEFAULT_VARIANT }])
  const [showMatrix, setShowMatrix] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]           = useState<string | null>(null)

  const updateVariant = (idx: number, field: keyof VariantDraft, val: unknown) =>
    setVariants(prev => prev.map((v, i) => i === idx ? { ...v, [field]: val } : v))

  const addVariant = () => setVariants(prev => [...prev, { ...DEFAULT_VARIANT }])
  const removeVariant = (idx: number) => setVariants(prev => prev.filter((_, i) => i !== idx))

  const handleSubmit = async () => {
    if (!title.trim()) { setError('El nombre del producto es obligatorio'); return }
    if (variants.some(v => !v.sku.trim())) { setError('Todas las variantes deben tener un SKU'); return }
    if (variants.some(v => v.price <= 0)) { setError('Todos los precios deben ser mayores a 0'); return }

    setSubmitting(true); setError(null)
    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string }
    if (!session?.access_token || !meta.tenant_id) { setError('Sesión expirada'); setSubmitting(false); return }

    try {
      const { data: prod, error: e1 } = await supabase.from('products').insert({
        tenant_id: meta.tenant_id, platform_category_id: categoryId || null,
        title: title.trim(), description: description.trim() || null,
        safety_note: safetyNote.trim() || null,
        cover_image_url: coverUrl.trim() || null, status: 'active',
      }).select().single()
      if (e1 || !prod) throw new Error(e1?.message ?? 'Error al crear producto')

      const payload = variants.map(v => {
        let finalPrice = v.price > 0 ? v.price : 1
        let finalCompare: number | null = null
        const promo = v.compare_at_price === '' ? null : Number(v.compare_at_price)
        if (promo && promo > 0 && promo < finalPrice) { finalCompare = finalPrice; finalPrice = promo }
        return {
          product_id: prod.id, tenant_id: meta.tenant_id, sku: v.sku.trim(),
          price: finalPrice, compare_at_price: finalCompare,
          cost_price: v.cost_price === '' ? 0 : Number(v.cost_price),
          stock_quantity: v.stock, attributes: attrsToObj(v.attrs),
          weight_kg: v.weight_kg === '' ? null : v.weight_kg,
          length_cm: v.length_cm === '' ? null : v.length_cm,
          width_cm:  v.width_cm  === '' ? null : v.width_cm,
          height_cm: v.height_cm === '' ? null : v.height_cm,
          image_url: v.image_url || null,
        }
      })

      const { error: e2 } = await supabase.from('product_variations').insert(payload)
      if (e2) throw new Error(e2.message)

      setTitle(''); setDescription(''); setSafetyNote(''); setVariants([{ ...DEFAULT_VARIANT }]); setCoverUrl('')
      onCreated(); router.refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al crear producto')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-5">

      {/* ① INFORMACIÓN */}
      <div className="space-y-3">
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">① Información</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] font-semibold text-muted-foreground uppercase">Nombre *</label>
            <Input value={title} onChange={e => setTitle(e.target.value)}
              placeholder="Ej: Aceite Esencial de Lavanda" className="h-8 text-sm mt-1" />
          </div>
          <div>
            <label className="text-[10px] font-semibold text-muted-foreground uppercase">Categoría</label>
            <select value={categoryId} onChange={e => setCategoryId(e.target.value)}
              className="w-full h-8 rounded-md border border-input bg-background text-sm px-2 mt-1 text-foreground">
              <option value="">Sin categoría</option>
              {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="text-[10px] font-semibold text-muted-foreground uppercase">Descripción (la IA la usa para responder sobre el producto)</label>
            <Textarea value={description} onChange={e => setDescription(e.target.value)}
              placeholder="Ingredientes, beneficios, cómo usarlo..." className="min-h-[70px] text-sm resize-y mt-1" />
          </div>
          <div className="sm:col-span-2">
            <label className="text-[10px] font-semibold text-muted-foreground uppercase">⚠️ Nota de seguridad (opcional — la IA SIEMPRE la menciona)</label>
            <Textarea value={safetyNote} onChange={e => setSafetyNote(e.target.value)}
              placeholder="Ej.: Diluir antes de usar, no aplicar directo en la piel." className="min-h-[44px] text-sm resize-y mt-1" />
          </div>
        </div>
        <ImageUploadBox name="cover_image_url" defaultUrl={coverUrl}
          tenantId={tenantId} size="lg" label="Imagen portada del producto"
          onUrlChange={setCoverUrl} key="cover" />
      </div>

      {/* ② VARIANTES */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">② Variantes</p>
          <div className="flex gap-2">
            <button type="button" onClick={addVariant}
              className="inline-flex items-center gap-1 h-6 px-2.5 text-[11px] font-medium rounded-md border border-primary/30 text-primary bg-primary/5 hover:bg-primary/10 transition-colors">
              <Plus className="h-3 w-3" /> Agregar
            </button>
            <button type="button" onClick={() => setShowMatrix(m => !m)}
              className="inline-flex items-center gap-1 h-6 px-2.5 text-[11px] font-medium rounded-md border border-border text-muted-foreground bg-muted/30 hover:bg-muted hover:text-foreground transition-colors">
              <Zap className="h-3 w-3" /> Generar variantes
            </button>
          </div>
        </div>

        {showMatrix && (
          <InlineMatrixBuilder
            productTitle={title}
            onGenerate={generated => {
              setVariants(generated)
              setShowMatrix(false)
            }}
            onClose={() => setShowMatrix(false)}
          />
        )}

        <div className="space-y-3">
          {variants.map((v, idx) => (
            <VariantForm key={idx} v={v} idx={idx} total={variants.length}
              tenantId={tenantId}
              onChange={(field, val) => updateVariant(idx, field, val)}
              onRemove={() => removeVariant(idx)} />
          ))}
        </div>
      </div>

      {/* Error + Guardar */}
      {error && (
        <p className="text-xs text-red-500 font-medium bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>
      )}

      <button type="button" onClick={handleSubmit} disabled={submitting}
        className="w-full h-10 rounded-lg bg-foreground text-background text-sm font-medium hover:bg-foreground/80 disabled:opacity-60 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2">
        {submitting ? <><Loader2 className="h-4 w-4 animate-spin" />Guardando...</> : 'Guardar producto'}
      </button>
    </div>
  )
}
