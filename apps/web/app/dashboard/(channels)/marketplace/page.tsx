import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import { Store, ExternalLink, Eye } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import { Alert, AlertDescription } from '@/components/ui/alert'
import MarketplaceManager, { type MeliItem } from './_components/marketplace-manager'
import { EmptyState } from '@/components/ui/empty-state'
import { CORE_API_URL } from '@/lib/runtime-env'

export const metadata = { title: 'Mercado Libre' }

const PAGE_SIZE = 50

export default async function MarketplacePage(props: {
  searchParams: Promise<{ offset?: string }>
}) {
  // Sem 5 perf: cached.
  const user = await getCachedUser()
  if (!user) redirect('/login')

  // F3: paginación server-side. El offset viaja por query param (?offset=) para
  // que el pager sea navegable/compartible y el RSC re-consulte la página exacta.
  const sp = await props.searchParams
  const parsedOffset = Number.parseInt(sp.offset ?? '0', 10)
  const offset = Number.isFinite(parsedOffset) && parsedOffset > 0 ? parsedOffset : 0

  const supabase = await createClient()
  // getUser() ya validó el usuario. getSession() solo extrae el token para llamar la API interna.
  const { data: { session } } = await supabase.auth.getSession()
  const { tenantId, role } = await getCachedTenantMeta()
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
    // Gate migrado al EmptyState del DS (CABO 2, programa WOW): halo +
    // flotación + pop de entrada. Texto y CTA preservados verbatim.
    return (
      <div className="flex items-center justify-center h-[calc(100dvh-7rem)] sm:h-[calc(100vh-4rem)]">
        <EmptyState
          variant="plain"
          icon={Store}
          className="max-w-sm px-4"
          title="Mercado Libre no conectado"
          description="Conecta tu cuenta vendedor de Mercado Libre para gestionar tus publicaciones y sincronizar stock automáticamente."
          action={
            <a
              href="/dashboard/integrations"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-yellow-500 hover:bg-yellow-400 text-black text-sm font-medium transition-colors"
            >
              <ExternalLink className="h-4 w-4" /> Configurar integración
            </a>
          }
        />
      </div>
    )
  }

  // ── Publicaciones MeLi (desde API — datos reales de MeLi) ─────────────────
  let connected = false
  let items: MeliItem[] = []
  let paging: { total: number; limit?: number; offset?: number } = { total: 0, limit: PAGE_SIZE, offset }
  let marketplaceLoadError: string | null = null

  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/marketplace/listings?offset=${offset}&limit=${PAGE_SIZE}`, {
      headers: { 'Authorization': `Bearer ${session?.access_token}` },
      cache: 'no-store',
      signal: AbortSignal.timeout(12000),
    })
    if (!res.ok) {
      const raw = await res.text().catch(() => '')
      let detail = ''
      try {
        const parsed = JSON.parse(raw)
        detail = typeof parsed?.detail === 'string' ? parsed.detail : ''
      } catch {
        detail = raw
      }
      marketplaceLoadError = detail || `Error ${res.status} al cargar publicaciones de Mercado Libre.`
    } else {
      const data = await res.json()
      connected = data.connected ?? false
      items     = data.items ?? []
      paging    = data.paging ?? { total: 0, limit: PAGE_SIZE, offset }
    }
  } catch (error) {
    console.error('Failed to fetch marketplace listings:', error)
    marketplaceLoadError = 'No se pudo cargar Mercado Libre en este momento (timeout o error de red).'
  }

  if (marketplaceLoadError) {
    return (
      <div className="flex items-center justify-center h-[calc(100dvh-7rem)] sm:h-[calc(100vh-4rem)]">
        <div className="flex flex-col items-center gap-4 text-center max-w-lg px-4">
          <div className="h-14 w-14 rounded-2xl bg-red-500/10 border border-red-700/20 flex items-center justify-center">
            <Store className="h-7 w-7 text-red-700" />
          </div>
          <div className="space-y-1.5">
            <h2 className="text-base font-semibold">No se pudo cargar Mercado Libre</h2>
            <p className="text-muted-foreground text-sm leading-relaxed">
              La integración parece conectada, pero falló la consulta de publicaciones.
            </p>
            <p className="text-xs text-red-700 wrap-break-word">{marketplaceLoadError}</p>
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
    // Mismo patrón que el gate "no conectado" → EmptyState del DS (CABO 2).
    return (
      <div className="flex items-center justify-center h-[calc(100dvh-7rem)] sm:h-[calc(100vh-4rem)]">
        <EmptyState
          variant="plain"
          icon={Store}
          className="max-w-sm px-4"
          title="Mercado Libre requiere reconexión"
          description="El tenant aparece conectado, pero el API no pudo validar la sesión actual de Mercado Libre. Vuelve a conectar para restablecer el acceso."
          action={
            <a
              href="/dashboard/integrations"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-yellow-500 hover:bg-yellow-400 text-black text-sm font-medium transition-colors"
            >
              <ExternalLink className="h-4 w-4" /> Configurar integración
            </a>
          }
        />
      </div>
    )
  }

  // ── Categorías OPERATIVAS per-tenant (product_categories) — la ÚNICA taxonomía que se muestra al operador
  // y se asigna al importar: la que administra el módulo Categorías y usa el bot (ADR-0027/0029 D2). La de
  // marketplace (platform_categories) ya NO se usa aquí (ni para agrupar ni para el import → coherencia).
  const { data: pcats } = tenantId
    ? await supabase.from('product_categories').select('id, display_label').eq('tenant_id', tenantId).order('sort_order')
    : { data: [] }
  const categories = (pcats ?? []) as { id: string; display_label: string }[]
  const opCatMap = Object.fromEntries(categories.map(c => [c.id, c.display_label]))

  // ── Variantes del catálogo interno (Supabase directo con join de producto) ─
  // Usamos Supabase directo (no API) para poder resolver la categoría en el servidor
  type RawVariationProduct = { id: string; title: string; category_id: string | null }
  type RawVariation = {
    id: string
    sku: string
    stock_quantity: number
    price: number
    attributes: Record<string, string> | null
    products: RawVariationProduct | RawVariationProduct[] | null
  }
  let rawVariations: RawVariation[] = []
  if (tenantId) {
    // Techo de seguridad: el selector de vinculación es un combobox con
    // búsqueda client-side sobre este set. 1000 cubre cualquier catálogo real
    // del tenant y evita inflar el payload del RSC en casos patológicos.
    const { data } = await supabase
      .from('product_variations')
      .select('id, sku, stock_quantity, price, attributes, products(id, title, category_id)')
      .eq('tenant_id', tenantId)
      .order('sku')
      .limit(1000)
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
      const category_id  = product.category_id
      const category_name = category_id ? (opCatMap[category_id] ?? 'Sin categoría') : 'Sin categoría'
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
      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={Store}
        title="Mercado Libre"
        description="Tus publicaciones en MeLi. Vincula manualmente cada item al producto de tu catálogo para activar el sync de stock — solo los items vinculados se sincronizan."
      />

      {!canWrite && (
        <Alert className="border-border/60">
          <Eye className="h-4 w-4" />
          <AlertDescription className="text-sm text-muted-foreground">
            Tienes acceso de solo lectura. Puedes consultar las publicaciones y su vínculo con el catálogo,
            pero vincular, importar, pausar o sincronizar requiere el rol de propietario o gerente.
          </AlertDescription>
        </Alert>
      )}

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
