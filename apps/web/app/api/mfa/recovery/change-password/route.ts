/**
 * Proxy POST /api/mfa/recovery/change-password
 *
 * Rev. 109 J.2.4.3 — AAL2 bypass via recovery code para cambio de password.
 */
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

export async function POST(req: NextRequest) {
  const sb = await createClient()
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
      `${CORE_API_URL}/api/v1/mfa/recovery/change-password`,
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
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json({ detail: 'No se pudo cambiar la contraseña.' }, { status: 503 })
  }
}
