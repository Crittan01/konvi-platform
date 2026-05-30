/**
 * Proxy POST /api/mfa/recovery-codes/verify
 *
 * Rev. 109 J.2.4.3 — fix multi-user bug founder 2026-05-29.
 *
 * Si backend valida + consume code correctamente:
 *   1. Setea cookie HttpOnly `mfa_recovery_session` (24h max)
 *      → middleware la acepta como bypass de la verificación AAL2.
 *   2. UI redirige a /dashboard normal.
 *
 * Por qué cookie HttpOnly en lugar de sessionStorage:
 *   - sessionStorage no es visible para el middleware server-side.
 *   - El middleware bloquearía /dashboard al ver AAL1 sin la cookie.
 *   - Cookie firmada + Secure + SameSite=Strict + HttpOnly previene
 *     leaks via XSS.
 *
 * Compromiso de seguridad documentado: usar recovery code permite acceso
 * AAL2-equivalent por 24h pero usuario DEBE regenerar codes + re-enrollar
 * TOTP idealmente en esa sesión. Banner UI lo recordará.
 */
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

const RECOVERY_SESSION_COOKIE = 'mfa_recovery_session'
const RECOVERY_SESSION_MAX_AGE_SECONDS = 24 * 60 * 60 // 24h

export async function POST(req: NextRequest) {
  const sb = createClient()
  const { data: { session } } = await sb.auth.getSession()
  const headerAuth = req.headers.get('Authorization') || ''
  const token = session?.access_token ?? (
    headerAuth.startsWith('Bearer ') ? headerAuth.slice('Bearer '.length) : null
  )
  if (!token) {
    return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })
  }

  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ detail: 'Payload inválido' }, { status: 400 })
  }

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/mfa/recovery-codes/verify`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(10000),
      },
    )

    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))

    // Si el backend OK → setear cookie bypass AAL.
    if (upstream.ok && data.ok) {
      const response = NextResponse.json(data, { status: 200 })
      response.cookies.set({
        name: RECOVERY_SESSION_COOKIE,
        value: '1',
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'strict',
        maxAge: RECOVERY_SESSION_MAX_AGE_SECONDS,
        path: '/',
      })
      return response
    }

    return NextResponse.json(data, { status: upstream.status })
  } catch (error: unknown) {
    if (error instanceof Error && error.name === 'TimeoutError') {
      return NextResponse.json(
        { detail: 'Timeout verificando el código.' },
        { status: 504 },
      )
    }
    return NextResponse.json(
      { detail: 'No se pudo verificar el código.' },
      { status: 503 },
    )
  }
}
