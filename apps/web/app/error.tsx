'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui/button'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Log to console — in production this goes to Render logs
    console.error('[GlobalError]', error)
  }, [error])

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-8">
      <div className="max-w-md w-full text-center space-y-6">
        <div className="space-y-2">
          <h1 className="text-2xl font-bold text-foreground">Algo salió mal</h1>
          <p className="text-sm text-muted-foreground">
            Ocurrió un error inesperado. Si el problema persiste, contacta a soporte.
          </p>
          {error.digest && (
            <p className="text-xs font-mono text-muted-foreground/60 mt-1">
              Código: {error.digest}
            </p>
          )}
        </div>
        <div className="flex gap-3 justify-center">
          <Button onClick={reset} variant="default">
            Reintentar
          </Button>
          <Button onClick={() => window.location.href = '/dashboard'} variant="outline">
            Ir al inicio
          </Button>
        </div>
      </div>
    </div>
  )
}
