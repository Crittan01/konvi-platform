'use client'

import { useState } from 'react'
import { Copy, Check } from 'lucide-react'

/**
 * Botón inline "Copiar" reutilizable dentro de un server component.
 * whatsapp-setup.tsx es server → no puede tener onClick; este client wrapper sí.
 */
export function CopyInlineButton({ value, label = 'Copiar' }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value)
          setCopied(true)
          setTimeout(() => setCopied(false), 2000)
        } catch {
          /* clipboard puede fallar sin gesto de usuario / http; no-op */
        }
      }}
      className="inline-flex items-center gap-1 text-xs text-primary hover:underline shrink-0"
      aria-label={label}
    >
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {copied ? 'Copiado' : label}
    </button>
  )
}
