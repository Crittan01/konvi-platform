import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { ShoppingBag, Package, Tag } from 'lucide-react'
import CatalogForm from './_components/catalog-form'
import MassImporter from './_components/mass-importer'
import CatalogTable from './_components/catalog-table'
import type { Product } from './types'

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
  let products: Product[] = []
  let archivedProducts: Product[] = []
  if (tenantId) {
    const [activeRes, archivedRes] = await Promise.all([
      supabase
        .from('products')
        .select(`id, title, description, cover_image_url, platform_category_id,
                 product_variations(id, sku, cost_price, price, compare_at_price, stock_quantity, attributes, weight_kg, length_cm, width_cm, height_cm, image_url)`)
        .eq('tenant_id', tenantId)
        .eq('status', 'active')
        .order('title'),
      supabase
        .from('products')
        .select(`id, title, description, cover_image_url, platform_category_id,
                 product_variations(id, sku, cost_price, price, compare_at_price, stock_quantity, attributes, weight_kg, length_cm, width_cm, height_cm, image_url)`)
        .eq('tenant_id', tenantId)
        .eq('status', 'inactive')
        .order('title')
    ])
    products = (activeRes.data as Product[]) ?? []
    archivedProducts = (archivedRes.data as Product[]) ?? []
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
    const compareStr = formData.get('compare_at_price') as string
    const compareObj = compareStr ? parseFloat(compareStr) : null
    const finalCompare = compareObj && compareObj > price ? compareObj : null
    
    const costStr = formData.get('cost_price') as string
    const cost_price = costStr ? parseFloat(costStr) : 0
    
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
      compare_at_price: finalCompare,
      cost_price,
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
    const compareStr = formData.get('compare_at_price') as string
    const costStr = formData.get('cost_price') as string

    // Record<string, any> para poder inyectar null
    const updates: Record<string, any> = {}
    
    if (!isNaN(price) && price > 0) updates.price = price
    if (!isNaN(stock) && stock >= 0) updates.stock_quantity = stock
    
    if (costStr !== null) {
      const parsedCost = parseFloat(costStr)
      if (!isNaN(parsedCost) && parsedCost >= 0) updates.cost_price = parsedCost
    }
    
    // Si se pasa compare_at_price, se verifica que sea mayor al precio validado o inicial
    if (compareStr !== null) {
       const cmp = parseFloat(compareStr)
       const basePrice = updates.price || 0 // el trigger DB se encarga del resto
       updates.compare_at_price = (!isNaN(cmp) && cmp > 0 && cmp > basePrice) ? cmp : null
    }
    if (!Object.keys(updates).length) return
    await sb.from('product_variations')
      .update(updates)
      .eq('id', formData.get('variation_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/catalog')
  }

  async function restoreProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('products')
      .update({ status: 'active' })
      .eq('id', formData.get('product_id') as string)
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

  async function deleteProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const productId = formData.get('product_id') as string

    // Get variation IDs to cascade-delete marketplace_listings first
    const { data: vars } = await sb.from('product_variations')
      .select('id')
      .eq('product_id', productId)
      .eq('tenant_id', m.tenant_id)
    const varIds = (vars ?? []).map((v: { id: string }) => v.id)

    if (varIds.length > 0) {
      await sb.from('marketplace_listings')
        .delete()
        .in('variation_id', varIds)
      await sb.from('product_variations')
        .delete()
        .in('id', varIds)
    }

    await sb.from('products')
      .delete()
      .eq('id', productId)
      .eq('tenant_id', m.tenant_id)

    revalidatePath('/dashboard/catalog')
    revalidatePath('/dashboard/marketplace')
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
            archivedProducts={archivedProducts}
            catMap={catMap}
            canWrite={canWrite}
            editProductAction={editProduct}
            editVariationAction={editVariation}
            addVariationAction={addVariation}
            deactivateProductAction={deactivateProduct}
            restoreProductAction={restoreProduct}
            deleteProductAction={deleteProduct}
          />
        </div>
      </div>
    </div>
  )
}
