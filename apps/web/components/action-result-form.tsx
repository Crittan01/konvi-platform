'use client'

import { createContext, useContext, useState, ReactNode } from 'react'
import { toast } from 'sonner'
import type { ActionResult } from '@/lib/action-result'

/**
 * ActionResultForm — form client para server actions con contrato ActionResult
 * (F-doc Fase 6, v2 en F1 2026-07-04).
 *
 * v2: el error se surfacea por TOAST (canal único del DS, decisión founder)
 * en vez de window.alert, y expone el resultado vía contexto para que
 * SubmitButton muestre "Guardado" SOLO cuando la action realmente terminó ok
 * (antes lo infería de pending→false y mentía en fallos).
 */
type Status = 'idle' | 'ok' | 'error'

const ActionResultContext = createContext<Status | null>(null)

/** Consumido por SubmitButton: null = form sin canal de resultado. */
export function useActionResultStatus(): Status | null {
  return useContext(ActionResultContext)
}

export default function ActionResultForm({
  action,
  children,
  className,
  successMessage,
}: {
  action: (formData: FormData) => Promise<ActionResult>
  children: ReactNode
  className?: string
  /** Toast de éxito opcional (p.ej. "Configuración guardada"). */
  successMessage?: string
}) {
  const [status, setStatus] = useState<Status>('idle')

  return (
    <ActionResultContext.Provider value={status}>
      <form
        className={className}
        action={async (fd) => {
          setStatus('idle')
          const r = await action(fd)
          if (!r.ok) {
            setStatus('error')
            toast.error(r.error || 'No se pudo guardar. Intenta de nuevo.')
            return
          }
          setStatus('ok')
          if (successMessage || r.message) toast.success(r.message || successMessage)
        }}
      >
        {children}
      </form>
    </ActionResultContext.Provider>
  )
}
