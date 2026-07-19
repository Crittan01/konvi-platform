import type { MetadataRoute } from 'next'

// Web App Manifest — habilita "instalar" (add-to-home-screen) en móvil/desktop.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Konvi',
    short_name: 'Konvi',
    description: 'Backoffice multi-tenant para comercio por WhatsApp',
    start_url: '/dashboard',
    scope: '/',
    display: 'standalone',
    orientation: 'portrait-primary',
    background_color: '#F8F5F1',
    theme_color: '#2E5C4A',
    lang: 'es',
    categories: ['business', 'productivity'],
    icons: [
      { src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
      { src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'maskable' },
      { src: '/apple-icon', sizes: '180x180', type: 'image/png' },
    ],
  }
}
