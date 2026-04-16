import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import PurchasesClient from './_components/purchases-client'

export const dynamic = 'force-dynamic'

export default async function PurchasesPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) {
    redirect('/auth/login')
  }

  const meta = user.app_metadata as { tenant_id?: string; role?: string }
  if (!meta.tenant_id) {
    return <div className="p-8 text-center text-red-500">Error: Usuario no asociado a ningún tenant.</div>
  }

  const role = meta.role ?? ''
  const canWrite = role === 'owner' || role === 'manager'

  // Fetch Suppliers
  const { data: suppliersRes } = await supabase
    .from('suppliers')
    .select('*')
    .eq('tenant_id', meta.tenant_id)
    .order('name')
  
  const suppliers = suppliersRes || []

  // Fetch Purchase Orders
  const { data: posRes } = await supabase
    .from('purchase_orders')
    .select(`
      id, status, expected_date, total_amount, created_at,
      suppliers(id, name),
      purchase_order_items(id, quantity, unit_cost, variation_id, product_variations(sku, price, products(title)))
    `)
    .eq('tenant_id', meta.tenant_id)
    .order('created_at', { ascending: false })
  
  const purchaseOrders = posRes || []

  // Fetch product variations to build new POs
  const { data: prods } = await supabase
    .from('products')
    .select(`
      id, title, status,
      product_variations(id, sku, price, cost_price, stock_quantity)
    `)
    .eq('tenant_id', meta.tenant_id)
    .eq('status', 'active')
    .order('title')

  const products = prods || []

  return (
    <div className="space-y-6 max-w-7xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
           Compras y Proveedores
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Gestiona tu cadena de suministro, reabastece inventario y controla costos
        </p>
      </div>

      <PurchasesClient 
        tenantId={meta.tenant_id}
        role={role}
        canWrite={canWrite}
        initialSuppliers={suppliers}
        initialPurchaseOrders={purchaseOrders}
        products={products}
      />
    </div>
  )
}
