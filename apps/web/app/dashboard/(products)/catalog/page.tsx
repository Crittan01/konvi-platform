import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { revalidatePath } from 'next/cache'
import ProductsManager from './_components/products-manager'
import type { Product, AttributeDef } from './types'
import { CORE_API_URL } from '@/lib/runtime-env'
import { ok, fail, type ActionResult } from '@/lib/action-result'

const DEFAULT_THRESHOLD = 5

// Extrae un mensaje legible del cuerpo de error del Core API (FastAPI `{detail}`,
// error de validación `[{msg}]` o texto plano) para surfacearlo al operador.
async function readApiError(res: Response): Promise<string> {
  try {
    const txt = await res.text()
    if (!txt) return `Error ${res.status}`
    try {
      const j = JSON.parse(txt) as { detail?: unknown }
      const d = j?.detail
      if (typeof d === 'string') return d
      if (Array.isArray(d)) return (d[0] as { msg?: string })?.msg ?? `Error ${res.status}`
    } catch { /* no era JSON */ }
    return txt.slice(0, 300)
  } catch {
    return `Error ${res.status}`
  }
}

// Traduce el fallo de red/abort a un mensaje de operador + deja traza server-side.
function networkFail(ctx: string, err: unknown): ActionResult {
  const aborted = err instanceof Error && err.name === 'AbortError'
  console.error(`[catalog:${ctx}] fallo de red`, err)
  return fail(aborted
    ? 'La operación tardó demasiado y se canceló. Intenta de nuevo.'
    : 'No se pudo conectar con el servidor. Revisa tu conexión e intenta de nuevo.')
}

export default async function CatalogPage() {
  // Sem 5 perf: cached.
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = await createClient()

  // ADR-0027 — categorías OPERATIVAS per-tenant (las que el bot presenta). RLS via JWT.
  const { data: pcats } = tenantId
    ? await supabase
        .from('product_categories')
        .select('id, display_label, parent_id')
        .eq('tenant_id', tenantId)
        .order('sort_order')
        .order('display_label')
    : { data: [] }
  const productCategories = (pcats as { id: string; display_label: string; parent_id: string | null }[]) ?? []
  // Coherencia: el listado etiqueta/ordena por la categoría OPERATIVA (category_id → display_label), la
  // misma que administra el módulo Categorías y usa el bot — NO la de marketplace (platform_category_id).
  const catMap = Object.fromEntries(productCategories.map(c => [c.id, c.display_label]))

  // ADR-0029 F1/F3 — contrato de atributos por categoría (guía el alta hacia valores canónicos).
  const { data: adefs } = tenantId
    ? await supabase
        .from('product_attribute_definitions')
        .select('product_category_id, code, label, type, unit, allowed_values, is_variant_axis, sort_order')
        .eq('tenant_id', tenantId)
        .order('sort_order')
    : { data: [] }
  const attributeDefs = (adefs as AttributeDef[]) ?? []

  // Products (active + archived) + inventory data
  let products: Product[] = []
  let archivedProducts: Product[] = []
  let threshold = DEFAULT_THRESHOLD
  let linkedVariationIds: string[] = []
  // Cota explícita: PostgREST trunca en su max-rows por defecto SIN avisar. Se pide una ventana acotada
  // + el count exacto para detectar si el catálogo excede lo mostrado y avisarlo al operador (data-fetching).
  const PRODUCT_WINDOW = 1000
  let activeTotal = 0
  let loadError = false

  if (tenantId) {
    const productCols = `id, title, description, safety_note, cover_image_url, platform_category_id, category_id, attributes,
                 retracto_excluded, retracto_excluded_reason,
                 product_variations(id, sku, cost_price, price, compare_at_price, stock_quantity, attributes, weight_kg, length_cm, width_cm, height_cm, image_url)`
    const [activeRes, archivedRes, tenantRes, listingsRes] = await Promise.all([
      supabase
        .from('products')
        .select(productCols, { count: 'exact' })
        .eq('tenant_id', tenantId)
        .eq('status', 'active')
        .order('title')
        .range(0, PRODUCT_WINDOW - 1),
      supabase
        .from('products')
        .select(productCols)
        .eq('tenant_id', tenantId)
        .eq('status', 'inactive')
        .order('title')
        .range(0, PRODUCT_WINDOW - 1),
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
    // Surfacear el error en vez de mostrar un falso catálogo vacío (data-fetching: no falso-0).
    if (activeRes.error) { console.error('[catalog] fallo cargando productos', activeRes.error.message); loadError = true }
    products          = (activeRes.data as Product[]) ?? []
    archivedProducts  = (archivedRes.data as Product[]) ?? []
    activeTotal       = activeRes.count ?? products.length
    threshold         = (tenantRes.data as { low_stock_threshold?: number } | null)?.low_stock_threshold ?? DEFAULT_THRESHOLD
    linkedVariationIds = (listingsRes.data ?? []).map((l: { variation_id: string }) => l.variation_id).filter(Boolean)
  }

  // ── Server Actions ──────────────────────────────────────────────────────────

  async function editProduct(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return fail('No tienes permiso para editar productos.')

    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return fail('Sesión expirada. Vuelve a iniciar sesión.')

    // F2.2: editar vía API (restaura @audit_log + RBAC server-side; antes era write directo a
    // Supabase sin auditar). PATCH semántico: los campos opcionales enviados como null SE LIMPIAN
    // (el backend usa exclude_unset + never_clear), preservando la capacidad de borrar safety_note,
    // categoría o razón de retracto. cover_image_url solo se envía si hay una nueva (se preserva).
    const payload: Record<string, unknown> = {
      title:                formData.get('title') as string,
      description:          (formData.get('description') as string) || null,
      safety_note:          (formData.get('safety_note') as string) || null,
      // ADR-0029: platform_category_id NO se gestiona por producto (se deriva por categoría). Se OMITE del
      // PATCH a propósito: el PATCH semántico limpia los null → enviarlo borraría el valor de productos que
      // sí lo tengan (p.ej. seteado por el flujo de publicación MeLi). Ausente = intacto.
      category_id:          (formData.get('category_id') as string) || null,  // ADR-0027 operativa
      retracto_excluded:        formData.get('retracto_excluded') === 'on',
      retracto_excluded_reason: (formData.get('retracto_excluded_reason') as string) || null,
    }
    const coverUrl = formData.get('cover_image_url') as string
    if (coverUrl) payload.cover_image_url = coverUrl
    // ADR-0029 D4: atributos product-level (JSON del editor guiado por el contrato). El backend los
    // valida contra product_attribute_definitions de la categoría (rechaza fuera de contrato).
    const attrsJson = formData.get('attributes') as string
    if (attrsJson != null && attrsJson !== '') {
      try { payload.attributes = JSON.parse(attrsJson) } catch { /* malformado → no se envía */ }
    }

    const productId = formData.get('product_id') as string
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${CORE_API_URL}/api/v1/products/${productId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const detail = await readApiError(res)
        console.error('[catalog:editProduct] rechazo API', { productId, status: res.status, detail })
        return fail(detail)
      }
    } catch (err) {
      return networkFail('editProduct', err)
    }
    revalidatePath('/dashboard/catalog')
    return ok('Producto actualizado.')
  }

  async function addVariation(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return fail('No tienes permiso para crear variantes.')
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
    if (isNaN(price) || price <= 0 || isNaN(stock) || stock < 0) return fail('Precio y stock inválidos.')
    let attributes: Record<string, string> | null = null
    if (attrsJson) {
      try { attributes = JSON.parse(attrsJson) } catch { /* usa legado */ }
    }
    if (!attributes && attrKey && attrVal) attributes = { [attrKey.trim()]: attrVal.trim() }

    // F2.2: crear variante vía API (audita la creación + RBAC server-side). sku/attributes nullable
    // (variante única sin SKU/atributos) — el contrato VariationCreate ahora los acepta.
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return fail('Sesión expirada. Vuelve a iniciar sesión.')
    const productId = formData.get('product_id') as string
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${CORE_API_URL}/api/v1/products/${productId}/variations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({
          sku, price, compare_at_price: finalCompare, cost_price, stock_quantity: stock, attributes,
        }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const detail = await readApiError(res)
        console.error('[catalog:addVariation] rechazo API', { productId, status: res.status, detail })
        return fail(detail)
      }
    } catch (err) {
      return networkFail('addVariation', err)
    }
    revalidatePath('/dashboard/catalog')
    return ok('Variante creada.')
  }

  async function editVariation(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return fail('No tienes permiso para editar variantes.')
    const price = parseFloat(formData.get('price') as string)
    const stock = parseInt(formData.get('stock') as string)
    const compareStr = formData.get('compare_at_price') as string
    const costStr = formData.get('cost_price') as string
    const updates: Record<string, number | string | null> = {}
    if (!isNaN(price) && price > 0) updates.price = price
    if (!isNaN(stock) && stock >= 0) updates.stock_quantity = stock
    if (costStr !== null) {
      const parsedCost = parseFloat(costStr)
      if (!isNaN(parsedCost) && parsedCost >= 0) updates.cost_price = parsedCost
    }
    if (compareStr !== null) {
      const cmp = parseFloat(compareStr)
      const basePrice = typeof updates.price === 'number' ? updates.price : 0
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
    if (!Object.keys(updates).length) return fail('No hay cambios para guardar.')

    // F2.2: editar variante vía API (restaura @audit_log + RBAC server-side). `updates` mapea 1:1 a
    // VariationPatch; compare_at_price=null se limpia vía el contrato semántico (exclude_unset).
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return fail('Sesión expirada. Vuelve a iniciar sesión.')
    const productId = formData.get('product_id') as string
    const variationId = formData.get('variation_id') as string

    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${CORE_API_URL}/api/v1/products/${productId}/variations/${variationId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify(updates),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const detail = await readApiError(res)
        console.error('[catalog:editVariation] rechazo API', { productId, variationId, status: res.status, detail })
        return fail(detail)
      }
    } catch (err) {
      return networkFail('editVariation', err)
    }
    revalidatePath('/dashboard/catalog')
    return ok('Variante actualizada.')
  }

  // Borra una variante concreta (endpoint con guard "no si es única" → surfacea el 422 al operador).
  async function deleteVariation(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return fail('No tienes permiso para eliminar variantes.')
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return fail('Sesión expirada. Vuelve a iniciar sesión.')
    const productId = formData.get('product_id') as string
    const variationId = formData.get('variation_id') as string
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${CORE_API_URL}/api/v1/products/${productId}/variations/${variationId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` },
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const detail = await readApiError(res)
        console.error('[catalog:deleteVariation] rechazo API', { productId, variationId, status: res.status, detail })
        return fail(detail)
      }
    } catch (err) {
      return networkFail('deleteVariation', err)
    }
    revalidatePath('/dashboard/catalog')
    revalidatePath('/dashboard/marketplace')
    return ok('Variante eliminada.')
  }

  async function restoreProduct(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return fail('No tienes permiso.')
    // F2.2: reactivar vía API (auditado). PATCH semántico solo toca status.
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return fail('Sesión expirada. Vuelve a iniciar sesión.')
    const productId = formData.get('product_id') as string
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${CORE_API_URL}/api/v1/products/${productId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ status: 'active' }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const detail = await readApiError(res)
        console.error('[catalog:restoreProduct] rechazo API', { productId, status: res.status, detail })
        return fail(detail)
      }
    } catch (err) {
      return networkFail('restoreProduct', err)
    }
    revalidatePath('/dashboard/catalog')
    return ok('Producto restaurado.')
  }

  async function deactivateProduct(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return fail('No tienes permiso.')
    // F2.2: desactivar vía API (auditado). PATCH semántico solo toca status.
    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return fail('Sesión expirada. Vuelve a iniciar sesión.')
    const productId = formData.get('product_id') as string
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${CORE_API_URL}/api/v1/products/${productId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ status: 'inactive' }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const detail = await readApiError(res)
        console.error('[catalog:deactivateProduct] rechazo API', { productId, status: res.status, detail })
        return fail(detail)
      }
    } catch (err) {
      return networkFail('deactivateProduct', err)
    }
    revalidatePath('/dashboard/catalog')
    return ok('Producto archivado.')
  }

  async function deleteProduct(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return fail('No tienes permiso.')
    const productId = formData.get('product_id') as string

    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return fail('Sesión expirada. Vuelve a iniciar sesión.')
    // F2.2: hard-delete vía API (auditado). La cascada FK borra variantes, marketplace_listings y
    // stock_reservations; los order_items quedan en NULL (historial de pedidos preservado por diseño).
    // Reemplaza el borrado multi-tabla explícito (la cascada lo cubre).
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${CORE_API_URL}/api/v1/products/${productId}?hard=true`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` },
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const detail = await readApiError(res)
        console.error('[catalog:deleteProduct] rechazo API', { productId, status: res.status, detail })
        return fail(detail)
      }
    } catch (err) {
      return networkFail('deleteProduct', err)
    }
    revalidatePath('/dashboard/catalog')
    revalidatePath('/dashboard/marketplace')
    return ok('Producto eliminado.')
  }

  async function adjustStock(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return fail('No tienes permiso para ajustar inventario.')
    const variationId = formData.get('variation_id') as string
    const productId   = formData.get('product_id') as string
    const delta       = parseInt(formData.get('delta') as string)
    const reason      = (formData.get('reason') as string) || 'Ajuste manual'
    if (!variationId || isNaN(delta) || delta === 0) return fail('Ingresa una cantidad distinta de cero (usa − para salidas).')
    const { data: variation, error: readErr } = await sb
      .from('product_variations')
      .select('stock_quantity')
      .eq('id', variationId)
      .eq('tenant_id', m.tenant_id)
      .single()
    if (readErr || !variation) {
      console.error('[catalog:adjustStock] variante no encontrada', { variationId, error: readErr?.message })
      return fail('No se encontró la variante. Recarga la página e intenta de nuevo.')
    }
    const prevStock = (variation as { stock_quantity: number }).stock_quantity
    const newStock  = Math.max(0, prevStock + delta)
    // El ledger debe cuadrar: se registra el delta EFECTIVO (newStock - prevStock), no el solicitado.
    // Restar 50 a un stock de 10 asienta delta=-10 (clamp a 0), no -50 → la suma reconcilia con el stock.
    const effectiveDelta = newStock - prevStock
    const { data: { session: s } } = await sb.auth.getSession()
    // NOTA F2.2: update + insert no son transaccionales aquí (escritura directa a Supabase, sin RPC/audit
    // API). Se hace el update primero; solo si cuadra se asienta el movimiento, para no dejar un asiento
    // de ledger sin su cambio de stock. Backend-gated: mover a un RPC atómico auditado (ver needs_founder).
    const { error: updErr } = await sb
      .from('product_variations')
      .update({ stock_quantity: newStock })
      .eq('id', variationId)
      .eq('tenant_id', m.tenant_id)
    if (updErr) {
      console.error('[catalog:adjustStock] fallo update stock', { variationId, error: updErr.message })
      return fail('No se pudo actualizar el stock. Intenta de nuevo.')
    }
    const { error: mvErr } = await sb.from('stock_movements').insert({
      tenant_id: m.tenant_id,
      product_id: productId,
      variation_id: variationId,
      delta: effectiveDelta,
      new_stock: newStock,
      reason,
      created_by: s?.user?.id ?? null,
    })
    if (mvErr) {
      // El stock ya cambió; solo falló el asiento de historial. Se registra para diagnóstico y se avisa.
      console.error('[catalog:adjustStock] stock actualizado pero fallo el asiento de movimiento', { variationId, error: mvErr.message })
      revalidatePath('/dashboard/catalog')
      return fail('Stock actualizado, pero no se pudo registrar el movimiento en el historial.')
    }
    revalidatePath('/dashboard/catalog')
    return ok(effectiveDelta === delta
      ? `Stock ajustado (${effectiveDelta > 0 ? '+' : ''}${effectiveDelta}).`
      : `Stock ajustado a 0 (movimiento registrado: ${effectiveDelta}).`)
  }

  async function saveThreshold(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return fail('No tienes permiso.')
    const val = parseInt(formData.get('threshold') as string)
    if (isNaN(val) || val < 0) return fail('Ingresa un umbral válido (0 o mayor).')
    const { error } = await sb.from('tenants').update({ low_stock_threshold: val }).eq('id', m.tenant_id)
    if (error) {
      console.error('[catalog:saveThreshold] fallo update', { error: error.message })
      return fail('No se pudo guardar el umbral. Intenta de nuevo.')
    }
    revalidatePath('/dashboard/catalog')
    return ok('Umbral de alerta actualizado.')
  }

  // ── UI ──────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 max-w-7xl flex-1 h-full overflow-auto">
      <ProductsManager
        products={products}
        archivedProducts={archivedProducts}
        catMap={catMap}
        canWrite={canWrite}
        productCategories={productCategories}
        attributeDefs={attributeDefs}
        tenantId={tenantId ?? ''}
        apiUrl={CORE_API_URL}
        threshold={threshold}
        activeTotal={activeTotal}
        loadError={loadError}
        editProductAction={editProduct}
        editVariationAction={editVariation}
        addVariationAction={addVariation}
        deleteVariationAction={deleteVariation}
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
