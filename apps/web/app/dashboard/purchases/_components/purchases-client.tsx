'use client'

import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Building2, ShoppingCart } from 'lucide-react'
import SuppliersManager from './suppliers-manager'
import PurchaseOrdersManager from './purchase-orders-manager'

type Props = {
  tenantId: string
  role: string
  canWrite: boolean
  initialSuppliers: any[]
  initialPurchaseOrders: any[]
  products: any[]
}

export default function PurchasesClient({
  tenantId,
  role,
  canWrite,
  initialSuppliers,
  initialPurchaseOrders,
  products
}: Props) {
  const [activeTab, setActiveTab] = useState('orders')

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
        />
      </TabsContent>

      <TabsContent value="suppliers" className="m-0 mt-2">
        <SuppliersManager 
          suppliers={initialSuppliers} 
          canWrite={canWrite} 
        />
      </TabsContent>
    </Tabs>
  )
}
