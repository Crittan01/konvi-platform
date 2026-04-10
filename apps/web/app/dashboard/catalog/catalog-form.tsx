'use client'

import { useState } from 'react'
import { Plus, Trash2, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { createClient } from '@/utils/supabase/client'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface Attr { key: string; value: string }
interface VariantDraft { attrs: Attr[]; price: number; stock: number }
interface Props { apiUrl: string; onCreated: () => void }

const DEFAULT_VARIANT: VariantDraft = { attrs: [{ key: 'Talla', value: '' }], price: 0, stock: 0 }

// ─── Helpers ──────────────────────────────────────────────────────────────────

function attrsToObj(attrs: Attr[]): Record<string, string> {
  const obj: Record<string, string> = {}
  for (const a of attrs) if (a.key.trim() && a.value.trim()) obj[a.key.trim()] = a.value.trim()
  return obj
}

function variantLabel(v: VariantDraft): string {
  const filled = v.attrs.filter(a => a.key.trim() && a.value.trim())
  if (filled.length === 0) return 'Estándar'
  return filled.map(a => `${a.key}: ${a.value}`).join(', ')
}

// ─── Componente ───────────────────────────────────────────────────────────────

export default function CatalogForm({ apiUrl, onCreated }: Props) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [variants, setVariants] = useState<VariantDraft[]>([{ ...DEFAULT_VARIANT }])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── Variantes ───────────────────────────────────────────────────────────────

  const addVariant = () => setVariants(prev => [
    ...prev,
    { attrs: [{ key: 'Talla', value: '' }], price: 0, stock: 0 },
  ])

  const removeVariant = (idx: number) => {
    if (variants.length === 1) return
    setVariants(prev => prev.filter((_, i) => i !== idx))
  }

  const updateVariantField = (idx: number, field: 'price' | 'stock', val: number) =>
    setVariants(prev => prev.map((v, i) => i === idx ? { ...v, [field]: val } : v))

  const addAttr = (vIdx: number) =>
    setVariants(prev => prev.map((v, i) =>
      i === vIdx ? { ...v, attrs: [...v.attrs, { key: '', value: '' }] } : v
    ))

  const removeAttr = (vIdx: number, aIdx: number) =>
    setVariants(prev => prev.map((v, i) =>
      i === vIdx ? { ...v, attrs: v.attrs.filter((_, j) => j !== aIdx) } : v
    ))

  const updateAttr = (vIdx: number, aIdx: number, field: 'key' | 'value', val: string) =>
    setVariants(prev => prev.map((v, i) =>
      i === vIdx
        ? { ...v, attrs: v.attrs.map((a, j) => j === aIdx ? { ...a, [field]: val } : a) }
        : v
    ))

  // ── Submit ──────────────────────────────────────────────────────────────────

  const handleSubmit = async () => {
    if (!title.trim()) { setError('El nombre del producto es obligatorio'); return }
    if (variants.some(v => v.price <= 0)) { setError('Todos los precios deben ser mayores a 0'); return }

    setSubmitting(true)
    setError(null)

    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token
    const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!token || !meta.tenant_id) { setError('Sesión expirada'); setSubmitting(false); return }

    try {
      // Crear producto
      const { data: prod, error: prodErr } = await supabase
        .from('products')
        .insert({
          tenant_id: meta.tenant_id,
          title: title.trim(),
          description: description.trim() || null,
          status: 'active',
        })
        .select()
        .single()

      if (prodErr || !prod) throw new Error(prodErr?.message ?? 'Error al crear producto')

      // Crear variantes
      const variationsPayload = variants.map(v => ({
        product_id: prod.id,
        tenant_id: meta.tenant_id,
        price: v.price,
        stock_quantity: v.stock,
        attributes: attrsToObj(v.attrs),
      }))

      const { error: varErr } = await supabase
        .from('product_variations')
        .insert(variationsPayload)

      if (varErr) throw new Error(varErr.message)

      // Reset
      setTitle('')
      setDescription('')
      setVariants([{ ...DEFAULT_VARIANT }])
      onCreated()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al crear producto')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">Añadir Producto</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">

        <div className="space-y-2">
          <Label>Nombre *</Label>
          <Input value={title} onChange={e => setTitle(e.target.value)} placeholder="Ej: Zapatillas Pro V2" />
        </div>

        <div className="space-y-2">
          <Label>Descripción</Label>
          <Input value={description} onChange={e => setDescription(e.target.value)} placeholder="Breve descripción..." />
        </div>

        {/* Variantes */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Variantes ({variants.length})</Label>
            <Button type="button" size="sm" variant="outline" onClick={addVariant} className="h-7 text-xs gap-1">
              <Plus className="h-3 w-3" /> Añadir variante
            </Button>
          </div>

          {variants.map((v, vIdx) => (
            <div key={vIdx} className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">
                  Variante {vIdx + 1} — {variantLabel(v)}
                </span>
                {variants.length > 1 && (
                  <button type="button" onClick={() => removeVariant(vIdx)} className="text-muted-foreground hover:text-destructive">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              {/* Atributos */}
              <div className="space-y-1">
                {v.attrs.map((attr, aIdx) => (
                  <div key={aIdx} className="flex gap-1.5 items-center">
                    <Input
                      value={attr.key}
                      onChange={e => updateAttr(vIdx, aIdx, 'key', e.target.value)}
                      placeholder="Talla"
                      className="h-7 text-xs w-24 flex-shrink-0"
                    />
                    <span className="text-muted-foreground text-xs">:</span>
                    <Input
                      value={attr.value}
                      onChange={e => updateAttr(vIdx, aIdx, 'value', e.target.value)}
                      placeholder="M"
                      className="h-7 text-xs flex-1"
                    />
                    {v.attrs.length > 1 && (
                      <button type="button" onClick={() => removeAttr(vIdx, aIdx)} className="text-muted-foreground hover:text-destructive flex-shrink-0">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => addAttr(vIdx)}
                  className="text-xs text-primary hover:underline"
                >
                  + atributo
                </button>
              </div>

              {/* Precio y stock */}
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-0.5">
                  <label className="text-xs text-muted-foreground">Precio ($)</label>
                  <Input
                    type="number" step="0.01" min="0.01"
                    value={v.price || ''}
                    onChange={e => updateVariantField(vIdx, 'price', parseFloat(e.target.value) || 0)}
                    className="h-7 text-xs"
                  />
                </div>
                <div className="space-y-0.5">
                  <label className="text-xs text-muted-foreground">Stock</label>
                  <Input
                    type="number" min="0"
                    value={v.stock}
                    onChange={e => updateVariantField(vIdx, 'stock', parseInt(e.target.value) || 0)}
                    className="h-7 text-xs"
                  />
                </div>
              </div>
            </div>
          ))}
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}

        <Button type="button" onClick={handleSubmit} disabled={submitting} className="w-full">
          {submitting ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Guardando...</> : 'Guardar producto'}
        </Button>
      </CardContent>
    </Card>
  )
}
