'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Plus, Trash2, Pencil, X, Loader2, Check } from 'lucide-react'
import { createAttributeDef, updateAttributeDef, deleteAttributeDef, type AttributeDefInput } from '../actions'
import { useConfirm } from '@/components/ui/confirm-dialog'
import { parseAllowedValues } from '../_lib/category-forms'

// ADR-0029 D3 — editor del CONTRATO de atributos de UNA categoría (hoja). El bot cita estos atributos
// como HECHOS (SET membership); definirlos aquí guía el alta y habilita la validación HARD server-side.

export type AttributeDef = {
  id: string
  product_category_id: string
  label: string
  type: 'select' | 'metric' | 'number' | 'boolean' | 'text'
  unit: string | null
  is_variant_axis: boolean
  allowed_values: (string | number)[]
  sort_order: number
}

const TYPES: AttributeDef['type'][] = ['select', 'metric', 'number', 'boolean', 'text']
const TYPE_HINT: Record<AttributeDef['type'], string> = {
  select: 'Lista cerrada de opciones (ej. Aroma)',
  metric: 'Número con unidad + opciones (ej. Volumen ml)',
  number: 'Número libre (ej. FPS)',
  boolean: 'Sí / No (ej. 100% puro)',
  text: 'Texto libre (ej. Ingrediente principal)',
}

const EMPTY = { label: '', type: 'select' as AttributeDef['type'], unit: '', is_variant_axis: false, allowedText: '' }

export function AttributeContractEditor({
  categoryId, categoryLabel, defs, open, onOpenChange,
}: {
  categoryId: string
  categoryLabel: string
  defs: AttributeDef[]
  open: boolean
  onOpenChange: (o: boolean) => void
}) {
  const router = useRouter()
  const confirmar = useConfirm()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)  // null = modo alta
  const [form, setForm] = useState(EMPTY)

  const resetForm = () => { setForm(EMPTY); setEditingId(null); setError(null) }

  const startEdit = (d: AttributeDef) => {
    setEditingId(d.id)
    setError(null)
    setForm({
      label: d.label,
      type: d.type,
      unit: d.unit ?? '',
      is_variant_axis: d.is_variant_axis,
      allowedText: (d.allowed_values ?? []).join(', '),
    })
  }

  const handleSubmit = async () => {
    const label = form.label.trim()
    if (!label) { setError('El nombre del atributo es obligatorio'); return }
    setPending(true); setError(null)
    const payload: Omit<AttributeDefInput, 'product_category_id'> = {
      label,
      type: form.type,
      unit: form.unit.trim() || null,
      is_variant_axis: form.is_variant_axis,
      allowed_values: parseAllowedValues(form.type, form.allowedText),
      sort_order: editingId ? undefined : defs.length,
    }
    const res = editingId
      ? await updateAttributeDef(editingId, payload)
      : await createAttributeDef({ ...payload, product_category_id: categoryId })
    setPending(false)
    if (res.error) { setError(res.error); return }
    resetForm(); router.refresh()
  }

  const handleDelete = async (id: string) => {
    if (!(await confirmar({
      title: '¿Eliminar este atributo del contrato?',
      description: 'Los valores ya guardados en productos no se tocan.',
      confirmLabel: 'Eliminar', destructive: true,
    }))) return
    setPending(true); setError(null)
    const res = await deleteAttributeDef(id)
    setPending(false)
    if (res.error) { setError(res.error); return }
    if (editingId === id) resetForm()
    router.refresh()
  }

  const needsAllowed = form.type === 'select' || form.type === 'metric'

  return (
    <Dialog open={open} onOpenChange={o => { if (!o) resetForm(); onOpenChange(o) }}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Atributos de <span className="text-primary">{categoryLabel}</span>
          </DialogTitle>
        </DialogHeader>

        <p className="text-xs text-muted-foreground -mt-1">
          Definen qué datos estructurados describen los productos de esta categoría. El bot los cita como
          hechos y el alta se guía por ellos; los de tipo <b>lista</b> o <b>número con unidad</b> se validan
          contra sus opciones (el sistema rechaza valores fuera de contrato).
        </p>

        {/* Lista de atributos */}
        <div className="rounded-lg border border-border divide-y divide-border/60">
          {defs.length === 0 && (
            <p className="px-3 py-4 text-sm text-muted-foreground text-center">
              Sin atributos aún. Agrega el primero abajo.
            </p>
          )}
          {defs.map(d => (
            <div key={d.id} className="flex items-center gap-2 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground truncate">
                  {d.label}
                  {d.is_variant_axis && <span className="ml-2 text-[10px] uppercase text-primary/70">variante</span>}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  {d.type}{d.unit ? ` · ${d.unit}` : ''}
                  {(d.allowed_values?.length ?? 0) > 0 && ` · ${d.allowed_values.length} opciones`}
                </p>
              </div>
              <button onClick={() => startEdit(d)} disabled={pending}
                className="h-7 w-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted" aria-label="Editar">
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button onClick={() => handleDelete(d.id)} disabled={pending}
                className="h-7 w-7 inline-flex items-center justify-center rounded-md text-red-700 hover:bg-red-700/10" aria-label="Eliminar">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>

        {error && (
          <div className="rounded-lg border border-red-700/40 bg-red-700/10 px-3 py-2 text-sm text-red-700">{error}</div>
        )}

        {/* Formulario alta/edición */}
        <div className="rounded-lg border border-border bg-card p-3 space-y-3">
          <div className="flex items-center justify-between">
            <Label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide">
              {editingId ? 'Editar atributo' : 'Nuevo atributo'}
            </Label>
            {editingId && (
              <button onClick={resetForm} className="text-[11px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
                <X className="h-3 w-3" /> cancelar edición
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div>
              <Label htmlFor="attr-label" className="text-[10px] uppercase text-muted-foreground">Nombre *</Label>
              <Input id="attr-label" value={form.label} onChange={e => setForm({ ...form, label: e.target.value })}
                placeholder="Ej. Ingrediente activo" className="h-8 mt-1" disabled={pending} />
            </div>
            <div>
              <Label htmlFor="attr-type" className="text-[10px] uppercase text-muted-foreground">Tipo</Label>
              <select id="attr-type" aria-label="Tipo de atributo"
                value={form.type} onChange={e => setForm({ ...form, type: e.target.value as AttributeDef['type'] })}
                disabled={pending}
                className="w-full h-8 mt-1 rounded-md border border-input bg-background text-sm px-2 text-foreground">
                {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>
          <p className="text-[11px] text-muted-foreground">{TYPE_HINT[form.type]}</p>

          {(form.type === 'metric') && (
            <div>
              <Label htmlFor="attr-unit" className="text-[10px] uppercase text-muted-foreground">Unidad</Label>
              <Input id="attr-unit" value={form.unit} onChange={e => setForm({ ...form, unit: e.target.value })}
                placeholder="Ej. ml, g, h" className="h-8 mt-1 w-32" disabled={pending} />
            </div>
          )}

          {needsAllowed && (
            <div>
              <Label htmlFor="attr-allowed" className="text-[10px] uppercase text-muted-foreground">Opciones (separadas por coma)</Label>
              <Input id="attr-allowed" value={form.allowedText} onChange={e => setForm({ ...form, allowedText: e.target.value })}
                placeholder={form.type === 'metric' ? 'Ej. 5, 10, 30, 50' : 'Ej. Lavanda, Menta, Coco'}
                className="h-8 mt-1" disabled={pending} />
              <p className="text-[10px] text-muted-foreground/70 mt-1">
                El sistema rechazará valores fuera de esta lista (anti-alucinación).
              </p>
            </div>
          )}

          <label htmlFor="attr-variant" className="flex items-center gap-2 text-xs text-foreground/80 cursor-pointer">
            <input id="attr-variant" type="checkbox" checked={form.is_variant_axis}
              onChange={e => setForm({ ...form, is_variant_axis: e.target.checked })} disabled={pending} />
            Genera variantes (SKU) — ej. cada Volumen/Aroma es una variante distinta del mismo producto
          </label>

          <div className="flex justify-end">
            <Button onClick={handleSubmit} size="sm" className="h-8 gap-1.5" disabled={pending || !form.label.trim()}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : editingId ? <Check className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
              {editingId ? 'Guardar' : 'Agregar'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
