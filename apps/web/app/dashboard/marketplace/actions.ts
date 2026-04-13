'use server'

import { revalidatePath } from 'next/cache'
import { cookies } from 'next/headers'

// In a real app we'd load this from env variables instead of hard-coding the api service url
const API_URL = process.env.API_URL || 'http://localhost:8000'

export async function publishToMarketplace(variationId: string, externalPrice: number) {
  const cookieStore = cookies()
  const token = cookieStore.get('sb-access-token')?.value || ''

  await fetch(`${API_URL}/api/v1/marketplace/publish`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({ variation_id: variationId, external_price: externalPrice })
  })

  revalidatePath('/dashboard/marketplace')
}

export async function changeListingStatus(listingId: string, status: 'active' | 'paused' | 'closed') {
  const cookieStore = cookies()
  const token = cookieStore.get('sb-access-token')?.value || ''

  await fetch(`${API_URL}/api/v1/marketplace/${listingId}/status`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({ status })
  })

  revalidatePath('/dashboard/marketplace')
}
