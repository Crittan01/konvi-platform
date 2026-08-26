'use client'

// Boundary de error del módulo — superficie compartida RouteError (T7.6,
// patrón anti-falso-0 §3.2: error + retry, nunca un 0 que parezca dato).
import { RouteError } from '@/components/route-error'

export default function PromotionsError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <RouteError
      title="Error al cargar Promociones"
      description="No se pudieron cargar las promociones. Puede ser un problema de conexión temporal."
      error={error}
      reset={reset}
      logTag="PromotionsError"
    />
  )
}
