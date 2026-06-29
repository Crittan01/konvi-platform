'use client'

import { useState, useTransition } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Plus, Pencil, Trash2, Check, X, Tag, Loader2 } from 'lucide-react'
import { createCategory, updateCategory, deleteCategory } from '../actions'

export type CategoryRow = {
  id: string
  name: string
  display_label: string
  sort_order: number
  product_count: number
}

/** Clave normalizada (única por tenant) derivada del label: sin acentos, minúsculas, _ por espacios. */
function slugify(s: string): string {
  return s
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

export default function CategoriesManager({
  categories,
  canWrite,
}: {
  categories: CategoryRow[]
  canWrite: boolean
}) {
  const [pending, startTransition] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const [newLabel, setNewLabel] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editLabel, setEditLabel] = useState('')

  function handleCreate() {
    const label = newLabel.trim()
    if (!label) return
    const name = slugify(label)
    if (!name) { setError('El nombre de categoría no es válido.'); return }
    setError(null)
    startTransition(async () => {
      const res = await createCategory({ name, display_label: label, sort_order: categories.length })
      if (res.error) setError(res.error)
      else setNewLabel('')
    })
  }

  function handleSaveEdit(id: string) {
    const label = editLabel.trim()
    if (!label) return
    setError(null)
    startTransition(async () => {
      const res = await updateCategory(id, { display_label: label })
      if (res.error) setError(res.error)
      else setEditingId(null)
    })
  }

  function handleDelete(id: string, count: number) {
    const msg = count > 0
      ? `Esta categoría tiene ${count} producto(s). Si la eliminas, esos productos quedarán SIN categoría (el bot caería a la heurística por título). ¿Continuar?`
      : '¿Eliminar esta categoría?'
    if (!confirm(msg)) return
    setError(null)
    startTransition(async () => {
      const res = await deleteCategory(id)
      if (res.error) setError(res.error)
    })
  }

  return (
    <div className="space-y-5 max-w-3xl">
      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Tag className="h-5 w-5 text-primary" /> Categorías
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Las categorías con las que el bot presenta tu catálogo al cliente. {categories.length} categoría(s).
        </p>
      </div>

      {/* Crear */}
      {canWrite && (
        <div className="rounded-xl border border-border bg-card p-4 space-y-2">
          <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
            Nueva categoría
          </label>
          <div className="flex items-center gap-2">
            <Input
              value={newLabel}
              onChange={e => setNewLabel(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleCreate() }}
              placeholder="Ej. Aceites Esenciales"
              maxLength={120}
              className="h-9"
              disabled={pending}
            />
            <Button onClick={handleCreate} size="sm" className="h-9 gap-1.5 shrink-0" disabled={pending || !newLabel.trim()}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Crear
            </Button>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-700/40 bg-red-700/10 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Lista */}
      <div className="rounded-xl border border-border bg-card divide-y divide-border">
        {categories.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted-foreground text-center">
            Aún no hay categorías. {canWrite ? 'Crea la primera arriba.' : ''}
          </p>
        )}
        {categories.map(c => (
          <div key={c.id} className="flex items-center gap-3 px-4 py-3">
            {editingId === c.id ? (
              <>
                <Input
                  value={editLabel}
                  onChange={e => setEditLabel(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') handleSaveEdit(c.id)
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  maxLength={120}
                  autoFocus
                  className="h-8 flex-1"
                  disabled={pending}
                />
                <button
                  onClick={() => handleSaveEdit(c.id)}
                  disabled={pending}
                  className="h-8 w-8 inline-flex items-center justify-center rounded-md text-green-700 hover:bg-green-700/10"
                  aria-label="Guardar"
                >
                  <Check className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setEditingId(null)}
                  className="h-8 w-8 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                  aria-label="Cancelar"
                >
                  <X className="h-4 w-4" />
                </button>
              </>
            ) : (
              <>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground truncate">{c.display_label}</p>
                  <p className="text-[10px] text-muted-foreground/70 font-mono">{c.name}</p>
                </div>
                <span className="text-xs text-muted-foreground tabular-nums shrink-0">
                  {c.product_count} producto{c.product_count === 1 ? '' : 's'}
                </span>
                {canWrite && (
                  <>
                    <button
                      onClick={() => { setEditingId(c.id); setEditLabel(c.display_label) }}
                      className="h-8 w-8 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"
                      aria-label="Editar"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => handleDelete(c.id, c.product_count)}
                      disabled={pending}
                      className="h-8 w-8 inline-flex items-center justify-center rounded-md text-red-700 hover:bg-red-700/10"
                      aria-label="Eliminar"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </>
                )}
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
