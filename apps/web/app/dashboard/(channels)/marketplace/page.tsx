import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Store, ExternalLink } from 'lucide-react'
import MarketplaceManager from './_components/marketplace-manager'
import { CORE_API_URL } from '@/lib/runtime-env'

export default async function MarketplacePage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) redirect('/login')

  // getUser() ya validó el usuario. getSession() solo extrae el token para llamar la API interna.
  const { data: { session } } = await supabase.auth.getSession()
  const meta     = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role     = meta.role ?? 'operator'
  const canWrite = ['owner', 'manager'].includes(role)

  // ── Estado integración MeLi desde DB (fuente local) ───────────────────────
  const { data: meliInt } = await supabase
    .from('tenant_integrations')
    .select('status')
    .eq('tenant_id', tenantId ?? '')
    .eq('provider', 'mercadolibre')
    .maybeSingle()

  const meliConnectedInDb = meliInt?.status === 'connected'

  if (!meliConnectedInDb) {
    return (
      <div className="flex items-center justify-center h-[calc(100dvh-7rem)] sm:h-[calc(100vh-4rem)]">
        <div className="flex flex-col items-center gap-4 text-center max-w-sm px-4">
          <div className="h-14 w-14 rounded-2xl bg-yellow-500/10 border border-yellow-500/20 flex items-center justify-center">
            <Store className="h-7 w-7 text-yellow-500" />
          </div>
          <div className="space-y-1.5">
            <h2 className="text-base font-semibold">Mercado Libre no conectado</h2>
            <p className="text-muted-foreground text-sm leading-relaxed">
              Conecta tu cuenta vendedor de Mercado Libre para gestionar tus publicaciones y sincronizar stock automáticamente.
            </p>
          </div>
          <a
            href="/dashboard/integrations"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-yellow-500 hover:bg-yellow-400 text-black text-sm font-medium transition-colors"
          >
            <ExternalLink className="h-4 w-4" /> Configurar integración
          </a>
        </div>
      </div>
    )
  }

  // ── Publicaciones MeLi (desde API — datos reales de MeLi) ─────────────────
  let connected = false
  let items: any[] = []
  let paging = { total: 0 }
  let marketplaceLoadError: string | null = null

  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/listings`, {
      headers: { 'Authorization': `Bearer ${session?.access_token}` },
      cache: 'no-store',
      signal: AbortSignal.timeout(12000),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      marketplaceLoadError = detail || `Error ${res.status} al cargar publicaciones de Mercado Libre.`
    } else {
      const data = await res.json()
      connected = data.connected ?? false
      items     = data.items ?? []
      paging    = data.paging ?? { total: 0 }
    }
  } catch (error) {
    console.error('Failed to fetch marketplace listings:', error)
    marketplaceLoadError = 'No se pudo cargar Mercado Libre en este momento (timeout o error de red).'
  }

  if (marketplaceLoadError) {
    return (
      <div className="flex items-center justify-center h-[calc(100dvh-7rem)] sm:h-[calc(100vh-4rem)]">
        <div className="flex flex-col items-center gap-4 text-center max-w-lg px-4">
          <div className="h-14 w-14 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center">
            <Store className="h-7 w-7 text-red-500" />
          </div>
          <div className="space-y-1.5">
            <h2 className="text-base font-semibold">No se pudo cargar Mercado Libre</h2>
            <p className="text-muted-foreground text-sm leading-relaxed">
              La integración parece conectada, pero falló la consulta de publicaciones.
            </p>
            <p className="text-xs text-red-400 font-mono break-words">{marketplaceLoadError}</p>
          </div>
          <div className="flex items-center gap-2">
            <a
              href="/dashboard/marketplace"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium transition-colors hover:opacity-90"
            >
              Reintentar
            </a>
            <a
              href="/dashboard/integrations"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-border bg-card text-sm font-medium transition-colors hover:bg-muted"
            >
              Revisar integración
            </a>
          </div>
        </div>
      </div>
    )
  }

  if (!connected) {
    return (
      <div className="flex items-center justify-center h-[calc(100dvh-7rem)] sm:h-[calc(100vh-4rem)]">
        <div className="flex flex-col items-center gap-4 text-center max-w-sm px-4">
          <div className="h-14 w-14 rounded-2xl bg-yellow-500/10 border border-yellow-500/20 flex items-center justify-center">
            <Store className="h-7 w-7 text-yellow-500" />
          </div>
          <div className="space-y-1.5">
            <h2 className="text-base font-semibold">Mercado Libre requiere reconexión</h2>
            <p className="text-muted-foreground text-sm leading-relaxed">
              El tenant aparece conectado, pero el API no pudo validar la sesión actual de Mercado Libre.
              Vuelve a conectar para restablecer el acceso.
            </p>
          </div>
          <a
            href="/dashboard/integrations"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-yellow-500 hover:bg-yellow-400 text-black text-sm font-medium transition-colors"
          >
            <ExternalLink className="h-4 w-4" /> Configurar integración
          </a>
        </div>
      </div>
    )
  }

  // ── Categorías globales (Supabase directo — igual que catalog/page.tsx) ────
  const { data: cats } = await supabase
    .from('platform_categories')
    .select('id, name')
    .eq('is_active', true)
    .order('name')
  const categories = (cats ?? []) as { id: string; name: string }[]
  const catMap = Object.fromEntries(categories.map(c => [c.id, c.name]))

  // ── Variantes del catálogo interno (Supabase directo con join de producto) ─
  // Usamos Supabase directo (no API) para poder resolver la categoría en el servidor
  let rawVariations: any[] = []
  if (tenantId) {
    const { data } = await supabase
      .from('product_variations')
      .select('id, sku, stock_quantity, price, attributes, products(id, title, platform_category_id)')
      .eq('tenant_id', tenantId)
      .order('sku')
    rawVariations = data ?? []
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

  const variations = rawVariations
    .filter(v => v.products)
    .map(v => {
      // Supabase puede retornar el join como objeto o array según la dirección del FK
      const product      = Array.isArray(v.products) ? v.products[0] : v.products
      if (!product) return null
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
    }).filter(Boolean) as VariationOption[]

  return (
    <div className="space-y-6 max-w-7xl flex-1 h-full overflow-auto">
      <div className="flex flex-col gap-2">
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Store className="h-5 w-5 text-yellow-500" /> Mercado Libre
        </h1>
        <p className="text-muted-foreground max-w-3xl text-sm">
          Tus publicaciones en MeLi. Vincula manualmente cada item al producto de tu catálogo para activar el sync de stock — solo los items vinculados se sincronizan.
        </p>
      </div>

      <MarketplaceManager
        items={items}
        paging={paging}
        variations={variations}
        categories={categories}
        canWrite={canWrite}
      />
    </div>
  )
}
