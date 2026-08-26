'use client'

// Boundary de error del módulo — superficie compartida RouteError (T7.6,
// patrón anti-falso-0 §3.2: error + retry, nunca un 0 que parezca dato).
import { RouteError } from '@/components/route-error'

export default function KnowledgeBaseError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <RouteError
      title="Error al cargar Base de conocimiento"
      description="No se pudo cargar la base de conocimiento. Puede ser un problema de conexión temporal."
      error={error}
      reset={reset}
      logTag="KnowledgeBaseError"
    />
  )
}
