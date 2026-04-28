import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import ProductsManager from './_components/products-manager'
import type { Product } from './types'
import { CORE_API_URL } from '@/lib/runtime-env'

const DEFAULT_THRESHOLD = 5

export default async function CatalogPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta   = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role     = meta.role ?? 'operator'
  const canWrite = role === 'owner' || role === 'manager'

  // Categories
  const { data: cats } = await supabase
    .from('platform_categories')
    .select('id, name')
    .eq('is_active', true)
    .order('name')
  const platformCategories = (cats as { id: string; name: string }[]) ?? []
  const catMap = Object.fromEntries(platformCategories.map(c => [c.id, c.name]))

  // Products (active + archived) + inventory data
  let products: Product[] = []
  let archivedProducts: Product[] = []
  let threshold = DEFAULT_THRESHOLD
  let linkedVariationIds: string[] = []

  if (tenantId) {
    const [activeRes, archivedRes, tenantRes, listingsRes] = await Promise.all([
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
        .order('title'),
      supabase
        .from('tenants')
        .select('low_stock_threshold')
        .eq('id', tenantId)
        .single(),
      supabase
        .from('marketplace_listings')
        .select('variation_id')
        .eq('tenant_id', tenantId)
        .eq('provider', 'mercadolibre')
        .not('variation_id', 'is', null),
    ])
    products          = (activeRes.data as Product[]) ?? []
    archivedProducts  = (archivedRes.data as Product[]) ?? []
    threshold         = (tenantRes.data as { low_stock_threshold?: number } | null)?.low_stock_threshold ?? DEFAULT_THRESHOLD
    linkedVariationIds = (listingsRes.data ?? []).map((l: { variation_id: string }) => l.variation_id).filter(Boolean)
  }

  // ── Server Actions ──────────────────────────────────────────────────────────

  async function editProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const updates: Record<string, unknown> = {
      title:                formData.get('title') as string,
      description:          (formData.get('description') as string) || null,
      platform_category_id: (formData.get('platform_category_id') as string) || null,
    }
    const coverUrl = formData.get('cover_image_url') as string
    if (coverUrl) updates.cover_image_url = coverUrl
    await sb.from('products').update(updates)
      .eq('id', formData.get('product_id') as string).eq('tenant_id', m.tenant_id)
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
    // Soporte multi-atributo: attrs_json tiene prioridad sobre attr_key/attr_val legacy
    const attrsJson = formData.get('attrs_json') as string
    const attrKey   = formData.get('attr_key') as string
    const attrVal   = formData.get('attr_val') as string
    if (isNaN(price) || price <= 0 || isNaN(stock) || stock < 0) return
    let attributes: Record<string, string> | null = null
    if (attrsJson) {
      try { attributes = JSON.parse(attrsJson) } catch { /* usa legado */ }
    }
    if (!attributes && attrKey && attrVal) attributes = { [attrKey.trim()]: attrVal.trim() }
    await sb.from('product_variations').insert({
      tenant_id: m.tenant_id,
      product_id: formData.get('product_id') as string,
      sku, price, compare_at_price: finalCompare, cost_price, stock_quantity: stock, attributes
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
    const updates: Record<string, any> = {}
    if (!isNaN(price) && price > 0) updates.price = price
    if (!isNaN(stock) && stock >= 0) updates.stock_quantity = stock
    if (costStr !== null) {
      const parsedCost = parseFloat(costStr)
      if (!isNaN(parsedCost) && parsedCost >= 0) updates.cost_price = parsedCost
    }
    if (compareStr !== null) {
      const cmp = parseFloat(compareStr)
      const basePrice = updates.price || 0
      updates.compare_at_price = (!isNaN(cmp) && cmp > 0 && cmp > basePrice) ? cmp : null
    }
    // Dimensiones, peso, imagen y SKU
    const wkg = parseFloat(formData.get('weight_kg') as string)
    const lcm = parseFloat(formData.get('length_cm') as string)
    const wcm = parseFloat(formData.get('width_cm')  as string)
    const hcm = parseFloat(formData.get('height_cm') as string)
    const imgUrl = (formData.get('image_url') as string) || null
    const sku    = (formData.get('sku')       as string) || null
    if (!isNaN(wkg) && wkg > 0) updates.weight_kg = wkg
    if (!isNaN(lcm) && lcm > 0) updates.length_cm = lcm
    if (!isNaN(wcm) && wcm > 0) updates.width_cm  = wcm
    if (!isNaN(hcm) && hcm > 0) updates.height_cm = hcm
    if (imgUrl !== null) updates.image_url = imgUrl
    if (sku !== null)   updates.sku        = sku
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
    const { data: vars } = await sb.from('product_variations')
      .select('id')
      .eq('product_id', productId)
      .eq('tenant_id', m.tenant_id)
    const varIds = (vars ?? []).map((v: { id: string }) => v.id)
    if (varIds.length > 0) {
      await sb.from('marketplace_listings').delete().in('variation_id', varIds)
      await sb.from('product_variations').delete().in('id', varIds)
    }
    await sb.from('products').delete().eq('id', productId).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/catalog')
    revalidatePath('/dashboard/marketplace')
  }

  async function adjustStock(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const variationId = formData.get('variation_id') as string
    const productId   = formData.get('product_id') as string
    const delta       = parseInt(formData.get('delta') as string)
    const reason      = (formData.get('reason') as string) || 'Ajuste manual'
    if (!variationId || isNaN(delta) || delta === 0) return
    const { data: variation } = await sb
      .from('product_variations')
      .select('stock_quantity')
      .eq('id', variationId)
      .eq('tenant_id', m.tenant_id)
      .single()
    if (!variation) return
    const newStock = Math.max(0, (variation as { stock_quantity: number }).stock_quantity + delta)
    const { data: { session: s } } = await sb.auth.getSession()
    await Promise.all([
      sb.from('product_variations').update({ stock_quantity: newStock }).eq('id', variationId).eq('tenant_id', m.tenant_id),
      sb.from('stock_movements').insert({
        tenant_id: m.tenant_id,
        product_id: productId,
        variation_id: variationId,
        delta,
        new_stock: newStock,
        reason,
        created_by: s?.user?.id ?? null,
      }),
    ])
    revalidatePath('/dashboard/catalog')
  }

  async function saveThreshold(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const val = parseInt(formData.get('threshold') as string)
    if (isNaN(val) || val < 0) return
    await sb.from('tenants').update({ low_stock_threshold: val }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/catalog')
  }

  // ── UI ──────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 max-w-7xl flex-1 h-full overflow-auto">
      <ProductsManager
        products={products}
        archivedProducts={archivedProducts}
        catMap={catMap}
        canWrite={canWrite}
        categories={platformCategories}
        tenantId={tenantId ?? ''}
        apiUrl={CORE_API_URL}
        threshold={threshold}
        editProductAction={editProduct}
        editVariationAction={editVariation}
        addVariationAction={addVariation}
        deactivateProductAction={deactivateProduct}
        restoreProductAction={restoreProduct}
        deleteProductAction={deleteProduct}
        adjustStockAction={adjustStock}
        saveThresholdAction={saveThreshold}
        linkedVariationIds={linkedVariationIds}
      />
    </div>
  )
}
