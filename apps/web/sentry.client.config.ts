/**
 * Sentry client (browser) config.
 *
 * Rev. 109 J.2.7.4 — Sentry tracing E2E cross-service.
 *
 * Esta config se aplica al bundle del navegador (apps/web).
 * Captura: JS errors en el cliente, navegaciones, fetches outbound al backend.
 *
 * Trace propagation:
 *   - Cada fetch() del cliente a `/api/...` recibe automáticamente headers
 *     `sentry-trace` + `baggage` (W3C compatible).
 *   - El backend FastAPI (services/api) ya tiene sentry-sdk[fastapi] que
 *     EXTRAE esos headers y continúa el trace en su span.
 *   - Resultado: 1 trace_id correlaciona browser click → API call →
 *     Orchestrator dispatch → Supabase query.
 *
 * Sampling:
 *   - traces_sample_rate=0.1 (10% de transacciones). Subir a 1.0 en
 *     debugging activo, bajar en producción heavy traffic para reducir
 *     volumen Sentry (free tier 5k events/mo).
 *   - send_default_pii=false — no enviar emails/IPs por default (Habeas
 *     Data + cliente puede tener PII en URL parameters).
 */
import * as Sentry from '@sentry/nextjs'

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

  // Capturar 10% de transacciones — suficiente para detectar patrones sin
  // saturar quota free tier. Ajustable per environment.
  tracesSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_TRACES_RATE || 0.1),

  // PII control: NO enviar emails/IPs/cookies por default (Habeas Data).
  // Si necesitas debug específico → habilitar localmente via env override.
  sendDefaultPii: false,

  // Replay (grabaciones de sesión browser) — DESACTIVADO por costo + PII.
  // Habilitar caso por caso para debugging de bugs específicos.
  replaysSessionSampleRate: 0,
  replaysOnErrorSampleRate: 0,

  // Solo enviar a Sentry si DSN configurado (NEXT_PUBLIC_SENTRY_DSN puede
  // estar vacío en local dev — silencioso, no crashea).
  enabled: !!process.env.NEXT_PUBLIC_SENTRY_DSN,

  // Tag environment para distinguir staging vs prod en el UI Sentry.
  environment: process.env.NEXT_PUBLIC_VERCEL_ENV
    || process.env.NEXT_PUBLIC_SENTRY_ENV
    || 'development',

  // Integraciones default (browser tracing) — auto incluyen fetch
  // instrumentation con trace propagation a /api/* y al backend.
  integrations: [
    Sentry.browserTracingIntegration(),
  ],

  // Ignore errores de extensiones del browser + bots que generan ruido.
  ignoreErrors: [
    'ResizeObserver loop limit exceeded',
    'Non-Error promise rejection captured',
    /^Network request failed$/,  // intermitente, ya manejado en cada caller
  ],
})
