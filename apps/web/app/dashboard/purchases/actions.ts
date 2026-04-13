'use server'

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'

export async function addSupplier(formData: FormData) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const m = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

  const name = formData.get('name') as string
  const contact_email = formData.get('contact_email') as string
  const phone = formData.get('phone') as string
  const lead_time_days = parseInt(formData.get('lead_time_days') as string) || 0

  if (!name.trim()) return

  await supabase.from('suppliers').insert({
    tenant_id: m.tenant_id,
    name: name.trim(),
    contact_email: contact_email.trim() || null,
    phone: phone.trim() || null,
    lead_time_days
  })

  revalidatePath('/dashboard/purchases')
}

export async function createPurchaseOrder(formData: FormData) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const m = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

  const supplier_id = formData.get('supplier_id') as string
  const expected_str = formData.get('expected_date') as string
  const expected_date = expected_str ? new Date(expected_str).toISOString() : null
  
  const itemsStr = formData.get('items') as string
  if (!itemsStr || !supplier_id) return
  
  const items = JSON.parse(itemsStr) as Array<{ variation_id: string; quantity: number; unit_cost: number }>
  if (!items.length) return

  const total_amount = items.reduce((acc, i) => acc + (i.quantity * i.unit_cost), 0)

  const poRes = await supabase.from('purchase_orders').insert({
    tenant_id: m.tenant_id,
    supplier_id,
    status: 'ordered',
    expected_date,
    total_amount
  }).select('id').single()

  if (!poRes.data || poRes.error) return

  const poId = poRes.data.id

  const validItems = items.map(i => ({
    tenant_id: m.tenant_id,
    po_id: poId,
    variation_id: i.variation_id,
    quantity: i.quantity,
    unit_cost: i.unit_cost
  }))

  await supabase.from('purchase_order_items').insert(validItems)

  revalidatePath('/dashboard/purchases')
}

export async function cancelPurchaseOrder(poId: string) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const m = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

  await supabase
    .from('purchase_orders')
    .update({ status: 'cancelled' })
    .eq('id', poId)
    .eq('tenant_id', m.tenant_id)
    .eq('status', 'ordered')

  revalidatePath('/dashboard/purchases')
}

export async function receivePurchaseOrder(poId: string) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const m = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

  // 1. Get PO items
  const { data: items } = await supabase
    .from('purchase_order_items')
    .select('variation_id, quantity, unit_cost')
    .eq('po_id', poId)
    .eq('tenant_id', m.tenant_id)
  
  if (!items) return

  // 2. Mark PO as received
  const { error: poErr } = await supabase
    .from('purchase_orders')
    .update({ status: 'received' })
    .eq('id', poId)
    .eq('tenant_id', m.tenant_id)
    .eq('status', 'ordered')
  
  if (poErr) return

  // 3. Update stock and WAC cost_price for each variation
  for (const item of items) {
    const { data: varData } = await supabase
      .from('product_variations')
      .select('stock_quantity, cost_price')
      .eq('id', item.variation_id)
      .single()
    
    if (varData) {
      const currentStock = varData.stock_quantity || 0
      const currentCost = varData.cost_price || 0
      const newStock = currentStock + item.quantity
      
      // Calculate Weighted Average Cost (WAC)
      let wac = 0
      if (newStock > 0) {
        // Handle negative stock anomalies safely
        const effectiveStock = Math.max(0, currentStock)
        wac = ((effectiveStock * currentCost) + (item.quantity * item.unit_cost)) / (effectiveStock + item.quantity)
      }

      await supabase.from('product_variations').update({
        stock_quantity: newStock,
        cost_price: wac
      }).eq('id', item.variation_id)

      // Audit movement
      await supabase.from('stock_movements').insert({
        tenant_id: m.tenant_id,
        variation_id: item.variation_id,
        delta: item.quantity,
        new_stock: newStock,
        reason: 'purchase_restock'
      })
    }
  }

  revalidatePath('/dashboard/purchases')
}
