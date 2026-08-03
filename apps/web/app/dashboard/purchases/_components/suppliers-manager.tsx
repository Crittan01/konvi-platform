'use client'

import { useMemo, useState, useTransition } from 'react'
import { toast } from 'sonner'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { SubmitButton } from '@/components/ui/submit-button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useConfirm } from '@/components/ui/confirm-dialog'
import ActionResultForm from '@/components/action-result-form'
import { Plus, User, Mail, Phone, CalendarClock, Building2, Pencil, Power, PowerOff, Loader2 } from 'lucide-react'
import { addSupplier, updateSupplier, setSupplierActive } from '../actions'

export type Supplier = {
  id: string
  name: string
  contact_email?: string | null
  phone?: string | null
  lead_time_days?: number | null
  is_active?: boolean | null
}

type Props = {
  suppliers: Supplier[]
  canWrite: boolean
}

/** is_active ausente (columna aún no migrada) se trata como activo. */
function isActive(s: Supplier): boolean {
  return s.is_active !== false
}

export default function SuppliersManager({ suppliers, canWrite }: Props) {
  const confirm = useConfirm()
  const [showAdd, setShowAdd] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [showInactive, setShowInactive] = useState(false)
  const [isPending, startTransition] = useTransition()

  const activeCount = useMemo(() => suppliers.filter(isActive).length, [suppliers])
  const inactiveCount = suppliers.length - activeCount

  const visible = useMemo(
    () => (showInactive ? suppliers : suppliers.filter(isActive)),
    [suppliers, showInactive],
  )

  const handleToggleActive = (s: Supplier) => {
    const deactivating = isActive(s)
    startTransition(async () => {
      if (deactivating) {
        const okToDo = await confirm({
          title: `¿Desactivar a ${s.name}?`,
          description:
            'El proveedor dejará de aparecer al crear nuevas órdenes de compra. No se borra: su historial de compras se conserva y puedes reactivarlo cuando quieras.',
          confirmLabel: 'Sí, desactivar',
          cancelLabel: 'Volver',
          destructive: true,
        })
        if (!okToDo) return
      }
      const res = await setSupplierActive(s.id, !isActive(s))
      if (!res.ok) {
        toast.error(res.error || 'No se pudo cambiar el estado del proveedor.')
        return
      }
      toast.success(res.message || 'Proveedor actualizado.')
    })
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center bg-muted/20 p-3 rounded-lg border border-border/50">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">Directorio de Proveedores</h2>
          <p className="text-xs text-muted-foreground">
            {activeCount} activo(s)
            {inactiveCount > 0 && ` · ${inactiveCount} inactivo(s)`}
          </p>
        </div>
        {canWrite && !showAdd && (
          <Button onClick={() => setShowAdd(true)} size="sm" className="h-8 text-xs gap-1.5">
            <Plus className="h-3.5 w-3.5" /> Agregar proveedor
          </Button>
        )}
      </div>

      {showAdd && (
        <Card className="border-primary/30">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm">Nuevo Proveedor</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <ActionResultForm
              action={async (fd) => {
                const r = await addSupplier(fd)
                if (r.ok) setShowAdd(false)
                return r
              }}
              className="space-y-4"
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label htmlFor="sup-name" className="text-xs font-semibold text-muted-foreground uppercase">
                    Nombre de la empresa *
                  </label>
                  <Input id="sup-name" name="name" placeholder="Ej: Importadora Gato" required className="h-8 text-sm" />
                </div>
                <div className="space-y-1">
                  <label htmlFor="sup-email" className="text-xs font-semibold text-muted-foreground uppercase">
                    Email de contacto
                  </label>
                  <Input id="sup-email" name="contact_email" type="email" placeholder="ventas@empresa.com" className="h-8 text-sm" />
                </div>
                <div className="space-y-1">
                  <label htmlFor="sup-phone" className="text-xs font-semibold text-muted-foreground uppercase">
                    Teléfono
                  </label>
                  <Input id="sup-phone" name="phone" placeholder="3000000000" className="h-8 text-sm" />
                </div>
                <div className="space-y-1">
                  <label htmlFor="sup-lead" className="text-xs font-semibold text-muted-foreground uppercase">
                    Tiempo de entrega (días)
                  </label>
                  <Input id="sup-lead" name="lead_time_days" type="number" min="0" step="1" placeholder="Ej: 5" className="h-8 text-sm" />
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2 border-t">
                <Button type="button" variant="ghost" size="sm" onClick={() => setShowAdd(false)} className="text-xs">
                  Cancelar
                </Button>
                <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado" className="text-xs">
                  Guardar proveedor
                </SubmitButton>
              </div>
            </ActionResultForm>
          </CardContent>
        </Card>
      )}

      {canWrite && inactiveCount > 0 && (
        <button
          type="button"
          onClick={() => setShowInactive((v) => !v)}
          aria-pressed={showInactive}
          className="text-xs font-medium text-primary hover:underline"
        >
          {showInactive ? 'Ocultar inactivos' : `Mostrar ${inactiveCount} inactivo(s)`}
        </button>
      )}

      {suppliers.length === 0 && !showAdd ? (
        <EmptyState
          icon={Building2}
          className="p-8"
          title="Aún no tienes proveedores"
          description="Registra a quién le compras para poder crear órdenes de compra y reabastecer tu inventario."
          action={
            canWrite ? (
              <Button onClick={() => setShowAdd(true)} size="sm" className="gap-1.5">
                <Plus className="h-3.5 w-3.5" /> Agregar primer proveedor
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {visible.map((s) =>
            editingId === s.id ? (
              <Card key={s.id} className="border-primary/40 md:col-span-2 lg:col-span-1">
                <CardContent className="p-4">
                  <ActionResultForm
                    action={async (fd) => {
                      const r = await updateSupplier(s.id, fd)
                      if (r.ok) setEditingId(null)
                      return r
                    }}
                    className="space-y-3"
                  >
                    <div className="space-y-2">
                      <div className="space-y-1">
                        <label htmlFor={`e-name-${s.id}`} className="text-[11px] font-semibold text-muted-foreground uppercase">
                          Nombre *
                        </label>
                        <Input id={`e-name-${s.id}`} name="name" defaultValue={s.name} required className="h-8 text-sm" />
                      </div>
                      <div className="space-y-1">
                        <label htmlFor={`e-email-${s.id}`} className="text-[11px] font-semibold text-muted-foreground uppercase">
                          Email
                        </label>
                        <Input id={`e-email-${s.id}`} name="contact_email" type="email" defaultValue={s.contact_email || ''} className="h-8 text-sm" />
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                          <label htmlFor={`e-phone-${s.id}`} className="text-[11px] font-semibold text-muted-foreground uppercase">
                            Teléfono
                          </label>
                          <Input id={`e-phone-${s.id}`} name="phone" defaultValue={s.phone || ''} className="h-8 text-sm" />
                        </div>
                        <div className="space-y-1">
                          <label htmlFor={`e-lead-${s.id}`} className="text-[11px] font-semibold text-muted-foreground uppercase">
                            Entrega (días)
                          </label>
                          <Input id={`e-lead-${s.id}`} name="lead_time_days" type="number" min="0" step="1" defaultValue={s.lead_time_days ?? ''} className="h-8 text-sm" />
                        </div>
                      </div>
                    </div>
                    <div className="flex justify-end gap-2 pt-2 border-t">
                      <Button type="button" variant="ghost" size="sm" onClick={() => setEditingId(null)} className="text-xs">
                        Cancelar
                      </Button>
                      <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado" className="text-xs">
                        Guardar cambios
                      </SubmitButton>
                    </div>
                  </ActionResultForm>
                </CardContent>
              </Card>
            ) : (
              <Card
                key={s.id}
                className={`transition-colors ${isActive(s) ? 'hover:border-primary/40' : 'opacity-70 bg-muted/20'}`}
              >
                <CardContent className="p-4 flex flex-col h-full">
                  <div className="mb-3 flex items-start justify-between gap-2">
                    <h3 className="font-semibold text-base truncate flex items-center gap-2 min-w-0">
                      <User className="h-4 w-4 text-primary shrink-0" /> <span className="truncate">{s.name}</span>
                    </h3>
                    {!isActive(s) && <Badge variant="secondary" className="shrink-0">Inactivo</Badge>}
                  </div>
                  <div className="space-y-2 text-sm text-muted-foreground">
                    <div className="flex items-center gap-2">
                      <Mail className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate">{s.contact_email || 'Sin email'}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Phone className="h-3.5 w-3.5 shrink-0" />
                      <span>{s.phone || 'Sin teléfono'}</span>
                    </div>
                    <div className="flex items-center gap-2 pt-2 border-t border-border mt-2">
                      <CalendarClock className="h-3.5 w-3.5 shrink-0" />
                      <span className="text-xs font-medium">
                        {typeof s.lead_time_days === 'number'
                          ? `Tiempo de entrega: ${s.lead_time_days} días`
                          : 'Tiempo de entrega no definido'}
                      </span>
                    </div>
                  </div>
                  {canWrite && (
                    <div className="flex flex-wrap gap-2 justify-end pt-3 mt-3 border-t">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={isPending}
                        onClick={() => setEditingId(s.id)}
                        className="h-8 text-xs gap-1.5"
                      >
                        <Pencil className="h-3.5 w-3.5" /> Editar
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={isPending}
                        onClick={() => handleToggleActive(s)}
                        className={`h-8 text-xs gap-1.5 ${
                          isActive(s)
                            ? 'text-red-700 hover:text-red-800 hover:bg-red-500/10 border-red-700/25'
                            : 'text-emerald-700 hover:text-emerald-800 hover:bg-emerald-500/10 border-emerald-700/25'
                        }`}
                      >
                        {isPending ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : isActive(s) ? (
                          <PowerOff className="h-3.5 w-3.5" />
                        ) : (
                          <Power className="h-3.5 w-3.5" />
                        )}
                        {isActive(s) ? 'Desactivar' : 'Reactivar'}
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            ),
          )}
        </div>
      )}
    </div>
  )
}
