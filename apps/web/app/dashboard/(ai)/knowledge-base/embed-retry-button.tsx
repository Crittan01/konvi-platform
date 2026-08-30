'use client'

import { useTransition } from 'react'
import { toast } from 'sonner'
import { Clock, Loader2 } from 'lucide-react'
import type { ActionResult } from '@/lib/action-result'

interface Props {
  docId: string
  reindexDocument: (fd: FormData) => Promise<ActionResult>
}

export function EmbedRetryButton({ docId, reindexDocument }: Props) {
  const [isPending, startTransition] = useTransition()

  const handleClick = () => {
    const fd = new FormData()
    fd.append('doc_id', docId)
    startTransition(async () => {
      const r = await reindexDocument(fd)
      if (r.ok) toast.success('Documento preparado para la IA')
      else toast.error(r.error || 'No se pudo preparar el documento. Reintenta en unos minutos.')
    })
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={isPending}
      aria-label={isPending
        ? 'Preparando documento para la IA'
        : 'Hubo un problema al preparar el documento. Clic para reintentar.'}
      title={isPending
        ? 'Preparando documento para la IA...'
        : 'Hubo un problema al preparar el documento. Clic para reintentar.'}
      className="inline-flex items-center gap-0.5 text-[10px] border rounded-full px-1.5 py-0.5 transition-colors disabled:opacity-60 disabled:cursor-wait cursor-pointer text-warning-fg border-warning-border bg-warning-bg hover:bg-warning-border/40"
    >
      {isPending
        ? <><Loader2 className="h-2.5 w-2.5 animate-spin" /> Preparando...</>
        : <><Clock className="h-2.5 w-2.5" /> Error al preparar — reintentar</>
      }
    </button>
  )
}
