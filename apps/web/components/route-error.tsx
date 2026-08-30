'use client'

// RouteError — boundary de error por módulo (patrón anti-falso-0 §3.2: la
// pantalla de error es error+retry, NUNCA un "0" que parezca dato real).
// Extraído en T7.6 de los 6 error.tsx idénticos (orders/inbox/catalog/
// shipping/metrics/dashboard): una sola superficie visual; cada ruta solo
// aporta su título, descripción y tag de log.

import { useEffect } from 'react'
import Link from 'next/link'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

export interface RouteErrorProps {
  /** "Error al cargar Pedidos" */
  title: string
  /** "No se pudieron cargar los pedidos. Puede ser un problema de conexión temporal." */
  description: string
  error: Error & { digest?: string }
  reset: () => void
  /** Tag del console.error — nombre del boundary (p. ej. "OrdersError"). */
  logTag: string
}

export function RouteError({ title, description, error, reset, logTag }: RouteErrorProps) {
  useEffect(() => {
    console.error(`[${logTag}]`, error)
  }, [error, logTag])

  return (
    <div className="flex items-center justify-center p-12">
      <Card className="max-w-md w-full">
        <CardContent className="pt-8 pb-8 text-center space-y-5">
          <div className="flex justify-center">
            <div className="h-12 w-12 rounded-full bg-danger-bg flex items-center justify-center">
              <AlertTriangle className="h-6 w-6 text-danger-fg" />
            </div>
          </div>
          <div className="space-y-1">
            <h2 className="text-lg font-semibold text-foreground">{title}</h2>
            <p className="text-sm text-muted-foreground">{description}</p>
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
