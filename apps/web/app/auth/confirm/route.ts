import { type NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import type { EmailOtpType } from '@supabase/supabase-js'

/**
 * Route handler de confirmación de auth.
 * Maneja dos flujos:
 *  1. PKCE: Supabase envía ?code=... → exchangeCodeForSession
 *  2. OTP/Magic link: ?token_hash=...&type=... → verifyOtp
 *
 * El parámetro ?next=/ruta permite redirigir al destino correcto post-verificación.
 * Para invitaciones de equipo, next=/set-password.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url)

  const code      = searchParams.get('code')
  const tokenHash = searchParams.get('token_hash')
  const type      = searchParams.get('type') as EmailOtpType | null
  const next      = searchParams.get('next') ?? '/dashboard'

  const supabase = createClient()

  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) return NextResponse.redirect(`${origin}${next}`)
  } else if (tokenHash && type) {
    const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type })
    if (!error) return NextResponse.redirect(`${origin}${next}`)
  }

  // Token inválido o expirado
  return NextResponse.redirect(`${origin}/login?message=El+enlace+ha+expirado+o+es+inválido.+Solicita+una+nueva+invitación.`)
}
