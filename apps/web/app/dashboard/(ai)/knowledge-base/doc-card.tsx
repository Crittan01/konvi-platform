'use client'

import { useEffect, useState, useTransition } from 'react'
import { toast } from 'sonner'
import { SubmitButton } from '@/components/ui/submit-button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2, CheckCircle2 } from 'lucide-react'
import { useConfirm } from '@/components/ui/confirm-dialog'
import ActionResultForm, { useActionResultStatus } from '@/components/action-result-form'
import type { ActionResult } from '@/lib/action-result'
import { EmbedRetryButton } from './embed-retry-button'
import { KB_CATEGORIES, categoryBadgeClass, categoryLabel } from './categories'

type KbDoc = {
  id: string
  title: string
  content: string
  category: string
  is_active: boolean
  updated_at: string
  has_embedding: boolean
}

interface Props {
  doc: KbDoc
  canWrite: boolean
  updateDocument:      (fd: FormData) => Promise<ActionResult>
  activateDocument:    (fd: FormData) => Promise<ActionResult>
  reindexDocument:     (fd: FormData) => Promise<ActionResult>
  desactivateDocument: (fd: FormData) => Promise<ActionResult>
  deleteDocument:      (fd: FormData) => Promise<ActionResult>
}

/** Cierra el editor SOLO cuando la server action confirmó ok (no en fallo). */
function CloseOnSuccess({ onOk }: { onOk: () => void }) {
  const status = useActionResultStatus()
  useEffect(() => {
    if (status === 'ok') onOk()
  }, [status, onOk])
  return null
}

function DeleteButton({
  docId,
  deleteDocument,
}: {
  docId: string
  deleteDocument: (fd: FormData) => Promise<ActionResult>
}) {
  const confirm = useConfirm()
  const [isPending, startTransition] = useTransition()

  async function handleClick() {
    const okToDelete = await confirm({
      title: 'Eliminar documento',
      description:
        'El documento quedará inactivo, liberará un cupo y perderá su preparación para la IA. Podrás reactivarlo, pero deberás prepararlo de nuevo.',
      confirmLabel: 'Eliminar',
      cancelLabel: 'Cancelar',
      destructive: true,
    })
    if (!okToDelete) return
    const fd = new FormData()
    fd.append('doc_id', docId)
    startTransition(async () => {
      const r = await deleteDocument(fd)
      if (r.ok) toast.success('Documento eliminado')
      else toast.error(r.error || 'No se pudo eliminar el documento.')
    })
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isPending}
      className="inline-flex items-center justify-center gap-1.5 text-destructive hover:text-destructive hover:bg-destructive/10 text-xs h-7 w-full rounded-md transition-colors disabled:opacity-60 disabled:cursor-wait"
    >
      {isPending
        ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Eliminando...</>
        : 'Eliminar'}
    </button>
  )
}

export function DocCard({
  doc,
  canWrite,
  updateDocument,
  activateDocument,
  reindexDocument,
  desactivateDocument,
  deleteDocument,
}: Props) {
  const [editing, setEditing] = useState(false)
  const catLabel = categoryLabel(doc.category)
  const titleId = `kb-title-${doc.id}`
  const catId = `kb-cat-${doc.id}`
  const contentId = `kb-content-${doc.id}`

  if (editing && canWrite) {
    return (
      <div className="rounded-xl border border-primary/40 bg-primary/5 p-4">
        <ActionResultForm
          action={updateDocument}
          successMessage="Documento guardado"
          className="space-y-3"
        >
          <CloseOnSuccess onOk={() => setEditing(false)} />
          <input type="hidden" name="doc_id" value={doc.id} />
          <div className="space-y-1">
            <Label htmlFor={titleId} className="text-xs">Título</Label>
            <Input id={titleId} name="title" defaultValue={doc.title} required maxLength={120} className="h-8 text-sm" />
          </div>
          <div className="space-y-1">
            <Label htmlFor={catId} className="text-xs">Categoría</Label>
            <select id={catId} name="category" defaultValue={doc.category}
              className="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-sm focus:outline-hidden focus:ring-1 focus:ring-primary">
              {KB_CATEGORIES.map(c => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor={contentId} className="text-xs">Contenido</Label>
            <textarea id={contentId} name="content" defaultValue={doc.content} required maxLength={3000} rows={6}
              className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm resize-none focus:outline-hidden focus:ring-1 focus:ring-primary" />
          </div>
          <div className="flex gap-2">
            <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado" className="h-8 text-xs">
              Guardar cambios
            </SubmitButton>
            <button type="button" onClick={() => setEditing(false)}
              className="h-8 px-3 text-xs rounded-md border border-input bg-background hover:bg-accent transition-colors">
              Cancelar
            </button>
          </div>
        </ActionResultForm>
      </div>
    )
  }

  return (
    <div className={`rounded-xl border bg-card p-4 transition-all hover:shadow-xs ${
      doc.is_active ? 'border-border' : 'border-border/50 opacity-60'
    }`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full ${categoryBadgeClass(doc.category)}`}>
              {catLabel}
            </span>
            {/* Terminología humana: sin "embedding" ni "RAG" */}
            {doc.is_active && doc.has_embedding ? (
              <span className="inline-flex items-center gap-0.5 text-[10px] font-medium text-emerald-700 border border-emerald-700/30 bg-emerald-500/10 rounded-full px-1.5 py-0.5">
                <CheckCircle2 className="h-2.5 w-2.5" /> Listo para IA
              </span>
            ) : doc.is_active && !doc.has_embedding ? (
              canWrite
                ? <EmbedRetryButton docId={doc.id} reindexDocument={reindexDocument} />
                : <span className="text-[10px] text-amber-700 border border-amber-700/30 rounded-full px-1.5 py-0.5">Pendiente de preparar</span>
            ) : (
              <span className="text-[11px] text-muted-foreground border border-border rounded-full px-2 py-0.5">
                Inactivo
              </span>
            )}
          </div>
          <p className="font-medium text-sm">{doc.title}</p>
          <p className="text-xs text-muted-foreground mt-1 line-clamp-2 leading-relaxed">{doc.content}</p>
          <p className="text-[11px] text-muted-foreground/70 mt-2">
            Actualizado: {new Date(doc.updated_at).toLocaleDateString('es-CO', { timeZone: 'America/Bogota', day: '2-digit', month: 'short', year: 'numeric' })}
          </p>
        </div>

        {canWrite && (
          <div className="flex flex-col gap-1.5 shrink-0">
            {/* Editar inline */}
            <button onClick={() => setEditing(true)}
              className="inline-flex items-center justify-center h-7 px-2.5 rounded-md border border-input bg-background text-xs font-medium hover:bg-accent hover:text-accent-foreground transition-colors">
              Editar
            </button>

            {/* Activar — el bot vuelve a usar este doc (conserva la preparación previa) */}
            {!doc.is_active && (
              <ActionResultForm action={activateDocument} successMessage="Documento activado">
                <input type="hidden" name="doc_id" value={doc.id} />
                <SubmitButton size="sm" variant="outline"
                  pendingText="Activando..."
                  savedText="Activado"
                  className="text-xs h-7 w-full text-emerald-700 border-emerald-700/30 hover:bg-emerald-500/10">
                  Activar
                </SubmitButton>
              </ActionResultForm>
            )}

            {/* Desactivar — el bot deja de usar este doc (la preparación se conserva) */}
            {doc.is_active && (
              <ActionResultForm action={desactivateDocument} successMessage="Documento desactivado">
                <input type="hidden" name="doc_id" value={doc.id} />
                <SubmitButton size="sm" variant="outline"
                  pendingText="..." savedText="Desactivado"
                  className="text-xs h-7 w-full">
                  Desactivar
                </SubmitButton>
              </ActionResultForm>
            )}

            {/* Eliminar permanentemente — con confirmación */}
            <DeleteButton docId={doc.id} deleteDocument={deleteDocument} />
          </div>
        )}
      </div>
    </div>
  )
}
