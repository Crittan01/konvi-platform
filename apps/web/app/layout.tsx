import './globals.css'
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { Toaster } from '@/components/ui/sonner'
import { ConfirmProvider } from '@/components/ui/confirm-dialog'
import { ThemeProvider } from '@/components/theme/theme-provider'

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
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="es" className={inter.variable} suppressHydrationWarning>
      <body className="antialiased font-sans">
        {/* Anti-FOUC: primer hijo del body, corre síncrono antes del paint. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
        <ThemeProvider>
          <ConfirmProvider>{children}</ConfirmProvider>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  )
}
