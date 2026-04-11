import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { ShoppingBag, Package, Tag } from 'lucide-react'
import CatalogForm from './catalog-form'
import MassImporter from './mass-importer'
import CatalogTable from './catalog-table'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

export default async function CatalogPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta   = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role     = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  // Categories
  const { data: cats } = await supabase
    .from('platform_categories')
    .select('id, name')
    .eq('is_active', true)
    .order('name')
  const platformCategories = (cats as { id: string; name: string }[]) ?? []
  const catMap = Object.fromEntries(platformCategories.map(c => [c.id, c.name]))

  // Products
  type Variation = { id: string; sku: string | null; price: number; stock_quantity: number; attributes: Record<string, string> | null }
  type Product   = { id: string; title: string; description: string | null; cover_image_url: string | null; platform_category_id: string | null; product_variations: Variation[] }

  let products: Product[] = []
  if (tenantId) {
    const { data } = await supabase
      .from('products')
      .select(`id, title, description, cover_image_url, platform_category_id,
               product_variations(id, sku, price, stock_quantity, attributes)`)
      .eq('tenant_id', tenantId)
      .eq('status', 'active')
      .order('title')
    products = (data as Product[]) ?? []
  }

  const totalVariations = products.reduce((s, p) => s + p.product_variations.length, 0)
  const totalStock      = products.flatMap(p => p.product_variations).reduce((s, v) => s + (v.stock_quantity ?? 0), 0)

  // ── Server Actions ──────────────────────────────────────────────────────────

  async function editProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('products').update({
      title:       formData.get('title') as string,
      description: (formData.get('description') as string) || null,
    }).eq('id', formData.get('product_id') as string).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/catalog')
  }

  async function addVariation(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const price = parseFloat(formData.get('price') as string)
    const stock = parseInt(formData.get('stock') as string)
    const sku = (formData.get('sku') as string) || null
    const attrKey = formData.get('attr_key') as string
    const attrVal = formData.get('attr_val') as string
    
    if (isNaN(price) || price <= 0 || isNaN(stock) || stock < 0) return

    let attributes = null
    if (attrKey && attrVal) {
      attributes = { [attrKey.trim()]: attrVal.trim() }
    }

    await sb.from('product_variations').insert({
      tenant_id: m.tenant_id,
      product_id: formData.get('product_id') as string,
      sku,
      price,
      stock_quantity: stock,
      attributes
    })
    revalidatePath('/dashboard/catalog')
  }

  async function editVariation(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const price = parseFloat(formData.get('price') as string)
    const stock = parseInt(formData.get('stock') as string)
    const updates: Record<string, number> = {}
    if (!isNaN(price) && price > 0) updates.price = price
    if (!isNaN(stock) && stock >= 0) updates.stock_quantity = stock
    if (!Object.keys(updates).length) return
    await sb.from('product_variations')
      .update(updates)
      .eq('id', formData.get('variation_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/catalog')
  }

  async function deactivateProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('products')
      .update({ status: 'inactive' })
      .eq('id', formData.get('product_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/catalog')
  }

  // ── UI ──────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 max-w-[1400px]">

      {/* Header */}
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
            <Package className="h-3 w-3" />{products.length} productos
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full bg-muted text-muted-foreground border border-border">
            <Tag className="h-3 w-3" />{totalVariations} variantes
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full bg-muted text-muted-foreground border border-border">
            {totalStock} u. en stock
          </span>
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-6 items-start">

        {/* Left panel: Form + Importer */}
        {canWrite && (
          <div className="xl:col-span-2 space-y-5">
            <div className="rounded-2xl border border-border bg-card shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b border-border bg-muted/30 flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-primary/15 flex items-center justify-center">
                  <span className="text-primary text-sm font-bold">+</span>
                </div>
                <p className="text-sm font-semibold">Nuevo Producto</p>
              </div>
              <div className="p-5">
                <CatalogForm
                  apiUrl={API_URL}
                  categories={platformCategories}
                  tenantId={tenantId ?? ''}
                />
              </div>
            </div>
            <MassImporter categories={platformCategories} tenantId={tenantId ?? ''} />
          </div>
        )}

        {/* Right panel: Product Catalog Table */}
        <div className={canWrite ? 'xl:col-span-3' : 'xl:col-span-5'}>
          <CatalogTable
            products={products}
            catMap={catMap}
            canWrite={canWrite}
            editProductAction={editProduct}
            editVariationAction={editVariation}
            addVariationAction={addVariation}
            deactivateProductAction={deactivateProduct}
          />
        </div>
      </div>
    </div>
  )
}
