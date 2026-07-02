'use client'

/**
 * VariantMatrixGenerator — Genera combinaciones de variantes automáticamente.
 *
 * Flujo:
 *   1. El operador define atributos con sus valores: Color → [Rojo, Azul], Talla → [S, M, L]
 *   2. El sistema genera el producto cartesiano: 2 × 3 = 6 variantes
 *   3. El operador llena precio y stock por combinación
 *   4. "Crear variantes" submite todo en batch
 */

import { useState, useCallback } from 'react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Plus, Trash2, Zap, X } from 'lucide-react'

interface AttrDef { name: string; values: string[] }
interface VariantRow { attrs: Record<string, string>; price: string; stock: string; sku: string }

function cartesian(defs: AttrDef[]): Record<string, string>[] {
  if (!defs.length) return []
  return defs.reduce<Record<string, string>[]>((acc, def) => {
    if (!def.values.length) return acc
    if (!acc.length) return def.values.map(v => ({ [def.name]: v }))
    return acc.flatMap(combo => def.values.map(v => ({ ...combo, [def.name]: v })))
  }, [])
}

function labelFromAttrs(attrs: Record<string, string>): string {
  return Object.entries(attrs).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

interface Props {
  productId: string
  addVariationAction: (fd: FormData) => Promise<void>
  onDone?: () => void
}

export function VariantMatrixGenerator({ productId, addVariationAction, onDone }: Props) {
  const [defs, setDefs] = useState<AttrDef[]>([{ name: '', values: [''] }])
  const [matrix, setMatrix] = useState<VariantRow[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState(false)

  // ── Gestión de atributos ─────────────────────────────────────────────────────

  const addAttrDef = () => setDefs(d => [...d, { name: '', values: [''] }])

  const removeAttrDef = (i: number) => setDefs(d => d.filter((_, idx) => idx !== i))

  const updateAttrName = (i: number, name: string) =>
    setDefs(d => d.map((def, idx) => idx === i ? { ...def, name } : def))

  const addValue = (i: number) =>
    setDefs(d => d.map((def, idx) => idx === i ? { ...def, values: [...def.values, ''] } : def))

  const updateValue = (defIdx: number, valIdx: number, val: string) =>
    setDefs(d => d.map((def, i) => i === defIdx
      ? { ...def, values: def.values.map((v, j) => j === valIdx ? val : v) }
      : def
    ))

  const removeValue = (defIdx: number, valIdx: number) =>
    setDefs(d => d.map((def, i) => i === defIdx
      ? { ...def, values: def.values.filter((_, j) => j !== valIdx) }
      : def
    ))

  // ── Generar combinaciones ────────────────────────────────────────────────────

  const generate = useCallback(() => {
    const validDefs = defs
      .map(d => ({ name: d.name.trim(), values: d.values.map(v => v.trim()).filter(Boolean) }))
      .filter(d => d.name && d.values.length)

    const combos = cartesian(validDefs)
    if (!combos.length) return

    setMatrix(combos.map((attrs) => ({
      attrs,
      price: '',
      stock: '0',
      sku: '',
    })))
  }, [defs])

  const updateRow = (i: number, field: 'price' | 'stock' | 'sku', val: string) =>
    setMatrix(m => m ? m.map((row, idx) => idx === i ? { ...row, [field]: val } : row) : m)

  // ── Guardar todas las variantes ──────────────────────────────────────────────

  const handleSave = async () => {
    if (!matrix) return
    setSaving(true)
    try {
      for (const row of matrix) {
        if (!row.price || parseFloat(row.price) <= 0) continue
        const fd = new FormData()
        fd.append('product_id', productId)
        fd.append('attrs_json', JSON.stringify(row.attrs))
        fd.append('price', row.price)
        fd.append('stock', row.stock || '0')
        if (row.sku) fd.append('sku', row.sku)
        await addVariationAction(fd)
      }
      setDone(true)
      onDone?.()
    } finally {
      setSaving(false)
    }
  }

  if (done) {
    return (
      <div className="p-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 text-sm text-emerald-400 flex items-center gap-2">
        <Zap className="h-4 w-4" />
        {matrix?.length} variantes creadas exitosamente.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Definición de atributos */}
      <div className="space-y-3">
        {defs.map((def, defIdx) => (
          <div key={defIdx} className="rounded-lg border border-border bg-card p-3 space-y-2">
            <div className="flex items-center gap-2">
              <Input
                value={def.name}
                onChange={e => updateAttrName(defIdx, e.target.value)}
                placeholder="Nombre del atributo (Ej: Color, Talla, Aroma)"
                className="h-8 text-xs font-semibold flex-1"
              />
              {defs.length > 1 && (
                <button type="button" onClick={() => removeAttrDef(defIdx)}
                  className="text-muted-foreground hover:text-destructive transition-colors">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {def.values.map((val, valIdx) => (
                <div key={valIdx} className="flex items-center gap-1">
                  <Input
                    value={val}
                    onChange={e => updateValue(defIdx, valIdx, e.target.value)}
                    placeholder={`Valor ${valIdx + 1}`}
                    className="h-7 text-xs w-28"
                  />
                  {def.values.length > 1 && (
                    <button type="button" onClick={() => removeValue(defIdx, valIdx)}
                      className="text-muted-foreground hover:text-destructive">
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </div>
              ))}
              <button type="button" onClick={() => addValue(defIdx)}
                className="h-7 px-2 text-[11px] text-primary border border-primary/30 rounded-md hover:bg-primary/10 transition-colors">
                + valor
              </button>
            </div>
          </div>
        ))}
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="outline" onClick={addAttrDef} className="h-7 text-xs gap-1.5">
            <Plus className="h-3 w-3" /> Otro atributo
          </Button>
          <Button type="button" size="sm" onClick={generate} className="h-7 text-xs gap-1.5 bg-primary/90 hover:bg-primary">
            <Zap className="h-3 w-3" /> Generar combinaciones
          </Button>
        </div>
      </div>

      {/* Tabla de combinaciones generadas */}
      {matrix && matrix.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold text-muted-foreground uppercase">
            {matrix.length} variante{matrix.length !== 1 ? 's' : ''} — completa precio y stock
          </p>
          <div className="rounded-lg border border-border overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-muted/40">
                <tr>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground">Combinación</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground w-28">SKU</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground w-28">Precio *</th>
                  <th className="text-left px-3 py-2 font-medium text-muted-foreground w-24">Stock</th>
                </tr>
              </thead>
              <tbody>
                {matrix.map((row, i) => (
                  <tr key={i} className="border-t border-border/40">
                    <td className="px-3 py-2">
                      <span className="font-medium">{labelFromAttrs(row.attrs)}</span>
                    </td>
                    <td className="px-3 py-1.5">
                      <Input value={row.sku} onChange={e => updateRow(i, 'sku', e.target.value)}
                        placeholder="SKU-001" className="h-7 text-xs font-mono" />
                    </td>
                    <td className="px-3 py-1.5">
                      <Input value={row.price} onChange={e => updateRow(i, 'price', e.target.value)}
                        type="number" min="50" step="50" placeholder="0"
                        className="h-7 text-xs font-mono" required />
                    </td>
                    <td className="px-3 py-1.5">
                      <Input value={row.stock} onChange={e => updateRow(i, 'stock', e.target.value)}
                        type="number" min="0" defaultValue="0"
                        className="h-7 text-xs font-mono" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2 justify-end">
            <Button type="button" size="sm" onClick={handleSave} disabled={saving}
              className="gap-1.5 h-8 text-xs">
              {saving ? 'Creando variantes...' : `Crear ${matrix.length} variantes`}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setMatrix(null)}
              className="h-8 text-xs text-muted-foreground">
              Volver
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
