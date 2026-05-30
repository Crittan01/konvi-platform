/**
 * Sentry server (Node) config — Next.js server-side render + API routes.
 *
 * Rev. 109 J.2.7.4 — Sentry tracing E2E cross-service.
 *
 * Esta config se aplica al runtime Node de Next.js:
 *   - Server components (RSC)
 *   - Server actions
 *   - API routes (apps/web/app/api/*)
 *
 * Captura: errors en server, latency de SSR, fetches outbound desde
 * server actions / API routes al backend FastAPI.
 *
 * Trace propagation server-side:
 *   - Si la request browser→Next.js trae `sentry-trace` header (browser
 *     config), el server lo continúa en su transaction.
 *   - Cuando server action o API route hace fetch al backend Python,
 *     Sentry SDK Node propaga el trace headers automáticamente.
 */
import * as Sentry from '@sentry/nextjs'

Sentry.init({
  dsn: process.env.SENTRY_DSN,

  tracesSampleRate: Number(process.env.SENTRY_TRACES_RATE || 0.1),

  // PII off por default (consistente con client).
  sendDefaultPii: false,

  enabled: !!process.env.SENTRY_DSN,

  environment: process.env.VERCEL_ENV
    || process.env.SENTRY_ENV
    || process.env.NODE_ENV
    || 'development',

  // Server-side spans automáticos para HTTP outbound, ya incluidos por
  // default en @sentry/nextjs.
})
