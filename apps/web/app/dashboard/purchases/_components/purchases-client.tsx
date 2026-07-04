'use client'

import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Building2, ShoppingCart, AlertTriangle } from 'lucide-react'
import SuppliersManager, { type Supplier } from './suppliers-manager'
import PurchaseOrdersManager, { type PurchaseOrder, type PurchaseProduct } from './purchase-orders-manager'

type Props = {
  tenantId: string
  role: string
  canWrite: boolean
  initialSuppliers: Supplier[]
  initialPurchaseOrders: PurchaseOrder[]
  products: PurchaseProduct[]
  loadError: string | null
  totalOrders: number
}

export default function PurchasesClient({
  canWrite,
  initialSuppliers,
  initialPurchaseOrders,
  products,
  loadError,
  totalOrders,
}: Props) {
  const [activeTab, setActiveTab] = useState('orders')

  // Fallo de carga en el RSC: mostrarlo explícito para que el operador no
  // confunda un error de DB con "tenant nuevo" (listas vacías por swallow).
  if (loadError) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>No se pudieron cargar tus compras</AlertTitle>
        <AlertDescription>
          Ocurrió un problema al consultar la base de datos. Refresca la página; si persiste, contacta a soporte.
          <span className="block mt-1 text-xs opacity-70">Detalle: {loadError}</span>
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
      <TabsList className="mb-4">
        <TabsTrigger value="orders" className="flex items-center gap-2">
          <ShoppingCart className="h-4 w-4" /> Órdenes de Compra
        </TabsTrigger>
        <TabsTrigger value="suppliers" className="flex items-center gap-2">
          <Building2 className="h-4 w-4" /> Proveedores
        </TabsTrigger>
      </TabsList>

      <TabsContent value="orders" className="m-0 mt-2">
        <PurchaseOrdersManager
          orders={initialPurchaseOrders}
          suppliers={initialSuppliers}
          products={products}
          canWrite={canWrite}
          totalOrders={totalOrders}
        />
      </TabsContent>

      <TabsContent value="suppliers" className="m-0 mt-2">
        <SuppliersManager suppliers={initialSuppliers} canWrite={canWrite} />
      </TabsContent>
    </Tabs>
  )
}
