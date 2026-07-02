import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { ShoppingCart } from 'lucide-react'
import PurchasesClient from './_components/purchases-client'
import type { PurchaseOrder } from './_components/purchase-orders-manager'

export const dynamic = 'force-dynamic'

export default async function PurchasesPage() {
  // Sem 5 perf: cached comparten con DashboardLayout.
  const user = await getCachedUser()
  if (!user) redirect('/login')

  const { tenantId, role } = await getCachedTenantMeta()
  if (!tenantId) {
    return <div className="p-8 text-center text-destructive">Error: Usuario no asociado a ningún tenant.</div>
  }
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = createClient()
  const meta = user.app_metadata as { tenant_id?: string; role?: string }

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
  
  // Supabase infiere las relaciones anidadas (suppliers, product_variations) como
  // arrays, pero al ser FKs to-one el runtime devuelve objeto — que es lo que el
  // componente lee. Cast en el boundary para reflejar el shape real.
  const purchaseOrders = (posRes || []) as unknown as PurchaseOrder[]

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
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <ShoppingCart className="h-5 w-5 text-primary" /> Compras y Proveedores
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Gestiona tu cadena de suministro, reabastece inventario y controla costos
        </p>
      </div>

      <PurchasesClient
        tenantId={tenantId}
        role={role}
        canWrite={canWrite}
        initialSuppliers={suppliers}
        initialPurchaseOrders={purchaseOrders}
        products={products}
      />
    </div>
  )
}
