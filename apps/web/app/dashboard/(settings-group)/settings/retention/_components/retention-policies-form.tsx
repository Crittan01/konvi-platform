'use client'

import { useState, useTransition } from 'react'
import { Button } from '@/components/ui/button'
import { useConfirm } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2, Save, Trash2 } from 'lucide-react'

type Entity = 'messages' | 'conversations' | 'contacts_inactive' | 'pii_access_log'
type Action = 'archive' | 'soft_delete' | 'hard_delete' | 'anonymize'

type Policy = {
  id: string
  tenant_id: string | null
  entity: Entity
  ttl_days: number
  action: Action
  enabled: boolean
}

type Props = {
  defaults: Policy[]
  overrides: Policy[]
  canWrite: boolean
  entityLabels: Record<Entity, { label: string; description: string }>
  saveAction: (fd: FormData) => Promise<void>
  deleteAction: (fd: FormData) => Promise<void>
}

const ALL_ENTITIES: Entity[] = ['messages', 'conversations', 'contacts_inactive', 'pii_access_log']

export default function RetentionPoliciesForm({
  defaults, overrides, canWrite, entityLabels, saveAction, deleteAction,
}: Props) {
  const [isPending, startTransition] = useTransition()
  const [busyEntity, setBusyEntity] = useState<Entity | null>(null)
  const confirmar = useConfirm()

  const overridesByEntity = new Map(overrides.map(o => [o.entity, o]))
  const defaultsByEntity = new Map(defaults.map(d => [d.entity, d]))

  const handleSave = (entity: Entity, fd: FormData) => {
    setBusyEntity(entity)
    startTransition(async () => {
      try { await saveAction(fd) } finally { setBusyEntity(null) }
    })
  }

  const handleDelete = async (entity: Entity, id: string) => {
    if (!(await confirmar({
      title: `¿Eliminar el override de ${entityLabels[entity].label}?`,
      description: 'La retención de tu tenant volverá a regirse por el default global.',
      confirmLabel: 'Eliminar override',
      destructive: true,
    }))) return
    setBusyEntity(entity)
    const fd = new FormData()
    fd.set('id', id)
    startTransition(async () => {
      try { await deleteAction(fd) } finally { setBusyEntity(null) }
    })
  }

  return (
    <div className="space-y-3">
      {ALL_ENTITIES.map(entity => {
        const def = defaultsByEntity.get(entity)
        const ov = overridesByEntity.get(entity)
        const labels = entityLabels[entity]
        const effectiveTtl = ov?.ttl_days ?? def?.ttl_days ?? 0
        const effectiveAction = ov?.action ?? def?.action ?? 'hard_delete'
        const isOverridden = !!ov
        const busy = busyEntity === entity && isPending
        return (
          <div
            key={entity}
            className={`rounded-xl border px-4 py-3 ${
              isOverridden ? 'border-blue-700/40 bg-blue-700/5' : 'border-border bg-card/30'
            }`}
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="font-semibold text-foreground flex items-center gap-2">
                  {labels.label}
                  {isOverridden && (
                    <span className="text-xs font-normal text-blue-700 bg-blue-700/10 px-1.5 py-0.5 rounded">
                      Override per-tenant
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">{labels.description}</p>
                <p className="text-xs text-muted-foreground/70 mt-0.5">
                  Default global: <strong>{def?.ttl_days ?? '?'} días · {def?.action ?? '?'}</strong>
                  {isOverridden && (
                    <> → Tu tenant: <strong className="text-blue-700">{effectiveTtl} días · {effectiveAction}</strong></>
                  )}
                </p>
              </div>
            </div>

            {canWrite && (
              <form
                action={fd => handleSave(entity, fd)}
                className="mt-3 flex flex-wrap items-end gap-3"
              >
                <input type="hidden" name="entity" value={entity} />
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">TTL días (1-3650)</Label>
                  <Input
                    type="number"
                    name="ttl_days"
                    min={1}
                    max={3650}
                    defaultValue={effectiveTtl}
                    className="h-8 w-28 text-sm"
                    required
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Acción</Label>
                  <select
                    name="action"
                    defaultValue={effectiveAction}
                    className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                  >
                    <option value="archive">archive</option>
                    <option value="soft_delete">soft_delete</option>
                    <option value="hard_delete">hard_delete</option>
                    <option value="anonymize">anonymize</option>
                  </select>
                </div>
                <Button
                  type="submit"
                  disabled={busy}
                  size="sm"
                  variant="outline"
                  className="h-8 text-xs gap-1.5"
                >
                  {busy
                    ? <><Loader2 className="h-3 w-3 animate-spin" />Guardando...</>
                    : <><Save className="h-3 w-3" />Guardar override</>}
                </Button>
                {isOverridden && ov && (
                  <Button
                    type="button"
                    onClick={() => void handleDelete(entity, ov.id)}
                    disabled={busy}
                    size="sm"
                    variant="ghost"
                    className="h-8 text-xs text-amber-700 hover:bg-amber-700/10 gap-1.5"
                  >
                    <Trash2 className="h-3 w-3" />
                    Volver al default
                  </Button>
                )}
              </form>
            )}
          </div>
        )
      })}
    </div>
  )
}
