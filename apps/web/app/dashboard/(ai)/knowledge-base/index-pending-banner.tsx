'use client'

import { useState } from 'react'
import { Loader2, Zap } from 'lucide-react'

interface Props {
  pendingCount: number
}

export function IndexPendingBanner({ pendingCount }: Props) {
  const [state, setState] = useState<'idle' | 'loading' | 'done'>('idle')
  const [, setResult] = useState<{ indexed: number; total: number } | null>(null)

  if (pendingCount === 0 || state === 'done') return null

  const handleIndex = async () => {
    setState('loading')
    try {
      const res = await fetch('/api/ai/index-pending', { method: 'POST' })
      const data = await res.json() as { indexed: number; total: number }
      setResult(data)
      setState('done')
      // Recargar la página para reflejar los badges actualizados
      window.location.reload()
    } catch {
      setState('idle')
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-amber-700/25 bg-amber-500/5 flex-wrap">
      <div className="flex items-center gap-2">
        <Zap className="h-4 w-4 text-amber-700 shrink-0" />
        <p className="text-xs text-amber-700">
          {state === 'loading'
            ? `Preparando documentos para IA...`
            : `${pendingCount} documento${pendingCount !== 1 ? 's' : ''} pendiente${pendingCount !== 1 ? 's' : ''} de preparar para IA`
          }
        </p>
      </div>
      {state !== 'loading' && (
        <button
          onClick={handleIndex}
          className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-amber-500/15 text-amber-700 border border-amber-700/30 hover:bg-amber-500/25 transition-colors shrink-0"
        >
          <Zap className="h-3 w-3" /> Preparar para IA
        </button>
      )}
      {state === 'loading' && (
        <Loader2 className="h-4 w-4 animate-spin text-amber-700 shrink-0" />
      )}
    </div>
  )
}
