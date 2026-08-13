// G5 (auditoría full-stack 2026-08-13) — Content-Security-Policy con nonce por request.
//
// Antes: CSP estática en next.config.js con `script-src 'unsafe-inline'
// 'unsafe-eval'` → la defensa XSS principal quedaba neutralizada (cualquier
// script inline inyectado hubiera corrido). Ahora: nonce por request generado
// en el proxy + 'strict-dynamic'. Los scripts que Next renderiza reciben el
// nonce del request header `x-nonce` (mecánica oficial App Router) y el único
// script inline propio (anti-FOUC del theme en app/layout.tsx) lo lee vía
// headers(). Cualquier script inline SIN nonce queda bloqueado — esa es la
// defensa.
//
// Decisiones:
//  - 'unsafe-eval' SOLO en desarrollo (React Refresh lo exige); en prod jamás.
//  - upgrade-insecure-requests SOLO en prod (dev corre en http://localhost).
//  - style-src conserva 'unsafe-inline' (Tailwind inline styles); riesgo bajo
//    con object-src 'none' y scripts bajo nonce.
//  - worker-src 'self' por el service worker /sw.js (PWA).
//  - Si se añaden más proveedores externos, actualizar aquí (antes estaba en
//    next.config.js).

function parseOrigin(url: string | undefined): string | null {
  if (!url) return null
  try {
    return new URL(url).origin
  } catch {
    return null
  }
}

function toWsOrigin(httpOrigin: string | null): string | null {
  if (!httpOrigin) return null
  if (httpOrigin.startsWith('https://')) return httpOrigin.replace('https://', 'wss://')
  if (httpOrigin.startsWith('http://')) return httpOrigin.replace('http://', 'ws://')
  return null
}

function unique(values: Array<string | null>): string[] {
  return Array.from(new Set(values.filter((v): v is string => Boolean(v))))
}

export function buildCsp(nonce: string, isDev: boolean): string {
  const supabaseOrigin = parseOrigin(process.env.NEXT_PUBLIC_SUPABASE_URL)
  const supabaseWsOrigin = toWsOrigin(supabaseOrigin)
  const appOrigin = parseOrigin(process.env.NEXT_PUBLIC_APP_URL || process.env.APP_URL)
  const apiOrigin = parseOrigin(process.env.API_URL)
  const orchestratorOrigin = parseOrigin(process.env.ORCHESTRATOR_URL)
  const connectorOrigin = parseOrigin(process.env.CONNECTOR_URL)

  const imgSrc = unique([
    "'self'",
    'data:',
    'blob:',
    supabaseOrigin,
    'https://http2.mlstatic.com',
    'https://mlstatic.com',
  ]).join(' ')

  const connectSrc = unique([
    "'self'",
    supabaseOrigin,
    supabaseWsOrigin,
    appOrigin,
    apiOrigin,
    orchestratorOrigin,
    connectorOrigin,
  ]).join(' ')

  const scriptSrc = [
    "'self'",
    `'nonce-${nonce}'`,
    "'strict-dynamic'",
    ...(isDev ? ["'unsafe-eval'"] : []),
  ].join(' ')

  const directives = [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    `img-src ${imgSrc}`,
    `connect-src ${connectSrc}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-src 'none'",
    "frame-ancestors 'self'",
    "worker-src 'self'",
  ]
  if (!isDev) directives.push('upgrade-insecure-requests')
  return directives.join('; ')
}
