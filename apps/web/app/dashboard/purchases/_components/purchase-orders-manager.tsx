'use client'

import { useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { SubmitButton } from '@/components/ui/submit-button'
import { Plus, PackageSearch, Trash2, Check, XCircle } from 'lucide-react'
import { createPurchaseOrder, receivePurchaseOrder, cancelPurchaseOrder } from '../actions'

type Props = {
  orders: any[]
  suppliers: any[]
  products: any[]
  canWrite: boolean
}

export default function PurchaseOrdersManager({ orders, suppliers, products, canWrite }: Props) {
  const [showAdd, setShowAdd] = useState(false)
  const [selectedSupplier, setSelectedSupplier] = useState('')
  const [expectedDate, setExpectedDate] = useState('')
  const [items, setItems] = useState<Array<{ variation_id: string, product_title: string, qty: number, cost: number }>>([])

  const getProductVariations = () => {
    const list = []
    for (const p of products) {
      for (const v of (p.product_variations || [])) {
        list.push({ ...v, product_title: p.title })
      }
    }
    return list
  }
  const variations = getProductVariations()

  const addItem = (vid: string) => {
    if (!vid) return
    const v = variations.find(x => x.id === vid)
    if (!v) return
    setItems(prev => [...prev, { variation_id: v.id, product_title: v.product_title, qty: 10, cost: v.cost_price || 0 }])
  }

  const completePO = async () => {
    if (!selectedSupplier || items.length === 0) return
    const fd = new FormData()
    fd.append('supplier_id', selectedSupplier)
    if (expectedDate) fd.append('expected_date', expectedDate)
    
    const payload = items.map(i => ({ variation_id: i.variation_id, quantity: i.qty, unit_cost: i.cost }))
    fd.append('items', JSON.stringify(payload))
    await createPurchaseOrder(fd)
    setShowAdd(false)
    setItems([])
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center bg-muted/20 p-3 rounded-lg border border-border/50">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">Órdenes a Proveedores</h2>
          <p className="text-xs text-muted-foreground">Historial de reabastecimiento</p>
        </div>
        {canWrite && !showAdd && suppliers.length > 0 && (
          <Button onClick={() => setShowAdd(true)} size="sm" className="h-8 text-xs gap-1.5">
            <Plus className="h-3.5 w-3.5" /> Nueva Orden
          </Button>
        )}
      </div>

      {showAdd && (
        <Card className="border-primary/50 shadow-md">
           <CardContent className="pt-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-muted-foreground uppercase">Proveedor *</label>
                  <select value={selectedSupplier} onChange={(e) => setSelectedSupplier(e.target.value)} className="w-full h-9 px-3 rounded-md border text-sm bg-background">
                    <option value="">Selecciona...</option>
                    {suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-muted-foreground uppercase">Fecha Estimada de Llegada</label>
                  <input type="date" value={expectedDate} onChange={(e) => setExpectedDate(e.target.value)} className="w-full h-9 px-3 rounded-md border text-sm bg-background" />
                </div>
              </div>

              <div className="pt-4 border-t">
                <div className="flex items-center gap-2 mb-2">
                  <label className="text-xs font-semibold text-muted-foreground uppercase">Añadir Ítems a la Orden</label>
                  <select onChange={e => { addItem(e.target.value); e.target.value="" }} className="h-7 text-xs bg-muted/50 rounded flex-1 px-2 border border-border">
                    <option value="">Buscar producto / SKU...</option>
                    {variations.map(v => <option key={v.id} value={v.id}>{v.product_title} - {v.sku || 'Sin SKU'}</option>)}
                  </select>
                </div>
                
                {items.length > 0 && (
                  <div className="border rounded-md overflow-hidden bg-muted/10">
                    <table className="w-full text-xs text-left">
                      <thead className="bg-muted">
                        <tr>
                          <th className="p-2 font-medium">Producto</th>
                          <th className="p-2 font-medium w-20">Cantidad</th>
                          <th className="p-2 font-medium w-24">Costo Total</th>
                          <th className="p-2 w-8"></th>
                        </tr>
                      </thead>
                      <tbody className="divide-y text-xs">
                        {items.map((it, idx) => (
                           <tr key={idx}>
                             <td className="p-2 truncate max-w-[200px] font-medium">{it.product_title}</td>
                             <td className="p-2">
                               <input type="number" value={it.qty} onChange={(e) => setItems(cur => cur.map((x, i) => i === idx ? { ...x, qty: Number(e.target.value) } : x))} className="w-full p-1 border rounded" />
                             </td>
                             <td className="p-2">
                               <input type="number" value={it.cost} step="0.01" onChange={(e) => setItems(cur => cur.map((x, i) => i === idx ? { ...x, cost: Number(e.target.value) } : x))} className="w-full p-1 border rounded" />
                             </td>
                             <td className="p-2 text-center">
                               <button onClick={() => setItems(cur => cur.filter((_, i) => i !== idx))}><Trash2 className="h-3.5 w-3.5 text-red-400" /></button>
                             </td>
                           </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="ghost" size="sm" onClick={() => setShowAdd(false)} className="text-xs">Cancelar</Button>
                <Button onClick={completePO} disabled={!selectedSupplier || items.length === 0} size="sm" className="text-xs">Crear Orden de Compra</Button>
              </div>
           </CardContent>
        </Card>
      )}

      {suppliers.length === 0 && !showAdd && canWrite && (
        <div className="border border-amber-500/20 bg-amber-500/10 p-4 rounded-lg flex items-center justify-between">
           <p className="text-xs text-amber-600/90 font-medium">Aún no hay proveedores registrados. Ve a la pestaña Proveedores primero.</p>
        </div>
      )}

      <div className="space-y-3">
        {orders.map(o => (
          <div key={o.id} className="border border-border/50 bg-card rounded-lg p-4">
             <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-2 mb-3">
               <div>
                  <p className="font-semibold text-sm flex items-center gap-2">
                    <PackageSearch className="h-4 w-4 text-primary" /> {o.suppliers?.name || 'Proveedor Eliminado'}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">ID: {o.id.split('-')[0].toUpperCase()} • Pedido el {new Date(o.created_at).toLocaleDateString()}</p>
               </div>
               <div className="text-left sm:text-right">
                  <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                    o.status === 'received' ? 'bg-green-500/15 text-green-500' :
                    o.status === 'cancelled' ? 'bg-red-500/15 text-red-500' :
                    'bg-blue-500/15 text-blue-500'
                  }`}>
                    {o.status === 'ordered' ? 'Solicitado / Pendiente' : o.status === 'received' ? 'Recibido' : 'Cancelado'}
                  </span>
                  <p className="font-bold text-sm mt-1">${o.total_amount.toLocaleString()}</p>
               </div>
             </div>
             
             <div className="bg-muted/30 p-2 rounded text-xs space-y-1 mt-2">
                {o.purchase_order_items.map((i: any, k: number) => (
                  <div key={k} className="flex justify-between w-full">
                     <span className="truncate">{i.quantity}x {i.product_variations?.products?.title} ({i.product_variations?.sku})</span>
                     <span className="font-mono tabular-nums text-muted-foreground ml-2">${i.unit_cost.toLocaleString()}/u.</span>
                  </div>
                ))}
             </div>

             {o.status === 'ordered' && canWrite && (
               <div className="mt-3 flex flex-wrap gap-2 justify-end pt-3 border-t">
                  <form action={async () => await cancelPurchaseOrder(o.id)}>
                    <SubmitButton variant="outline" size="sm" pendingText="Cancelando..." savedText="Cancelada" className="h-8 text-xs text-red-500 hover:text-red-600 hover:bg-red-500/10 gap-2 border-red-500/20">
                      <XCircle className="h-3.5 w-3.5" /> Cancelar Orden
                    </SubmitButton>
                  </form>
                  <form action={async () => await receivePurchaseOrder(o.id)}>
                    <SubmitButton size="sm" pendingText="Registrando..." savedText="Recibida ✓" className="h-8 text-xs bg-green-600 hover:bg-green-700 text-white gap-2">
                      <Check className="h-3.5 w-3.5" /> Marcar como Recibida (Ingresar al Inventario)
                    </SubmitButton>
                  </form>
               </div>
             )}
          </div>
        ))}
        {orders.length === 0 && !showAdd && (
          <div className="p-8 text-center text-muted-foreground border border-dashed rounded-xl">
             No tienes órdenes de compra en curso.
          </div>
        )}
      </div>
    </div>
  )
}
