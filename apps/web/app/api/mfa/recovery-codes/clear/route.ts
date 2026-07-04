/**
 * Proxy DELETE /api/mfa/recovery-codes/clear
 *
 * Rev. 109 J.2.4.3.
 */
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

export async function DELETE(req: NextRequest) {
  const sb = await createClient()
  const { data: { session } } = await sb.auth.getSession()
  const headerAuth = req.headers.get('Authorization') || ''
  const token = session?.access_token ?? (
    headerAuth.startsWith('Bearer ') ? headerAuth.slice('Bearer '.length) : null
  )
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/mfa/recovery-codes/clear`,
      {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` },
        signal: AbortSignal.timeout(10000),
      },
    )
    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json({ detail: 'No se pudieron borrar los códigos.' }, { status: 503 })
  }
}
