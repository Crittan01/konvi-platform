/**
 * Next.js instrumentation hook — Sentry SDK init server-side.
 *
 * Rev. 109 J.2.7.4 cleanup post-merge — Sentry 8.x recomienda migrar
 * `sentry.server.config.ts` + `sentry.edge.config.ts` a esta `register()`
 * function en lugar de auto-inject vía `withSentryConfig`.
 *
 * Esta función se invoca UNA VEZ al boot del servidor Next.js, antes
 * de procesar requests. Carga el config correcto según runtime activo.
 *
 * Docs: https://nextjs.org/docs/app/building-your-application/optimizing/instrumentation
 *
 * Browser config (`sentry.client.config.ts`) NO entra aquí — sigue
 * auto-inyectado por `withSentryConfig` al bundle browser.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    await import('./sentry.server.config')
  }

  if (process.env.NEXT_RUNTIME === 'edge') {
    await import('./sentry.edge.config')
  }
}

// Sentry SDK 8.x — captura errores en server actions + Next.js route handlers
// que NO son atrapados por error boundaries de React.
export { captureRequestError } from '@sentry/nextjs'
