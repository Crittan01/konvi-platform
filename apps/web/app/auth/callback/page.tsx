'use client'

/**
 * /auth/callback — Client Component para invite flow (implicit).
 *
 * inviteUserByEmail envía un email con tokens en el URL fragment (#access_token=...).
 * Los hash fragments nunca llegan al servidor → no pueden manejarse en un Route Handler.
 * Este componente los lee en el browser y establece la sesión con setSession().
 *
 * Flujos manejados:
 *   - #access_token= + #refresh_token= (invite, magic link implicit)
 *
 * Para PKCE (resetPasswordForEmail) y OTP (token_hash) → ver /auth/confirm/route.ts
 */

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'
import { Loader2, AlertCircle } from 'lucide-react'

function AuthCallbackInner() {
  const router       = useRouter()
  const searchParams = useSearchParams()
  const [error, setError] = useState<string | null>(null)

  const next = searchParams.get('next') ?? '/set-password'

  useEffect(() => {
    const hash = typeof window !== 'undefined' ? window.location.hash : ''
    const supabase = createClient()

    async function handleCallback() {
      try {
        if (hash.includes('access_token=')) {
          const params       = new URLSearchParams(hash.substring(1))
          const accessToken  = params.get('access_token')
          const refreshToken = params.get('refresh_token')

          if (accessToken && refreshToken) {
            const { error } = await supabase.auth.setSession({
              access_token: accessToken,
              refresh_token: refreshToken,
            })
            if (error) throw error
            router.replace(next)
            return
          }
        }
        setError('Enlace de invitación inválido o expirado. Solicita una nueva invitación.')
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Error desconocido')
      }
    }

    handleCallback()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4 px-4">
        <div className="flex items-start gap-3 p-4 rounded-xl border border-red-700/30 bg-red-500/10 text-sm text-red-700 max-w-md w-full">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Enlace inválido</p>
            <p className="text-xs text-red-700/70 mt-0.5">{error}</p>
          </div>
        </div>
        <a href="/login" className="text-xs text-primary underline">Ir al inicio de sesión</a>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-3">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      <p className="text-xs text-muted-foreground">Verificando invitación…</p>
    </div>
  )
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    }>
      <AuthCallbackInner />
    </Suspense>
  )
}
