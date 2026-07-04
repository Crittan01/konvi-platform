import './globals.css'
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { Toaster } from '@/components/ui/sonner'
import { ConfirmProvider } from '@/components/ui/confirm-dialog'

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
    <html lang="es" className={inter.variable}>
      <body className="antialiased font-sans">
        <ConfirmProvider>{children}</ConfirmProvider>
        <Toaster />
      </body>
    </html>
  )
}
