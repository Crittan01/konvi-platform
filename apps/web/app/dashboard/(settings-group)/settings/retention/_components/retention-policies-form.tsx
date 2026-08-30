'use client'

import { useState, useTransition } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useConfirm } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2, Save, Trash2 } from 'lucide-react'

export type Entity = 'messages' | 'conversations' | 'contacts_inactive' | 'pii_access_log'
type Action = 'archive' | 'soft_delete' | 'hard_delete' | 'anonymize'
type ActionResult = { ok: boolean; error?: string; message?: string }

/**
 * Única acción implementada por entidad en fn_apply_retention
 * (supabase/migrations/20260508010000_retention_per_tenant_fix.sql).
 * El cron hace `ELSE CONTINUE` para cualquier otra combinación → si la UI
 * dejara elegir archive/anonymize, el tenant creería configurar una política
 * de purga que en realidad NUNCA se ejecuta (gap de cumplimiento). Por eso la
 * acción es fija por entidad y el server la fuerza a este valor.
 */
export const IMPLEMENTED_ACTION: Record<Entity, Action> = {
  messages: 'hard_delete',
  conversations: 'soft_delete',
  contacts_inactive: 'soft_delete',
  pii_access_log: 'hard_delete',
}

const ACTION_LABEL_ES: Record<Action, string> = {
  hard_delete: 'Eliminación definitiva',
  soft_delete: 'Archivado (reversible)',
  archive: 'Archivado',
  anonymize: 'Anonimización',
}

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
  saveAction: (fd: FormData) => Promise<ActionResult>
  deleteAction: (fd: FormData) => Promise<ActionResult>
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
      try {
        const r = await saveAction(fd)
        if (r.ok) toast.success(r.message || 'Plazo de retención guardado.')
        else toast.error(r.error || 'No se pudo guardar el plazo.')
      } catch {
        toast.error('Error inesperado al guardar el plazo.')
      } finally { setBusyEntity(null) }
    })
  }

  const handleDelete = async (entity: Entity, id: string) => {
    if (!(await confirmar({
      title: `¿Restaurar el plazo predeterminado de ${entityLabels[entity].label}?`,
      description: 'La retención de tu cuenta volverá a regirse por el plazo global.',
      confirmLabel: 'Restaurar predeterminado',
      destructive: true,
    }))) return
    setBusyEntity(entity)
    const fd = new FormData()
    fd.set('id', id)
    startTransition(async () => {
      try {
        const r = await deleteAction(fd)
        if (r.ok) toast.success(r.message || 'Restaurado al plazo predeterminado.')
        else toast.error(r.error || 'No se pudo restaurar el plazo.')
      } catch {
        toast.error('Error inesperado al restaurar el plazo.')
      } finally { setBusyEntity(null) }
    })
  }

  return (
    <div className="space-y-3">
      {ALL_ENTITIES.map(entity => {
        const def = defaultsByEntity.get(entity)
        const ov = overridesByEntity.get(entity)
        const labels = entityLabels[entity]
        const effectiveTtl = ov?.ttl_days ?? def?.ttl_days ?? 0
        const action = IMPLEMENTED_ACTION[entity]
        const isOverridden = !!ov
        const busy = busyEntity === entity && isPending
        return (
          <div
            key={entity}
            className={`rounded-xl border px-4 py-3 ${
              isOverridden ? 'border-info-border bg-info-bg' : 'border-border bg-card/30'
            }`}
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="font-semibold text-foreground flex items-center gap-2">
                  {labels.label}
                  {isOverridden && (
                    <span className="text-xs font-normal text-info-fg bg-info-bg px-1.5 py-0.5 rounded">
                      Plazo personalizado
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">{labels.description}</p>
                <p className="text-xs text-muted-foreground/70 mt-0.5">
                  Al cumplirse el plazo: <strong>{ACTION_LABEL_ES[action]}</strong>
                  {' · '}Predeterminado global: <strong>{def?.ttl_days ?? '?'} días</strong>
                  {isOverridden && (
                    <> → Tu cuenta: <strong className="text-info-fg">{effectiveTtl} días</strong></>
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
                  <Label className="text-xs text-muted-foreground">Conservar durante (días, 1-3650)</Label>
                  <Input
                    type="number"
                    name="ttl_days"
                    min={1}
                    max={3650}
                    defaultValue={effectiveTtl}
                    className="h-8 w-32 text-sm"
                    required
                  />
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
                    : <><Save className="h-3 w-3" />Guardar plazo</>}
                </Button>
                {isOverridden && ov && (
                  <Button
                    type="button"
                    onClick={() => void handleDelete(entity, ov.id)}
                    disabled={busy}
                    size="sm"
                    variant="ghost"
                    className="h-8 text-xs text-warning-fg hover:bg-warning-bg gap-1.5"
                  >
                    <Trash2 className="h-3 w-3" />
                    Volver al predeterminado
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
