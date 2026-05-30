/**
 * Proxy POST /api/mfa/recovery-codes/regenerate
 *
 * Rev. 109 J.2.4.3 — MFA recovery codes management.
 */
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

export async function POST(req: NextRequest) {
  const sb = createClient()
  const { data: { session } } = await sb.auth.getSession()
  const headerAuth = req.headers.get('Authorization') || ''
  const token = session?.access_token ?? (
    headerAuth.startsWith('Bearer ') ? headerAuth.slice('Bearer '.length) : null
  )
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/mfa/recovery-codes/regenerate`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        signal: AbortSignal.timeout(10000),
      },
    )
    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json({ detail: 'No se pudieron generar los códigos.' }, { status: 503 })
  }
}
