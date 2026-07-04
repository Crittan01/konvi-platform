'use client'

import { useState, useTransition } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Plus, Pencil, Trash2, Check, X, Tag, Loader2, FolderTree, CornerDownRight, SlidersHorizontal } from 'lucide-react'
import { createCategory, updateCategory, deleteCategory } from '../actions'
import { AttributeContractEditor, type AttributeDef } from './attribute-contract-editor'
import { useConfirm } from '@/components/ui/confirm-dialog'

export type { AttributeDef }

export type CategoryRow = {
  id: string
  name: string
  display_label: string
  sort_order: number
  parent_id: string | null
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

const ROOT = '__root__'  // sentinel de <select> = sin padre (categoría raíz / vertical)

export default function CategoriesManager({
  categories,
  attributeDefs,
  canWrite,
}: {
  categories: CategoryRow[]
  attributeDefs: AttributeDef[]
  canWrite: boolean
}) {
  const confirmar = useConfirm()
  const [pending, startTransition] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const [newLabel, setNewLabel] = useState('')
  const [newParent, setNewParent] = useState<string>(ROOT)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editLabel, setEditLabel] = useState('')
  const [editParent, setEditParent] = useState<string>(ROOT)
  const [editorCat, setEditorCat] = useState<CategoryRow | null>(null)   // categoría cuyo contrato de atributos se edita

  // Raíces = candidatos a padre (la API exige que el padre sea raíz → jerarquía de 2 niveles).
  const roots = categories.filter(c => !c.parent_id)
  const childrenOf = (id: string) => categories.filter(c => c.parent_id === id)
  const hasChildren = (id: string) => categories.some(c => c.parent_id === id)
  const defsFor = (id: string) => attributeDefs.filter(d => d.product_category_id === id)

  function handleCreate() {
    const label = newLabel.trim()
    if (!label) return
    const name = slugify(label)
    if (!name) { setError('El nombre de categoría no es válido.'); return }
    setError(null)
    const parent_id = newParent === ROOT ? null : newParent
    startTransition(async () => {
      const res = await createCategory({ name, display_label: label, sort_order: categories.length, parent_id })
      if (res.error) setError(res.error)
      else { setNewLabel(''); setNewParent(ROOT) }
    })
  }

  function startEdit(c: CategoryRow) {
    setEditingId(c.id)
    setEditLabel(c.display_label)
    setEditParent(c.parent_id ?? ROOT)
  }

  function handleSaveEdit(id: string) {
    const label = editLabel.trim()
    if (!label) return
    setError(null)
    const parent_id = editParent === ROOT ? null : editParent
    startTransition(async () => {
      const res = await updateCategory(id, { display_label: label, parent_id })
      if (res.error) setError(res.error)
      else setEditingId(null)
    })
  }

  async function handleDelete(id: string, count: number) {
    const kids = hasChildren(id)
    const description = kids
      ? 'Es una VERTICAL con subcategorías. Si la eliminas, sus subcategorías quedarán como raíz (no se borran).'
      : count > 0
        ? `Tiene ${count} producto(s). Si la eliminas, esos productos quedarán SIN categoría (el bot caería a la heurística por título).`
        : undefined
    if (!(await confirmar({
      title: '¿Eliminar esta categoría?',
      description, confirmLabel: 'Eliminar', destructive: true,
    }))) return
    setError(null)
    startTransition(async () => {
      const res = await deleteCategory(id)
      if (res.error) setError(res.error)
    })
  }

  // Opciones de padre para un <select>; excluye a la propia categoría (no puede ser su padre).
  function parentOptions(excludeId?: string) {
    return roots.filter(r => r.id !== excludeId)
  }

  // Fila de una categoría (raíz o subcategoría). `depth` controla la sangría visual.
  function Row({ c, depth }: { c: CategoryRow; depth: number }) {
    const editing = editingId === c.id
    const isParent = hasChildren(c.id)
    return (
      <div className="flex items-center gap-3 px-4 py-3" style={{ paddingLeft: 16 + depth * 24 }}>
        {editing ? (
          <>
            <div className="flex-1 flex flex-col sm:flex-row gap-2">
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
              {/* Reasignar padre solo si la categoría NO es ya una vertical con hijos (evita 3 niveles). */}
              {!isParent && (
                <select
                  value={editParent}
                  onChange={e => setEditParent(e.target.value)}
                  disabled={pending}
                  className="h-8 rounded-md border border-input bg-background text-sm px-2 text-foreground sm:w-56"
                >
                  <option value={ROOT}>— Raíz (vertical) —</option>
                  {parentOptions(c.id).map(r => (
                    <option key={r.id} value={r.id}>{r.display_label}</option>
                  ))}
                </select>
              )}
            </div>
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
            {depth > 0 && <CornerDownRight className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />}
            {isParent && <FolderTree className="h-3.5 w-3.5 text-primary shrink-0" />}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-foreground truncate">
                {c.display_label}
                {isParent && <span className="ml-2 text-[10px] font-normal text-primary/70 uppercase tracking-wide">vertical</span>}
              </p>
              <p className="text-[10px] text-muted-foreground/70 font-mono">{c.name}</p>
            </div>
            {!isParent && (
              <span className="text-xs text-muted-foreground tabular-nums shrink-0">
                {c.product_count} producto{c.product_count === 1 ? '' : 's'}
              </span>
            )}
            {/* Contrato de atributos: solo en HOJAS (los productos cuelgan de hojas y heredan su contrato). */}
            {!isParent && canWrite && (
              <button
                onClick={() => setEditorCat(c)}
                className="text-[11px] h-7 px-2 inline-flex items-center gap-1 rounded-md border border-primary/30 text-primary hover:bg-primary/10 shrink-0"
                title="Definir los atributos que describen los productos de esta categoría"
              >
                <SlidersHorizontal className="h-3 w-3" /> Atributos ({defsFor(c.id).length})
              </button>
            )}
            {canWrite && (
              <>
                <button
                  onClick={() => startEdit(c)}
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
    )
  }

  return (
    <div className="space-y-5 max-w-3xl">
      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Tag className="h-5 w-5 text-primary" /> Categorías
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Las categorías con las que el bot presenta tu catálogo. Organízalas en 2 niveles: <span className="font-medium text-foreground/80">vertical</span> (ej. Salud y Belleza) › <span className="font-medium text-foreground/80">subcategoría</span> (ej. Aceites Esenciales). Los productos cuelgan de las subcategorías. {categories.length} en total.
        </p>
      </div>

      {/* Crear */}
      {canWrite && (
        <div className="rounded-xl border border-border bg-card p-4 space-y-2">
          <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
            Nueva categoría
          </label>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
            <Input
              value={newLabel}
              onChange={e => setNewLabel(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleCreate() }}
              placeholder="Ej. Aceites Esenciales"
              maxLength={120}
              className="h-9 flex-1"
              disabled={pending}
            />
            <select
              value={newParent}
              onChange={e => setNewParent(e.target.value)}
              disabled={pending}
              className="h-9 rounded-md border border-input bg-background text-sm px-2 text-foreground sm:w-56"
              aria-label="Categoría padre"
            >
              <option value={ROOT}>— Raíz (vertical) —</option>
              {parentOptions().map(r => (
                <option key={r.id} value={r.id}>Dentro de: {r.display_label}</option>
              ))}
            </select>
            <Button onClick={handleCreate} size="sm" className="h-9 gap-1.5 shrink-0" disabled={pending || !newLabel.trim()}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Crear
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Deja «Raíz (vertical)» para crear una agrupación de alto nivel; elige una vertical para crear una subcategoría dentro de ella.
          </p>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-700/40 bg-red-700/10 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Lista en árbol: raíces en orden; bajo cada raíz, sus subcategorías indentadas. */}
      <div className="rounded-xl border border-border bg-card divide-y divide-border">
        {categories.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted-foreground text-center">
            Aún no hay categorías. {canWrite ? 'Crea la primera arriba.' : ''}
          </p>
        )}
        {roots.map(root => (
          <div key={root.id} className="divide-y divide-border/60">
            <Row c={root} depth={0} />
            {childrenOf(root.id).map(child => (
              <Row key={child.id} c={child} depth={1} />
            ))}
          </div>
        ))}
      </div>

      {/* Editor del contrato de atributos de la categoría hoja seleccionada. */}
      {editorCat && (
        <AttributeContractEditor
          categoryId={editorCat.id}
          categoryLabel={editorCat.display_label}
          defs={defsFor(editorCat.id)}
          open={!!editorCat}
          onOpenChange={o => { if (!o) setEditorCat(null) }}
        />
      )}
    </div>
  )
}
