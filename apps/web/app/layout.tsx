import './globals.css'
import type { Metadata } from 'next'

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
    <html lang="es">
      <body className="antialiased font-sans">{children}</body>
    </html>
  )
}
