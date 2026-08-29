import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { createClient } from '@/utils/supabase/server'
import CategoriesManager, { type CategoryRow, type AttributeDef } from './_components/categories-manager'

export const metadata = { title: 'Categorías' }

// ADR-0027 — gestión de categorías OPERATIVAS per-tenant (las que el bot presenta al cliente).
// READ directo (RLS via JWT, como el catálogo); WRITE vía API (actions.ts → RBAC + audit).

// Cota del conteo de productos por categoría. Alineada con MAX_CATALOG_PRODUCTS
// (ADR-0027): si un tenant superara este techo, el conteo por-categoría dejaría
// de ser completo y hay que señalizarlo (nunca mostrar un total inexacto en silencio).
const PRODUCT_COUNT_CAP = 1000

export default async function CategoriesPage() {
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = await createClient()

  let categories: CategoryRow[] = []
  let attributeDefs: AttributeDef[] = []
  let loadError: string | null = null
  let countsExact = true
  if (tenantId) {
    const [catsRes, prodsRes, defsRes] = await Promise.all([
      supabase
        .from('product_categories')
        .select('id, name, display_label, sort_order, parent_id')
        .eq('tenant_id', tenantId)
        .order('sort_order')
        .order('display_label'),
      // `count: exact` da el total real del tenant; `limit(CAP)` acota las filas que
      // agrupamos en memoria. Si count > filas traídas, el conteo por-categoría está
      // truncado → lo señalizamos en la UI en vez de mostrar un badge inexacto.
      supabase
        .from('products')
        .select('category_id', { count: 'exact' })
        .eq('tenant_id', tenantId)
        .eq('status', 'active')
        .limit(PRODUCT_COUNT_CAP),
      // ADR-0029 D3 — contrato de atributos por categoría (READ directo por RLS; WRITE vía actions.ts).
      supabase
        .from('product_attribute_definitions')
        .select('id, product_category_id, label, type, unit, is_variant_axis, allowed_values, sort_order')
        .eq('tenant_id', tenantId)
        .order('sort_order'),
    ])

    // Surfacear errores: un fallo de RLS/red debe verse como error (con reintento),
    // NO degradarse a "no hay categorías" (falso-vacío) ni a "0 productos" (falso-0).
    if (catsRes.error || defsRes.error) {
      loadError = catsRes.error?.message || defsRes.error?.message || 'No se pudieron cargar las categorías.'
    }
    if (prodsRes.error) {
      countsExact = false
      console.warn('[categories] conteo de productos falló:', prodsRes.error.message)
    }

    const cats = (catsRes.data as Omit<CategoryRow, 'product_count'>[]) ?? []
    const rows = (prodsRes.data as { category_id: string | null }[]) ?? []
    const total = prodsRes.count ?? rows.length
    if (total > rows.length) {
      countsExact = false
      console.warn(`[categories] conteo truncado: ${rows.length}/${total} productos activos (cap ${PRODUCT_COUNT_CAP}).`)
    }
    const counts: Record<string, number> = {}
    for (const p of rows) {
      if (p.category_id) counts[p.category_id] = (counts[p.category_id] ?? 0) + 1
    }
    categories = cats.map(c => ({ ...c, product_count: counts[c.id] ?? 0 }))
    attributeDefs = (defsRes.data as AttributeDef[]) ?? []
  }

  return (
    <CategoriesManager
      categories={categories}
      attributeDefs={attributeDefs}
      canWrite={canWrite}
      loadError={loadError}
      countsExact={countsExact}
    />
  )
}
