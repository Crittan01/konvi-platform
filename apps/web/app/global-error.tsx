'use client'

/**
 * Global error boundary — Next.js App Router top-level fallback.
 *
 * Captura React rendering errors que escapan a los error boundaries de cada
 * page (errores de render en RSC o client components).
 *
 * Nota: este componente DEBE incluir <html>+<body> porque reemplaza
 * el layout root cuando se monta (último fallback antes del crash).
 */
import NextError from 'next/error'
import { useEffect } from 'react'

export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string }
}) {
  useEffect(() => {
    // Sin error-tracking externo (S8): la señal queda en los logs del server.
    console.error('[global-error] React render error:', error)
  }, [error])

  return (
    <html>
      <body>
        {/* NextError es el fallback estándar de Next.js — minimalista pero
            consistente con el resto de errores. Si quieres branding propio
            (logo Konvi, mensaje en español), reemplazar este componente. */}
        <NextError statusCode={0} />
      </body>
    </html>
  )
}
