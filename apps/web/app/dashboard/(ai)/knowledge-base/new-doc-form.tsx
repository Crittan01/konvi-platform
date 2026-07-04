'use client'

import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SubmitButton } from '@/components/ui/submit-button'

interface CategoryDef { value: string; label: string }
interface CategoryGuide { placeholder: string; doYes: string; doNo: string }

interface Props {
  categories:     CategoryDef[]
  guides:         Record<string, CategoryGuide>
  emptyCategories: string[]
  maxTitle:       number
  maxContent:     number
  createDocument: (formData: FormData) => Promise<void>
}

export function NewDocForm({
  categories, guides, emptyCategories, maxTitle, maxContent, createDocument,
}: Props) {
  // Si hay categorías vacías, default a la primera vacía (empuja al tenant a llenarlas).
  // Si todas tienen docs, default a la primera categoría.
  const initialCategory =
    emptyCategories.length > 0 ? emptyCategories[0] : (categories[0]?.value ?? 'faq')
  const [category, setCategory] = useState<string>(initialCategory)
  const guide = guides[category]

  return (
    <form action={createDocument} className="space-y-3 mt-3">
      <div className="space-y-1">
        <Label className="text-xs">
          Título * <span className="text-muted-foreground font-normal">(máx {maxTitle} chars)</span>
        </Label>
        <Input name="title" placeholder="Ej: Política de devoluciones" required maxLength={maxTitle} className="h-8 text-sm" />
      </div>

      <div className="space-y-1">
        <Label className="text-xs">Categoría</Label>
        <select
          name="category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {categories.map((c) => {
            const isEmpty = emptyCategories.includes(c.value)
            return (
              <option key={c.value} value={c.value}>
                {c.label}{isEmpty ? '  ⚠️ vacía' : ''}
              </option>
            )
          })}
        </select>
        {emptyCategories.includes(category) && (
          <p className="text-[11px] text-amber-700 mt-1">
            Esta categoría está vacía — el bot no podrá responder con verdad si un cliente pregunta sobre este tema.
          </p>
        )}
      </div>

      {/* Rev. 71 — Guía visible por default para la categoría seleccionada
          (antes estaba colapsada en `<details>` y los tenants no la veían). */}
      {guide && (
        <div className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs space-y-1">
          <p className="font-semibold text-foreground/90">Guía para esta categoría</p>
          <p className="text-muted-foreground italic">{guide.placeholder}</p>
          <p className="text-emerald-600">✓ Sí: <span className="text-foreground/80">{guide.doYes}</span></p>
          <p className="text-red-700">✗ No: <span className="text-foreground/80">{guide.doNo}</span></p>
        </div>
      )}

      <div className="space-y-1">
        <Label className="text-xs">
          Contenido * <span className="text-muted-foreground font-normal">(máx {maxContent} chars)</span>
        </Label>
        <textarea
          name="content"
          rows={7}
          required
          maxLength={maxContent}
          placeholder={guide?.placeholder ?? 'Escribe el texto tal como quieres que la IA lo lea.'}
          className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <p className="text-xs text-muted-foreground">
          La IA usará búsqueda semántica para encontrar el doc más relevante.
        </p>
      </div>

      {/* Detalle expandible con TODAS las categorías para referencia cruzada. */}
      <details className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs">
        <summary className="cursor-pointer font-medium text-foreground/80">
          Ver guía de las otras categorías
        </summary>
        <div className="mt-2 space-y-2.5">
          {categories.map((c) => {
            if (c.value === category) return null
            const g = guides[c.value]
            if (!g) return null
            return (
              <div key={c.value} className="border-l-2 border-primary/20 pl-2.5">
                <p className="font-semibold text-foreground/90">{c.label}</p>
                <p className="text-muted-foreground italic">{g.placeholder}</p>
                <p className="text-emerald-600 mt-0.5">✓ Sí: <span className="text-foreground/80">{g.doYes}</span></p>
                <p className="text-red-700">✗ No: <span className="text-foreground/80">{g.doNo}</span></p>
              </div>
            )
          })}
        </div>
      </details>

      <SubmitButton className="w-full h-8 text-sm" pendingText="Guardando y generando embedding...">
        Agregar documento
      </SubmitButton>
    </form>
  )
}
