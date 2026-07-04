'use client'

/**
 * Botón "Actualizar" — refresca los datos server-side sin recarga dura.
 *
 * F6 2026-07-04: la página es server-component force-dynamic; sin esto el
 * operador debía recargar a mano para ver el ciclo de 5 min. router.refresh()
 * re-ejecuta el fetch en el servidor manteniendo el estado de scroll.
 */
import { useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function RefreshButton() {
  const router = useRouter()
  const [isPending, startTransition] = useTransition()

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={isPending}
      onClick={() => startTransition(() => router.refresh())}
    >
      <RefreshCw
        className={`h-4 w-4 mr-2 ${isPending ? 'animate-spin' : ''}`}
        aria-hidden="true"
      />
      {isPending ? 'Actualizando…' : 'Actualizar'}
    </Button>
  )
}
