import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { ShoppingCart } from 'lucide-react'
import PurchasesClient from './_components/purchases-client'
import type { PurchaseOrder } from './_components/purchase-orders-manager'

export const dynamic = 'force-dynamic'

// Ventana de listado: acotamos el historial para no traer joins anidados sin
// cota (data-fetching.md). El operador ve las más recientes; el total real se
// muestra como contador para no fingir un "0" cuando hay más.
const PO_LIMIT = 100
// Cota del catálogo que puebla el combobox de ítems. Con catálogos enormes la
// búsqueda server-side sería lo ideal (requiere endpoint), pero acotar + filtrar
// en cliente mantiene el picker usable sin inflar el RSC sin límite.
const CATALOG_LIMIT = 300

export default async function PurchasesPage() {
  // Sem 5 perf: cached comparten con DashboardLayout.
  const user = await getCachedUser()
  if (!user) redirect('/login')

  const { tenantId, role } = await getCachedTenantMeta()
  if (!tenantId) {
    return <div className="p-8 text-center text-destructive">Error: Usuario no asociado a ningún tenant.</div>
  }
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = await createClient()

  // Fuente única de tenant_id: el mismo valor que pasamos al cliente filtra las
  // queries (antes se leía user.app_metadata.tenant_id por separado — si divergía
  // del cached meta, se filtraba distinto de lo que veía el cliente).

  // Suppliers
  const { data: suppliersRes, error: suppliersError } = await supabase
    .from('suppliers')
    .select('id, name, contact_email, phone, lead_time_days')
    .eq('tenant_id', tenantId)
    .order('name')

  const suppliers = suppliersRes || []

  // Purchase Orders (acotado + contador total)
  const { data: posRes, error: posError } = await supabase
    .from('purchase_orders')
    .select(`
      id, status, expected_date, total_amount, created_at,
      suppliers(id, name),
      purchase_order_items(id, quantity, unit_cost, variation_id, product_variations(sku, products(title)))
    `)
    .eq('tenant_id', tenantId)
    .order('created_at', { ascending: false })
    .limit(PO_LIMIT)

  const { count: poTotal } = await supabase
    .from('purchase_orders')
    .select('id', { count: 'exact', head: true })
    .eq('tenant_id', tenantId)

  // Supabase infiere las relaciones anidadas (suppliers, product_variations) como
  // arrays, pero al ser FKs to-one el runtime devuelve objeto — que es lo que el
  // componente lee. Cast en el boundary para reflejar el shape real.
  const purchaseOrders = (posRes || []) as unknown as PurchaseOrder[]

  // Catálogo para armar nuevas OCs (solo columnas que el picker consume).
  const { data: prods, error: prodsError } = await supabase
    .from('products')
    .select(`
      id, title, status,
      product_variations(id, sku, cost_price, stock_quantity)
    `)
    .eq('tenant_id', tenantId)
    .eq('status', 'active')
    .order('title')
    .limit(CATALOG_LIMIT)

  const products = prods || []

  // No tragar el fallo de DB: si alguna query erró, el cliente muestra banner de
  // error en vez de un vacío indistinguible de "tenant nuevo".
  const loadError = suppliersError?.message || posError?.message || prodsError?.message || null

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
        loadError={loadError}
        totalOrders={poTotal ?? purchaseOrders.length}
      />
    </div>
  )
}
