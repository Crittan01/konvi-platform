'use client'

import { useTransition } from 'react'
import { Clock, Loader2 } from 'lucide-react'

interface Props {
  docId: string
  activateDocument: (fd: FormData) => Promise<void>
}

export function EmbedRetryButton({ docId, activateDocument }: Props) {
  const [isPending, startTransition] = useTransition()

  const handleClick = () => {
    const fd = new FormData()
    fd.append('doc_id', docId)
    startTransition(() => activateDocument(fd))
  }

  return (
    <button
      onClick={handleClick}
      disabled={isPending}
      title={isPending ? 'Generando índice semántico...' : 'Hubo un problema al indexar. Clic para reintentar.'}
      className="inline-flex items-center gap-0.5 text-[10px] border rounded-full px-1.5 py-0.5 transition-colors disabled:opacity-60 disabled:cursor-wait cursor-pointer text-amber-700/80 border-amber-700/30 bg-amber-500/8 hover:bg-amber-500/15 hover:text-amber-700"
    >
      {isPending
        ? <><Loader2 className="h-2.5 w-2.5 animate-spin" /> Indexando...</>
        : <><Clock className="h-2.5 w-2.5" /> Error al indexar — reintentar</>
      }
    </button>
  )
}
