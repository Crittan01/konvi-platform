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

// Captura errores en server actions + Next.js route handlers / RSC que NO son
// atrapados por error boundaries de React.
//
// BUG FIX: Next.js invoca el hook por su nombre EXACTO `onRequestError` exportado
// desde este archivo (contrato del framework). Antes se exportaba como
// `captureRequestError` → el hook quedaba MUERTO y los errores server-side NO
// llegaban a Sentry. Se aliasa al nombre que Next espera.
// Ref: docs.sentry.io/platforms/javascript/guides/nextjs/manual-setup (onRequestError).
export { captureRequestError as onRequestError } from '@sentry/nextjs'
