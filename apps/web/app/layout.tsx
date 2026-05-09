import './globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Konvi · Tu tienda en WhatsApp',
  description: 'Plataforma SaaS para vender por WhatsApp con bot AI, pagos y despachos integrados.',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="es">
      <body className="antialiased font-sans">{children}</body>
    </html>
  )
}
