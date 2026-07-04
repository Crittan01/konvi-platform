'use client'

import { ReactNode } from 'react'
import { toast } from 'sonner'

type ActionResult = { ok: boolean; error?: string }

/**
 * F-doc (Fase 6): wrapper client para forms que llaman server actions con contrato
 * ActionResult {ok,error}. Permite usar esas actions dentro de un SERVER component
 * (settings/page.tsx) surfacing el resultado al usuario. Antes eran <form action={X}>
 * directos: un throw se enmascaraba en prod, o (tras migrar a return) el error
 * quedaba silencioso porque el form ignoraba el retorno.
 *
 * F6: se migró de window.alert (bloqueante, sin confirmación de éxito) a toast del DS
 * — el operador ahora ve "Guardado ✓" al persistir bien (antes solo veía errores) y un
 * toast de error no-bloqueante si falla.
 */
export default function ActionResultForm({
  action,
  children,
  className,
  successMessage = 'Cambios guardados',
}: {
  action: (formData: FormData) => Promise<ActionResult>
  children: ReactNode
  className?: string
  successMessage?: string
}) {
  return (
    <form
      className={className}
      action={async (fd) => {
        const r = await action(fd)
        if (r.ok) toast.success(successMessage)
        else toast.error(r.error || 'No se pudo guardar. Intenta de nuevo.')
      }}
    >
      {children}
    </form>
  )
}
