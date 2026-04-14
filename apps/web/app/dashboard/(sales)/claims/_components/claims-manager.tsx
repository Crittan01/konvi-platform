'use client'

import { useState } from 'react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Plus, Search, HelpCircle, FileText, CheckCircle2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { createClaim, updateClaimStatus } from '../actions'

type Claim = {
  id: string
  order: any
  customer: any
  status: string
  reason: string
  requested_amount: number | null
  resolution_notes: string | null
  created_at: string
}

const statusMap: any = {
  'open': { label: 'Abierto', color: 'bg-red-500' },
  'investigating': { label: 'Investigando', color: 'bg-yellow-500' },
  'resolved': { label: 'Resuelto', color: 'bg-green-500' },
  'refunded': { label: 'Reembolsado', color: 'bg-emerald-600' },
  'rejected': { label: 'Rechazado', color: 'bg-zinc-500' }
}

const reasonMap: any = {
  'defective': 'Defectuoso',
  'wrong_item': 'Ítem Incorrecto',
  'delayed': 'Envío Retrasado',
  'missing_parts': 'Partes Faltantes',
  'other': 'Otro'
}

export default function ClaimsManager({ claims, recentOrders, canWrite }: { claims: Claim[], recentOrders: any[], canWrite: boolean }) {
  const [searchTerm, setSearchTerm] = useState('')
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [selectedClaim, setSelectedClaim] = useState<Claim | null>(null)

  // Create Form State
  const [newOrderId, setNewOrderId] = useState('')
  const [newReason, setNewReason] = useState('defective')
  const [newAmount, setNewAmount] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const filteredClaims = claims.filter(c => 
    c.order?.display_id?.toLowerCase().includes(searchTerm.toLowerCase()) || 
    c.customer?.first_name?.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const handleCreate = async () => {
    if (!newOrderId || !newReason) return alert('Selecciona el pedido y la razón')
    setIsSubmitting(true)

    const order = recentOrders.find(o => o.id === newOrderId)
    
    try {
      const resp = await createClaim({
        order_id: newOrderId,
        customer_id: order?.contact_id || null,
        reason: newReason,
        requested_amount: newAmount ? parseFloat(newAmount) : undefined
      })
      if (resp?.error) throw new Error(resp.error)
      setIsCreateOpen(false)
      setNewOrderId('')
      setNewAmount('')
    } catch(err: any) {
      alert(`Error creando reclamo: ${err.message}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleUpdateStatus = async (status: string) => {
    if (!selectedClaim) return
    setIsSubmitting(true)
    try {
      const resp = await updateClaimStatus(selectedClaim.id, status)
      if (resp?.error) throw new Error(resp.error)
      // Optimistic update locally
      setSelectedClaim({...selectedClaim, status})
    } catch(err: any) {
      alert(`Error actualizando: ${err.message}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex flex-col h-full space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-4 flex-none">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            placeholder="Buscar por ID de pedido o cliente..." 
            className="pl-8 bg-zinc-900 border-zinc-800"
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
          />
        </div>
        {canWrite && (
          <Button onClick={() => setIsCreateOpen(true)} className="gap-2">
            <Plus className="w-4 h-4"/> 
            Nuevo Reclamo
          </Button>
        )}
      </div>

      {/* Grid view */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0 overflow-auto pb-4 pr-1">
        
        {/* List side */}
        <div className="lg:col-span-1 space-y-3">
          <div className="flex gap-2 mb-2 px-1">
            <span className="text-sm text-zinc-400 font-medium">Tickets Abiertos ({filteredClaims.filter(c => c.status !== 'resolved' && c.status !== 'refunded' && c.status !== 'rejected').length})</span>
          </div>

          {filteredClaims.length === 0 && (
            <div className="p-8 text-center text-zinc-500 bg-zinc-900/50 rounded-xl border border-zinc-800/50 border-dashed">
              <HelpCircle className="w-8 h-8 mx-auto mb-3 opacity-20" />
              <p>No hay reclamos que coincidan</p>
            </div>
          )}

          {filteredClaims.map(claim => (
            <Card 
              key={claim.id} 
              className={`cursor-pointer transition-colors border-zinc-800/60 bg-zinc-900 hover:bg-zinc-800/50 ${selectedClaim?.id === claim.id ? 'ring-1 ring-red-500/50 border-red-500/30 bg-red-950/10' : ''}`}
              onClick={() => setSelectedClaim(claim)}
            >
              <CardContent className="p-4 flex flex-col gap-2">
                <div className="flex justify-between items-start">
                  <span className="font-medium text-zinc-200">Pedido {claim.order?.display_id}</span>
                  <div className="flex items-center gap-1.5">
                    <span className={`w-2 h-2 rounded-full ${statusMap[claim.status]?.color || 'bg-zinc-500'}`} />
                    <span className="text-xs uppercase font-medium text-zinc-400 tracking-wider">
                      {statusMap[claim.status]?.label || claim.status}
                    </span>
                  </div>
                </div>
                <div className="text-sm text-zinc-400 flex justify-between">
                  <span>{claim.customer?.first_name} {claim.customer?.last_name || ''}</span>
                  <span className="text-zinc-500 text-xs">{new Date(claim.created_at).toLocaleDateString()}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Selected Details Side */}
        <div className="lg:col-span-2 hidden lg:flex flex-col">
          {selectedClaim ? (
            <Card className="flex-1 bg-zinc-900/80 border-zinc-800 flex flex-col overflow-hidden">
              <CardHeader className="border-b border-zinc-800 bg-zinc-900 px-6 py-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-lg bg-zinc-800/80 flex items-center justify-center`}>
                      <FileText className="w-5 h-5 text-red-400" />
                    </div>
                    <div>
                      <CardTitle className="text-xl">Reclamo / Pedido {selectedClaim.order?.display_id}</CardTitle>
                      <p className="text-sm text-zinc-400">Cliente: {selectedClaim.customer?.first_name} {selectedClaim.customer?.last_name}</p>
                    </div>
                  </div>
                  
                  {/* Status Toggles */}
                  {canWrite && selectedClaim.status !== 'refunded' && selectedClaim.status !== 'rejected' && (
                    <div className="flex items-center gap-2">
                      <Button size="sm" variant={selectedClaim.status === 'investigating' ? 'default' : 'outline'} onClick={() => handleUpdateStatus('investigating')} disabled={isSubmitting}>
                        Investigando
                      </Button>
                      <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white" onClick={() => handleUpdateStatus('refunded')} disabled={isSubmitting}>
                        Reembolsar
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => handleUpdateStatus('rejected')} disabled={isSubmitting}>
                        Rechazar
                      </Button>
                    </div>
                  )}
                  {selectedClaim.status === 'refunded' && <Button size="sm" variant="outline" className="text-emerald-500 border-emerald-500/20 bg-emerald-500/10 pointer-events-none"><CheckCircle2 className="w-4 h-4 mr-2"/> Reembolso Efectuado</Button>}
                </div>
              </CardHeader>
              <CardContent className="p-6 flex-1 overflow-auto space-y-6">
                
                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-1">
                    <p className="text-sm text-zinc-500">Motivo del Reclamo</p>
                    <p className="font-medium">{reasonMap[selectedClaim.reason] || selectedClaim.reason}</p>
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm text-zinc-500">Monto Solicitado a debolver</p>
                    <p className="font-medium font-mono text-red-400">
                      {selectedClaim.requested_amount ? `$${selectedClaim.requested_amount.toLocaleString()}` : 'No definido'}
                    </p>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Notas de Resolución</Label>
                  <Textarea placeholder="El agente de soporte agregará de forma interna su investigación general..." className="min-h-[150px] resize-none border-zinc-800 bg-zinc-900/50" readOnly value={selectedClaim.resolution_notes || ''} />
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="flex-1 rounded-xl border border-dashed border-zinc-800 flex items-center justify-center flex-col text-zinc-500 gap-2">
              <FileText className="w-10 h-10 opacity-20" />
              <p>Selecciona un reclamo para ver los detalles y resolverlo</p>
            </div>
          )}
        </div>
      </div>

      {/* Create Dialog */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="bg-zinc-950 border-zinc-800 sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Registrar Nuevo Reclamo</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label>Pedido Relacionado</Label>
              <Select onValueChange={setNewOrderId} value={newOrderId}>
                <SelectTrigger className="border-zinc-800 bg-zinc-900">
                   <SelectValue placeholder="Busca la orden de compra" />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800 text-zinc-200">
                  {recentOrders.map((o: any) => (
                    <SelectItem key={o.id} value={o.id}>{o.display_id} - ${o.total_amount?.toLocaleString()}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            <div className="grid gap-2">
              <Label>Motivo Principal</Label>
              <Select onValueChange={setNewReason} value={newReason}>
                <SelectTrigger className="border-zinc-800 bg-zinc-900">
                   <SelectValue placeholder="Seleccionar motivo" />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800 text-zinc-200">
                  <SelectItem value="defective">Producto Defectuoso</SelectItem>
                  <SelectItem value="wrong_item">Équivocado (Te llega otro)</SelectItem>
                  <SelectItem value="missing_parts">Faltan piezas</SelectItem>
                  <SelectItem value="delayed">Envío Retrasado Fuertemente</SelectItem>
                  <SelectItem value="other">Otro / Garantía extendida</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label>Monto a reembolsar / Impacto (Opcional)</Label>
              <Input 
                type="number"
                placeholder="0.00" 
                className="bg-zinc-900 border-zinc-800"
                value={newAmount}
                onChange={e => setNewAmount(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)} disabled={isSubmitting}>Cancelar</Button>
            <Button onClick={handleCreate} disabled={isSubmitting || !newOrderId}>
              {isSubmitting ? 'Guardando...' : 'Crear Ticket'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
