import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

/**
 * Proxy notes — GET + POST.
 *
 * GET  /api/conversations/[id]/notes        → lista notas vigentes (no deleted).
 * POST /api/conversations/[id]/notes        → crea nota nueva.
 *
 * Patrón canónico Inbox (mirror de context/status/send proxies). Auth
 * via session SSR + fallback Bearer header. Upstream FastAPI maneja RBAC
 * y RLS.
 */

const UPSTREAM_TIMEOUT_MS = 10000

async function _authToken(req: NextRequest): Promise<string | null> {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  if (session?.access_token) return session.access_token
  const auth = req.headers.get('Authorization') || ''
  return auth.startsWith('Bearer ') ? auth.slice('Bearer '.length) : null
}

export async function GET(
  req: NextRequest,
  { params }: { params: { conversationId: string } },
) {
  const token = await _authToken(req)
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  const { conversationId } = params
  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/conversations/${conversationId}/notes`,
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      },
    )
    const data = await upstream.json().catch(() => ([]))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json({ detail: 'No se pudieron cargar las notas.' }, { status: 503 })
  }
}

export async function POST(
  req: NextRequest,
  { params }: { params: { conversationId: string } },
) {
  const token = await _authToken(req)
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  const { conversationId } = params
  const body = await req.json().catch(() => ({}))

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/conversations/${conversationId}/notes`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      },
    )
    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json({ detail: 'No se pudo crear la nota.' }, { status: 503 })
  }
}
