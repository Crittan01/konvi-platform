import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ShoppingBag, Package, ChevronDown, Plus } from 'lucide-react'
import CatalogForm from './catalog-form'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

type Variation = { id: string; price: number; stock_quantity: number; attributes: Record<string, string> | null }
type Product = {
  id: string
  title: string
  description: string | null
  status: string
  product_variations: Variation[]
}

function formatAttributes(attrs: Record<string, string> | null): string {
  if (!attrs || Object.keys(attrs).length === 0) return 'Estándar'
  return Object.entries(attrs).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

export default async function CatalogPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  let products: Product[] = []
  if (tenantId) {
    const { data } = await supabase
      .from('products')
      .select('id, title, description, status, product_variations(id, price, stock_quantity, attributes)')
      .eq('tenant_id', tenantId)
      .eq('status', 'active')
      .order('title')
    products = (data as Product[]) || []
  }

  const totalVariations = products.reduce((s, p) => s + p.product_variations.length, 0)
  const totalStock      = products.flatMap(p => p.product_variations).reduce((s, v) => s + (v.stock_quantity ?? 0), 0)

  // ── Server Actions ─────────────────────────────────────────────────────────

  async function editProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('products').update({
      title: formData.get('title') as string,
      description: (formData.get('description') as string) || null,
    }).eq('id', formData.get('product_id') as string).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/catalog')
  }

  async function editVariation(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('product_variations').update({
      price: parseFloat(formData.get('price') as string),
      stock_quantity: parseInt(formData.get('stock') as string),
    }).eq('id', formData.get('variation_id') as string).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/catalog')
  }

  async function deactivateProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('products').update({ status: 'inactive' })
      .eq('id', formData.get('product_id') as string).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/catalog')
  }

  // ── UI ─────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <ShoppingBag className="h-5 w-5 text-primary" /> Catálogo
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {products.length} productos activos · {totalVariations} variantes · {totalStock} unidades en stock
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

        {/* Formulario multi-variante */}
        {canWrite && (
          <div className="xl:col-span-1">
            <div className="rounded-xl border border-border bg-card overflow-hidden sticky top-4">
              <div className="px-5 py-4 border-b border-border bg-muted/20">
                <p className="text-sm font-semibold flex items-center gap-1.5"><Plus className="h-4 w-4" /> Nuevo producto</p>
              </div>
              <div className="p-5">
                <CatalogForm apiUrl={API_URL} />
              </div>
            </div>
          </div>
        )}

        {/* Lista de productos */}
        <div className={canWrite ? 'xl:col-span-2' : 'xl:col-span-3'}>
          {products.length === 0 ? (
            <div className="flex flex-col items-center py-16 rounded-xl border border-dashed border-border text-center">
              <Package className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground text-sm font-medium">El catálogo está vacío.</p>
              {canWrite && (
                <p className="text-xs text-muted-foreground mt-1">Agrega productos para que la IA pueda venderlos por WhatsApp.</p>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {products.map(p => {
                const vars = p.product_variations ?? []
                const v0 = vars[0]
                const priceRange = vars.length > 1
                  ? `$${Math.min(...vars.map(v => v.price)).toLocaleString('es-MX')} – $${Math.max(...vars.map(v => v.price)).toLocaleString('es-MX')}`
                  : `$${v0?.price?.toLocaleString('es-MX') ?? '—'}`
                const totalStock = vars.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)
                const hasLowStock = vars.some(v => v.stock_quantity === 0)

                return (
                  <div key={p.id} className={`rounded-xl border bg-card overflow-hidden transition-all hover:shadow-sm ${
                    hasLowStock ? 'border-red-500/30' : 'border-border'
                  }`}>
                    {/* Product header */}
                    <div className="px-4 py-3.5 flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="font-semibold text-sm truncate">{p.title}</p>
                          {hasLowStock && (
                            <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full bg-red-500/15 text-red-400 border border-red-500/30">
                              Sin stock
                            </span>
                          )}
                        </div>
                        {p.description && (
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">{p.description}</p>
                        )}
                        {/* Variante chips */}
                        {vars.length > 1 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {vars.map(v => (
                              <span key={v.id} className={`text-[10px] px-2 py-0.5 rounded-full border ${
                                v.stock_quantity === 0
                                  ? 'bg-red-500/10 text-red-400 border-red-500/20'
                                  : 'bg-muted text-muted-foreground border-border'
                              }`}>
                                {formatAttributes(v.attributes)} · ${v.price} · {v.stock_quantity}u
                              </span>
                            ))}
                          </div>
                        )}
                        {vars.length === 1 && v0 && (
                          <p className="text-xs text-muted-foreground mt-1">
                            Stock: {v0.stock_quantity} unidades
                          </p>
                        )}
                      </div>
                      <div className="text-right shrink-0 ml-2">
                        <p className="font-bold text-lg text-primary leading-tight">{priceRange}</p>
                        <p className="text-xs text-muted-foreground">{vars.length} variante{vars.length !== 1 ? 's' : ''}</p>
                        <p className="text-xs text-muted-foreground">{totalStock} u. totales</p>
                      </div>
                    </div>

                    {/* Edición colapsable */}
                    {canWrite && (
                      <details className="group border-t border-border">
                        <summary className="flex items-center gap-2 px-4 py-2.5 cursor-pointer text-xs text-muted-foreground hover:text-primary transition-colors select-none">
                          <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
                          Editar producto
                        </summary>

                        <div className="px-4 pb-4 space-y-4 border-t border-border bg-muted/10">
                          {/* Nombre y descripción */}
                          <form action={editProduct} className="pt-4 space-y-3">
                            <input type="hidden" name="product_id" value={p.id} />
                            <div className="grid sm:grid-cols-2 gap-3">
                              <div className="space-y-1">
                                <Label className="text-xs">Nombre del producto</Label>
                                <Input name="title" defaultValue={p.title} required className="h-8 text-sm" />
                              </div>
                              <div className="space-y-1">
                                <Label className="text-xs">Descripción</Label>
                                <Input name="description" defaultValue={p.description ?? ''} className="h-8 text-sm" />
                              </div>
                            </div>
                            <Button type="submit" size="sm" variant="outline" className="h-7 text-xs">
                              Guardar nombre/descripción
                            </Button>
                          </form>

                          {/* Variantes — edición individual */}
                          <div className="space-y-2">
                            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-widest">
                              Variantes — precio y stock
                            </p>
                            {vars.map(v => (
                              <form key={v.id} action={editVariation}
                                className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
                                <input type="hidden" name="variation_id" value={v.id} />
                                <span className="text-xs text-muted-foreground flex-1 min-w-24 truncate">
                                  {formatAttributes(v.attributes)}
                                </span>
                                <div className="flex items-center gap-1 shrink-0">
                                  <span className="text-xs text-muted-foreground">$</span>
                                  <Input name="price" type="number" step="0.01" min="0.01"
                                    defaultValue={v.price} className="h-7 text-xs w-20" required />
                                </div>
                                <div className="flex items-center gap-1 shrink-0">
                                  <span className="text-xs text-muted-foreground">uds</span>
                                  <Input name="stock" type="number" min="0"
                                    defaultValue={v.stock_quantity} className="h-7 text-xs w-16" />
                                </div>
                                <Button type="submit" size="sm" className="h-7 text-xs shrink-0">Guardar</Button>
                              </form>
                            ))}
                          </div>

                          {/* Desactivar */}
                          <form action={deactivateProduct}>
                            <input type="hidden" name="product_id" value={p.id} />
                            <Button type="submit" size="sm" variant="outline"
                              className="h-7 text-xs text-destructive border-destructive/30 hover:bg-destructive/10">
                              Desactivar producto
                            </Button>
                          </form>
                        </div>
                      </details>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
