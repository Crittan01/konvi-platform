'use client'

import { useState } from 'react'
import { Plus, Trash2, Loader2, Upload, Image as ImageIcon, Check, Info, Layers } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { createClient } from '@/utils/supabase/client'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface Attr { key: string; value: string }
interface VariantDraft {
  sku: string; attrs: Attr[]; price: number; compare_at_price: number | ''; stock: number;
  weight_kg: number | ''; length_cm: number | ''; width_cm: number | ''; height_cm: number | ''; image_url: string;
}
interface Props { apiUrl: string; onCreated?: () => void; categories?: {id: string, name: string}[]; tenantId: string }

const DEFAULT_VARIANT: VariantDraft = {
  sku: '', attrs: [{ key: 'Talla', value: '' }], price: 0, compare_at_price: '', stock: 0,
  weight_kg: '', length_cm: '', width_cm: '', height_cm: '', image_url: ''
}

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

export default function CatalogForm({ apiUrl, onCreated = () => {}, categories = [], tenantId }: Props) {
  const [platformCategoryId, setPlatformCategoryId] = useState('')
  const [coverImageUrl, setCoverImageUrl] = useState('')
  const [uploadingCover, setUploadingCover] = useState(false)
  const [uploadingVariantIdx, setUploadingVariantIdx] = useState<number | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [variants, setVariants] = useState<VariantDraft[]>([{ ...DEFAULT_VARIANT }])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── Variantes ───────────────────────────────────────────────────────────────

  const addVariant = () => setVariants(prev => [
    ...prev,
    { ...DEFAULT_VARIANT },
  ])

  const removeVariant = (idx: number) => {
    if (variants.length === 1) return
    setVariants(prev => prev.filter((_, i) => i !== idx))
  }

  const updateVariantField = (idx: number, field: keyof VariantDraft, val: any) =>
    setVariants(prev => prev.map((v, i) => i === idx ? { ...v, [field]: val } : v))

  // ── Upload ──────────────────────────────────────────────────────────────────
  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>, variantIdx?: number) {
    const file = e.target.files?.[0]
    if (!file || !tenantId) return

    const isCover = variantIdx === undefined
    if (isCover) setUploadingCover(true)
    else setUploadingVariantIdx(variantIdx)
    setError(null)

    try {
      const ext = file.name.split('.').pop()
      const filename = `${Date.now()}-${Math.random().toString(36).slice(2)}.${ext}`
      const path = `${tenantId}/${filename}`
      const supabase = createClient()
      const { error: uploadError } = await supabase.storage.from('tenant-media').upload(path, file)
      if (uploadError) throw new Error(uploadError.message)
      const { data } = supabase.storage.from('tenant-media').getPublicUrl(path)

      if (isCover) {
        setCoverImageUrl(data.publicUrl)
      } else {
        updateVariantField(variantIdx, 'image_url', data.publicUrl)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al subir imagen')
    } finally {
      if (isCover) setUploadingCover(false)
      else setUploadingVariantIdx(null)
    }
  }

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
    if (variants.some(v => !v.sku.trim())) { setError('Todas las variantes deben tener un SKU (Obligatorio)'); return }
    if (variants.some(v => v.price <= 0)) { setError('Todos los precios normales deben ser mayores a 0'); return }

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
          platform_category_id: platformCategoryId || null,
          title: title.trim(),
          description: description.trim() || null,
          cover_image_url: coverImageUrl.trim() || null,
          status: 'active',
        })
        .select()
        .single()

      if (prodErr || !prod) throw new Error(prodErr?.message ?? 'Error al crear producto')

      // Crear variantes
      const variationsPayload = variants.map(v => {
        let finalPrice = v.price > 0 ? v.price : 1;
        let finalCompare = null;
        const promo = v.compare_at_price === '' ? null : Number(v.compare_at_price);

        // Lógica de inversión automática de promoción
        if (promo && promo > 0 && promo < finalPrice) {
          finalPrice = promo;
          finalCompare = v.price; // El "Precio Normal" original pasa a ser el tachado
        }

        return {
          product_id: prod.id,
          tenant_id: meta.tenant_id,
          sku: v.sku.trim(),
          price: finalPrice,
          compare_at_price: finalCompare,
          stock_quantity: v.stock,
          attributes: attrsToObj(v.attrs),
          weight_kg: v.weight_kg === '' ? null : v.weight_kg,
          length_cm: v.length_cm === '' ? null : v.length_cm,
          width_cm: v.width_cm === '' ? null : v.width_cm,
          height_cm: v.height_cm === '' ? null : v.height_cm,
          image_url: v.image_url.trim() || null,
        }
      })

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
        <Tabs defaultValue="general" className="w-full">
          <TabsList className="grid w-full grid-cols-2 mb-4 h-auto">
            <TabsTrigger value="general" className="flex items-center gap-1.5 py-2.5 text-xs sm:text-sm">
              <Info className="h-3.5 w-3.5 flex-shrink-0" />
              <span className="hidden xs:inline sm:inline">Info</span>
              <span className="hidden sm:inline"> General</span>
            </TabsTrigger>
            <TabsTrigger value="variants" className="flex items-center gap-1.5 py-2.5 text-xs sm:text-sm">
              <Layers className="h-3.5 w-3.5 flex-shrink-0" />
              <span className="hidden xs:inline sm:inline">Variantes</span>
              <span className="hidden sm:inline"> e Inventario</span>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="general" className="space-y-4 mt-2">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
            <Label>Nombre del Producto *</Label>
            <Input value={title} onChange={e => setTitle(e.target.value)} placeholder="Ej: Zapatillas Pro V2" />
          </div>
          <div className="space-y-2">
            <Label>Categoría Global</Label>
            <select
              value={platformCategoryId}
              onChange={e => setPlatformCategoryId(e.target.value)}
              className="w-full h-10 px-3 py-2 rounded-md border border-input text-sm bg-background"
            >
              <option value="">-- Seleccionar Categoría --</option>
              {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
        </div>

        <div className="space-y-2">
          <Label>Descripción</Label>
          <Input value={description} onChange={e => setDescription(e.target.value)} placeholder="Breve descripción..." />
        </div>

        <div className="space-y-2">
          <Label>Imagen Principal</Label>
          <div className="flex items-center gap-3">
            {coverImageUrl ? (
              <div className="relative h-16 w-16 border border-border rounded-lg bg-muted overflow-hidden flex-shrink-0">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={coverImageUrl} alt="Cover" className="object-cover w-full h-full" />
                <button type="button" onClick={() => setCoverImageUrl('')} className="absolute top-1 right-1 bg-black/60 text-white p-0.5 rounded-full hover:bg-black">
                  <Plus className="h-3 w-3 rotate-45" />
                </button>
              </div>
            ) : null}
            <div className="relative overflow-hidden inline-block">
              <input type="file" accept="image/*" onChange={handleFileUpload} disabled={uploadingCover} className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed" />
              <Button type="button" variant="outline" disabled={uploadingCover} className="gap-2 h-9 text-sm">
                {uploadingCover ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {uploadingCover ? 'Subiendo...' : 'Subir Foto'}
              </Button>
            </div>
          </div>
        </div>
        </TabsContent>

        <TabsContent value="variants" className="space-y-4 mt-2">
        <div className="flex items-center justify-between bg-muted/20 p-3 rounded-lg border border-border/50">
          <div className="space-y-0.5">
            <Label className="text-base">Variantes de Producto</Label>
            <p className="text-xs text-muted-foreground mr-4">Agrega tallas, colores y gestiona el inventario ({variants.length} en total)</p>
          </div>
          <Button type="button" size="sm" variant="secondary" onClick={addVariant} className="h-8 text-xs gap-1.5 flex-shrink-0">
            <Plus className="h-3.5 w-3.5" /> Añadir variante
          </Button>
        </div>

        <Accordion type="multiple" defaultValue={["item-0"]} className="w-full space-y-3">
          {variants.map((v, vIdx) => (
            <AccordionItem key={vIdx} value={`item-${vIdx}`} className="border border-border/60 bg-card rounded-lg px-4 shadow-sm overflow-hidden data-[state=open]:border-primary/30">
              <AccordionTrigger className="hover:no-underline py-4">
                <div className="flex items-center gap-3 text-left">
                  <span className="text-sm font-semibold">{v.sku || `Variante ${vIdx + 1}`}</span>
                  <span className="text-xs text-muted-foreground hidden sm:inline-block">— {variantLabel(v)}</span>
                  {v.price > 0 && (
                     <div className="flex items-center gap-1.5 ml-2">
                       {v.compare_at_price && Number(v.compare_at_price) > 0 && Number(v.compare_at_price) < v.price ? (
                         <>
                           <span className="text-[10px] text-muted-foreground line-through">${v.price}</span>
                           <span className="text-[10px] font-bold border border-green-500/20 text-green-600 px-2 py-0.5 rounded-full bg-green-500/10">${v.compare_at_price}</span>
                         </>
                       ) : (
                         <span className="text-[10px] font-medium border border-primary/20 text-primary px-2 py-0.5 rounded-full bg-primary/5">${v.price}</span>
                       )}
                     </div>
                  )}
                </div>
              </AccordionTrigger>
              <AccordionContent className="pt-2 pb-5 space-y-5 border-t border-border/30 mt-1">
                <div className="flex justify-end p-0 m-0">
                  {variants.length > 1 && (
                    <button type="button" onClick={() => removeVariant(vIdx)} className="text-muted-foreground hover:text-destructive flex items-center gap-1.5 text-xs font-medium -mt-2 bg-destructive/5 px-2 py-1 rounded">
                      <Trash2 className="h-3.5 w-3.5" /> Eliminar
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

              {/* Pricing, SKU y Configuración de Stock */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-muted-foreground uppercase">SKU *</label>
                  <Input
                    value={v.sku}
                    onChange={e => updateVariantField(vIdx, 'sku', e.target.value.toUpperCase())}
                    className="h-8 text-xs font-mono"
                    placeholder="PROD-001"
                    maxLength={50}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-muted-foreground uppercase">Precio Normal ($) *</label>
                  <Input
                    type="number" step="1" min="1"
                    value={v.price === 0 ? '' : v.price}
                    onChange={e => updateVariantField(vIdx, 'price', parseFloat(e.target.value) || 0)}
                    className="h-8 text-xs font-mono"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-muted-foreground uppercase">Precio Promo ($)</label>
                  <Input
                    type="number" step="1" min="1"
                    value={v.compare_at_price}
                    onChange={e => updateVariantField(vIdx, 'compare_at_price', parseFloat(e.target.value) || '')}
                    className="h-8 text-xs font-mono placeholder:text-muted-foreground/50"
                    placeholder="Opcional"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-medium text-muted-foreground uppercase">Inventario</label>
                  <Input
                    type="number" min="0"
                    value={v.stock}
                    onChange={e => updateVariantField(vIdx, 'stock', parseInt(e.target.value) || 0)}
                    className="h-8 text-xs"
                  />
                </div>
              </div>

              {/* Opciones Avanzadas (Dimensiones e Imagen Variante) */}
              <div className="space-y-3 bg-muted/40 p-3 rounded-lg border border-border/40">
                <div className="flex items-center gap-2">
                  <div className="relative overflow-hidden inline-block">
                    <input type="file" accept="image/*" onChange={e => handleFileUpload(e, vIdx)} disabled={uploadingVariantIdx === vIdx} className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed" />
                    <Button type="button" variant="secondary" size="sm" disabled={uploadingVariantIdx === vIdx} className="h-7 text-xs gap-1.5 px-2">
                      {uploadingVariantIdx === vIdx ? <Loader2 className="h-3 w-3 animate-spin" /> : <ImageIcon className="h-3 w-3" />}
                      Foto Variante
                    </Button>
                  </div>
                  {v.image_url && (
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground bg-background px-2 py-1 rounded border">
                      <Check className="h-3 w-3 text-green-500" /> Adjunta
                      <button type="button" onClick={() => updateVariantField(vIdx, 'image_url', '')} className="text-secondary-foreground hover:text-destructive shrink-0 ml-1">
                        <Plus className="h-3 w-3 rotate-45" />
                      </button>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="space-y-1">
                    <label className="text-[10px] text-muted-foreground uppercase">Peso (kg)</label>
                    <Input type="number" step="0.001" value={v.weight_kg} onChange={e => updateVariantField(vIdx, 'weight_kg', parseFloat(e.target.value) || '')} className="h-7 text-xs bg-background" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] text-muted-foreground uppercase">Largo (cm)</label>
                    <Input type="number" step="0.01" value={v.length_cm} onChange={e => updateVariantField(vIdx, 'length_cm', parseFloat(e.target.value) || '')} className="h-7 text-xs bg-background" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] text-muted-foreground uppercase">Ancho (cm)</label>
                    <Input type="number" step="0.01" value={v.width_cm} onChange={e => updateVariantField(vIdx, 'width_cm', parseFloat(e.target.value) || '')} className="h-7 text-xs bg-background" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] text-muted-foreground uppercase">Alto (cm)</label>
                    <Input type="number" step="0.01" value={v.height_cm} onChange={e => updateVariantField(vIdx, 'height_cm', parseFloat(e.target.value) || '')} className="h-7 text-xs bg-background" />
                  </div>
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
        </TabsContent>
        </Tabs>

        {error && <p className="text-xs text-red-500 font-medium px-1 bg-red-500/10 p-2 rounded">{error}</p>}

        <div className="pt-4 mt-2 border-t border-border">
            <Button type="button" onClick={handleSubmit} disabled={submitting} className="w-full sm:w-auto sm:min-w-[200px]">
              {submitting ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Guardando...</> : 'Guardar Producto'}
            </Button>
        </div>
      </CardContent>
    </Card>
  )
}
