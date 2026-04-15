/** @type {import('next').NextConfig} */

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
      // Imágenes: mismo origen + Supabase Storage + data URIs
      "img-src 'self' data: blob: https://***SUPABASE_PROJECT_REF_REDACTED***.supabase.co",
      // Conexiones API: mismo origen + Supabase + Render services
      // IMPORTANTE: actualizar si los nombres de servicio de Render cambian
      "connect-src 'self' https://***SUPABASE_PROJECT_REF_REDACTED***.supabase.co wss://***SUPABASE_PROJECT_REF_REDACTED***.supabase.co https://commerce-ops-web.onrender.com https://commerce-ops-api.onrender.com https://commerce-ops-orchestrator.onrender.com https://commerce-ops-connector.onrender.com",
      // Frames: ninguno
      "frame-src 'none'",
    ].join('; '),
  },
]

const nextConfig = {
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '***SUPABASE_PROJECT_REF_REDACTED***.supabase.co',
        port: '',
        pathname: '/storage/v1/object/public/**',
      },
    ],
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
