import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { createClient } from '@/utils/supabase/server'
import CategoriesManager, { type CategoryRow } from './_components/categories-manager'

// ADR-0027 — gestión de categorías OPERATIVAS per-tenant (las que el bot presenta al cliente).
// READ directo (RLS via JWT, como el catálogo); WRITE vía API (actions.ts → RBAC + audit).
export default async function CategoriesPage() {
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = createClient()

  let categories: CategoryRow[] = []
  if (tenantId) {
    const [catsRes, prodsRes] = await Promise.all([
      supabase
        .from('product_categories')
        .select('id, name, display_label, sort_order')
        .eq('tenant_id', tenantId)
        .order('sort_order')
        .order('display_label'),
      supabase
        .from('products')
        .select('category_id')
        .eq('tenant_id', tenantId)
        .eq('status', 'active'),
    ])
    const cats = (catsRes.data as Omit<CategoryRow, 'product_count'>[]) ?? []
    const counts: Record<string, number> = {}
    for (const p of ((prodsRes.data as { category_id: string | null }[]) ?? [])) {
      if (p.category_id) counts[p.category_id] = (counts[p.category_id] ?? 0) + 1
    }
    categories = cats.map(c => ({ ...c, product_count: counts[c.id] ?? 0 }))
  }

  return <CategoriesManager categories={categories} canWrite={canWrite} />
}
