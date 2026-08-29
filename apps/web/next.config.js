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
  // GREEN-27 (auditoría OWASP 2026-08-23): placehold.co / dummyimage.com
  // RETIRADOS de remotePatterns — grep repo-wide (apps/web, services,
  // supabase/migrations; 2026-08-28) sin ningún uso en código, seeds ni
  // migraciones. Hosts de terceros en remotePatterns amplían la superficie
  // del optimizer de imágenes sin necesidad. (Histórico: Rev. 107 los añadió
  // por 16 productos KAIU con cover_image_url placeholder en datos live.)
]

// GREEN-27: orígenes dev permitidos SOLO en development y configurables por
// env (NEXT_ALLOWED_DEV_ORIGINS, CSV). Antes la IP de la VM estaba
// hardcodeada y se emitía en cualquier entorno. Fallback: la IP histórica.
const allowedDevOrigins = process.env.NODE_ENV === 'development'
  ? (process.env.NEXT_ALLOWED_DEV_ORIGINS?.split(',').map(s => s.trim()).filter(Boolean) ?? ['192.168.20.5'])
  : null
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
  // CABO 1 (programa WOW 2026-08-28): View Transitions de React en App Router.
  // Habilita que las navegaciones de ruta se ejecuten como transiciones del
  // navegador; el crossfade sutil del contenido de página lo disparan el
  // wrapper <ViewTransition> de app/dashboard/layout.tsx + el CSS
  // ::view-transition-* de globals.css (con reduced-motion respetado).
  experimental: {
    viewTransition: true,
  },

  // STG local (2026-08-21): permitir ver el dev server desde otro equipo de la
  // LAN (la IP de la VM). Sin esto, Next 16 bloquea el origen por protección
  // anti-DNS-rebinding: el HMR ws moría con ERR_INVALID_HTTP_RESPONSE y la
  // página servida por LAN nunca hidrataba (formularios nativos sin React).
  // Solo aplica a `next dev`; producción (Render) no usa dev origins.
  // GREEN-27: la key solo se emite en development (ver `allowedDevOrigins`
  // computado arriba — env NEXT_ALLOWED_DEV_ORIGINS con fallback histórico).
  ...(allowedDevOrigins ? { allowedDevOrigins } : {}),

  // Sem 5 perf (rev. 105 2026-05-07): activa gzip en respuestas Next.
  // Reduce 3-4x el tamaño de bundles JS (.js dev son 6.5MB sin
  // comprimir; con gzip ~1.5-2MB). Crítico para devs accediendo via
  // SSH port-forward a VM remota: sin compress, cada page load
  // descargaba MB de bundles dev por el túnel.
  // Producción Render no se afecta (static assets ya van por CDN).
  compress: true,

  images: {
    remotePatterns,
    // Next.js Image bloquea SVG por defecto (riesgo XSS si la fuente no es
    // confiable). Se habilita para assets propios (logos/imágenes de catálogo
    // en el bucket de Storage) con el remotePatterns acotado de arriba y la
    // CSP estricta de abajo como defensa en profundidad.
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
