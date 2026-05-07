'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import {
  Tag, Plus, Pencil, Power, AlertTriangle, CheckCircle2, Loader2,
  Percent, DollarSign, Truck, Trash2, ShieldCheck, HelpCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import type { Coupon, DiscountType } from '../page'

type ActionResult = { ok: boolean; error?: string }

type Props = {
  initialCoupons: Coupon[]
  canWrite: boolean
  createCouponAction: (formData: FormData) => Promise<ActionResult>
  updateCouponAction: (formData: FormData) => Promise<ActionResult>
  toggleCouponActiveAction: (formData: FormData) => Promise<ActionResult>
  deleteCouponAction: (formData: FormData) => Promise<ActionResult>
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
  if (c.discount_type === 'fixed_amount') return formatCOP(c.discount_value * 100)
  return 'Envío gratis'
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('es-CO', { year: 'numeric', month: 'short', day: '2-digit' })
}

export default function PromotionsManager({
  initialCoupons,
  canWrite,
  createCouponAction,
  updateCouponAction,
  toggleCouponActiveAction,
  deleteCouponAction,
}: Props) {
  const router = useRouter()
  const [pending, startTransition] = useTransition()
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<Coupon | null>(null)
  const [deleting, setDeleting] = useState<Coupon | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

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
    <div className="space-y-4">
      {successMsg && (
        <div className="rounded-md border border-emerald-700 bg-emerald-50 p-3 text-sm text-emerald-900">
          <CheckCircle2 className="inline h-4 w-4 mr-1" />
          {successMsg}
        </div>
      )}
      {formError && (
        <div className="rounded-md border border-rose-700 bg-rose-50 p-3 text-sm text-rose-900">
          <AlertTriangle className="inline h-4 w-4 mr-1" />
          {formError}
        </div>
      )}

      {canWrite && (
        <Button
          onClick={() => { setFormError(null); setCreateOpen(true) }}
          className="bg-emerald-700 text-white hover:bg-emerald-800"
        >
          <Plus className="h-4 w-4 mr-1" />
          Nuevo cupón
        </Button>
      )}

      {initialCoupons.length === 0 ? (
        <div className="rounded-md border border-slate-300 bg-slate-50 p-6 text-center text-slate-700">
          <Tag className="mx-auto h-8 w-8 text-slate-500 mb-2" />
          <p className="text-sm">Aún no tienes cupones. Crea el primero arriba.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-slate-300 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-100 text-left text-slate-800">
              <tr>
                <th className="px-3 py-2 font-medium">Código</th>
                <th className="px-3 py-2 font-medium">Tipo</th>
                <th className="px-3 py-2 font-medium">Valor</th>
                <th className="px-3 py-2 font-medium">Mín. compra</th>
                <th className="px-3 py-2 font-medium">Usos</th>
                <th className="px-3 py-2 font-medium">Vigencia</th>
                <th className="px-3 py-2 font-medium">Estado</th>
                <th className="px-3 py-2 font-medium text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {initialCoupons.map((c) => {
                const Icon = DISCOUNT_TYPE_ICON[c.discount_type]
                const usageStr = c.max_redemptions
                  ? `${c.redemptions_count} / ${c.max_redemptions}`
                  : `${c.redemptions_count} / ∞`
                return (
                  <tr key={c.id} className={c.is_active ? '' : 'bg-slate-50 text-slate-600'}>
                    <td className="px-3 py-2">
                      <div className="font-mono font-semibold">{c.code}</div>
                      {c.description && (
                        <div className="text-xs text-slate-700 mt-0.5">{c.description}</div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1">
                        <Icon className="h-3.5 w-3.5 text-slate-700" />
                        {DISCOUNT_TYPE_LABEL[c.discount_type]}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-medium">{formatDiscountValue(c)}</td>
                    <td className="px-3 py-2">
                      {c.min_subtotal_cents > 0
                        ? formatCOP(c.min_subtotal_cents)
                        : '—'}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <span title="Veces consumido (orden con pago APROBADO)">
                          {usageStr}
                        </span>
                        {c.total_historical_redemptions > c.redemptions_count && (
                          <span
                            className="inline-flex items-center rounded-full border border-slate-400 bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-700"
                            title={
                              `${c.total_historical_redemptions} aplicaciones en historial ` +
                              `(incluye revocadas y consumidas). El contador principal solo ` +
                              `cuenta órdenes con pago aprobado.`
                            }
                          >
                            {c.total_historical_redemptions} hist.
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {c.valid_from || c.valid_until ? (
                        <>
                          {formatDate(c.valid_from)} → {formatDate(c.valid_until)}
                        </>
                      ) : 'Sin límite'}
                    </td>
                    <td className="px-3 py-2">
                      {c.is_active ? (
                        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-700 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-900">
                          Activo
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full border border-slate-400 bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                          Inactivo
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {canWrite && (
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={pending}
                            onClick={() => { setFormError(null); setEditing(c) }}
                            title="Editar"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={pending}
                            onClick={() => handleToggle(c)}
                            title={c.is_active ? 'Desactivar' : 'Activar'}
                            className={c.is_active
                              ? 'border-amber-700 text-amber-900 hover:bg-amber-50'
                              : 'border-emerald-700 text-emerald-900 hover:bg-emerald-50'}
                          >
                            <Power className="h-3.5 w-3.5" />
                          </Button>
                          {/*
                            * Trash condicional (ADR-0015 D6): SOLO si nunca
                            * tuvo redenciones (Habeas Data Ley 1581 audit
                            * preservation). Si tiene historiales, mostramos
                            * un icono read-only con tooltip explicativo
                            * para que el owner entienda por qué no puede.
                            */}
                          {c.has_historical_redemptions ? (
                            <span
                              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-300 bg-slate-50 text-slate-400"
                              title="No se puede eliminar: este cupón ya tuvo redenciones (audit Habeas Data). Usa Desactivar."
                            >
                              <ShieldCheck className="h-3.5 w-3.5" />
                            </span>
                          ) : (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={pending}
                              onClick={() => { setFormError(null); setDeleting(c) }}
                              title="Eliminar permanentemente"
                              className="border-rose-700 text-rose-900 hover:bg-rose-50"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
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
            <DialogTitle className="flex items-center gap-2 text-rose-900">
              <Trash2 className="h-5 w-5" />
              Eliminar cupón {deleting?.code}
            </DialogTitle>
            <DialogDescription>
              Esta acción <b>no se puede deshacer</b>. El cupón se borrará
              permanentemente de la base de datos.
            </DialogDescription>
          </DialogHeader>

          <div className="rounded-md border border-emerald-700 bg-emerald-50 p-3 text-sm text-emerald-900">
            <ShieldCheck className="inline h-4 w-4 mr-1" />
            Este cupón <b>nunca tuvo redenciones</b>, así que es seguro
            eliminarlo sin afectar auditoría Habeas Data.
          </div>

          {formError && (
            <div className="rounded-md border border-rose-700 bg-rose-50 p-3 text-sm text-rose-900">
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
              onClick={handleDelete}
              disabled={pending}
              className="bg-rose-700 text-white hover:bg-rose-800"
            >
              {pending ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
              Sí, eliminar permanentemente
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ─── Sub-componente: Label con tooltip de ayuda ──────────────────────────────

function LabelWithHelp({
  htmlFor, label, help,
}: { htmlFor: string; label: string; help: string }) {
  return (
    <Label htmlFor={htmlFor} className="flex items-center gap-1.5">
      <span>{label}</span>
      <span
        className="inline-flex cursor-help text-slate-500 hover:text-slate-800"
        title={help}
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </span>
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
            className="w-full rounded-md border border-slate-400 px-3 py-2 text-sm"
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
            defaultValue={initialCoupon?.discount_value ?? ''}
            disabled={discountType === 'free_shipping'}
          />
        </div>
      </div>

      {/* Subtítulo explicativo per tipo (lo más importante: aclara
          comportamiento que owner no conoce sin leer ADR-0015). */}
      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
        <b className="text-slate-900">¿Cómo funciona?</b>{' '}
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
            defaultValue={
              initialCoupon?.valid_from
                ? initialCoupon.valid_from.slice(0, 16)
                : ''
            }
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
            defaultValue={
              initialCoupon?.valid_until
                ? initialCoupon.valid_until.slice(0, 16)
                : ''
            }
          />
        </div>
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
