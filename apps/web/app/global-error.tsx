'use client'

/**
 * Global error boundary — Next.js App Router top-level fallback.
 *
 * Rev. 109 J.2.7.4 cleanup post-merge — Sentry 8.x recomienda este
 * archivo para capturar React rendering errors que escapan a los
 * error boundaries de cada page. Sin esto, errores de render en RSC
 * o client components no llegan a Sentry.
 *
 * Docs: https://docs.sentry.io/platforms/javascript/guides/nextjs/manual-setup/#react-render-errors-in-app-router
 *
 * Nota: este componente DEBE incluir <html>+<body> porque reemplaza
 * el layout root cuando se monta (último fallback antes del crash).
 */
import * as Sentry from '@sentry/nextjs'
import NextError from 'next/error'
import { useEffect } from 'react'

export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string }
}) {
  useEffect(() => {
    Sentry.captureException(error)
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
