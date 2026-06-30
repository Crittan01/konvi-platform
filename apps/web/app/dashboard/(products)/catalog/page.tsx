import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { revalidatePath } from 'next/cache'
import ProductsManager from './_components/products-manager'
import type { Product } from './types'
import { CORE_API_URL } from '@/lib/runtime-env'

const DEFAULT_THRESHOLD = 5

export default async function CatalogPage() {
  // Sem 5 perf: cached.
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = createClient()

  // Categories
  const { data: cats } = await supabase
    .from('platform_categories')
    .select('id, name')
    .eq('is_active', true)
    .order('name')
  const platformCategories = (cats as { id: string; name: string }[]) ?? []
  const catMap = Object.fromEntries(platformCategories.map(c => [c.id, c.name]))

  // ADR-0027 — categorías OPERATIVAS per-tenant (las que el bot presenta). RLS via JWT.
  const { data: pcats } = tenantId
    ? await supabase
        .from('product_categories')
        .select('id, display_label')
        .eq('tenant_id', tenantId)
        .order('sort_order')
        .order('display_label')
    : { data: [] }
  const productCategories = (pcats as { id: string; display_label: string }[]) ?? []

  // Products (active + archived) + inventory data
  let products: Product[] = []
  let archivedProducts: Product[] = []
  let threshold = DEFAULT_THRESHOLD
  let linkedVariationIds: string[] = []

  if (tenantId) {
    const [activeRes, archivedRes, tenantRes, listingsRes] = await Promise.all([
      supabase
        .from('products')
        .select(`id, title, description, safety_note, cover_image_url, platform_category_id, category_id,
                 retracto_excluded, retracto_excluded_reason,
                 product_variations(id, sku, cost_price, price, compare_at_price, stock_quantity, attributes, weight_kg, length_cm, width_cm, height_cm, image_url)`)
        .eq('tenant_id', tenantId)
        .eq('status', 'active')
        .order('title'),
      supabase
        .from('products')
        .select(`id, title, description, safety_note, cover_image_url, platform_category_id, category_id,
                 retracto_excluded, retracto_excluded_reason,
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

    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return

    // F2.2: editar vía API (restaura @audit_log + RBAC server-side; antes era write directo a
    // Supabase sin auditar). PATCH semántico: los campos opcionales enviados como null SE LIMPIAN
    // (el backend usa exclude_unset + never_clear), preservando la capacidad de borrar safety_note,
    // categoría o razón de retracto. cover_image_url solo se envía si hay una nueva (se preserva).
    const payload: Record<string, unknown> = {
      title:                formData.get('title') as string,
      description:          (formData.get('description') as string) || null,
      safety_note:          (formData.get('safety_note') as string) || null,
      platform_category_id: (formData.get('platform_category_id') as string) || null,
      category_id:          (formData.get('category_id') as string) || null,  // ADR-0027 operativa
      retracto_excluded:        formData.get('retracto_excluded') === 'on',
      retracto_excluded_reason: (formData.get('retracto_excluded_reason') as string) || null,
    }
    const coverUrl = formData.get('cover_image_url') as string
    if (coverUrl) payload.cover_image_url = coverUrl

    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      await fetch(`${CORE_API_URL}/api/v1/products/${formData.get('product_id') as string}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
    } catch { /* non-fatal */ }
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

    // F2.2: crear variante vía API (audita la creación + RBAC server-side). sku/attributes nullable
    // (variante única sin SKU/atributos) — el contrato VariationCreate ahora los acepta.
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      await fetch(`${CORE_API_URL}/api/v1/products/${formData.get('product_id') as string}/variations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({
          sku, price, compare_at_price: finalCompare, cost_price, stock_quantity: stock, attributes,
        }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
    } catch { /* non-fatal */ }
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

    // F2.2: editar variante vía API (restaura @audit_log + RBAC server-side). `updates` mapea 1:1 a
    // VariationPatch; compare_at_price=null se limpia vía el contrato semántico (exclude_unset).
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return
    const productId = formData.get('product_id') as string
    const variationId = formData.get('variation_id') as string

    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      await fetch(`${CORE_API_URL}/api/v1/products/${productId}/variations/${variationId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify(updates),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
    } catch { /* non-fatal */ }
    revalidatePath('/dashboard/catalog')
  }

  async function restoreProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    // F2.2: reactivar vía API (auditado). PATCH semántico solo toca status.
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      await fetch(`${CORE_API_URL}/api/v1/products/${formData.get('product_id') as string}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ status: 'active' }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
    } catch { /* non-fatal */ }
    revalidatePath('/dashboard/catalog')
  }

  async function deactivateProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    // F2.2: desactivar vía API (auditado). PATCH semántico solo toca status.
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      await fetch(`${CORE_API_URL}/api/v1/products/${formData.get('product_id') as string}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ status: 'inactive' }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
    } catch { /* non-fatal */ }
    revalidatePath('/dashboard/catalog')
  }

  async function deleteProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const productId = formData.get('product_id') as string

    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return
    // F2.2: hard-delete vía API (auditado). La cascada FK borra variantes, marketplace_listings y
    // stock_reservations; los order_items quedan en NULL (historial de pedidos preservado por diseño).
    // Reemplaza el borrado multi-tabla explícito (la cascada lo cubre).
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      await fetch(`${CORE_API_URL}/api/v1/products/${productId}?hard=true`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` },
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
    } catch { /* non-fatal */ }
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
        productCategories={productCategories}
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
