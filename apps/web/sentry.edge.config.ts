/**
 * Sentry edge (middleware Edge runtime) config — Next.js Edge runtime.
 *
 * Rev. 109 J.2.7.4 — Sentry tracing E2E cross-service.
 *
 * Esta config se aplica al Edge runtime (middleware.ts si existe, y
 * cualquier route handler con `export const runtime = 'edge'`).
 *
 * Hoy apps/web NO usa Edge runtime (todos los API routes corren en Node),
 * pero el SDK lo requiere para no warninguear. Si en futuro se agrega
 * middleware.ts edge, este config se activa automáticamente.
 */
import * as Sentry from '@sentry/nextjs'

Sentry.init({
  dsn: process.env.SENTRY_DSN,

  // F97 fix — nombre canónico (el blueprint declara SENTRY_TRACES_SAMPLE_RATE, no *_RATE).
  tracesSampleRate: Number(process.env.SENTRY_TRACES_SAMPLE_RATE || 0.1),

  sendDefaultPii: false,

  enabled: !!process.env.SENTRY_DSN,

  environment: process.env.VERCEL_ENV
    || process.env.SENTRY_ENV
    || process.env.NODE_ENV
    || 'development',
})
