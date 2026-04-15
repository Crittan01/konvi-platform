import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import InventoryManager from './_components/inventory-manager'
import type { Product, Movement } from './types'

const DEFAULT_THRESHOLD = 5

export default async function InventoryPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const canWrite = role === 'owner' || role === 'manager'

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const [productsRes, movementsRes, tenantRes] = await Promise.all([
    supabase
      .from('products')
      .select('id, title, status, product_variations(id, attributes, stock_quantity, price, sku)')
      .eq('tenant_id', tenantId)
      .eq('status', 'active')
      .order('title'),
    supabase
      .from('stock_movements')
      .select('id, delta, new_stock, reason, created_at, variation_id')
      .eq('tenant_id', tenantId)
      .order('created_at', { ascending: false })
      .limit(30),
    supabase
      .from('tenants')
      .select('low_stock_threshold')
      .eq('id', tenantId)
      .single(),
  ])

  const products  = (productsRes.data as Product[]) ?? []
  const movements = (movementsRes.data as Movement[]) ?? []
  const threshold: number = (tenantRes.data as { low_stock_threshold?: number } | null)?.low_stock_threshold ?? DEFAULT_THRESHOLD

  // ── Server Actions ────────────────────────────────────────────────────────

  async function adjustStock(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    
    const variationId = formData.get('variation_id') as string
    const productId   = formData.get('product_id') as string
    const delta       = parseInt(formData.get('delta') as string)
    const reason      = (formData.get('reason') as string) || 'Ajuste manual'
    
    if (!variationId || isNaN(delta) || delta === 0) return
    
    const { data: variation } = await sb
      .from('product_variations')
      .select('stock_quantity')
      .eq('id', variationId)
      .eq('tenant_id', m.tenant_id)
      .single()
      
    if (!variation) return
    
    const newStock = Math.max(0, (variation as { stock_quantity: number }).stock_quantity + delta)
    const { data: { session: s } } = await sb.auth.getSession()
    
    await Promise.all([
      sb.from('product_variations').update({ stock_quantity: newStock }).eq('id', variationId).eq('tenant_id', m.tenant_id),
      sb.from('stock_movements').insert({
        tenant_id: m.tenant_id, 
        product_id: productId, 
        variation_id: variationId,
        delta, 
        new_stock: newStock, 
        reason, 
        created_by: s?.user?.id ?? null,
      }),
    ])
    revalidatePath('/dashboard/inventory')
  }

  async function saveThreshold(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    
    const val = parseInt(formData.get('threshold') as string)
    if (isNaN(val) || val < 0) return
    
    await sb.from('tenants').update({ low_stock_threshold: val }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/inventory')
  }

  return (
    <InventoryManager
      products={products}
      movements={movements}
      threshold={threshold}
      canWrite={canWrite}
      role={role}
      adjustStockAction={adjustStock}
      saveThresholdAction={saveThreshold}
    />
  )
}
