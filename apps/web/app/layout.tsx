import './globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Commerce Ops Platform',
  description: 'Multi-Tenant Backoffice for WhatsApp Commerce',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="es">
      <body className="antialiased">{children}</body>
    </html>
  )
}
