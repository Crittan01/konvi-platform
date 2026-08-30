'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Loader2, Zap } from 'lucide-react'

interface Props {
  pendingCount: number
}

export function IndexPendingBanner({ pendingCount }: Props) {
  const [state, setState] = useState<'idle' | 'loading' | 'done'>('idle')

  if (pendingCount === 0 || state === 'done') return null

  const handleIndex = async () => {
    setState('loading')
    try {
      const res = await fetch('/api/ai/index-pending', { method: 'POST' })
      const data = await res.json().catch(() => ({})) as { indexed?: number; total?: number; error?: string }
      if (!res.ok) {
        toast.error(data.error || 'No se pudieron preparar los documentos. Reintenta en unos minutos.')
        setState('idle')
        return
      }
      const indexed = data.indexed ?? 0
      const total = data.total ?? 0
      if (indexed < total) {
        toast.warning(`Se prepararon ${indexed} de ${total}. Reintenta los pendientes en unos minutos.`)
      } else if (indexed > 0) {
        toast.success(`${indexed} documento${indexed !== 1 ? 's' : ''} listo${indexed !== 1 ? 's' : ''} para IA`)
      }
      setState('done')
      // Recargar la página para reflejar los badges actualizados
      window.location.reload()
    } catch {
      toast.error('No se pudieron preparar los documentos. Revisa tu conexión e intenta de nuevo.')
      setState('idle')
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-warning-border bg-warning-bg flex-wrap">
      <div className="flex items-center gap-2">
        <Zap className="h-4 w-4 text-warning-fg shrink-0" />
        <p className="text-xs text-warning-fg">
          {state === 'loading'
            ? `Preparando documentos para IA...`
            : `${pendingCount} documento${pendingCount !== 1 ? 's' : ''} pendiente${pendingCount !== 1 ? 's' : ''} de preparar para IA`
          }
        </p>
      </div>
      {state !== 'loading' && (
        <button
          onClick={handleIndex}
          className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-warning-bg text-warning-fg border border-warning-border hover:bg-amber-500/25 transition-colors shrink-0"
        >
          <Zap className="h-3 w-3" /> Preparar para IA
        </button>
      )}
      {state === 'loading' && (
        <Loader2 className="h-4 w-4 animate-spin text-warning-fg shrink-0" />
      )}
    </div>
  )
}
