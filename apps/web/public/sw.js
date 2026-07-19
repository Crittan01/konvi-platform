/*
 * Service worker mínimo y CONSERVADOR — Web UX Fase 0 (PWA instalable).
 *
 * Objetivo: habilitar la instalabilidad (requiere un SW con handler de fetch) y
 * acelerar los assets estáticos, SIN riesgo de servir contenido obsoleto.
 *
 * Estrategia: cache-first SOLO para `/_next/static/**` — assets con hash de
 * contenido en el nombre → inmutables → cachearlos nunca sirve algo viejo.
 * TODO lo demás (navegaciones, API, auth, /_next/data, imágenes) NO se
 * intercepta → el navegador usa su fetch normal (network). Así no se rompe
 * el login/redirects ni se cachea data dinámica.
 *
 * Offline real (cachear navegaciones + fallback) se difiere: requiere testing
 * en navegador para no romper flujos autenticados.
 */
const CACHE = 'konvi-static-v1'

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys()
      await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return

  let url
  try {
    url = new URL(req.url)
  } catch {
    return
  }

  // Solo assets inmutables del build de Next (hash en el nombre).
  const isImmutableStatic =
    url.origin === self.location.origin && url.pathname.startsWith('/_next/static/')
  if (!isImmutableStatic) return // resto → fetch normal del navegador

  event.respondWith(
    (async () => {
      const cached = await caches.match(req)
      if (cached) return cached
      const res = await fetch(req)
      if (res && res.ok) {
        const cache = await caches.open(CACHE)
        cache.put(req, res.clone())
      }
      return res
    })(),
  )
})
