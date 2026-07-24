import { createServerClient, type CookieOptions } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'
import { verifyRecoveryCookie } from '@/lib/mfa-recovery-cookie'

// Next 16: `middleware.ts` (Edge) fue renombrado a `proxy.ts` (runtime NODEJS,
// no configurable). El export DEBE llamarse `proxy` — con otro nombre Next NO lo
// invoca y el gate MFA/AAL2 desaparecería SIN error de build (bypass silencioso).
// NO agregar `export const runtime` aquí: el config `runtime` no está disponible
// en Proxy y LANZA error. El helper HMAC (verifyRecoveryCookie) usa Web Crypto
// (crypto.subtle), que ya corre en nodejs en el resto del código server-side.
export async function proxy(request: NextRequest) {
  let supabaseResponse = NextResponse.next({
    request: {
      headers: request.headers,
    },
  })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    (process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY)!,
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

  // Si trata de entrar a dashboard y NO hay user, lo patea al login.
  // Deep-link: preserva el destino en `?next=` para volver ahí tras autenticar
  // (el path viene del request → inherentemente same-origin; el consumidor lo
  // revalida con safeNextPath antes de redirigir).
  if (!user && request.nextUrl.pathname.startsWith('/dashboard')) {
    const dest = request.nextUrl.pathname + request.nextUrl.search
    const url = request.nextUrl.clone()
    url.pathname = '/login'
    url.search = ''
    url.searchParams.set('next', dest)
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
  // F85: el enforcement AAL2 ahora cubre TAMBIÉN /api/* (antes el matcher excluía `api`, así que
  // una sesión solo-password podía llamar GET /api/audit/export, POST /api/conversations/{id}/send,
  // etc. — MFA era cosmético a nivel API). Excepción: /api/mfa/* (flujo de recovery pre-AAL2).
  const _path = request.nextUrl.pathname
  const _isApi = _path.startsWith('/api')
  const _isMfaApi = _path.startsWith('/api/mfa/')
  const _mfaGated = _path.startsWith('/dashboard') || (_isApi && !_isMfaApi)
  if (user && _mfaGated) {
    // F83: verificar la FIRMA HMAC de la cookie (ligada a este user + no expirada), no su mera
    // presencia. Antes `=== '1'` dejaba fabricar el bypass con la contraseña robada (sesión AAL1).
    const recoveryBypass = await verifyRecoveryCookie(
      request.cookies.get('mfa_recovery_session')?.value,
      user.id,
      Math.floor(Date.now() / 1000),
    )
    if (!recoveryBypass) {
      try {
        const { data: aalData } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
        const needsMfa =
          aalData?.nextLevel === 'aal2' && aalData.currentLevel === 'aal1'
        if (needsMfa) {
          // F85: /api → 401 JSON (no redirect); /dashboard → challenge TOTP.
          if (_isApi) {
            return NextResponse.json({ detail: 'MFA requerida' }, { status: 401 })
          }
          // Deep-link: preserva el destino para aterrizar ahí tras el challenge.
          const dest = request.nextUrl.pathname + request.nextUrl.search
          const url = request.nextUrl.clone()
          url.pathname = '/login/mfa'
          url.search = ''
          url.searchParams.set('next', dest)
          return NextResponse.redirect(url)
        }
      } catch (e) {
        // Si el check de AAL falla (network/timeout), prefer fail open para no
        // bloquear users por outage temporal de Supabase Auth. F6: se emite una
        // señal (antes el catch era vacío → si el check fallaba de forma
        // sistemática, el gate MFA quedaba desactivado de facto sin que nadie lo
        // supiera). console.error queda en los logs de Render / Sentry.
        console.error(
          '[proxy] AAL2 check falló — fail-open (gate MFA omitido en este request):',
          e instanceof Error ? e.message : e,
        )
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
    // F85: `api` YA NO se excluye — el gate MFA debe correr también para /api/* (los route
    // handlers autenticaban con sesiones AAL1). Los endpoints pre-AAL2 (/api/mfa/*) se exceptúan
    // dentro del handler, no aquí.
    '/((?!_next/static|_next/image|favicon.ico|login|forgot-password|auth/confirm|auth/callback|cuenta-suspendida).*)',
  ],
}
