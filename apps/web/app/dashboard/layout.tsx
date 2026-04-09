import * as React from "react"
import Link from 'next/link'
import { redirect } from 'next/navigation'
import { LayoutDashboard, ShoppingCart, MessageSquare, LogOut } from 'lucide-react'
import { createClient } from '@/utils/supabase/server'

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  const logoutAction = async () => {
    'use server'
    const supabase = createClient()
    await supabase.auth.signOut()
    redirect('/login')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar V2 */}
      <aside className="w-64 border-r bg-card flex flex-col justify-between">
        <div className="py-6 px-4">
          <h2 className="text-xl font-bold tracking-tight text-primary px-2 mb-8">Commerce Ops</h2>
          <nav className="space-y-2">
            <Link href="/dashboard" className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground text-muted-foreground">
              <LayoutDashboard className="h-4 w-4" /> Resumen
            </Link>
            <Link href="/dashboard/catalog" className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground text-muted-foreground">
              <ShoppingCart className="h-4 w-4" /> Catálogo
            </Link>
            <Link href="/dashboard/inbox" className="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground text-muted-foreground">
              <MessageSquare className="h-4 w-4" /> Inbox AI
            </Link>
          </nav>
        </div>

        <div className="border-t p-4">
          <div className="flex items-center justify-between px-2 py-2">
            <div className="flex items-center gap-3">
              <div className="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center font-bold text-primary">
                {user?.email?.charAt(0).toUpperCase()}
              </div>
              <div className="flex flex-col">
                <span className="text-sm font-medium">{user?.email?.split('@')[0]}</span>
                <span className="text-xs text-muted-foreground">Operador</span>
              </div>
            </div>
            <form action={logoutAction}>
              <button
                type="submit"
                title="Cerrar sesión"
                className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </form>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-8">
        {children}
      </main>
    </div>
  )
}
