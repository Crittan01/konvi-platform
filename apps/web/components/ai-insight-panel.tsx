'use client'

import { useState, useEffect } from 'react'
import { BrainCircuit, Sparkles, AlertTriangle, CheckCircle2, ChevronRight, RefreshCw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

// ── Tipos ──────────────────────────────────────────────────────────────────────

type Prioridad = 'alta' | 'media' | 'baja'

type InsightResult = {
  resumen: string
  hallazgos: string[]
  acciones: { prioridad: Prioridad; accion: string }[]
  alerta: string | null
  generated_at: string
  tokens_used?: number
}

type Props = {
  module: 'inventory' | 'orders' | 'contacts' | 'metrics'
  label?: string   // Ej. "Inventario" — aparece en el botón y card
}

// ── Colores de prioridad ───────────────────────────────────────────────────────

const PRIORITY_STYLES: Record<Prioridad, { dot: string; text: string; badge: string }> = {
  alta:  { dot: 'bg-red-400',    text: 'text-red-700',    badge: 'bg-red-400/15 text-red-700 border border-red-700/30' },
  media: { dot: 'bg-amber-400',  text: 'text-amber-700',  badge: 'bg-amber-400/15 text-amber-700 border border-amber-700/30' },
  baja:  { dot: 'bg-green-400',  text: 'text-green-700',  badge: 'bg-green-400/15 text-green-700 border border-green-700/30' },
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function AiInsightPanel({ module, label = module }: Props) {
  // 'init' = cargando el último análisis persistido (decisión F4) antes de
  // decidir entre 'idle' y 'done'. Evita gastar tokens al re-montar/navegar.
  const [state, setState] = useState<'init' | 'idle' | 'loading' | 'done' | 'error'>('init')
  const [insight, setInsight] = useState<InsightResult | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [restored, setRestored] = useState(false)

  // Restaurar el último análisis guardado (GET, no consume Gemini). Si no hay
  // (o la persistencia aún no está disponible) → estado 'idle'.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`/api/insights?module=${encodeURIComponent(module)}`)
        if (!res.ok) { if (!cancelled) setState('idle'); return }
        const data = await res.json() as { insight: InsightResult | null }
        if (cancelled) return
        if (data.insight) {
          setInsight(data.insight)
          setRestored(true)
          setState('done')
        } else {
          setState('idle')
        }
      } catch {
        if (!cancelled) setState('idle')
      }
    })()
    return () => { cancelled = true }
  }, [module])

  async function generate() {
    setState('loading')
    setRestored(false)
    setErrorMsg(null)
    try {
      const res = await fetch('/api/insights', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ module }),
      })
      if (!res.ok) {
        const err = await res.json() as { error?: string }
        throw new Error(err.error ?? 'Error al generar análisis')
      }
      const data = await res.json() as InsightResult
      setInsight(data)
      setState('done')
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Error desconocido')
      setState('error')
    }
  }

  // ── Init: restaurando análisis guardado (placeholder sutil, evita salto) ────
  if (state === 'init') {
    return (
      <div
        className="w-full h-[54px] rounded-xl border border-dashed border-primary/20 bg-primary/5 animate-pulse"
        aria-hidden="true"
      />
    )
  }

  // ── Idle ──────────────────────────────────────────────────────────────────
  if (state === 'idle') {
    return (
      <button
        onClick={generate}
        className="group w-full flex items-center gap-3 rounded-xl border border-dashed border-primary/30 bg-primary/5 px-4 py-3 text-sm hover:border-primary/50 hover:bg-primary/10 transition-all duration-200"
      >
        <Sparkles className="h-4 w-4 text-primary shrink-0 group-hover:animate-pulse" />
        <div className="flex-1 text-left">
          <p className="font-medium text-foreground text-[13px]">Generar Análisis IA — {label}</p>
          <p className="text-[11px] text-muted-foreground mt-0.5">A demanda · consume 1 llamada a Gemini · análisis en ~10s</p>
        </div>
        <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
      </button>
    )
  }

  // ── Loading ───────────────────────────────────────────────────────────────
  if (state === 'loading') {
    return (
      <div className="rounded-xl border border-primary/30 bg-primary/5 px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 border-2 border-primary/40 border-t-primary rounded-full animate-spin shrink-0" />
          <div>
            <p className="text-sm font-medium text-foreground">Analizando {label}...</p>
            <p className="text-xs text-muted-foreground mt-0.5">Gemini está procesando tus datos (~10s)</p>
          </div>
        </div>
        {/* Shimmer bars */}
        <div className="mt-4 space-y-2">
          {[90, 75, 60].map(w => (
            <div key={w} className={`h-2.5 bg-primary/15 rounded-full animate-pulse`} style={{ width: `${w}%` }} />
          ))}
        </div>
      </div>
    )
  }

  // ── Error ─────────────────────────────────────────────────────────────────
  if (state === 'error') {
    return (
      <div className="rounded-xl border border-red-700/30 bg-red-500/5 px-4 py-3 flex items-start gap-3">
        <AlertTriangle className="h-4 w-4 text-red-700 shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="text-sm font-medium text-red-700">Error al generar análisis</p>
          <p className="text-xs text-muted-foreground mt-0.5">{errorMsg}</p>
        </div>
        <Button size="sm" variant="ghost" className="text-xs h-7 shrink-0" onClick={() => setState('idle')}>
          Reintentar
        </Button>
      </div>
    )
  }

  // ── Done ──────────────────────────────────────────────────────────────────
  if (!insight) return null

  const hasAlert = Boolean(insight.alerta)

  return (
    <div className="rounded-xl border border-primary/25 bg-linear-to-br from-primary/5 to-background overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-primary/15">
        <div className="flex items-center gap-2">
          <BrainCircuit className="h-4 w-4 text-primary" />
          <p className="text-sm font-semibold text-foreground">Análisis IA — {label}</p>
          {restored && (
            <span className="text-[10px] text-muted-foreground border border-border rounded-full px-1.5 py-0.5">
              guardado
            </span>
          )}
          {insight.tokens_used && (
            <span className="text-[10px] text-muted-foreground border border-border rounded-full px-1.5 py-0.5">
              ~{insight.tokens_used} tokens
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={generate} title="Regenerar" aria-label="Regenerar análisis"
            className="p-1.5 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => setState('idle')} title="Cerrar" aria-label="Cerrar panel de análisis"
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Alerta crítica */}
        {hasAlert && (
          <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-red-500/10 border border-red-700/25">
            <AlertTriangle className="h-3.5 w-3.5 text-red-700 shrink-0 mt-0.5" />
            <p className="text-xs text-red-700 font-medium leading-relaxed">{insight.alerta}</p>
          </div>
        )}

        {/* Resumen */}
        <div className="flex items-start gap-2">
          <CheckCircle2 className="h-4 w-4 text-primary shrink-0 mt-0.5" />
          <p className="text-sm text-foreground leading-relaxed">{insight.resumen}</p>
        </div>

        {/* Hallazgos */}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
            📊 Hallazgos clave
          </p>
          <ul className="space-y-1.5">
            {insight.hallazgos.map((h, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground leading-relaxed">
                <span className="text-primary mt-0.5 shrink-0">•</span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Acciones */}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
            ⚡ Acciones recomendadas
          </p>
          <div className="space-y-2">
            {insight.acciones.map((a, i) => {
              const styles = PRIORITY_STYLES[a.prioridad]
              return (
                <div key={i} className="flex items-start gap-2.5 rounded-lg border border-border bg-muted/30 px-3 py-2">
                  <span className={`inline-flex shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded-full mt-0.5 ${styles.badge}`}>
                    {a.prioridad.toUpperCase()}
                  </span>
                  <p className="text-xs text-foreground leading-relaxed">{a.accion}</p>
                </div>
              )
            })}
          </div>
        </div>

        {/* Footer */}
        <p className="text-[10px] text-muted-foreground/60 text-right">
          Generado el {new Date(insight.generated_at).toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' })}
        </p>
      </div>
    </div>
  )
}
