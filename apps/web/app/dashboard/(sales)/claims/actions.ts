'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'

export async function createClaim(data: {
  order_id: string
  customer_id: string | null
  reason: string
  requested_amount?: number
  resolution_notes?: string
}) {
  const supabase = createClient()
  
  const { data: userData, error: userError } = await supabase.auth.getUser()
  if (userError || !userData.user) return { error: 'Unauthorized' }
  const tenantId = userData.user.app_metadata.tenant_id

  const payload: any = {
    tenant_id: tenantId,
    order_id: data.order_id,
    customer_id: data.customer_id,
    reason: data.reason,
    status: 'open',
  }
  if (data.requested_amount) payload.requested_amount = data.requested_amount
  if (data.resolution_notes) payload.resolution_notes = data.resolution_notes

  const { error } = await supabase.from('claims').insert(payload)
  
  if (error) {
    console.error('Error creating claim:', error)
    return { error: error.message }
  }

  revalidatePath('/dashboard/claims')
  return { success: true }
}

export async function updateClaimStatus(claimId: string, status: string, notes?: string) {
  const supabase = createClient()
  
  const { data: userData, error: userError } = await supabase.auth.getUser()
  if (userError || !userData.user) return { error: 'Unauthorized' }
  const tenantId = userData.user.app_metadata.tenant_id

  const updatePayload: any = { status }
  if (notes !== undefined) updatePayload.resolution_notes = notes

  const { error } = await supabase
    .from('claims')
    .update(updatePayload)
    .eq('id', claimId)
    .eq('tenant_id', tenantId)

  if (error) {
    console.error('Error updating claim:', error)
    return { error: error.message }
  }

  revalidatePath('/dashboard/claims')
  return { success: true }
}
