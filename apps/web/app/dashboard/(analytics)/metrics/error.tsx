'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

export default function MetricsError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('[MetricsError]', error)
  }, [error])

  return (
    <div className="flex items-center justify-center p-12">
      <Card className="max-w-md w-full">
        <CardContent className="pt-8 pb-8 text-center space-y-5">
          <div className="flex justify-center">
            <div className="h-12 w-12 rounded-full bg-red-500/10 flex items-center justify-center">
              <AlertTriangle className="h-6 w-6 text-red-700" />
            </div>
          </div>
          <div className="space-y-1">
            <h2 className="text-lg font-semibold text-foreground">Error al cargar Métricas</h2>
            <p className="text-sm text-muted-foreground">
              No se pudieron cargar las métricas. Puede ser un problema de conexión temporal.
            </p>
            {error.digest && (
              <p className="text-xs font-mono text-muted-foreground/50 pt-1">
                #{error.digest}
              </p>
            )}
          </div>
          <div className="flex gap-3 justify-center">
            <Button size="sm" onClick={reset} className="gap-2">
              <RefreshCw className="h-3.5 w-3.5" />
              Reintentar
            </Button>
            <Button size="sm" variant="outline" asChild>
              <Link href="/dashboard">Ir al inicio</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
