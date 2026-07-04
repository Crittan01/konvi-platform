'use client'

import { useState } from 'react'
import { useFormStatus } from 'react-dom'
import { BrainCircuit, Loader2 } from 'lucide-react'
import { STARTER_TEMPLATES } from './starter-templates'
import { categoryBadgeClass, categoryLabel } from './categories'
import ActionResultForm from '@/components/action-result-form'
import type { ActionResult } from '@/lib/action-result'

function LoadButton({ count }: { count: number }) {
  const { pending } = useFormStatus()
  return (
    <button
      type="submit"
      disabled={pending || count === 0}
      className="inline-flex items-center gap-2 h-8 px-3 text-xs font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
    >
      {pending
        ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Cargando...</>
        : <><BrainCircuit className="h-3.5 w-3.5" />Cargar seleccionadas ({count})</>
      }
    </button>
  )
}

interface Props {
  loadSelectedTemplates: (fd: FormData) => Promise<ActionResult>
  defaultExpanded?: boolean
}

export function TemplatesSection({ loadSelectedTemplates, defaultExpanded = true }: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [selected, setSelected] = useState<Set<string>>(new Set(STARTER_TEMPLATES.map(t => t.id)))

  const allSelected = selected.size === STARTER_TEMPLATES.length
  const toggle = (id: string) =>
    setSelected(prev => {
      const s = new Set(prev)
      if (s.has(id)) s.delete(id)
      else s.add(id)
      return s
    })
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(STARTER_TEMPLATES.map(t => t.id)))

  return (
    <div className="rounded-xl border border-primary/25 bg-primary/5 p-5 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="font-semibold text-sm text-foreground">Plantillas de contenido</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Selecciona las que apliquen a tu negocio y cárgalas con un clic. Edítalas después a tu gusto.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {expanded && (
            <ActionResultForm action={loadSelectedTemplates} className="flex items-center gap-2">
              {Array.from(selected).map(id => (
                <input key={id} type="hidden" name="template_ids" value={id} />
              ))}
              <LoadButton count={selected.size} />
            </ActionResultForm>
          )}
          <button
            type="button"
            onClick={() => setExpanded(e => !e)}
            className="text-xs text-primary underline underline-offset-2 hover:no-underline shrink-0"
          >
            {expanded ? 'Ocultar' : 'Mostrar plantillas'}
          </button>
        </div>
      </div>

      {expanded && (
        <>
          {/* Seleccionar / Deseleccionar todas */}
          <button
            type="button"
            onClick={toggleAll}
            className="text-xs text-primary underline underline-offset-2 hover:no-underline"
          >
            {allSelected ? 'Deseleccionar todas' : 'Seleccionar todas'}
          </button>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {STARTER_TEMPLATES.map(t => {
              const isSelected = selected.has(t.id)
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => toggle(t.id)}
                  aria-pressed={isSelected}
                  aria-label={`${isSelected ? 'Quitar' : 'Seleccionar'} plantilla: ${t.title}`}
                  className={`text-left rounded-lg border p-3 space-y-1.5 transition-all ${
                    isSelected
                      ? 'border-primary/50 bg-primary/8 ring-1 ring-primary/30'
                      : 'border-border bg-card opacity-60 hover:opacity-80'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${categoryBadgeClass(t.category)}`}>
                      {categoryLabel(t.category)}
                    </span>
                    <span aria-hidden="true" className={`h-4 w-4 rounded border flex items-center justify-center shrink-0 ${
                      isSelected ? 'bg-primary border-primary' : 'border-muted-foreground/40'
                    }`}>
                      {isSelected && (
                        <svg className="h-2.5 w-2.5 text-primary-foreground" fill="none" viewBox="0 0 12 12">
                          <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </span>
                  </div>
                  <p className="text-xs font-medium text-foreground leading-snug">{t.title}</p>
                  <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2">
                    {t.content.split('\n')[0]}
                  </p>
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
