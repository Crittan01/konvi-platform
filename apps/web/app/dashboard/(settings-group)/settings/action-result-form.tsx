'use client'

import { ReactNode } from 'react'

type ActionResult = { ok: boolean; error?: string }

/**
 * F-doc (Fase 6): wrapper client para forms que llaman server actions con contrato
 * ActionResult {ok,error}. Permite usar esas actions dentro de un SERVER component
 * (settings/page.tsx) surfacing el error al usuario. Antes eran <form action={X}>
 * directos: un throw se enmascaraba en prod, o (tras migrar a return) el error
 * quedaba silencioso porque el form ignoraba el retorno.
 *
 * `alert` es bloqueante a propósito: el operador DEBE ver por qué no se guardó.
 */
export default function ActionResultForm({
  action,
  children,
  className,
}: {
  action: (formData: FormData) => Promise<ActionResult>
  children: ReactNode
  className?: string
}) {
  return (
    <form
      className={className}
      action={async (fd) => {
        const r = await action(fd)
        if (!r.ok) window.alert(r.error || 'No se pudo guardar. Intenta de nuevo.')
      }}
    >
      {children}
    </form>
  )
}
