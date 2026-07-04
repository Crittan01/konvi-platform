'use client'

import { useState } from 'react'
import { SubmitButton } from '@/components/ui/submit-button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { CheckCircle2 } from 'lucide-react'
import { EmbedRetryButton } from './embed-retry-button'

type KbDoc = {
  id: string
  title: string
  content: string
  category: string
  is_active: boolean
  updated_at: string
  has_embedding: boolean
}

const CATEGORIES = [
  { value: 'faq',      label: 'FAQ' },
  { value: 'politica', label: 'Políticas' },
  { value: 'negocio',  label: 'Negocio' },
  { value: 'producto', label: 'Productos' },
  { value: 'general',  label: 'General' },
]

const CATEGORY_COLORS: Record<string, string> = {
  faq:      'bg-blue-500/15 text-blue-700 border border-blue-700/30',
  politica: 'bg-purple-500/15 text-purple-400 border border-purple-500/30',
  negocio:  'bg-green-500/15 text-green-700 border border-green-700/30',
  producto: 'bg-orange-500/15 text-orange-700 border border-orange-700/30',
  general:  'bg-muted text-muted-foreground border border-border',
}

interface Props {
  doc: KbDoc
  updateDocument:      (fd: FormData) => Promise<void>
  activateDocument:    (fd: FormData) => Promise<void>
  desactivateDocument: (fd: FormData) => Promise<void>
  deleteDocument:      (fd: FormData) => Promise<void>
}

export function DocCard({ doc, updateDocument, activateDocument, desactivateDocument, deleteDocument }: Props) {
  const [editing, setEditing] = useState(false)
  const catLabel = CATEGORIES.find(c => c.value === doc.category)?.label ?? doc.category

  if (editing) {
    return (
      <div className="rounded-xl border border-primary/40 bg-primary/5 p-4">
        <form
          action={async (fd) => { await updateDocument(fd); setEditing(false) }}
          className="space-y-3"
        >
          <input type="hidden" name="doc_id" value={doc.id} />
          <div className="space-y-1">
            <Label className="text-xs">Título</Label>
            <Input name="title" defaultValue={doc.title} required maxLength={120} className="h-8 text-sm" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Categoría</Label>
            <select name="category" defaultValue={doc.category}
              className="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary">
              {CATEGORIES.map(c => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Contenido</Label>
            <textarea name="content" defaultValue={doc.content} required maxLength={3000} rows={6}
              className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-primary" />
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
        </form>
      </div>
    )
  }

  return (
    <div className={`rounded-xl border bg-card p-4 transition-all hover:shadow-sm ${
      doc.is_active ? 'border-border' : 'border-border/50 opacity-60'
    }`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full ${CATEGORY_COLORS[doc.category] ?? 'bg-muted text-muted-foreground'}`}>
              {catLabel}
            </span>
            {/* Terminología humana: sin "embedding" ni "RAG" */}
            {doc.is_active && doc.has_embedding ? (
              <span className="inline-flex items-center gap-0.5 text-[10px] font-medium text-emerald-700 border border-emerald-700/30 bg-emerald-500/10 rounded-full px-1.5 py-0.5">
                <CheckCircle2 className="h-2.5 w-2.5" /> Listo para IA
              </span>
            ) : doc.is_active && !doc.has_embedding ? (
              <EmbedRetryButton docId={doc.id} activateDocument={activateDocument} />
            ) : (
              <span className="text-[11px] text-muted-foreground border border-border rounded-full px-2 py-0.5">
                Inactivo
              </span>
            )}
          </div>
          <p className="font-medium text-sm">{doc.title}</p>
          <p className="text-xs text-muted-foreground mt-1 line-clamp-2 leading-relaxed">{doc.content}</p>
          <p className="text-[11px] text-muted-foreground/70 mt-2">
            Actualizado: {new Date(doc.updated_at).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })}
          </p>
        </div>

        <div className="flex flex-col gap-1.5 shrink-0">
          {/* Editar inline */}
          <button onClick={() => setEditing(true)}
            className="inline-flex items-center justify-center h-7 px-2.5 rounded-md border border-input bg-background text-xs font-medium hover:bg-accent hover:text-accent-foreground transition-colors">
            Editar
          </button>

          {/* Activar — genera indexación si falta + activa para el bot */}
          {!doc.is_active && (
            <form action={activateDocument}>
              <input type="hidden" name="doc_id" value={doc.id} />
              <SubmitButton size="sm" variant="outline"
                pendingText={doc.has_embedding ? 'Activando...' : 'Indexando...'}
                savedText="Activado"
                className="text-xs h-7 w-full text-emerald-700 border-emerald-700/30 hover:bg-emerald-500/10">
                Activar
              </SubmitButton>
            </form>
          )}

          {/* Desactivar — el bot deja de usar este doc (embedding se conserva) */}
          {doc.is_active && (
            <form action={desactivateDocument}>
              <input type="hidden" name="doc_id" value={doc.id} />
              <SubmitButton size="sm" variant="outline"
                pendingText="..." savedText="Desactivado"
                className="text-xs h-7 w-full">
                Desactivar
              </SubmitButton>
            </form>
          )}

          {/* Eliminar permanentemente */}
          <form action={deleteDocument}>
            <input type="hidden" name="doc_id" value={doc.id} />
            <SubmitButton size="sm" variant="ghost"
              pendingText="Eliminando..." savedText="Eliminado"
              className="text-destructive hover:text-destructive hover:bg-destructive/10 text-xs h-7 w-full">
              Eliminar
            </SubmitButton>
          </form>
        </div>
      </div>
    </div>
  )
}
