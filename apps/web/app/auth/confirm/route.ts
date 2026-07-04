/**
 * Route Handler para verificación de email — PKCE y OTP.
 *
 * Por qué Route Handler y no Client Component:
 *   En un Client Component, exchangeCodeForSession lee el code_verifier de las cookies
 *   del browser. Si el link de recuperación se abre en un browser distinto al que
 *   generó el verifier (ej: cliente de email, incógnito, VM con port-forwarding),
 *   el cookie no está disponible y falla con "PKCE code verifier not found".
 *
 *   Con Route Handler + @supabase/ssr, el server lee las cookies directamente del
 *   HTTP request. Si el browser que generó el verifier es el mismo que sigue el link,
 *   las cookies van en el request y el exchange funciona correctamente.
 *
 * Flujos manejados:
 *   - ?code=        → PKCE (resetPasswordForEmail, email confirm)
 *   - ?token_hash=  → OTP (magic link, recovery OTP)
 *
 * Flujo NO manejado aquí (hash fragment, invisible al servidor):
 *   - #access_token= → implicit (inviteUserByEmail) → ver /auth/callback
 */
import { type NextRequest, NextResponse } from 'next/server'
import { type EmailOtpType } from '@supabase/supabase-js'
import { createServerClient, type CookieOptions } from '@supabase/ssr'
import { cookies } from 'next/headers'

export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url)
  const code      = searchParams.get('code')
  const tokenHash = searchParams.get('token_hash')
  const type      = searchParams.get('type') as EmailOtpType | null
  const next      = searchParams.get('next') ?? '/dashboard'

  const cookieStore = await cookies()

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    (process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY)!,
    {
      cookies: {
        get(name: string) {
          return cookieStore.get(name)?.value
        },
        set(name: string, value: string, options: CookieOptions) {
          cookieStore.set({ name, value, ...options })
        },
        remove(name: string, options: CookieOptions) {
          cookieStore.set({ name, value: '', ...options })
        },
      },
    }
  )

  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) {
      return NextResponse.redirect(new URL(next, origin))
    }
    const msg = encodeURIComponent(error.message)
    return NextResponse.redirect(new URL(`/login?error=${msg}`, origin))
  }

  if (tokenHash && type) {
    const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type })
    if (!error) {
      return NextResponse.redirect(new URL(next, origin))
    }
    const msg = encodeURIComponent(error.message)
    return NextResponse.redirect(new URL(`/login?error=${msg}`, origin))
  }

  // Sin parámetros de verificación → enlace inválido o expirado
  return NextResponse.redirect(
    new URL('/login?error=Enlace+inv%C3%A1lido+o+expirado.+Solicita+uno+nuevo.', origin)
  )
}
