'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import {
  Tag, Plus, Pencil, Power, AlertTriangle, CheckCircle2, Loader2,
  Percent, DollarSign, Truck, Trash2, ShieldCheck, HelpCircle, RefreshCw,
  History, Receipt,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import {
  Tooltip, TooltipTrigger, TooltipContent, TooltipProvider,
} from '@/components/ui/tooltip'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import type { Coupon, DiscountType, Redemption, RedemptionStatus } from '../page'
import { utcToBogotaLocal } from '@/lib/date-window'

type ActionResult = { ok: boolean; error?: string }

type RedemptionsResult = { ok: boolean; rows?: Redemption[]; error?: string }

type Props = {
  initialCoupons: Coupon[]
  loadError?: string | null
  canWrite: boolean
  createCouponAction: (formData: FormData) => Promise<ActionResult>
  updateCouponAction: (formData: FormData) => Promise<ActionResult>
  toggleCouponActiveAction: (formData: FormData) => Promise<ActionResult>
  deleteCouponAction: (formData: FormData) => Promise<ActionResult>
  fetchRedemptionsAction: (couponId: string) => Promise<RedemptionsResult>
}

const DISCOUNT_TYPE_LABEL: Record<DiscountType, string> = {
  percent: 'Porcentaje',
  fixed_amount: 'Monto fijo',
  free_shipping: 'Envío gratis',
}

const DISCOUNT_TYPE_ICON: Record<DiscountType, React.ElementType> = {
  percent: Percent,
  fixed_amount: DollarSign,
  free_shipping: Truck,
}

function formatCOP(cents: number): string {
  if (!cents) return '$0'
  const pesos = Math.floor(cents / 100)
  return '$' + pesos.toLocaleString('es-CO').replace(/,/g, '.')
}

function formatDiscountValue(c: Coupon): string {
  if (c.discount_type === 'percent') return `${c.discount_value}%`
  if (c.discount_type === 'fixed_amount') return formatCOP(c.discount_value)  // discount_value ya está en centavos
  return 'Envío gratis'
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('es-CO', { year: 'numeric', month: 'short', day: '2-digit' })
}

// Fecha + hora en zona Colombia (los timestamps se persisten en UTC). Para el
// audit de redenciones importa la hora, no solo el día.
function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString('es-CO', {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', timeZone: 'America/Bogota',
  })
}

// Estado FSM de una redención (coupon_redemptions.status). Mapea al mismo
// vocabulario de Badge del resto del módulo:
//   applied  → cupón vivo en un carrito, aún no consumido (info).
//   consumed → orden con pago APROBADO; cuenta en redemptions_count (success).
//   revoked  → cliente lo quitó o el carrito murió; no cuenta (secondary).
const REDEMPTION_STATUS_META: Record<RedemptionStatus, {
  label: string
  variant: 'success' | 'info' | 'secondary'
  hint: string
}> = {
  consumed: {
    label: 'Consumido', variant: 'success',
    hint: 'Orden con pago aprobado. Cuenta en el total oficial de usos del cupón.',
  },
  applied: {
    label: 'Aplicado', variant: 'info',
    hint: 'Aplicado en un carrito activo, aún sin pago aprobado. No cuenta en el total oficial.',
  },
  revoked: {
    label: 'Revocado', variant: 'secondary',
    hint: 'El cliente lo removió o el carrito se canceló/abandonó. No cuenta en el total oficial.',
  },
}

/**
 * Estado REAL del cupón desde la perspectiva del bot — no solo `is_active`.
 *
 * El engine (services/api/lib/coupons.py) rechaza un cupón activo si expiró
 * (`valid_until` pasado) o agotó `max_redemptions`, y aún no lo aplica si su
 * `valid_from` es futuro. La tabla debe reflejar ese estado efectivo: antes,
 * un cupón expirado/agotado seguía en verde "Activo" mientras el bot ya lo
 * rechazaba. Prioridad: inactivo → expirado → agotado → programado → activo.
 */
type CouponStatus = {
  label: string
  variant: 'success' | 'warning' | 'info' | 'secondary'
  hint: string
}

function deriveStatus(c: Coupon, now: number): CouponStatus {
  if (!c.is_active) {
    return {
      label: 'Inactivo', variant: 'secondary',
      hint: 'Desactivado manualmente. El bot no lo aplica ni lo anuncia.',
    }
  }
  const until = c.valid_until ? new Date(c.valid_until).getTime() : null
  if (until !== null && !isNaN(until) && until <= now) {
    return {
      label: 'Expirado', variant: 'warning',
      hint: 'Pasó su fecha "Válido hasta". El bot ya rechaza nuevas aplicaciones aunque siga marcado como activo. Ajusta la vigencia o desactívalo.',
    }
  }
  if (c.max_redemptions !== null && c.redemptions_count >= c.max_redemptions) {
    return {
      label: 'Agotado', variant: 'warning',
      hint: 'Alcanzó el máximo de usos permitidos. El bot ya no lo acepta. Sube el máximo para reactivarlo.',
    }
  }
  const from = c.valid_from ? new Date(c.valid_from).getTime() : null
  if (from !== null && !isNaN(from) && from > now) {
    return {
      label: 'Programado', variant: 'info',
      hint: 'Su vigencia aún no empieza ("Válido desde" es futuro). El bot lo aplicará cuando llegue la fecha.',
    }
  }
  return {
    label: 'Activo', variant: 'success',
    hint: 'Vigente y disponible. El bot lo acepta cuando el cliente escribe el código.',
  }
}

export default function PromotionsManager({
  initialCoupons,
  loadError,
  canWrite,
  createCouponAction,
  updateCouponAction,
  toggleCouponActiveAction,
  deleteCouponAction,
  fetchRedemptionsAction,
}: Props) {
  const router = useRouter()
  const now = Date.now()
  const [pending, startTransition] = useTransition()
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<Coupon | null>(null)
  const [deleting, setDeleting] = useState<Coupon | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Vista de redenciones (F2): sheet de solo-lectura por cupón. Estado propio
  // (no useTransition) porque es una carga on-demand independiente de las
  // mutaciones. `viewing` guarda el cupón cuya auditoría se está mostrando.
  const [viewing, setViewing] = useState<Coupon | null>(null)
  const [redemptions, setRedemptions] = useState<Redemption[]>([])
  const [redemptionsLoading, setRedemptionsLoading] = useState(false)
  const [redemptionsError, setRedemptionsError] = useState<string | null>(null)

  const loadRedemptions = (c: Coupon) => {
    setRedemptionsLoading(true)
    setRedemptionsError(null)
    setRedemptions([])
    fetchRedemptionsAction(c.id)
      .then((res) => {
        if (!res.ok) {
          setRedemptionsError(res.error || 'No pudimos cargar las redenciones.')
          return
        }
        setRedemptions(res.rows ?? [])
      })
      .catch(() => setRedemptionsError('Error de red. Reintenta en un momento.'))
      .finally(() => setRedemptionsLoading(false))
  }

  const openRedemptions = (c: Coupon) => {
    setViewing(c)
    loadRedemptions(c)
  }

  const handleCreate = (formData: FormData) => {
    setFormError(null)
    setSuccessMsg(null)
    startTransition(async () => {
      const res = await createCouponAction(formData)
      if (!res.ok) {
        setFormError(res.error || 'Error desconocido')
        return
      }
      setSuccessMsg(`Cupón ${formData.get('code')} creado.`)
      setCreateOpen(false)
      router.refresh()
    })
  }

  const handleUpdate = (formData: FormData) => {
    setFormError(null)
    setSuccessMsg(null)
    startTransition(async () => {
      const res = await updateCouponAction(formData)
      if (!res.ok) {
        setFormError(res.error || 'Error desconocido')
        return
      }
      setSuccessMsg(`Cupón ${editing?.code} actualizado.`)
      setEditing(null)
      router.refresh()
    })
  }

  const handleToggle = (c: Coupon) => {
    const fd = new FormData()
    fd.set('id', c.id)
    fd.set('is_active', String(!c.is_active))
    startTransition(async () => {
      const res = await toggleCouponActiveAction(fd)
      if (!res.ok) {
        setFormError(res.error || 'Error desconocido')
        return
      }
      setSuccessMsg(
        `Cupón ${c.code} ${!c.is_active ? 'activado' : 'desactivado'}.`,
      )
      router.refresh()
    })
  }

  const handleDelete = () => {
    if (!deleting) return
    const fd = new FormData()
    fd.set('id', deleting.id)
    setFormError(null)
    setSuccessMsg(null)
    startTransition(async () => {
      const res = await deleteCouponAction(fd)
      if (!res.ok) {
        setFormError(res.error || 'Error desconocido')
        // Mantenemos el dialog abierto para que el owner lea el error
        // (típicamente: "tiene redenciones, usa Desactivar"). Podría
        // cerrarlo + mostrar como banner, pero el contexto del dialog
        // hace el mensaje más entendible.
        return
      }
      setSuccessMsg(`Cupón ${deleting.code} eliminado.`)
      setDeleting(null)
      router.refresh()
    })
  }

  return (
    <TooltipProvider delayDuration={200}>
    <div className="space-y-4">
      {successMsg && (
        <div className="rounded-md border border-emerald-700/40 bg-emerald-700/5 p-3 text-sm text-emerald-900">
          <CheckCircle2 className="inline h-4 w-4 mr-1" />
          {successMsg}
        </div>
      )}
      {formError && (
        <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-3 text-sm text-rose-900">
          <AlertTriangle className="inline h-4 w-4 mr-1" />
          {formError}
        </div>
      )}

      {canWrite && (
        <Button
          onClick={() => { setFormError(null); setCreateOpen(true) }}
        >
          <Plus className="h-4 w-4 mr-1" />
          Nuevo cupón
        </Button>
      )}

      {loadError ? (
        <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-6 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-rose-700 mb-2" />
          <p className="text-sm text-rose-900">{loadError}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3 border-rose-700/40 text-rose-900 hover:bg-rose-700/5"
            onClick={() => router.refresh()}
          >
            <RefreshCw className="h-3.5 w-3.5 mr-1" />
            Reintentar
          </Button>
        </div>
      ) : initialCoupons.length === 0 ? (
        <div className="rounded-md border border-border bg-muted/20 p-6 text-center text-muted-foreground">
          <Tag className="mx-auto h-8 w-8 text-muted-foreground mb-2" />
          <p className="text-sm">Aún no tienes cupones. Crea el primero arriba.</p>
        </div>
      ) : (
        <div className="rounded-md border border-border bg-card">
          <Table>
            <TableHeader className="bg-muted/30">
              <TableRow>
                <TableHead>Código</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead>Valor</TableHead>
                <TableHead>Mín. compra</TableHead>
                <TableHead>Usos</TableHead>
                <TableHead>Visible</TableHead>
                <TableHead>Vigencia</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead className="text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {initialCoupons.map((c) => {
                const Icon = DISCOUNT_TYPE_ICON[c.discount_type]
                const usageStr = c.max_redemptions
                  ? `${c.redemptions_count} / ${c.max_redemptions}`
                  : `${c.redemptions_count} / ∞`
                const status = deriveStatus(c, now)
                return (
                  <TableRow key={c.id} className={c.is_active ? '' : 'bg-muted/20 text-muted-foreground'}>
                    <TableCell>
                      <div className="font-mono font-semibold">{c.code}</div>
                      {c.description && (
                        <div className="text-xs text-muted-foreground mt-0.5">{c.description}</div>
                      )}
                    </TableCell>
                    <TableCell>
                      <span className="inline-flex items-center gap-1">
                        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                        {DISCOUNT_TYPE_LABEL[c.discount_type]}
                      </span>
                    </TableCell>
                    <TableCell className="font-medium">{formatDiscountValue(c)}</TableCell>
                    <TableCell>
                      {c.min_subtotal_cents > 0
                        ? formatCOP(c.min_subtotal_cents)
                        : '—'}
                    </TableCell>
                    <TableCell>
                      {c.total_historical_redemptions > 0 ? (
                        // Con historial: el contador es un botón que abre el
                        // sheet de auditoría de redenciones (F2). Cubre tanto
                        // "N hist." (revocadas/aplicadas) como el caso normal.
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              onClick={() => openRedemptions(c)}
                              aria-label={`Ver las ${c.total_historical_redemptions} redenciones del cupón ${c.code}`}
                              className="-mx-1.5 inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-left hover:bg-muted/50 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              <span className="underline decoration-dotted underline-offset-2">{usageStr}</span>
                              {c.total_historical_redemptions > c.redemptions_count && (
                                <span className="inline-flex items-center rounded-full border border-border bg-muted/30 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                                  {c.total_historical_redemptions} hist.
                                </span>
                              )}
                              <History className="h-3 w-3 text-muted-foreground" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            Ver redenciones: qué órdenes usaron este cupón, por cuánto y en qué estado.
                          </TooltipContent>
                        </Tooltip>
                      ) : (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="cursor-help">{usageStr}</span>
                          </TooltipTrigger>
                          <TooltipContent>Veces consumido (orden con pago APROBADO) sobre el máximo. Sin redenciones aún.</TooltipContent>
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell>
                      {/* F4.2: is_customer_visible gobierna si el bot lo anuncia
                          proactivamente. Antes solo visible abriendo el modal. */}
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="cursor-help">
                            <Badge variant={c.is_customer_visible ? 'info' : 'secondary'}>
                              {c.is_customer_visible ? 'Anunciable' : 'Interno'}
                            </Badge>
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>
                          {c.is_customer_visible
                            ? 'El bot puede mencionarlo proactivamente al cliente.'
                            : 'Interno: el bot no lo anuncia; solo se aplica si el cliente escribe el código exacto.'}
                        </TooltipContent>
                      </Tooltip>
                    </TableCell>
                    <TableCell className="text-xs">
                      {c.valid_from || c.valid_until ? (
                        <>
                          {formatDate(c.valid_from)} → {formatDate(c.valid_until)}
                        </>
                      ) : 'Sin límite'}
                    </TableCell>
                    <TableCell>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="cursor-help">
                            <Badge variant={status.variant}>{status.label}</Badge>
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>{status.hint}</TooltipContent>
                      </Tooltip>
                    </TableCell>
                    <TableCell className="text-right">
                      {canWrite && (
                        <div className="flex justify-end gap-1">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={pending}
                                onClick={() => { setFormError(null); setEditing(c) }}
                                aria-label={`Editar cupón ${c.code}`}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>Editar</TooltipContent>
                          </Tooltip>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={pending}
                                onClick={() => handleToggle(c)}
                                aria-label={`${c.is_active ? 'Desactivar' : 'Activar'} cupón ${c.code}`}
                                className={c.is_active
                                  ? 'border-amber-700/40 text-amber-900 hover:bg-amber-700/5'
                                  : 'border-emerald-700/40 text-emerald-900 hover:bg-emerald-700/5'}
                              >
                                <Power className="h-3.5 w-3.5" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>{c.is_active ? 'Desactivar' : 'Activar'}</TooltipContent>
                          </Tooltip>
                          {/*
                            * Trash condicional (ADR-0015 D6): SOLO si nunca
                            * tuvo redenciones (Habeas Data Ley 1581 audit
                            * preservation). Si tiene historiales, mostramos
                            * un icono read-only con tooltip explicativo
                            * para que el owner entienda por qué no puede.
                            */}
                          {c.has_historical_redemptions ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span
                                  role="img"
                                  aria-label={`El cupón ${c.code} no se puede eliminar: ya tuvo redenciones (audit Habeas Data)`}
                                  className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-muted/20 text-muted-foreground"
                                >
                                  <ShieldCheck className="h-3.5 w-3.5" />
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>
                                No se puede eliminar: este cupón ya tuvo redenciones (audit Habeas
                                Data). Usa Desactivar.
                              </TooltipContent>
                            </Tooltip>
                          ) : (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  disabled={pending}
                                  onClick={() => { setFormError(null); setDeleting(c) }}
                                  aria-label={`Eliminar cupón ${c.code} permanentemente`}
                                  className="border-rose-700/40 text-rose-900 hover:bg-rose-700/5"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Eliminar permanentemente</TooltipContent>
                            </Tooltip>
                          )}
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Modal crear */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Crear nuevo cupón</DialogTitle>
            <DialogDescription>
              Los clientes lo aplican por WhatsApp escribiendo
              &quot;tengo el cupón [CÓDIGO]&quot;.
            </DialogDescription>
          </DialogHeader>
          <CouponForm
            mode="create"
            pending={pending}
            onSubmit={handleCreate}
            onCancel={() => setCreateOpen(false)}
          />
        </DialogContent>
      </Dialog>

      {/* Modal editar */}
      <Dialog open={!!editing} onOpenChange={(o) => { if (!o) setEditing(null) }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Editar cupón {editing?.code}</DialogTitle>
            <DialogDescription>
              El código no se puede cambiar (preserva audit trail de redenciones).
            </DialogDescription>
          </DialogHeader>
          {editing && (
            <CouponForm
              mode="edit"
              initialCoupon={editing}
              pending={pending}
              onSubmit={handleUpdate}
              onCancel={() => setEditing(null)}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* Modal confirmar eliminación (hard delete) */}
      <Dialog open={!!deleting} onOpenChange={(o) => { if (!o) { setDeleting(null); setFormError(null) } }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-foreground">
              <Trash2 className="h-5 w-5 text-rose-700" />
              Eliminar cupón {deleting?.code}
            </DialogTitle>
            <DialogDescription>
              Esta acción <b>no se puede deshacer</b>. El cupón se borrará
              permanentemente de la base de datos.
            </DialogDescription>
          </DialogHeader>

          <div className="rounded-md border border-emerald-700/40 bg-emerald-700/5 p-3 text-sm text-emerald-900">
            <ShieldCheck className="inline h-4 w-4 mr-1" />
            Este cupón <b>nunca tuvo redenciones</b>, así que es seguro
            eliminarlo sin afectar auditoría Habeas Data.
          </div>

          {formError && (
            <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-3 text-sm text-rose-900">
              <AlertTriangle className="inline h-4 w-4 mr-1" />
              {formError}
            </div>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => { setDeleting(null); setFormError(null) }}
              disabled={pending}
            >
              Cancelar
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleDelete}
              disabled={pending}
            >
              {pending ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Sí, eliminar permanentemente
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Sheet de redenciones (F2): auditoría de solo-lectura por cupón.
          Responde "¿qué órdenes usaron este cupón, por cuánto y en qué
          estado?" sin depender de SQL. Datos ya en coupon_redemptions. */}
      <Sheet
        open={!!viewing}
        onOpenChange={(o) => {
          if (!o) { setViewing(null); setRedemptions([]); setRedemptionsError(null) }
        }}
      >
        <SheetContent
          side="right"
          className="w-full overflow-y-auto sm:max-w-xl"
        >
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <History className="h-5 w-5 text-primary" />
              Redenciones de{' '}
              <span className="font-mono">{viewing?.code}</span>
            </SheetTitle>
            <SheetDescription>
              Órdenes que aplicaron este cupón, el monto descontado y su estado.
              Solo lectura (auditoría Habeas Data).
            </SheetDescription>
          </SheetHeader>

          <div className="mt-4">
            {redemptionsLoading ? (
              <div className="space-y-2" aria-busy="true" aria-label="Cargando redenciones">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : redemptionsError ? (
              <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-6 text-center">
                <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-rose-700" />
                <p className="text-sm text-rose-900">{redemptionsError}</p>
                {viewing && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-3 border-rose-700/40 text-rose-900 hover:bg-rose-700/5"
                    onClick={() => loadRedemptions(viewing)}
                  >
                    <RefreshCw className="mr-1 h-3.5 w-3.5" />
                    Reintentar
                  </Button>
                )}
              </div>
            ) : redemptions.length === 0 ? (
              <div className="rounded-md border border-border bg-muted/20 p-6 text-center text-muted-foreground">
                <Receipt className="mx-auto mb-2 h-8 w-8" />
                <p className="text-sm">Este cupón aún no tiene redenciones registradas.</p>
              </div>
            ) : (
              <>
                {/* Resumen por estado — contexto rápido antes del detalle. */}
                <div className="mb-3 flex flex-wrap gap-2 text-xs">
                  {(['consumed', 'applied', 'revoked'] as RedemptionStatus[]).map((st) => {
                    const n = redemptions.filter((r) => r.status === st).length
                    if (n === 0) return null
                    const meta = REDEMPTION_STATUS_META[st]
                    return (
                      <Badge key={st} variant={meta.variant}>
                        {n} {meta.label.toLowerCase()}
                        {n === 1 ? '' : 's'}
                      </Badge>
                    )
                  })}
                </div>
                <div className="rounded-md border border-border bg-card">
                  <Table>
                    <TableHeader className="bg-muted/30">
                      <TableRow>
                        <TableHead>Estado</TableHead>
                        <TableHead>Descuento</TableHead>
                        <TableHead>Orden</TableHead>
                        <TableHead>Fecha</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {redemptions.map((r) => {
                        const meta = REDEMPTION_STATUS_META[r.status]
                        // Fecha relevante según el estado FSM.
                        const when = r.status === 'consumed'
                          ? r.consumed_at
                          : r.status === 'revoked'
                          ? r.revoked_at
                          : r.applied_at
                        return (
                          <TableRow key={r.id}>
                            <TableCell>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span className="cursor-help">
                                    <Badge variant={meta.variant}>{meta.label}</Badge>
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent>{meta.hint}</TooltipContent>
                              </Tooltip>
                              {r.status === 'revoked' && r.revoked_reason && (
                                <div className="mt-0.5 text-[11px] text-muted-foreground">
                                  {r.revoked_reason}
                                </div>
                              )}
                            </TableCell>
                            <TableCell className="font-medium">
                              {formatCOP(r.discount_applied_cents)}
                            </TableCell>
                            <TableCell>
                              {r.order_id ? (
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <span className="cursor-help font-mono text-xs">
                                      {r.order_id.slice(0, 8)}
                                    </span>
                                  </TooltipTrigger>
                                  <TooltipContent>Orden {r.order_id}</TooltipContent>
                                </Tooltip>
                              ) : (
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <span className="cursor-help text-muted-foreground">—</span>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    Aplicado en un carrito que aún no generó orden.
                                  </TooltipContent>
                                </Tooltip>
                              )}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {formatDateTime(when)}
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </div>
                {redemptions.length >= 500 && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Mostrando las 500 redenciones más recientes.
                  </p>
                )}
              </>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </div>
    </TooltipProvider>
  )
}

// ─── Sub-componente: Label con tooltip de ayuda ──────────────────────────────

function LabelWithHelp({
  htmlFor, label, help,
}: { htmlFor: string; label: string; help: string }) {
  return (
    <Label htmlFor={htmlFor} className="flex items-center gap-1.5">
      <span>{label}</span>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            role="img"
            aria-label={help}
            className="inline-flex cursor-help text-muted-foreground hover:text-foreground"
          >
            <HelpCircle className="h-3.5 w-3.5" />
          </span>
        </TooltipTrigger>
        <TooltipContent>{help}</TooltipContent>
      </Tooltip>
    </Label>
  )
}

// Subtítulos explicativos del comportamiento per discount_type. Owner
// adivinaba si percent aplicaba sobre productos o total — esto hace
// explícito el contrato de cómputo (services/api/lib/coupons.py
// compute_discount).
const DISCOUNT_TYPE_BEHAVIOR_HINT: Record<DiscountType, string> = {
  percent:
    'Resta el porcentaje del subtotal de productos. NO aplica al envío. ' +
    'Ejemplo: 10% sobre productos $100.000 = descuento $10.000.',
  fixed_amount:
    'Resta una cifra fija en pesos del subtotal de productos. NO aplica ' +
    'al envío. Ejemplo: $5.000 OFF en compra de productos $100.000 = ' +
    'cliente paga $95.000 + envío.',
  free_shipping:
    'Cubre 100% del costo de envío. NO toca el precio de productos. ' +
    'Si el envío cuesta $15.000, ese monto se descuenta del total.',
}

// ─── Sub-componente: formulario reusable crear/editar ────────────────────────

function CouponForm({
  mode,
  initialCoupon,
  pending,
  onSubmit,
  onCancel,
}: {
  mode: 'create' | 'edit'
  initialCoupon?: Coupon
  pending: boolean
  onSubmit: (fd: FormData) => void
  onCancel: () => void
}) {
  const [discountType, setDiscountType] = useState<DiscountType>(
    initialCoupon?.discount_type ?? 'percent'
  )

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    if (initialCoupon) fd.set('id', initialCoupon.id)
    onSubmit(fd)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {mode === 'create' && (
        <div>
          <LabelWithHelp
            htmlFor="code"
            label="Código (3-30 caracteres)"
            help={
              'Lo que el cliente escribe en WhatsApp. Por ejemplo: ' +
              '"tengo el cupón PROMO10". Solo mayúsculas, dígitos, ' +
              'guion (-) y guion bajo (_).'
            }
          />
          <Input
            id="code"
            name="code"
            required
            pattern="[A-Z0-9_-]{3,30}"
            placeholder="PROMO10"
            defaultValue=""
            className="font-mono uppercase"
          />
        </div>
      )}

      <div>
        <LabelWithHelp
          htmlFor="description"
          label="Descripción (opcional)"
          help={
            'Solo para ti. El cliente nunca ve este texto. Útil para ' +
            'recordar el motivo del cupón (campaña, evento, etc.).'
          }
        />
        <Input
          id="description"
          name="description"
          placeholder="Cupón de bienvenida 10%"
          defaultValue={initialCoupon?.description ?? ''}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <LabelWithHelp
            htmlFor="discount_type"
            label="Tipo de descuento"
            help={
              'Porcentaje y Monto fijo aplican sobre productos (no envío). ' +
              'Envío gratis cubre solo el costo de transportadora.'
            }
          />
          <select
            id="discount_type"
            name="discount_type"
            value={discountType}
            onChange={(e) => setDiscountType(e.target.value as DiscountType)}
            className="w-full rounded-md border border-slate-700 px-3 py-2 text-sm"
          >
            <option value="percent">Porcentaje (%)</option>
            <option value="fixed_amount">Monto fijo (COP)</option>
            <option value="free_shipping">Envío gratis</option>
          </select>
        </div>
        <div>
          <LabelWithHelp
            htmlFor="discount_value"
            label={
              discountType === 'percent' ? 'Porcentaje (0-100)' :
              discountType === 'fixed_amount' ? 'Monto en pesos COP' :
              '(No aplica)'
            }
            help={
              discountType === 'percent'
                ? 'Número entero de 0 a 100. Por ejemplo: 10 = 10% de descuento.'
                : discountType === 'fixed_amount'
                ? 'Cifra fija en pesos colombianos. Por ejemplo: 5000 = $5.000 OFF.'
                : 'Para envío gratis no se necesita valor — se cubre el costo total del envío.'
            }
          />
          <Input
            id="discount_value"
            name="discount_value"
            type="number"
            min="0"
            max={discountType === 'percent' ? '100' : undefined}
            required={discountType !== 'free_shipping'}
            defaultValue={
              initialCoupon
                // fixed_amount se guarda en centavos → mostrar pesos en el input
                ? (initialCoupon.discount_type === 'fixed_amount'
                    ? Math.floor(initialCoupon.discount_value / 100)
                    : initialCoupon.discount_value)
                : ''
            }
            disabled={discountType === 'free_shipping'}
          />
        </div>
      </div>

      {/* Subtítulo explicativo per tipo (lo más importante: aclara
          comportamiento que owner no conoce sin leer ADR-0015). */}
      <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        <b className="text-foreground">¿Cómo funciona?</b>{' '}
        {DISCOUNT_TYPE_BEHAVIOR_HINT[discountType]}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <LabelWithHelp
            htmlFor="min_subtotal_pesos"
            label="Mínimo de compra (COP)"
            help={
              'Subtotal mínimo de productos (sin envío) que el carrito debe ' +
              'tener para activar el cupón. Si el cliente no llega al mínimo, ' +
              'el bot rechaza el cupón con mensaje claro. Vacío o 0 = sin mínimo.'
            }
          />
          <Input
            id="min_subtotal_pesos"
            name="min_subtotal_pesos"
            type="number"
            min="0"
            placeholder="0 = sin mínimo"
            defaultValue={
              initialCoupon
                ? Math.floor(initialCoupon.min_subtotal_cents / 100)
                : ''
            }
          />
        </div>
        <div>
          <LabelWithHelp
            htmlFor="max_redemptions"
            label="Máximo de usos (total)"
            help={
              'Total de redenciones permitidas en TODA la tienda (no por ' +
              'cliente). Solo cuenta las que llegaron a pago APROBADO. ' +
              'Vacío = ilimitado.'
            }
          />
          <Input
            id="max_redemptions"
            name="max_redemptions"
            type="number"
            min="1"
            placeholder="vacío = ilimitado"
            defaultValue={initialCoupon?.max_redemptions ?? ''}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <LabelWithHelp
            htmlFor="valid_from"
            label="Válido desde"
            help={
              'Fecha y hora desde la cual el cupón puede aplicarse. ' +
              'Hora Colombia (UTC-5). Vacío = válido desde ahora.'
            }
          />
          <Input
            id="valid_from"
            name="valid_from"
            type="datetime-local"
            defaultValue={utcToBogotaLocal(initialCoupon?.valid_from)}
          />
        </div>
        <div>
          <LabelWithHelp
            htmlFor="valid_until"
            label="Válido hasta"
            help={
              'Fecha y hora cuando el cupón expira. Después de esta fecha ' +
              'el bot rechaza nuevas aplicaciones. Hora Colombia (UTC-5). ' +
              'Vacío = sin fecha de expiración.'
            }
          />
          <Input
            id="valid_until"
            name="valid_until"
            type="datetime-local"
            defaultValue={utcToBogotaLocal(initialCoupon?.valid_until)}
          />
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/20 p-3">
        <input
          type="checkbox"
          id="is_customer_visible"
          name="is_customer_visible"
          defaultChecked={initialCoupon ? initialCoupon.is_customer_visible : true}
          className="mt-0.5 h-4 w-4 accent-emerald-700"
        />
        <label htmlFor="is_customer_visible" className="text-sm text-foreground">
          <span className="font-medium">Visible al cliente</span>
          <span className="block text-xs text-muted-foreground">
            Si está marcado, el bot puede mencionar este cupón proactivamente. Si lo desmarcas, es
            interno: solo se aplica cuando el cliente escribe el código exacto.
          </span>
        </label>
      </div>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
          Cancelar
        </Button>
        <Button
          type="submit"
          disabled={pending}
          className="bg-emerald-700 text-white hover:bg-emerald-800"
        >
          {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {mode === 'create' ? 'Crear cupón' : 'Guardar cambios'}
        </Button>
      </DialogFooter>
    </form>
  )
}
