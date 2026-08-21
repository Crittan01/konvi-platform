/** @type {import('next').NextConfig} */

// G5: la lógica de orígenes para CSP (parseOrigin/toWsOrigin/unique + csp*)
// se movió a apps/web/lib/csp.ts — aquí solo queda lo que usa remotePatterns.
function parseHostname(url) {
  if (!url) return null
  try {
    return new URL(url).hostname
  } catch {
    return null
  }
}

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
  // Rev. 107 fix runtime KAIU 2026-05-24: 16 productos KAIU poblados con
  // cover_image_url apuntando a placeholders HTTPS por defecto cuando
  // tenant no sube imágenes reales.
  //
  // placehold.co retorna SVG sin XML prolog → Next.js detectContentType()
  // no lo reconoce (espera bytes mágicos `<?xml`) → rechaza con "isn't a
  // valid image" aunque dangerouslyAllowSVG=true (bug detección Next.js).
  //
  // dummyimage.com retorna PNG real → pasa por el optimizer sin problema.
  // Mantenemos placehold.co como host whitelisted para compat retro.
  {
    protocol: 'https',
    hostname: 'placehold.co',
  },
  {
    protocol: 'https',
    hostname: 'dummyimage.com',
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
  // G5 (2026-08-13): la CSP YA NO se emite aquí. La estática tenía
  // `script-src 'unsafe-inline' 'unsafe-eval'` (defensa XSS neutralizada).
  // Ahora la construye el proxy por request con nonce + 'strict-dynamic'
  // (apps/web/lib/csp.ts + proxy.ts). Si añades proveedores externos,
  // actualiza lib/csp.ts (no aquí).
]

const nextConfig = {
  // STG local (2026-08-21): permitir ver el dev server desde otro equipo de la
  // LAN (la IP de la VM). Sin esto, Next 16 bloquea el origen por protección
  // anti-DNS-rebinding: el HMR ws moría con ERR_INVALID_HTTP_RESPONSE y la
  // página servida por LAN nunca hidrataba (formularios nativos sin React).
  // Solo aplica a `next dev`; producción (Render) no usa dev origins.
  allowedDevOrigins: ['192.168.20.5'],

  // Sem 5 perf (rev. 105 2026-05-07): activa gzip en respuestas Next.
  // Reduce 3-4x el tamaño de bundles JS (.js dev son 6.5MB sin
  // comprimir; con gzip ~1.5-2MB). Crítico para devs accediendo via
  // SSH port-forward a VM remota: sin compress, cada page load
  // descargaba MB de bundles dev por el túnel.
  // Producción Render no se afecta (static assets ya van por CDN).
  compress: true,

  images: {
    remotePatterns,
    // Rev. 107 fix runtime KAIU 2026-05-24 web.log:
    // placehold.co retorna content-type=image/svg+xml (legítimo, su API
    // genera SVG dinámico). Next.js Image bloquea SVG por defecto (riesgo
    // XSS si fuente no confiable). placehold.co está en remotePatterns
    // (whitelisted hostname) → safe para nuestro caso. CSP estricta
    // adicional para defensa en profundidad.
    dangerouslyAllowSVG: true,
    contentSecurityPolicy: "default-src 'self'; script-src 'none'; sandbox;",
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
