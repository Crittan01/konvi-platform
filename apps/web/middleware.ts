import { createServerClient, type CookieOptions } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({
    request: {
      headers: request.headers,
    },
  })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return request.cookies.get(name)?.value
        },
        set(name: string, value: string, options: CookieOptions) {
          request.cookies.set({
            name,
            value,
            ...options,
          })
          supabaseResponse = NextResponse.next({
            request: {
              headers: request.headers,
            },
          })
          supabaseResponse.cookies.set({
            name,
            value,
            ...options,
          })
        },
        remove(name: string, options: CookieOptions) {
          request.cookies.set({
            name,
            value: '',
            ...options,
          })
          supabaseResponse = NextResponse.next({
            request: {
              headers: request.headers,
            },
          })
          supabaseResponse.cookies.set({
            name,
            value: '',
            ...options,
          })
        },
      },
    }
  )

  // Recupera la sesión actual para refrescar cookies
  const {
    data: { user },
  } = await supabase.auth.getUser()

  // Si trata de entrar a dashboard y NO hay user, lo patea al login
  if (!user && request.nextUrl.pathname.startsWith('/dashboard')) {
    const url = request.nextUrl.clone()
    url.pathname = '/login'
    return NextResponse.redirect(url)
  }

  // Rev. 109 J.2.4.3 — Enforcement MFA en /dashboard/*.
  // Si user tiene factor TOTP verified pero la sesión actual es solo
  // password (AAL1), bloquea acceso y manda al challenge.
  //
  // Excepciones:
  //   - /login/mfa: el challenge en sí
  //   - Cookie `mfa_recovery_session` HttpOnly seteada por
  //     /api/mfa/recovery-codes/verify cuando recovery code OK.
  //     Vigencia 24h. Permite acceso AAL1 si el user usó código de respaldo
  //     (no podemos forzar TOTP factor si lo perdió).
  if (user && request.nextUrl.pathname.startsWith('/dashboard')) {
    const recoveryBypass = request.cookies.get('mfa_recovery_session')?.value === '1'
    if (!recoveryBypass) {
      try {
        const { data: aalData } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
        const needsMfa =
          aalData?.nextLevel === 'aal2' && aalData.currentLevel === 'aal1'
        if (needsMfa) {
          const url = request.nextUrl.clone()
          url.pathname = '/login/mfa'
          return NextResponse.redirect(url)
        }
      } catch {
        // Si el check de AAL falla (network/timeout), prefer fail open
        // para no bloquear users por outage temporal de Supabase Auth.
      }
    }
  }

  // Nota: cuentas inactivas son manejadas nativamente por Supabase Auth (ban_duration).
  // Un usuario baneado no puede obtener sesión válida — getUser() retorna null → redirect a /login.
  // No se necesita check adicional aquí.

  return supabaseResponse
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|login|forgot-password|auth/confirm|auth/callback|cuenta-suspendida|api).*)',
  ],
}
