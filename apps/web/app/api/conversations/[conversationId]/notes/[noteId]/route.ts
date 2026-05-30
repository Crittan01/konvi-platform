import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

/**
 * Proxy nota individual — PATCH + DELETE.
 *
 * PATCH /api/conversations/[id]/notes/[noteId]   → edita content / is_pinned.
 * DELETE /api/conversations/[id]/notes/[noteId]  → soft-delete (deleted_at).
 */

const UPSTREAM_TIMEOUT_MS = 10000

async function _authToken(req: NextRequest): Promise<string | null> {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  if (session?.access_token) return session.access_token
  const auth = req.headers.get('Authorization') || ''
  return auth.startsWith('Bearer ') ? auth.slice('Bearer '.length) : null
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: { conversationId: string; noteId: string } },
) {
  const token = await _authToken(req)
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  const { conversationId, noteId } = params
  const body = await req.json().catch(() => ({}))

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/conversations/${conversationId}/notes/${noteId}`,
      {
        method: 'PATCH',
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
    return NextResponse.json({ detail: 'No se pudo actualizar la nota.' }, { status: 503 })
  }
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { conversationId: string; noteId: string } },
) {
  const token = await _authToken(req)
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  const { conversationId, noteId } = params

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/conversations/${conversationId}/notes/${noteId}`,
      {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` },
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      },
    )
    if (upstream.status === 204) return new NextResponse(null, { status: 204 })
    const data = await upstream.json().catch(() => ({ detail: 'Error' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json({ detail: 'No se pudo eliminar la nota.' }, { status: 503 })
  }
}
