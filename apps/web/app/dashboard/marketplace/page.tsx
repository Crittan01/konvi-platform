import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import MarketplaceManager from './_components/marketplace-manager'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

export default async function MarketplacePage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()

  if (!session) {
    redirect('/auth/login')
  }

  const { data: { user } } = await supabase.auth.getUser()
  const role = user?.app_metadata?.role || 'agent'
  const canWrite = ['owner', 'manager'].includes(role)

  // Fetch listing data from Backend
  let items = []
  try {
    const res = await fetch(`${API_URL}/api/v1/marketplace/listings`, {
      headers: {
        'Authorization': `Bearer ${session.access_token}`
      },
      cache: 'no-store'
    })
    if (res.ok) {
      const data = await res.json()
      items = data.items || []
    }
  } catch (error) {
    console.error("Failed to fetch marketplace listings:", error)
  }

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-7xl mx-auto flex-1 h-full overflow-auto">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Sindicación a Mercado Libre</h1>
        <p className="text-muted-foreground w-full max-w-3xl">
          Visualiza qué parte de tu Catálogo Central se encuentra publicado en la plataforma externa. 
          Aquí puedes publicar nuevos productos, ajustar sus precios unitarios (para cubrir comisiones) 
          y pausar anuncios en tiempo real.
        </p>
      </div>

      <MarketplaceManager items={items} canWrite={canWrite} />
    </div>
  )
}
