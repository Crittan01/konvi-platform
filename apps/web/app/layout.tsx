import './globals.css'
import type { Metadata, Viewport } from 'next'
import { headers } from 'next/headers'
import { Inter } from 'next/font/google'
import { Toaster } from '@/components/ui/sonner'
import { ConfirmProvider } from '@/components/ui/confirm-dialog'
import { ThemeProvider } from '@/components/theme/theme-provider'
import { ServiceWorkerRegister } from '@/components/pwa/sw-register'

// Script anti-FOUC: corre síncrono antes del primer paint y fija la clase .dark
// desde la preferencia guardada o del sistema → sin flash claro→oscuro. El
// ThemeProvider luego sincroniza el estado de React con lo ya aplicado.
const THEME_INIT = `(function(){try{var k='konvi-theme',t=localStorage.getItem(k);if(t!=='light'&&t!=='dark'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}var r=document.documentElement;if(t==='dark'){r.classList.add('dark');}r.style.colorScheme=t;}catch(e){}})();`

// F1 2026-07-04: Inter era la fuente DECLARADA del DS (--font-inter en
// globals.css + tailwind font-sans) pero jamás se cargaba — renderizaba el
// fallback del sistema. next/font la self-hostea (subset latino, zero CLS)
// y expone la variable CSS que el DS ya consumía.
const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
})

export const metadata: Metadata = {
  title: 'Konvi Platform',
  description: 'Multi-Tenant Backoffice for WhatsApp Commerce',
  manifest: '/manifest.webmanifest',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'default',
    title: 'Konvi',
  },
}

// Viewport móvil correcto + theme-color por tema (colorea la barra del navegador/
// status bar según claro/oscuro) + viewport-fit cover para respetar el safe-area
// de dispositivos con notch (necesario para el bottom-nav).
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#F8F5F1' },
    { media: '(prefers-color-scheme: dark)', color: '#1A211F' },
  ],
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  // G5: el script anti-FOUC es el único inline propio — lleva el nonce que el
  // proxy generó para este request (CSP script-src 'nonce-…' 'strict-dynamic').
  // En rutas sin proxy (assets) no hay CSP → el script corre igual sin nonce.
  const nonce = (await headers()).get('x-nonce') ?? undefined
  return (
    <html lang="es" className={inter.variable} suppressHydrationWarning>
      <body className="antialiased font-sans">
        {/* Anti-FOUC: primer hijo del body, corre síncrono antes del paint.
            suppressHydrationWarning: el nonce viene del header x-nonce del proxy
            (server, por request) — en dev el client re-renderiza sin ese contexto
            y React reportaba un hydration mismatch cosmético sobre este atributo;
            el valor del server es el autoritativo (así funciona la CSP). */}
        <script nonce={nonce} suppressHydrationWarning dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
        <ThemeProvider>
          <ConfirmProvider>{children}</ConfirmProvider>
          <Toaster />
          <ServiceWorkerRegister />
        </ThemeProvider>
      </body>
    </html>
  )
}
