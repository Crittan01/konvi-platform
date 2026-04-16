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
 *   1. Implicit (invite):  #access_token=... → parseado explícitamente con setSession()
 *   2. PKCE:               ?code=...         → exchangeCodeForSession
 *   3. OTP / magic link:   ?token_hash=...   → verifyOtp
 *
 * Por qué setSession() y no detectSessionInUrl/onAuthStateChange:
 *   createBrowserClient puede disparar SIGNED_IN durante su inicialización,
 *   antes de que onAuthStateChange esté suscrito → race condition → timeout falso.
 *   setSession() es explícito y síncrono: no depende de eventos ni de timing.
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
    // Capturar hash ANTES de createClient() para evitar que detectSessionInUrl
    // lo borre via history.replaceState durante su inicialización async.
    const hash = typeof window !== 'undefined' ? window.location.hash : ''

    const supabase = createClient()

    async function confirm() {
      try {
        // ── 1. PKCE flow (password reset, etc.) ──────────────────────────
        if (code) {
          const { error } = await supabase.auth.exchangeCodeForSession(code)
          if (error) throw error
          router.replace(next)
          return
        }

        // ── 2. OTP / magic link ───────────────────────────────────────────
        if (tokenHash && type) {
          const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type })
          if (error) throw error
          router.replace(next)
          return
        }

        // ── 3. Implicit flow (invite) ─────────────────────────────────────
        // setSession() explícito con tokens del hash — patrón recomendado por Supabase
        // (ver github.com/orgs/supabase/discussions/21097).
        // NO usamos onAuthStateChange: GoTrueClient despacha SIGNED_IN con setTimeout(0)
        // y no hay garantía de recibirlo si nos suscribimos después de initialize().
        if (hash.includes('access_token=')) {
          const params       = new URLSearchParams(hash.substring(1))
          const accessToken  = params.get('access_token')
          const refreshToken = params.get('refresh_token')

          if (accessToken && refreshToken) {
            const { error } = await supabase.auth.setSession({ access_token: accessToken, refresh_token: refreshToken })
            if (error) throw error
            router.replace(next)
            return
          }
        }

        // ── 4. Sin parámetros válidos ─────────────────────────────────────
        setError('El enlace ha expirado o ya fue utilizado. Solicita una nueva invitación al Administrador.')

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
