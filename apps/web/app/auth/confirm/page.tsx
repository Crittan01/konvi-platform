'use client'

/**
 * /auth/confirm — Client Component (no Route Handler)
 *
 * Por qué client y no server Route Handler:
 *   inviteUserByEmail usa implicit flow → sesión en URL fragment (#access_token=...)
 *   Los browsers eliminan el fragment antes del HTTP request → un Route Handler
 *   nunca lo recibe. Solo el browser puede leer window.location.hash.
 *
 * Flujos manejados:
 *   1. Implicit (invite):  #access_token=... → createBrowserClient lo parsea automáticamente
 *   2. PKCE:               ?code=...         → exchangeCodeForSession
 *   3. OTP / magic link:   ?token_hash=...   → verifyOtp
 */

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'
import type { EmailOtpType } from '@supabase/supabase-js'
import { Loader2, AlertCircle } from 'lucide-react'

function AuthConfirmInner() {
  const router       = useRouter()
  const searchParams = useSearchParams()
  const [error, setError] = useState<string | null>(null)

  const next      = searchParams.get('next') ?? '/dashboard'
  const code      = searchParams.get('code')
  const tokenHash = searchParams.get('token_hash')
  const type      = searchParams.get('type') as EmailOtpType | null

  useEffect(() => {
    const supabase = createClient()

    async function confirm() {
      try {
        if (code) {
          // PKCE flow (password reset, otros)
          const { error } = await supabase.auth.exchangeCodeForSession(code)
          if (error) throw error
          router.replace(next)
          return
        }

        if (tokenHash && type) {
          // OTP / magic link
          const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type })
          if (error) throw error
          router.replace(next)
          return
        }

        // Implicit flow (invite) — createBrowserClient parsea #access_token automáticamente.
        // onAuthStateChange dispara SIGNED_IN cuando la sesión del invitado queda establecida.
        //
        // IMPORTANTE: NO usar getSession() como atajo cuando hay #access_token en la URL.
        // Si el admin está logueado, getSession() devuelve su sesión antes de que el cliente
        // procese el hash del invitado → set-password mostraría la cuenta del admin.
        const hasHashToken = typeof window !== 'undefined' && window.location.hash.includes('access_token')

        const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
          if (event === 'SIGNED_IN' && session) {
            subscription.unsubscribe()
            router.replace(next)
          }
        })

        // Solo usar sesión existente si NO hay token nuevo en el hash
        if (!hasHashToken) {
          const { data: { session } } = await supabase.auth.getSession()
          if (session) {
            subscription.unsubscribe()
            router.replace(next)
            return
          }
        }

        // Si en 5s no hubo SIGNED_IN → el token expiró o fue inválido
        const timeout = setTimeout(() => {
          subscription.unsubscribe()
          setError('El enlace ha expirado o ya fue utilizado. Solicita una nueva invitación al Administrador.')
        }, 5000)

        return () => {
          clearTimeout(timeout)
          subscription.unsubscribe()
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : 'Error desconocido'
        setError(msg)
      }
    }

    confirm()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4 px-4">
        <div className="flex items-start gap-3 p-4 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400 max-w-md w-full">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Enlace inválido</p>
            <p className="text-xs text-red-400/70 mt-0.5">{error}</p>
          </div>
        </div>
        <a href="/login" className="text-xs text-primary underline">
          Ir al inicio de sesión
        </a>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-3">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      <p className="text-xs text-muted-foreground">Verificando enlace…</p>
    </div>
  )
}

export default function AuthConfirmPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    }>
      <AuthConfirmInner />
    </Suspense>
  )
}
