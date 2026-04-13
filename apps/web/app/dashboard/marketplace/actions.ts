'use server'

import { revalidatePath } from 'next/cache'
import { createClient } from '@/utils/supabase/server'

// In a real app we'd load this from env variables instead of hard-coding the api service url
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

export async function publishToMarketplace(variationId: string, externalPrice: number) {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token || ''

  try {
    const res = await fetch(`${API_URL}/api/v1/marketplace/publish`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ variation_id: variationId, external_price: externalPrice })
    })

    if (!res.ok) {
       const detail = await res.text()
       throw new Error(detail || res.statusText)
    }

    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch(error: any) {
    return { error: error.message || 'Error al conectar con la API' }
  }
}

export async function changeListingStatus(listingId: string, status: 'active' | 'paused' | 'closed') {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token || ''

  try {
    const res = await fetch(`${API_URL}/api/v1/marketplace/${listingId}/status`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ status })
    })

    if (!res.ok) {
       const detail = await res.text()
       throw new Error(detail || res.statusText)
    }

    revalidatePath('/dashboard/marketplace')
    return { success: true }
  } catch (error: any) {
    return { error: error.message || 'Error al conectar con la API' }
  }
}
