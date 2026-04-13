import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import MarketplaceManager from './_components/marketplace-manager'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

export default async function MarketplacePage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) redirect('/login')

  const { data: { session } } = await supabase.auth.getSession()
  const meta     = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role     = meta.role ?? 'agent'
  const canWrite = ['owner', 'manager'].includes(role)

  // ── Publicaciones MeLi (desde API — datos reales de MeLi) ─────────────────
  let connected = false
  let items: any[] = []
  let paging = { total: 0 }

  try {
    const res = await fetch(`${API_URL}/api/v1/marketplace/listings`, {
      headers: { 'Authorization': `Bearer ${session?.access_token}` },
      cache: 'no-store'
    })
    if (res.ok) {
      const data = await res.json()
      connected = data.connected ?? false
      items     = data.items ?? []
      paging    = data.paging ?? { total: 0 }
    }
  } catch (error) {
    console.error('Failed to fetch marketplace listings:', error)
  }

  // ── Categorías globales (Supabase directo — igual que catalog/page.tsx) ────
  const { data: cats } = await supabase
    .from('platform_categories')
    .select('id, name')
    .eq('is_active', true)
    .order('name')
  const catMap = Object.fromEntries(
    ((cats ?? []) as { id: string; name: string }[]).map(c => [c.id, c.name])
  )

  // ── Variantes del catálogo interno (Supabase directo con join de producto) ─
  // Usamos Supabase directo (no API) para poder resolver la categoría en el servidor
  type RawVariation = {
    id: string
    sku: string
    stock_quantity: number
    price: number
    attributes: Record<string, string> | null
    products: { id: string; title: string; platform_category_id: string | null } | null
  }

  let rawVariations: RawVariation[] = []
  if (tenantId) {
    const { data } = await supabase
      .from('product_variations')
      .select('id, sku, stock_quantity, price, attributes, products(id, title, platform_category_id)')
      .eq('tenant_id', tenantId)
      .order('sku')
    rawVariations = (data ?? []) as RawVariation[]
  }

  // ── Construir lista enriquecida para el selector ───────────────────────────
  // Estructura: { categoryId, categoryName, productId, productTitle, variation: {...} }
  type VariationOption = {
    id: string
    sku: string
    stock_quantity: number
    price: number
    attributes: Record<string, string>
    product_id: string
    product_title: string
    category_id: string | null
    category_name: string
  }

  const variations: VariationOption[] = rawVariations
    .filter(v => v.products)
    .map(v => {
      const product      = v.products!
      const category_id  = product.platform_category_id
      const category_name = category_id ? (catMap[category_id] ?? 'Sin categoría') : 'Sin categoría'
      return {
        id:             v.id,
        sku:            v.sku,
        stock_quantity: v.stock_quantity,
        price:          v.price,
        attributes:     (v.attributes ?? {}) as Record<string, string>,
        product_id:     product.id,
        product_title:  product.title,
        category_id,
        category_name,
      }
    })

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-7xl mx-auto flex-1 h-full overflow-auto">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Mercado Libre</h1>
        <p className="text-muted-foreground max-w-3xl">
          Gestión de tus publicaciones en Mercado Libre. Los datos vienen directamente de tu cuenta MeLi.
          Vincula cada publicación con una variante de tu catálogo para mantener el stock sincronizado automáticamente.
        </p>
      </div>

      <MarketplaceManager
        connected={connected}
        items={items}
        paging={paging}
        variations={variations}
        canWrite={canWrite}
      />
    </div>
  )
}
