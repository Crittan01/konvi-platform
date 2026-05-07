/** @type {import('next').NextConfig} */

function parseOrigin(url) {
  if (!url) return null
  try {
    return new URL(url).origin
  } catch {
    return null
  }
}

function parseHostname(url) {
  if (!url) return null
  try {
    return new URL(url).hostname
  } catch {
    return null
  }
}

function toWsOrigin(httpOrigin) {
  if (!httpOrigin) return null
  if (httpOrigin.startsWith('https://')) return httpOrigin.replace('https://', 'wss://')
  if (httpOrigin.startsWith('http://')) return httpOrigin.replace('http://', 'ws://')
  return null
}

function unique(values) {
  return Array.from(new Set(values.filter(Boolean)))
}

const supabaseOrigin = parseOrigin(process.env.NEXT_PUBLIC_SUPABASE_URL)
const supabaseWsOrigin = toWsOrigin(supabaseOrigin)
const appOrigin = parseOrigin(process.env.NEXT_PUBLIC_APP_URL || process.env.APP_URL)
const apiOrigin = parseOrigin(process.env.API_URL)
const orchestratorOrigin = parseOrigin(process.env.ORCHESTRATOR_URL)
const connectorOrigin = parseOrigin(process.env.CONNECTOR_URL)

const cspImgSrc = unique([
  "'self'",
  'data:',
  'blob:',
  supabaseOrigin,
  'https://http2.mlstatic.com',
  'https://mlstatic.com',
]).join(' ')

const cspConnectSrc = unique([
  "'self'",
  supabaseOrigin,
  supabaseWsOrigin,
  appOrigin,
  apiOrigin,
  orchestratorOrigin,
  connectorOrigin,
]).join(' ')

const supabaseStorageHost = parseHostname(process.env.NEXT_PUBLIC_SUPABASE_URL)
const remotePatterns = [
  {
    protocol: 'https',
    hostname: 'http2.mlstatic.com',
  },
  {
    protocol: 'https',
    hostname: 'mlstatic.com',
  },
]
if (supabaseStorageHost) {
  remotePatterns.unshift({
    protocol: 'https',
    hostname: supabaseStorageHost,
    port: '',
    pathname: '/storage/v1/object/public/**',
  })
}

// ── Security Headers ─────────────────────────────────────────────────────────
//
//  Aplicados globalmente a cada respuesta HTTP del frontend.
//  Ref: https://nextjs.org/docs/app/api-reference/next-config-js/headers
//
//  IMPORTANTE para Render:
//  Render no añade estos headers automáticamente — deben estar aquí.
//
const securityHeaders = [
  // Evita clickjacking — solo permite embeberse en el mismo origen
  {
    key: 'X-Frame-Options',
    value: 'SAMEORIGIN',
  },
  // Bloquea MIME type sniffing
  {
    key: 'X-Content-Type-Options',
    value: 'nosniff',
  },
  // Controla referrer en requests cross-origin
  {
    key: 'Referrer-Policy',
    value: 'strict-origin-when-cross-origin',
  },
  // Permisos de APIs del browser — mínimos necesarios para la app
  {
    key: 'Permissions-Policy',
    value: 'camera=(), microphone=(), geolocation=(), interest-cohort=()',
  },
  // HSTS — fuerza HTTPS durante 1 año, incluyendo subdominios
  // Solo efectivo en producción (Render sirve en HTTPS)
  {
    key: 'Strict-Transport-Security',
    value: 'max-age=31536000; includeSubDomains',
  },
  // Content Security Policy
  // Permite: mismo origen, Supabase (API + Storage), Google Fonts, data URIs para imágenes
  // NOTA: Si se añaden más proveedores externos, actualizar esta política aquí
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      // Scripts: mismo origen + inline (Next.js requiere unsafe-inline para hidration)
      "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
      // Estilos: mismo origen + inline (Tailwind) + Google Fonts
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
      // Fuentes
      "font-src 'self' https://fonts.gstatic.com",
      // Imágenes: mismo origen + Supabase Storage + MeLi CDN + data URIs
      `img-src ${cspImgSrc}`,
      // Conexiones API: mismo origen + Supabase + orígenes definidos por env
      `connect-src ${cspConnectSrc}`,
      // Frames: ninguno
      "frame-src 'none'",
    ].join('; '),
  },
]

const nextConfig = {
  // Sem 5 perf (rev. 105 2026-05-07): activa gzip en respuestas Next.
  // Reduce 3-4x el tamaño de bundles JS (.js dev son 6.5MB sin
  // comprimir; con gzip ~1.5-2MB). Crítico para devs accediendo via
  // SSH port-forward a VM remota: sin compress, cada page load
  // descargaba MB de bundles dev por el túnel.
  // Producción Render no se afecta (static assets ya van por CDN).
  compress: true,

  images: {
    remotePatterns,
  },

  async headers() {
    return [
      {
        // Aplicar a todas las rutas
        source: '/(.*)',
        headers: securityHeaders,
      },
    ]
  },
}

module.exports = nextConfig
