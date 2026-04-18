'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Plus, Search, HelpCircle, FileText, CheckCircle2, AlertCircle } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { createClaim, updateClaimStatus } from '../actions'

// ─── Types ────────────────────────────────────────────────────────────────────

type ClaimOrder    = { id: string; total_amount: number | null } | null
type ClaimCustomer = { id: string; name: string | null; phone: string | null } | null

type Claim = {
  id: string
  ticket_number: number | null
  order: ClaimOrder
  customer: ClaimCustomer
  status: string
  reason: string
  requested_amount: number | null
  resolution_notes: string | null
  created_at: string
}

type RecentOrder = {
  id: string
  status: string
  total_amount: number | null
  contact_id: string | null
}

// ─── Maps ─────────────────────────────────────────────────────────────────────

const STATUS_MAP: Record<string, { label: string; color: string; dot: string }> = {
  open:          { label: 'Abierto',      color: 'bg-red-500/15 text-red-400 border-red-500/30',       dot: 'bg-red-400' },
  investigating: { label: 'Investigando', color: 'bg-amber-500/15 text-amber-400 border-amber-500/30', dot: 'bg-amber-400' },
  resolved:      { label: 'Resuelto',     color: 'bg-green-500/15 text-green-400 border-green-500/30', dot: 'bg-green-400' },
  refunded:      { label: 'Reembolsado',  color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', dot: 'bg-emerald-400' },
  rejected:      { label: 'Rechazado',    color: 'bg-muted text-muted-foreground border-border',       dot: 'bg-muted-foreground' },
}

const REASON_MAP: Record<string, string> = {
  defective:     'Producto defectuoso',
  wrong_item:    'Ítem incorrecto',
  delayed:       'Envío retrasado',
  missing_parts: 'Partes faltantes',
  other:         'Otro',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const customerLabel = (c: ClaimCustomer) => c?.name ?? c?.phone ?? '—'

// ─── Componente Principal ─────────────────────────────────────────────────────

export default function ClaimsManager({
  claims,
  recentOrders,
  canWrite,
}: {
  claims: Claim[]
  recentOrders: RecentOrder[]
  canWrite: boolean
}) {
  const [searchTerm, setSearchTerm]     = useState('')
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [selectedClaim, setSelectedClaim] = useState<Claim | null>(null)
  const [actionError, setActionError]   = useState<string | null>(null)

  // Create form state
  const [newOrderId, setNewOrderId]     = useState('')
  const [newReason, setNewReason]       = useState('defective')
  const [newAmount, setNewAmount]       = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [createError, setCreateError]   = useState<string | null>(null)

  const filteredClaims = claims.filter(c =>
    c.order?.id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    customerLabel(c.customer).toLowerCase().includes(searchTerm.toLowerCase())
  )

  const openCount = filteredClaims.filter(
    c => c.status !== 'resolved' && c.status !== 'refunded' && c.status !== 'rejected'
  ).length

  const handleCreate = async () => {
    if (!newOrderId || !newReason) { setCreateError('Selecciona el pedido y la razón'); return }
    setIsSubmitting(true)
    setCreateError(null)
    const order = recentOrders.find(o => o.id === newOrderId)
    try {
      const resp = await createClaim({
        order_id:         newOrderId,
        customer_id:      order?.contact_id ?? null,
        reason:           newReason,
        requested_amount: newAmount ? parseFloat(newAmount) : undefined,
      })
      if (resp?.error) { setCreateError(resp.error); return }
      setIsCreateOpen(false)
      setNewOrderId('')
      setNewAmount('')
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Error desconocido')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleUpdateStatus = async (status: string) => {
    if (!selectedClaim) return
    setIsSubmitting(true)
    setActionError(null)
    try {
      const resp = await updateClaimStatus(selectedClaim.id, status)
      if (resp?.error) { setActionError(resp.error); return }
      setSelectedClaim({ ...selectedClaim, status })
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Error desconocido')
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
            placeholder="Buscar por pedido o cliente..."
            className="pl-8"
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
          />
        </div>
        {canWrite && (
          <Button onClick={() => { setIsCreateOpen(true); setCreateError(null) }} className="gap-2">
            <Plus className="w-4 h-4" /> Nuevo Reclamo
          </Button>
        )}
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0 overflow-auto pb-4 pr-1">

        {/* Lista */}
        <div className="lg:col-span-1 space-y-3">
          <p className="text-sm text-muted-foreground font-medium px-1">
            Tickets abiertos ({openCount})
          </p>

          {filteredClaims.length === 0 && (
            <div className="p-8 text-center text-muted-foreground rounded-xl border border-dashed border-border">
              <HelpCircle className="w-8 h-8 mx-auto mb-3 opacity-20" />
              <p className="text-sm">No hay reclamos que coincidan</p>
            </div>
          )}

          {filteredClaims.map(claim => {
            const st = STATUS_MAP[claim.status] ?? STATUS_MAP.open
            return (
              <div
                key={claim.id}
                onClick={() => { setSelectedClaim(claim); setActionError(null) }}
                className={`cursor-pointer rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/30 ${
                  selectedClaim?.id === claim.id
                    ? 'ring-1 ring-primary/50 border-primary/40 bg-primary/5'
                    : 'border-border'
                }`}
              >
                <div className="flex justify-between items-start gap-2">
                  <span className="font-medium text-sm text-foreground truncate">
                    Ticket #{claim.ticket_number != null ? String(claim.ticket_number).padStart(3, '0') : '—'}
                  </span>
                  <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border shrink-0 ${st.color}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />
                    {st.label}
                  </span>
                </div>
                <div className="flex justify-between mt-1.5 text-xs text-muted-foreground">
                  <span>{customerLabel(claim.customer)}</span>
                  <span>{new Date(claim.created_at).toLocaleDateString('es-CO', { day: '2-digit', month: 'short' })}</span>
                </div>
              </div>
            )
          })}
        </div>

        {/* Detalle */}
        <div className="lg:col-span-2 hidden lg:flex flex-col">
          {selectedClaim ? (
            <div className="flex-1 rounded-xl border border-border bg-card flex flex-col overflow-hidden">

              {/* Header detalle */}
              <div className="border-b border-border bg-card px-6 py-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="p-2 rounded-lg bg-primary/10 shrink-0">
                    <FileText className="w-5 h-5 text-primary" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-foreground truncate">
                      Ticket #{selectedClaim.ticket_number != null ? String(selectedClaim.ticket_number).padStart(3, '0') : '—'}
                      {selectedClaim.order && (
                        <span className="ml-2 text-xs font-normal text-muted-foreground font-mono">
                          Pedido {selectedClaim.order.id.split('-')[0].toUpperCase()}
                        </span>
                      )}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      Cliente: {customerLabel(selectedClaim.customer)}
                    </p>
                  </div>
                </div>

                {canWrite && selectedClaim.status !== 'refunded' && selectedClaim.status !== 'rejected' && (
                  <div className="flex items-center gap-2 shrink-0">
                    <Button
                      size="sm" variant={selectedClaim.status === 'investigating' ? 'default' : 'outline'}
                      onClick={() => handleUpdateStatus('investigating')} disabled={isSubmitting}
                      className="text-xs h-8"
                    >
                      Investigando
                    </Button>
                    <Button
                      size="sm" onClick={() => handleUpdateStatus('refunded')} disabled={isSubmitting}
                      className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs h-8"
                    >
                      Reembolsar
                    </Button>
                    <Button
                      size="sm" variant="destructive" onClick={() => handleUpdateStatus('rejected')} disabled={isSubmitting}
                      className="text-xs h-8"
                    >
                      Rechazar
                    </Button>
                  </div>
                )}

                {selectedClaim.status === 'refunded' && (
                  <span className="inline-flex items-center gap-1.5 text-xs text-emerald-400 border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 rounded-lg">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Reembolso efectuado
                  </span>
                )}
              </div>

              {/* Error acción */}
              {actionError && (
                <div className="mx-6 mt-4 flex items-center gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {actionError}
                </div>
              )}

              {/* Contenido */}
              <div className="p-6 flex-1 overflow-auto space-y-6">
                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Motivo</p>
                    <p className="font-medium text-sm">{REASON_MAP[selectedClaim.reason] ?? selectedClaim.reason}</p>
                  </div>
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Monto solicitado</p>
                    <p className="font-medium text-sm font-mono text-red-400">
                      {selectedClaim.requested_amount
                        ? `$${selectedClaim.requested_amount.toLocaleString('es-CO')}`
                        : 'No definido'}
                    </p>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label className="text-xs uppercase tracking-wide text-muted-foreground">Notas de resolución</Label>
                  <Textarea
                    placeholder="El agente de soporte agregará su investigación aquí..."
                    className="min-h-[120px] resize-none"
                    readOnly
                    value={selectedClaim.resolution_notes ?? ''}
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 rounded-xl border border-dashed border-border flex items-center justify-center flex-col text-muted-foreground gap-2">
              <FileText className="w-10 h-10 opacity-20" />
              <p className="text-sm">Selecciona un reclamo para ver el detalle</p>
            </div>
          )}
        </div>
      </div>

      {/* Dialog crear */}
      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Registrar nuevo reclamo</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label>Pedido relacionado</Label>
              <Select onValueChange={v => { setNewOrderId(v); setCreateError(null) }} value={newOrderId}>
                <SelectTrigger>
                  <SelectValue placeholder="Selecciona un pedido" />
                </SelectTrigger>
                <SelectContent>
                  {recentOrders.map(o => (
                    <SelectItem key={o.id} value={o.id}>
                      #{o.id.slice(-8).toUpperCase()} — ${o.total_amount?.toLocaleString('es-CO') ?? '0'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label>Motivo principal</Label>
              <Select onValueChange={setNewReason} value={newReason}>
                <SelectTrigger>
                  <SelectValue placeholder="Seleccionar motivo" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="defective">Producto defectuoso</SelectItem>
                  <SelectItem value="wrong_item">Ítem incorrecto</SelectItem>
                  <SelectItem value="missing_parts">Partes faltantes</SelectItem>
                  <SelectItem value="delayed">Envío retrasado</SelectItem>
                  <SelectItem value="other">Otro / Garantía extendida</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label>Monto a reembolsar (opcional)</Label>
              <Input
                type="number"
                placeholder="0"
                value={newAmount}
                onChange={e => setNewAmount(e.target.value)}
              />
            </div>

            {createError && (
              <p className="text-xs text-red-400 flex items-center gap-1">
                <AlertCircle className="h-3.5 w-3.5" /> {createError}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)} disabled={isSubmitting}>
              Cancelar
            </Button>
            <Button onClick={handleCreate} disabled={isSubmitting || !newOrderId}>
              {isSubmitting ? 'Guardando...' : 'Crear ticket'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
