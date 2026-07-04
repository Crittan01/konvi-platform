'use client'

/**
 * Notas privadas del operador per conversación.
 *
 * Refactor 2026-05-29 paso post-10/10 — P0-1 del backlog.
 *
 * State + CRUD encapsulado. Recibe `conversationId` y monta su UI completa:
 *   - Lista de notas (pinned primero).
 *   - Input para nueva nota con pin toggle.
 *   - Pin/unpin existente.
 *   - Edit inline del contenido (PATCH content — backend rev. conversations.py:1051).
 *   - Soft-delete con confirm.
 *
 * Visibilidad: solo se monta cuando hay conversación seleccionada (decisión
 * del padre `context-panel`).
 */
import { useCallback, useEffect, useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import {
  AlertCircle, BadgeCheck, Check, Loader2, Pencil, Pin, PinOff, Plus, Trash2, X,
} from 'lucide-react'
import type { ConversationNote } from '../_lib/types'
import { timeAgo } from '../_lib/format'
import { useConfirm } from '@/components/ui/confirm-dialog'

interface Props {
  conversationId: string
}

export function ConversationNotes({ conversationId }: Props) {
  const confirmar = useConfirm()
  const [notes, setNotes] = useState<ConversationNote[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newText, setNewText] = useState('')
  const [newPinned, setNewPinned] = useState(false)
  const [creating, setCreating] = useState(false)
  // Edición inline del contenido de una nota existente.
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)

  const fetchNotes = useCallback(async () => {
    setError(null)
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      const token = session?.access_token
      if (!token) { setError('Sesión expirada'); return }

      const res = await fetch(`/api/conversations/${conversationId}/notes`, {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      if (!res.ok) { setError('No se pudieron cargar las notas'); return }
      const data = await res.json()
      setNotes(Array.isArray(data) ? data : [])
    } catch {
      setError('Error de red al cargar notas')
    } finally {
      setLoading(false)
    }
  }, [conversationId])

  useEffect(() => {
    setLoading(true)
    fetchNotes()
  }, [fetchNotes])

  const onCreate = async () => {
    const text = newText.trim()
    if (!text) return
    if (text.length > 2000) { setError('Máximo 2000 caracteres'); return }
    setCreating(true)
    setError(null)
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      const token = session?.access_token
      if (!token) { setError('Sesión expirada'); return }

      const res = await fetch(`/api/conversations/${conversationId}/notes`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ content: text, is_pinned: newPinned }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.detail || 'Error al crear nota'); return }
      setNotes(prev => sortNotes([data, ...prev]))
      setNewText('')
      setNewPinned(false)
    } catch {
      setError('Error de red al crear nota')
    } finally {
      setCreating(false)
    }
  }

  const onTogglePin = async (note: ConversationNote) => {
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      const token = session?.access_token
      if (!token) return

      const next = !note.is_pinned
      // Optimistic update.
      setNotes(prev => sortNotes(prev.map(n =>
        n.id === note.id ? { ...n, is_pinned: next } : n,
      )))
      const res = await fetch(
        `/api/conversations/${conversationId}/notes/${note.id}`,
        {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({ is_pinned: next }),
        },
      )
      if (!res.ok) {
        // Rollback.
        setNotes(prev => sortNotes(prev.map(n =>
          n.id === note.id ? { ...n, is_pinned: note.is_pinned } : n,
        )))
        setError('No se pudo cambiar el pin')
      }
    } catch {
      setError('Error de red')
    }
  }

  const startEdit = (note: ConversationNote) => {
    setEditingId(note.id)
    setEditText(note.content)
    setError(null)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditText('')
  }

  const onSaveEdit = async (note: ConversationNote) => {
    const text = editText.trim()
    if (!text) { setError('La nota no puede quedar vacía'); return }
    if (text.length > 2000) { setError('Máximo 2000 caracteres'); return }
    if (text === note.content) { cancelEdit(); return }
    setSavingEdit(true)
    setError(null)
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      const token = session?.access_token
      if (!token) { setError('Sesión expirada'); return }

      const res = await fetch(
        `/api/conversations/${conversationId}/notes/${note.id}`,
        {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({ content: text }),
        },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.detail || 'No se pudo editar la nota'); return }
      // El backend devuelve la nota actualizada (con updated_at fresco).
      setNotes(prev => sortNotes(prev.map(n =>
        n.id === note.id
          ? { ...n, ...data, content: data.content ?? text }
          : n,
      )))
      cancelEdit()
    } catch {
      setError('Error de red al editar la nota')
    } finally {
      setSavingEdit(false)
    }
  }

  const onDelete = async (note: ConversationNote) => {
    if (!(await confirmar({
      title: '¿Eliminar esta nota?',
      description: 'Solo el autor o un owner/manager pueden hacerlo. La nota queda en el audit trail.',
      confirmLabel: 'Eliminar', destructive: true,
    }))) return
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      const token = session?.access_token
      if (!token) return

      const res = await fetch(
        `/api/conversations/${conversationId}/notes/${note.id}`,
        {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` },
        },
      )
      if (res.status === 204) {
        setNotes(prev => prev.filter(n => n.id !== note.id))
      } else {
        const data = await res.json().catch(() => ({}))
        setError(data.detail || 'No se pudo eliminar la nota')
      }
    } catch {
      setError('Error de red al eliminar')
    }
  }

  return (
    <section className="p-4 border-b border-border bg-amber-500/5">
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs font-semibold text-amber-700 uppercase tracking-wider flex items-center gap-1.5">
          <Pin className="h-3 w-3" /> Notas privadas del operador
        </p>
        {notes.length > 0 && (
          <span className="text-[10px] text-muted-foreground">{notes.length}</span>
        )}
      </div>

      {/* Editor nota nueva */}
      <div className="space-y-1.5 mb-3">
        <textarea
          value={newText}
          onChange={e => setNewText(e.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Agregar nota interna (no se envía al cliente)..."
          className="w-full resize-none px-2 py-1.5 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-1 focus:ring-amber-500 placeholder:text-muted-foreground"
        />
        <div className="flex items-center justify-between">
          <label className="text-[10px] text-muted-foreground flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={newPinned}
              onChange={e => setNewPinned(e.target.checked)}
              className="h-3 w-3 accent-amber-600"
            />
            <Pin className="h-3 w-3" /> Fijar arriba
          </label>
          <button
            onClick={onCreate}
            disabled={creating || !newText.trim()}
            className="inline-flex items-center gap-1 h-6 px-2 text-[11px] font-medium rounded-md bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 transition-colors"
          >
            {creating
              ? <><Loader2 className="h-3 w-3 animate-spin" /> Guardando</>
              : <><Plus className="h-3 w-3" /> Agregar</>}
          </button>
        </div>
        {newText.length > 0 && (
          <p className="text-[10px] text-muted-foreground text-right">
            {newText.length}/2000
          </p>
        )}
      </div>

      {error && (
        <p className="text-[11px] text-red-700 mb-2 flex items-center gap-1">
          <AlertCircle className="h-3 w-3" /> {error}
        </p>
      )}

      {/* Lista de notas */}
      {loading ? (
        <div className="space-y-1">
          {[1, 2].map(i => <div key={i} className="h-12 rounded-lg bg-border/30 animate-pulse" />)}
        </div>
      ) : notes.length === 0 ? (
        <p className="text-[11px] text-muted-foreground italic">
          Sin notas todavía. Las notas quedan visibles para todo el equipo del tenant.
        </p>
      ) : (
        <div className="space-y-1.5">
          {notes.map(note => (
            <div
              key={note.id}
              className={`p-2 rounded-lg border text-xs ${
                note.is_pinned
                  ? 'bg-amber-100/40 border-amber-700/40'
                  : 'bg-background border-border'
              }`}
            >
              {editingId === note.id ? (
                <div className="space-y-1.5 mb-1.5">
                  <textarea
                    value={editText}
                    onChange={e => setEditText(e.target.value)}
                    rows={2}
                    maxLength={2000}
                    autoFocus
                    className="w-full resize-none px-2 py-1.5 text-xs rounded-lg border border-amber-700/40 bg-background focus:outline-none focus:ring-1 focus:ring-amber-500"
                  />
                  <div className="flex items-center justify-end gap-1">
                    <button
                      onClick={cancelEdit}
                      disabled={savingEdit}
                      className="inline-flex items-center gap-1 h-6 px-2 text-[11px] rounded-md border border-border hover:bg-muted/40 disabled:opacity-50"
                    >
                      <X className="h-3 w-3" /> Cancelar
                    </button>
                    <button
                      onClick={() => onSaveEdit(note)}
                      disabled={savingEdit || !editText.trim()}
                      className="inline-flex items-center gap-1 h-6 px-2 text-[11px] font-medium rounded-md bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50"
                    >
                      {savingEdit
                        ? <><Loader2 className="h-3 w-3 animate-spin" /> Guardando</>
                        : <><Check className="h-3 w-3" /> Guardar</>}
                    </button>
                  </div>
                </div>
              ) : (
                <p className="whitespace-pre-wrap break-words mb-1.5">{note.content}</p>
              )}
              <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  {note.is_pinned && <BadgeCheck className="h-2.5 w-2.5 text-amber-700" />}
                  {timeAgo(note.created_at)}
                  {note.updated_at !== note.created_at && (
                    <span className="italic">(editada)</span>
                  )}
                </span>
                {editingId !== note.id && (
                  <div className="flex items-center gap-0.5">
                    <button
                      onClick={() => startEdit(note)}
                      title="Editar nota"
                      aria-label="Editar nota"
                      className="h-5 w-5 inline-flex items-center justify-center rounded hover:bg-muted/40"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                    <button
                      onClick={() => onTogglePin(note)}
                      title={note.is_pinned ? 'Quitar pin' : 'Fijar arriba'}
                      aria-label={note.is_pinned ? 'Quitar pin' : 'Fijar arriba'}
                      className="h-5 w-5 inline-flex items-center justify-center rounded hover:bg-muted/40"
                    >
                      {note.is_pinned
                        ? <PinOff className="h-3 w-3" />
                        : <Pin className="h-3 w-3" />}
                    </button>
                    <button
                      onClick={() => onDelete(note)}
                      title="Eliminar nota"
                      aria-label="Eliminar nota"
                      className="h-5 w-5 inline-flex items-center justify-center rounded hover:bg-red-500/10 hover:text-red-700"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

// Orden canónico: pinned primero, luego created_at desc.
function sortNotes(notes: ConversationNote[]): ConversationNote[] {
  return [...notes].sort((a, b) => {
    if (a.is_pinned !== b.is_pinned) return a.is_pinned ? -1 : 1
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  })
}
