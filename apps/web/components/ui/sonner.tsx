'use client'

import { Toaster as Sonner } from 'sonner'

/**
 * Toaster — canal ÚNICO de feedback de mutaciones (F1 2026-07-04, decisión
 * founder). Reemplaza los 3 patrones que convivían: confirm() nativo,
 * mensajes inline por pantalla y el falso "Guardado" de SubmitButton.
 *
 * Temado al DS Kaiu vía tokens (no colores hardcodeados).
 */
export function Toaster() {
  return (
    <Sonner
      position="bottom-right"
      closeButton
      toastOptions={{
        classNames: {
          toast:
            'group border-border bg-card text-card-foreground shadow-lg rounded-lg',
          title: 'text-sm font-medium',
          description: 'text-xs text-muted-foreground',
          success: 'border-success-border!',
          error: 'border-danger-border!',
          warning: 'border-warning-border!',
          closeButton: 'border-border bg-card text-muted-foreground',
        },
      }}
    />
  )
}
