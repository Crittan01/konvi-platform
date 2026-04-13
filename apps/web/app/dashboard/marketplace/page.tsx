import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import MarketplaceManager from './_components/marketplace-manager'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

export default async function MarketplacePage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) redirect('/login')

  const { data: { session } } = await supabase.auth.getSession()
  const role = user?.app_metadata?.role || 'agent'
  const canWrite = ['owner', 'manager'].includes(role)

  // Cargar items reales de MeLi + estado de vinculación con Supabase
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
      items = data.items ?? []
      paging = data.paging ?? { total: 0 }
    }
  } catch (error) {
    console.error('Failed to fetch marketplace listings:', error)
  }

  // Cargar variantes de Supabase (para el selector de vinculación)
  let variations: any[] = []
  try {
    const res = await fetch(`${API_URL}/api/v1/products/?limit=200`, {
      headers: { 'Authorization': `Bearer ${session?.access_token}` },
      cache: 'no-store'
    })
    if (res.ok) {
      const products = await res.json()
      // Aplanar variantes con nombre del producto
      // El campo viene como 'product_variations' del join de Supabase
      for (const product of products) {
        for (const v of product.product_variations ?? []) {
          variations.push({
            id: v.id,
            label: `${product.title} — ${v.sku} (Stock: ${v.stock_quantity})`,
            sku: v.sku,
            stock_quantity: v.stock_quantity,
            product_title: product.title,
          })
        }
      }
    }
  } catch (error) {
    console.error('Failed to fetch products for link selector:', error)
  }

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-7xl mx-auto flex-1 h-full overflow-auto">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Mercado Libre</h1>
        <p className="text-muted-foreground max-w-3xl">
          Gestión de tus publicaciones en Mercado Libre. Los datos vienen directamente de tu cuenta MeLi.
          Vincula cada publicación con una variante de tu catálogo interno para mantener el stock sincronizado automáticamente.
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
