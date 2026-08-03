'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Plus, Search, HelpCircle, FileText, CheckCircle2, AlertCircle, Info, RotateCcw } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import ReversionPanel from './reversion-panel'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useConfirm } from '@/components/ui/confirm-dialog'
import { toast } from 'sonner'
import { createClaim, updateClaimStatus, correctRefundAmount } from '../actions'

// ─── Types ────────────────────────────────────────────────────────────────────

type ClaimOrder    = { id: string; total_amount: number | null; payment_method: string | null } | null
type ClaimCustomer = { id: string; name: string | null; phone: string | null } | null

type Claim = {
  id: string
  ticket_number: number | null
  order: ClaimOrder
  customer: ClaimCustomer
  status: string
  reason: string
  requested_amount: number | null
  // BLOQUE G-2: monto REAL reembolsado + fecha (capturado al marcar 'refunded').
  refunded_amount: number | null
  refunded_at: string | null
  resolution_notes: string | null
  created_at: string
}

type RecentOrder = {
  id: string
  status: string
  total_amount: number | null
  contact_id: string | null
  created_at: string
  customer_name: string | null
}

// ─── Maps ─────────────────────────────────────────────────────────────────────

const STATUS_MAP: Record<string, { label: string; color: string; dot: string }> = {
  open:          { label: 'Abierto',      color: 'bg-red-500/15 text-red-700 border-red-700/30',        dot: 'bg-red-600' },
  investigating: { label: 'Investigando', color: 'bg-amber-500/15 text-amber-700 border-amber-700/30',  dot: 'bg-amber-600' },
  resolved:      { label: 'Resuelto',     color: 'bg-green-500/15 text-green-700 border-green-700/30',   dot: 'bg-green-600' },
  refunded:      { label: 'Reembolsado',  color: 'bg-emerald-500/15 text-emerald-700 border-emerald-700/30', dot: 'bg-emerald-600' },
  rejected:      { label: 'Rechazado',    color: 'bg-muted text-muted-foreground border-border',         dot: 'bg-muted-foreground' },
  cancelled:     { label: 'Cancelado',    color: 'bg-muted text-muted-foreground border-border',         dot: 'bg-muted-foreground' },
}

// Vocabulario canónico de 'reason' (decisión F2 — Opción A). Estas keys son la
// fuente de verdad: mismas que valida el API (claims.py VALID_REASONS) y que ofrece
// el dropdown de "Nuevo Reclamo" más abajo.
const REASON_MAP: Record<string, string> = {
  defective:     'Producto defectuoso',
  wrong_item:    'Ítem incorrecto',
  delayed:       'Envío retrasado',
  missing_parts: 'Partes faltantes',
  other:         'Otro',
}

// Estados terminales: el ticket ya se cerró (no admite acciones sin reapertura).
const TERMINAL = new Set(['resolved', 'refunded', 'rejected', 'cancelled'])

// Terminales reabribles por un owner (decisión F2 — Opción B). 'refunded' y
// 'resolved' quedan fuera: el guard del API los rechaza (409). Mantener alineado.
const REOPENABLE = new Set(['rejected', 'cancelled'])

// ─── Helpers ──────────────────────────────────────────────────────────────────

const customerLabel = (c: ClaimCustomer) => c?.name ?? c?.phone ?? '—'
const orderShort = (id: string) => id.split('-')[0].toUpperCase()
const ticketLabel = (n: number | null) => (n != null ? `#${String(n).padStart(3, '0')}` : '#—')

// ─── Componente Principal ─────────────────────────────────────────────────────

export default function ClaimsManager({
  claims,
  recentOrders,
  canWrite,
  canResolve,
  canReopen,
}: {
  claims: Claim[]
  recentOrders: RecentOrder[]
  canWrite: boolean
  canResolve: boolean
  canReopen: boolean
}) {
  const confirm = useConfirm()

  const [searchTerm, setSearchTerm]       = useState('')
  const [statusFilter, setStatusFilter]   = useState<'all' | 'open' | 'closed'>('all')
  const [isCreateOpen, setIsCreateOpen]   = useState(false)
  const [selectedClaim, setSelectedClaim] = useState<Claim | null>(null)
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false)
  const [notesDraft, setNotesDraft]       = useState('')     // F6: borrador editable de notas de resolución
  const [savingNotes, setSavingNotes]     = useState(false)
  const [actionError, setActionError]     = useState<string | null>(null)
  // BLOQUE G-2: modal para capturar el monto REAL reembolsado al marcar 'refunded'.
  const [refundOpen, setRefundOpen]       = useState(false)
  const [refundAmount, setRefundAmount]   = useState('')
  const [refundSubmitting, setRefundSubmitting] = useState(false)

  // Detecta viewport para decidir dónde mostrar el detalle (panel lg vs Sheet móvil).
  const [isDesktop, setIsDesktop] = useState(true)
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const sync = () => setIsDesktop(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  // Create form state
  const [newOrderId, setNewOrderId]     = useState('')
  const [newReason, setNewReason]       = useState('defective')
  const [newAmount, setNewAmount]       = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [createError, setCreateError]   = useState<string | null>(null)

  const needle = searchTerm.trim().toLowerCase().replace(/^#/, '')
  const filteredClaims = claims.filter(c => {
    // Filtro por estado (abierto / cerrado)
    if (statusFilter === 'open' && TERMINAL.has(c.status)) return false
    if (statusFilter === 'closed' && !TERMINAL.has(c.status)) return false
    if (!needle) return true
    // Búsqueda: incluye número de ticket (el ID que el bot da al cliente), pedido y cliente.
    const hay = [
      c.ticket_number != null ? String(c.ticket_number) : '',
      c.ticket_number != null ? String(c.ticket_number).padStart(3, '0') : '',
      c.order?.id ?? '',
      c.order ? orderShort(c.order.id) : '',
      customerLabel(c.customer),
    ].join(' ').toLowerCase().replace(/#/g, '')
    return hay.includes(needle)
  })

  const openCount = claims.filter(c => !TERMINAL.has(c.status)).length

  const selectClaim = (claim: Claim) => {
    setSelectedClaim(claim)
    setNotesDraft(claim.resolution_notes ?? '')
    setActionError(null)
    if (!isDesktop) setMobileDetailOpen(true)
  }

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
      toast.success('Reclamo registrado')
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

    // BLOQUE G-2: 'refunded' exige capturar el monto REAL reembolsado → modal dedicado
    // (no el confirm sí/no). Pre-llena con el monto solicitado como sugerencia.
    if (status === 'refunded') {
      setRefundAmount(selectedClaim.requested_amount != null ? String(selectedClaim.requested_amount) : '')
      setActionError(null)
      setRefundOpen(true)
      return
    }

    // Transiciones terminales: confirmación previa (evita el misclick irreversible en UI).
    if (TERMINAL.has(status)) {
      const copy: Record<string, { title: string; description: string; confirmLabel: string; destructive?: boolean }> = {
        rejected: {
          title: `¿Rechazar el ticket ${ticketLabel(selectedClaim.ticket_number)}?`,
          description: 'El reclamo quedará cerrado como rechazado. El cliente podrá ver este estado al consultar por WhatsApp.',
          confirmLabel: 'Rechazar reclamo',
          destructive: true,
        },
        resolved: {
          title: `¿Marcar ticket ${ticketLabel(selectedClaim.ticket_number)} como resuelto?`,
          description: 'Úsalo cuando el caso se cerró sin reembolso (p. ej. reposición o aclaración). El ticket quedará cerrado.',
          confirmLabel: 'Marcar resuelto',
        },
      }
      const c = copy[status]
      if (c && !(await confirm(c))) return
    }

    setIsSubmitting(true)
    setActionError(null)
    try {
      const resp = await updateClaimStatus(selectedClaim.id, status, notesDraft || undefined)
      if (resp?.error) { setActionError(resp.error); toast.error('No se pudo actualizar el reclamo'); return }
      setSelectedClaim({ ...selectedClaim, status, resolution_notes: notesDraft || selectedClaim.resolution_notes })
      toast.success(`Ticket ${ticketLabel(selectedClaim.ticket_number)} · ${STATUS_MAP[status]?.label ?? status}`)
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Error desconocido')
    } finally {
      setIsSubmitting(false)
    }
  }

  // BLOQUE G-2: confirma el reembolso con el monto real capturado. La API lo exige y
  // lo resta del KPI net-revenue (refunded_amount/refunded_at write-once).
  const submitRefund = async () => {
    if (!selectedClaim) return
    const amt = parseFloat(refundAmount)
    if (!Number.isFinite(amt) || amt < 0) {
      setActionError('Ingresa un monto reembolsado válido (≥ 0).')
      return
    }
    setRefundSubmitting(true)
    setActionError(null)
    try {
      // Corrección: el reclamo ya está 'refunded' (monto histórico NULL) → PATCH solo
      // el monto. Transición: aún no reembolsado → marca 'refunded' con el monto.
      const isCorrection = selectedClaim.status === 'refunded'
      const resp = isCorrection
        ? await correctRefundAmount(selectedClaim.id, amt)
        : await updateClaimStatus(selectedClaim.id, 'refunded', notesDraft || undefined, amt)
      if (resp?.error) { setActionError(resp.error); toast.error('No se pudo registrar el reembolso'); return }
      setSelectedClaim({
        ...selectedClaim, status: 'refunded', refunded_amount: amt,
        resolution_notes: notesDraft || selectedClaim.resolution_notes,
      })
      setRefundOpen(false)
      toast.success(`Ticket ${ticketLabel(selectedClaim.ticket_number)} · Reembolsado`)
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Error desconocido')
    } finally {
      setRefundSubmitting(false)
    }
  }

  // F6: guarda las notas de resolución SIN cambiar el estado (reusa el estado actual).
  const handleSaveNotes = async () => {
    if (!selectedClaim) return
    setSavingNotes(true)
    setActionError(null)
    try {
      const resp = await updateClaimStatus(selectedClaim.id, selectedClaim.status, notesDraft)
      if (resp?.error) { setActionError(resp.error); toast.error('No se pudieron guardar las notas'); return }
      setSelectedClaim({ ...selectedClaim, resolution_notes: notesDraft })
      toast.success('Notas guardadas')
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Error desconocido')
    } finally {
      setSavingNotes(false)
    }
  }

  // F2: reabre un terminal reabrible (rejected/cancelled) → vuelve a 'open'.
  // Owner-only en UI (canReopen) y en el API (guard 403/409). Conserva notas/historial.
  const handleReopen = async () => {
    if (!selectedClaim) return
    const ok = await confirm({
      title: `¿Reabrir el ticket ${ticketLabel(selectedClaim.ticket_number)}?`,
      description: 'El reclamo volverá a estado Abierto y podrá gestionarse de nuevo. Se conservan las notas y el historial.',
      confirmLabel: 'Reabrir',
    })
    if (!ok) return
    setIsSubmitting(true)
    setActionError(null)
    try {
      const resp = await updateClaimStatus(selectedClaim.id, 'open')
      if (resp?.error) { setActionError(resp.error); toast.error('No se pudo reabrir el reclamo'); return }
      setSelectedClaim({ ...selectedClaim, status: 'open' })
      toast.success(`Ticket ${ticketLabel(selectedClaim.ticket_number)} reabierto`)
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Error desconocido')
    } finally {
      setIsSubmitting(false)
    }
  }

  // ─── Detalle (reutilizado en panel desktop y Sheet móvil) ────────────────────
  const renderDetail = () => {
    if (!selectedClaim) return null
    const isTerminal = TERMINAL.has(selectedClaim.status)
    return (
      <div className="flex flex-col h-full overflow-hidden">
        {/* Header detalle */}
        <div className="border-b border-border bg-card px-4 sm:px-6 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2 rounded-lg bg-primary/10 shrink-0">
              <FileText className="w-5 h-5 text-primary" />
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-foreground truncate">
                Ticket {ticketLabel(selectedClaim.ticket_number)}
                {selectedClaim.order && (
                  <span className="ml-2 text-xs font-normal text-muted-foreground font-mono">
                    Pedido {orderShort(selectedClaim.order.id)}
                  </span>
                )}
              </p>
              <p className="text-sm text-muted-foreground">
                Cliente: {customerLabel(selectedClaim.customer)}
              </p>
            </div>
          </div>

          {canResolve && !isTerminal && (
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <Button
                size="sm" variant={selectedClaim.status === 'investigating' ? 'default' : 'outline'}
                onClick={() => handleUpdateStatus('investigating')} disabled={isSubmitting}
                className="text-xs h-8"
              >
                Investigando
              </Button>
              <Button
                size="sm" variant="outline" onClick={() => handleUpdateStatus('resolved')} disabled={isSubmitting}
                className="text-xs h-8"
              >
                Resolver
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

          {isTerminal && (
            <div className="flex items-center gap-2 shrink-0">
              <span className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border ${STATUS_MAP[selectedClaim.status]?.color ?? STATUS_MAP.rejected.color}`}>
                <CheckCircle2 className="w-3.5 h-3.5" /> {STATUS_MAP[selectedClaim.status]?.label ?? selectedClaim.status}
              </span>
              {canReopen && REOPENABLE.has(selectedClaim.status) && (
                <Button
                  size="sm" variant="outline" onClick={handleReopen} disabled={isSubmitting}
                  className="text-xs h-8 gap-1.5"
                >
                  <RotateCcw className="w-3.5 h-3.5" /> Reabrir
                </Button>
              )}
            </div>
          )}
        </div>

        {/* Aviso: el reembolso no mueve dinero */}
        {selectedClaim.status === 'refunded' && (
          <div className="mx-4 sm:mx-6 mt-4 flex items-start gap-2 text-xs text-amber-700 bg-amber-500/10 border border-amber-700/20 rounded-lg px-3 py-2">
            <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <span>Este estado solo registra el reclamo. El dinero se devuelve manualmente desde Wompi; verifica que el reembolso se haya emitido.</span>
          </div>
        )}

        {/* Error acción */}
        {actionError && (
          <div className="mx-4 sm:mx-6 mt-4 flex items-center gap-2 text-xs text-red-700 bg-red-500/10 border border-red-700/20 rounded-lg px-3 py-2">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {actionError}
          </div>
        )}

        {/* Contenido */}
        <div className="p-4 sm:p-6 flex-1 overflow-auto space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Motivo</p>
              <p className="font-medium text-sm">{REASON_MAP[selectedClaim.reason] ?? selectedClaim.reason}</p>
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Monto solicitado</p>
              <p className="font-medium text-sm font-mono text-red-700">
                {selectedClaim.requested_amount != null
                  ? `$${selectedClaim.requested_amount.toLocaleString('es-CO')}`
                  : 'No definido'}
              </p>
            </div>
          </div>

          {selectedClaim.order?.id && (
            <ReversionPanel
              key={selectedClaim.id}
              claimId={selectedClaim.id}
              formaPago={selectedClaim.order.payment_method}
              totalPedido={selectedClaim.order.total_amount}
              canWrite={canWrite}
            />
          )}

          {/* BLOQUE G-2: monto REAL reembolsado (lo que resta el KPI net-revenue). */}
          {selectedClaim.status === 'refunded' && (
            <div className="space-y-1 rounded-lg border border-emerald-700/25 bg-emerald-500/5 p-3">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Reembolsado (real)</p>
              {selectedClaim.refunded_amount != null ? (
                <p className="font-medium text-sm font-mono text-emerald-700">
                  ${selectedClaim.refunded_amount.toLocaleString('es-CO')}
                  {selectedClaim.refunded_at && (
                    <span className="ml-2 text-[11px] text-muted-foreground">
                      {new Date(selectedClaim.refunded_at).toLocaleDateString('es-CO', { timeZone: 'America/Bogota' })}
                    </span>
                  )}
                </p>
              ) : (
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="text-sm text-amber-700">Monto no registrado</p>
                  {canResolve && (
                    <button
                      onClick={() => { setRefundAmount(''); setActionError(null); setRefundOpen(true) }}
                      className="text-xs text-primary underline hover:no-underline"
                    >
                      Registrar monto
                    </button>
                  )}
                </div>
              )}
              <p className="text-[11px] text-muted-foreground">Se descuenta de las ventas netas del panel.</p>
            </div>
          )}

          <div className="space-y-2">
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">Notas de resolución</Label>
            <Textarea
              placeholder="El agente de soporte agrega aquí su investigación / resolución..."
              className="min-h-[120px] resize-none"
              readOnly={!canResolve}
              value={canResolve ? notesDraft : (selectedClaim.resolution_notes ?? '')}
              onChange={canResolve ? (e => setNotesDraft(e.target.value)) : undefined}
            />
            <p className="text-[11px] text-muted-foreground flex items-start gap-1">
              <Info className="h-3 w-3 shrink-0 mt-0.5" />
              El cliente puede leer el estado y estas notas al consultar el ticket con el bot por WhatsApp.
            </p>
            {canResolve && (
              <div className="flex items-center justify-end gap-2">
                {notesDraft !== (selectedClaim.resolution_notes ?? '') && (
                  <span className="text-[11px] text-amber-700">Cambios sin guardar</span>
                )}
                <Button
                  size="sm" variant="outline"
                  disabled={savingNotes || notesDraft === (selectedClaim.resolution_notes ?? '')}
                  onClick={handleSaveNotes}
                >
                  {savingNotes ? 'Guardando…' : 'Guardar notas'}
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  const filterTabs: { key: 'all' | 'open' | 'closed'; label: string }[] = [
    { key: 'all',    label: 'Todos' },
    { key: 'open',   label: 'Abiertos' },
    { key: 'closed', label: 'Cerrados' },
  ]

  return (
    <div className="flex flex-col h-full space-y-4">

      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 flex-none">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por ticket #, pedido o cliente..."
            aria-label="Buscar reclamos por número de ticket, pedido o cliente"
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

      {/* Filtro por estado */}
      <div className="flex items-center gap-1 flex-none" role="tablist" aria-label="Filtrar reclamos por estado">
        {filterTabs.map(t => (
          <button
            key={t.key}
            role="tab"
            aria-selected={statusFilter === t.key}
            onClick={() => setStatusFilter(t.key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              statusFilter === t.key
                ? 'bg-primary/10 border-primary/40 text-primary font-medium'
                : 'border-border text-muted-foreground hover:bg-accent/40'
            }`}
          >
            {t.label}
            {t.key === 'open' && openCount > 0 && <span className="ml-1 opacity-70">({openCount})</span>}
          </button>
        ))}
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0 overflow-auto pb-4 pr-1">

        {/* Lista */}
        <div className="lg:col-span-1 space-y-3">
          <p className="text-sm text-muted-foreground font-medium px-1">
            {filteredClaims.length} {filteredClaims.length === 1 ? 'reclamo' : 'reclamos'}
            {statusFilter !== 'all' && ` · ${statusFilter === 'open' ? 'abiertos' : 'cerrados'}`}
          </p>

          {filteredClaims.length === 0 && (
            <EmptyState
              icon={HelpCircle}
              className="p-8"
              title={claims.length === 0 ? 'Aún no hay reclamos' : undefined}
              description={
                claims.length === 0 ? (
                  <>
                    El bot registra un ticket automáticamente cuando un cliente reporta un problema por WhatsApp.
                    {canWrite && ' También puedes abrir uno con «Nuevo Reclamo».'}
                  </>
                ) : (
                  'Ningún reclamo coincide con tu búsqueda o filtro.'
                )
              }
            />
          )}

          {filteredClaims.map(claim => {
            const st = STATUS_MAP[claim.status] ?? STATUS_MAP.open
            const selected = selectedClaim?.id === claim.id
            return (
              <div
                key={claim.id}
                role="button"
                tabIndex={0}
                aria-pressed={selected}
                aria-label={`Ticket ${ticketLabel(claim.ticket_number)}, ${st.label}, cliente ${customerLabel(claim.customer)}`}
                onClick={() => selectClaim(claim)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectClaim(claim) } }}
                className={`cursor-pointer rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-accent/30 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-primary/50 ${
                  selected
                    ? 'ring-1 ring-primary/50 border-primary/40 bg-primary/5'
                    : 'border-border'
                }`}
              >
                <div className="flex justify-between items-start gap-2">
                  <span className="font-medium text-sm text-foreground truncate">
                    Ticket {ticketLabel(claim.ticket_number)}
                  </span>
                  <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border shrink-0 ${st.color}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />
                    {st.label}
                  </span>
                </div>
                <div className="flex justify-between mt-1.5 text-xs text-muted-foreground">
                  <span className="truncate">{customerLabel(claim.customer)}</span>
                  <span className="shrink-0">{new Date(claim.created_at).toLocaleDateString('es-CO', { timeZone: 'America/Bogota', day: '2-digit', month: 'short' })}</span>
                </div>
              </div>
            )
          })}
        </div>

        {/* Detalle (desktop) */}
        <div className="lg:col-span-2 hidden lg:flex flex-col">
          {selectedClaim ? (
            <div className="flex-1 rounded-xl border border-border bg-card overflow-hidden">
              {renderDetail()}
            </div>
          ) : (
            <EmptyState
              variant="plain"
              icon={FileText}
              className="flex-1 rounded-xl border border-dashed border-border text-muted-foreground"
              description="Selecciona un reclamo para ver el detalle"
            />
          )}
        </div>
      </div>

      {/* Detalle (móvil) — el panel lg no se renderiza bajo el breakpoint */}
      <Sheet open={mobileDetailOpen && !isDesktop} onOpenChange={setMobileDetailOpen}>
        <SheetContent side="right" className="w-full sm:max-w-md p-0 overflow-hidden flex flex-col">
          <SheetHeader className="sr-only">
            <SheetTitle>Detalle del reclamo {selectedClaim ? ticketLabel(selectedClaim.ticket_number) : ''}</SheetTitle>
          </SheetHeader>
          <div className="flex-1 overflow-hidden">
            {renderDetail()}
          </div>
        </SheetContent>
      </Sheet>

      {/* BLOQUE G-2: Dialog de reembolso — captura el monto REAL reembolsado. */}
      <Dialog open={refundOpen} onOpenChange={(o) => { setRefundOpen(o); if (!o) setActionError(null) }}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>
              Registrar reembolso {selectedClaim ? `· ${ticketLabel(selectedClaim.ticket_number)}` : ''}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Ingresa el monto <strong>realmente reembolsado</strong> en Wompi. Este valor se
              descuenta de las <strong>ventas netas</strong> del panel. Emite el reembolso en
              Wompi si aún no lo hiciste — este paso solo lo registra.
            </p>
            <div className="space-y-1.5">
              <Label htmlFor="refund-amount">Monto reembolsado (COP)</Label>
              <Input
                id="refund-amount" type="number" min="0" step="1" inputMode="numeric"
                value={refundAmount}
                onChange={(e) => setRefundAmount(e.target.value)}
                placeholder="0" autoFocus
              />
            </div>
            {actionError && <p className="text-sm text-red-700">{actionError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRefundOpen(false)} disabled={refundSubmitting}>
              Cancelar
            </Button>
            <Button onClick={submitRefund} disabled={refundSubmitting}>
              {refundSubmitting ? 'Guardando…' : 'Marcar reembolsado'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
                      <span className="font-mono">{orderShort(o.id)}</span>
                      {o.customer_name ? ` · ${o.customer_name}` : ''}
                      {` · ${new Date(o.created_at).toLocaleDateString('es-CO', { timeZone: 'America/Bogota', day: '2-digit', month: 'short' })}`}
                      {` · $${o.total_amount?.toLocaleString('es-CO') ?? '0'}`}
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
              <p className="text-xs text-red-700 flex items-center gap-1">
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
