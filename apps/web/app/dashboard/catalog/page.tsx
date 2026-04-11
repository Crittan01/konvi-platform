import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import Image from 'next/image'
import { ShoppingBag, Package, Plus, Tag, ImageOff, TrendingDown } from 'lucide-react'
import CatalogForm from './catalog-form'
import MassImporter from './mass-importer'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

type Variation = {
  id: string
  price: number
  stock_quantity: number
  attributes: Record<string, string> | null
  sku: string | null
}
type Product = {
  id: string
  title: string
  description: string | null
  status: string
  cover_image_url: string | null
  platform_category_id: string | null
  product_variations: Variation[]
}

function formatAttributes(attrs: Record<string, string> | null): string {
  if (!attrs || Object.keys(attrs).length === 0) return 'Estándar'
  return Object.entries(attrs).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

function priceRange(vars: Variation[]): string {
  if (vars.length === 0) return '—'
  const prices = vars.map(v => v.price)
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  return min === max
    ? `$${min.toLocaleString('es-MX', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
    : `$${min.toLocaleString('es-MX')} – $${max.toLocaleString('es-MX')}`
}

export default async function CatalogPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  let platformCategories: { id: string; name: string }[] = []
  const { data: cats } = await supabase
    .from('platform_categories')
    .select('id, name')
    .eq('is_active', true)
    .order('name')
  platformCategories = (cats as { id: string; name: string }[]) || []
  const catMap = Object.fromEntries(platformCategories.map(c => [c.id, c.name]))

  let products: Product[] = []
  if (tenantId) {
    const { data } = await supabase
      .from('products')
      .select(`
        id, title, description, status, cover_image_url, platform_category_id,
        product_variations(id, sku, price, stock_quantity, attributes)
      `)
      .eq('tenant_id', tenantId)
      .eq('status', 'active')
      .order('title')
    products = (data as Product[]) || []
  }

  const totalVariations = products.reduce((s, p) => s + p.product_variations.length, 0)
  const totalStock = products.flatMap(p => p.product_variations).reduce((s, v) => s + (v.stock_quantity ?? 0), 0)

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
    <div className="space-y-6 max-w-[1400px]">

      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2.5">
            <ShoppingBag className="h-6 w-6 text-primary" />
            Catálogo de Productos
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Gestiona el inventario que la IA vende por WhatsApp
          </p>
        </div>
        {/* Stats pills */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full bg-primary/10 text-primary border border-primary/20">
            <Package className="h-3 w-3" />
            {products.length} productos
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full bg-muted text-muted-foreground border border-border">
            <Tag className="h-3 w-3" />
            {totalVariations} variantes
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full bg-muted text-muted-foreground border border-border">
            {totalStock} u. en stock
          </span>
        </div>
      </div>

      {/* ── Main Grid ── */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-6 items-start">

        {/* ── Panel izquierdo: Nuevo Producto + Importador ── */}
        {canWrite && (
          <div className="xl:col-span-2 space-y-5">
            {/* Formulario */}
            <div className="rounded-2xl border border-border bg-card shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b border-border bg-muted/30 flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center">
                  <Plus className="h-4 w-4 text-primary" />
                </div>
                <p className="text-sm font-semibold">Nuevo Producto</p>
              </div>
              <div className="p-5">
                <CatalogForm apiUrl={API_URL} categories={platformCategories} tenantId={tenantId ?? ''} />
              </div>
            </div>

            {/* Importador Masivo */}
            <MassImporter categories={platformCategories} tenantId={tenantId ?? ''} />
          </div>
        )}

        {/* ── Panel derecho: Lista de Productos ── */}
        <div className={canWrite ? 'xl:col-span-3' : 'xl:col-span-5'}>
          {products.length === 0 ? (
            /* ── Empty State ── */
            <div className="flex flex-col items-center justify-center min-h-[420px] rounded-2xl border-2 border-dashed border-border/50 bg-muted/5 text-center px-10 py-16 gap-5">
              <div className="w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center shadow-inner">
                <Package className="h-10 w-10 text-primary/50" />
              </div>
              <div className="space-y-2">
                <p className="text-lg font-semibold text-foreground">Tu catálogo está listo para crecer</p>
                <p className="text-sm text-muted-foreground max-w-sm mx-auto leading-relaxed">
                  {canWrite
                    ? 'Crea tu primer producto con el formulario de la izquierda, o carga una lista completa desde Excel en segundos.'
                    : 'Aún no hay productos activos en este catálogo.'}
                </p>
              </div>
              {canWrite && (
                <div className="flex flex-col sm:flex-row gap-2.5 text-xs text-muted-foreground mt-1">
                  <span className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border border-border shadow-sm">
                    <span className="w-5 h-5 rounded-full bg-primary text-white font-bold flex items-center justify-center text-[10px]">1</span>
                    Agrega manualmente
                  </span>
                  <span className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-card border border-border shadow-sm">
                    <span className="w-5 h-5 rounded-full bg-primary text-white font-bold flex items-center justify-center text-[10px]">2</span>
                    Importa desde Excel
                  </span>
                </div>
              )}
            </div>
          ) : (
            /* ── Product Cards Grid ── */
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {products.map(p => {
                const vars = p.product_variations ?? []
                const stockTotal = vars.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)
                const hasZeroStock = vars.some(v => v.stock_quantity === 0)
                const hasLowStock = stockTotal > 0 && stockTotal <= 5
                const catName = p.platform_category_id ? catMap[p.platform_category_id] : null

                return (
                  <div key={p.id} className={`group flex flex-col rounded-2xl border bg-card shadow-sm overflow-hidden transition-all hover:shadow-md ${
                    hasZeroStock ? 'border-destructive/30' : hasLowStock ? 'border-amber-500/30' : 'border-border'
                  }`}>

                    {/* Imagen del Producto */}
                    <div className="relative w-full h-44 bg-muted/40 flex-shrink-0 overflow-hidden">
                      {p.cover_image_url ? (
                        <Image
                          src={p.cover_image_url}
                          alt={p.title}
                          fill
                          className="object-cover transition-transform duration-300 group-hover:scale-105"
                          sizes="(max-width: 640px) 100vw, 50vw"
                        />
                      ) : (
                        <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-muted-foreground/30">
                          <ImageOff className="h-10 w-10" />
                          <span className="text-[10px] uppercase tracking-wider font-medium">Sin imagen</span>
                        </div>
                      )}

                      {/* Badge de stock en overlay */}
                      <div className="absolute top-2.5 right-2.5">
                        {hasZeroStock ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-1 rounded-full bg-destructive/90 text-white shadow-sm backdrop-blur-sm">
                            <TrendingDown className="h-2.5 w-2.5" /> Sin stock
                          </span>
                        ) : hasLowStock ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-1 rounded-full bg-amber-500/90 text-white shadow-sm backdrop-blur-sm">
                            Stock bajo
                          </span>
                        ) : null}
                      </div>

                      {/* Badge categoría */}
                      {catName && (
                        <div className="absolute bottom-2.5 left-2.5">
                          <span className="text-[10px] font-medium px-2 py-1 rounded-full bg-black/60 text-white backdrop-blur-sm">
                            {catName}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Info del Producto */}
                    <div className="flex flex-col flex-1 p-4 gap-3">
                      <div>
                        <h3 className="font-semibold text-sm leading-tight line-clamp-1">{p.title}</h3>
                        {p.description && (
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2 leading-relaxed">{p.description}</p>
                        )}
                      </div>

                      {/* Precio y Stock */}
                      <div className="flex items-center justify-between">
                        <span className="text-lg font-bold text-primary">{priceRange(vars)}</span>
                        <span className="text-xs text-muted-foreground">
                          {stockTotal} u · {vars.length} var{vars.length !== 1 ? 's' : ''}
                        </span>
                      </div>

                      {/* Chips de variantes */}
                      {vars.length > 1 && (
                        <div className="flex flex-wrap gap-1">
                          {vars.slice(0, 4).map(v => (
                            <span key={v.id} className={`text-[10px] px-2 py-0.5 rounded-full border ${
                              v.stock_quantity === 0
                                ? 'bg-destructive/10 text-destructive border-destructive/20'
                                : 'bg-muted/60 text-muted-foreground border-border'
                            }`}>
                              {formatAttributes(v.attributes)}
                            </span>
                          ))}
                          {vars.length > 4 && (
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                              +{vars.length - 4} más
                            </span>
                          )}
                        </div>
                      )}

                      {/* Sección de edición colapsable */}
                      {canWrite && (
                        <details className="group/edit mt-auto border-t border-border/50 pt-3">
                          <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5 select-none list-none font-medium">
                            <span className="group-open/edit:hidden">▸ Editar producto</span>
                            <span className="hidden group-open/edit:inline">▾ Cerrar edición</span>
                          </summary>

                          <div className="mt-3 space-y-4">
                            {/* Editar nombre y descripción */}
                            <form action={editProduct} className="space-y-2.5">
                              <input type="hidden" name="product_id" value={p.id} />
                              <div className="space-y-1">
                                <Label className="text-[11px] text-muted-foreground uppercase tracking-wider font-medium">Nombre</Label>
                                <Input name="title" defaultValue={p.title} required className="h-8 text-sm" />
                              </div>
                              <div className="space-y-1">
                                <Label className="text-[11px] text-muted-foreground uppercase tracking-wider font-medium">Descripción</Label>
                                <Input name="description" defaultValue={p.description ?? ''} className="h-8 text-sm" placeholder="Descripción del producto..." />
                              </div>
                              <Button type="submit" size="sm" variant="secondary" className="h-7 text-xs w-full">
                                Guardar nombre / descripción
                              </Button>
                            </form>

                            {/* Editar variantes */}
                            {vars.length > 0 && (
                              <div className="space-y-2">
                                <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-medium">
                                  Precio y stock por variante
                                </p>
                                {vars.map(v => (
                                  <form key={v.id} action={editVariation}
                                    className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/20 px-3 py-2">
                                    <input type="hidden" name="variation_id" value={v.id} />
                                    <span className="text-xs text-foreground/70 flex-1 min-w-20 truncate font-medium">
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
                                    <Button type="submit" size="sm" className="h-7 text-xs shrink-0 px-3">✓</Button>
                                  </form>
                                ))}
                              </div>
                            )}

                            {/* Desactivar */}
                            <form action={deactivateProduct}>
                              <input type="hidden" name="product_id" value={p.id} />
                              <Button type="submit" size="sm" variant="ghost"
                                className="h-7 text-xs text-destructive/70 hover:text-destructive hover:bg-destructive/10 w-full border border-destructive/20">
                                Archivar producto
                              </Button>
                            </form>
                          </div>
                        </details>
                      )}
                    </div>
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
