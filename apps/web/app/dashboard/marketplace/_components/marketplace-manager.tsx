'use client'

import { useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { MoreHorizontal, ExternalLink, Play, Pause, Plus, Search } from 'lucide-react'
import { publishToMarketplace, changeListingStatus } from '../actions'

type MarketplaceItem = {
  variation_id: string
  product_name: string
  sku: string
  base_price: number
  stock: number
  is_published: boolean
  listing_id: string | null
  external_id: string | null
  status: 'unlisted' | 'active' | 'paused' | 'closed'
  external_price: number | null
  external_url: string | null
}

export default function MarketplaceManager({ items, canWrite }: { items: MarketplaceItem[], canWrite: boolean }) {
  const [searchTerm, setSearchTerm] = useState('')
  const [loadingIds, setLoadingIds] = useState<string[]>([])
  
  // Custom price for mappings (unlisted items)
  const [prices, setPrices] = useState<Record<string, number>>({})

  const filteredItems = items.filter(i => 
    i.product_name.toLowerCase().includes(searchTerm.toLowerCase()) || 
    i.sku?.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const handlePublish = async (itemId: string, defaultPrice: number) => {
    if (!canWrite) return
    const externalPrice = prices[itemId] || defaultPrice

    setLoadingIds(prev => [...prev, itemId])
    try {
      const resp = await publishToMarketplace(itemId, externalPrice)
      if (resp?.error) {
         alert(`Error: ${resp.error}`)
      }
    } finally {
      setLoadingIds(prev => prev.filter(id => id !== itemId))
    }
  }

  const handleStatusChange = async (listingId: string, newStatus: 'active' | 'paused' | 'closed', variationId: string) => {
    if (!canWrite) return
    setLoadingIds(prev => [...prev, variationId]) // disable the row temporarily
    try {
      const resp = await changeListingStatus(listingId, newStatus)
      if (resp?.error) {
         alert(`Error: ${resp.error}`)
      }
    } finally {
      setLoadingIds(prev => prev.filter(id => id !== variationId))
    }
  }

  return (
    <Card className="border-border/50 shadow-sm overflow-hidden flex flex-col min-h-0 h-full">
      <div className="p-4 border-b border-border/50 bg-muted/20 flex flex-col sm:flex-row gap-4 items-center justify-between">
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            placeholder="Buscar por Nombre o SKU interno..." 
            className="pl-9 h-9" 
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
      </div>
      
      <div className="overflow-x-auto flex-1 bg-background select-none">
        <table className="w-full text-sm min-w-[800px]">
          <thead>
            <tr className="border-b bg-muted/40 text-muted-foreground">
              <th className="py-3 px-4 font-medium text-left">SKU | Producto (Supabase)</th>
              <th className="py-3 px-4 font-medium text-right">Cost. / Precio Base</th>
              <th className="py-3 px-4 font-medium text-center">Stock</th>
              <th className="py-3 px-4 font-medium text-center">Status Meli</th>
              <th className="py-3 px-4 font-medium text-right">Precio Meli</th>
              <th className="py-3 px-4 font-medium text-right">Acciones</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {filteredItems.map(item => {
              const rowLoading = loadingIds.includes(item.variation_id)

              return (
                <tr key={item.variation_id} className={`hover:bg-muted/30 transition-colors ${rowLoading ? 'opacity-50 pointer-events-none' : ''}`}>
                  <td className="py-3 px-4 whitespace-nowrap">
                    <p className="font-semibold text-foreground">{item.product_name}</p>
                    <p className="text-xs text-muted-foreground">{item.sku || 'Sin SKU'}</p>
                  </td>
                  <td className="py-3 px-4 text-right whitespace-nowrap">
                    <p className="font-medium">${item.base_price.toLocaleString()}</p>
                  </td>
                  <td className="py-3 px-4 text-center">
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${item.stock > 0 ? 'bg-amber-500/15 text-amber-600' : 'bg-red-500/15 text-red-500'}`}>
                      {item.stock} u.
                    </span>
                  </td>
                  
                  {/* Status Badge */}
                  <td className="py-3 px-4 text-center">
                    {!item.is_published ? (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-muted text-muted-foreground">
                        No Publicado
                      </span>
                    ) : item.status === 'active' ? (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-green-500/15 text-green-500">
                        Activo
                      </span>
                    ) : item.status === 'paused' ? (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-yellow-500/15 text-yellow-600">
                        Pausado
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-red-500/15 text-red-500">
                        Cerrado
                      </span>
                    )}
                    {item.external_id && (
                       <p className="text-[10px] text-muted-foreground mt-1 truncate max-w-[80px] mx-auto">{item.external_id}</p>
                    )}
                  </td>
                  
                  {/* Precio en Marketplace Editor */}
                  <td className="py-3 px-4 text-right">
                     {!item.is_published ? (
                       <div className="flex items-center justify-end gap-2">
                         <span className="text-muted-foreground">$</span>
                         <Input 
                            type="number" 
                            className="w-24 h-8 text-right text-xs" 
                            placeholder={String(item.base_price)}
                            value={prices[item.variation_id] ?? ''}
                            onChange={(e) => setPrices({...prices, [item.variation_id]: parseFloat(e.target.value) || 0})}
                         />
                       </div>
                     ) : (
                       <p className="font-bold text-amber-600">${item.external_price?.toLocaleString()}</p>
                     )}
                  </td>
                  
                  {/* Acciones */}
                  <td className="py-3 px-4">
                    <div className="flex items-center justify-end gap-2">
                       {item.external_url && (
                          <Button variant="ghost" size="icon" className="h-8 w-8 text-blue-500 hover:text-blue-600 hover:bg-blue-50" asChild>
                            <a href={item.external_url} target="_blank" rel="noreferrer" title="Ver en Mercado Libre">
                              <ExternalLink className="h-4 w-4" />
                            </a>
                          </Button>
                       )}

                       {!item.is_published && canWrite ? (
                         <Button size="sm" className="h-8 text-xs bg-primary text-primary-foreground gap-1.5" onClick={() => handlePublish(item.variation_id, item.base_price)}>
                            <Plus className="h-3.5 w-3.5" /> Publicar
                         </Button>
                       ) : item.is_published && canWrite ? (
                         <>
                           {item.status === 'active' ? (
                              <Button variant="outline" size="sm" className="h-8 text-xs text-yellow-600 border-yellow-500/30 gap-1.5" onClick={() => handleStatusChange(item.listing_id!, 'paused', item.variation_id)}>
                                <Pause className="h-3.5 w-3.5" /> Pausar
                              </Button>
                           ) : item.status === 'paused' ? (
                              <Button variant="outline" size="sm" className="h-8 text-xs text-green-600 border-green-500/30 gap-1.5" onClick={() => handleStatusChange(item.listing_id!, 'active', item.variation_id)}>
                                <Play className="h-3.5 w-3.5" /> Reactivar
                              </Button>
                           ) : null}
                         </>
                       ) : null}
                    </div>
                  </td>
                </tr>
              )
            })}
            
            {filteredItems.length === 0 && (
              <tr>
                <td colSpan={6} className="py-12 text-center text-muted-foreground">
                  No hay productos en el catálogo que coincidan con la búsqueda.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
