import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

const UPSTREAM_TIMEOUT_MS = 30000

export async function PATCH(
  req: NextRequest,
  { params }: { params: { conversationId: string } }
) {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const fallbackAuth = req.headers.get('Authorization') || ''
  const fallbackToken = fallbackAuth.startsWith('Bearer ')
    ? fallbackAuth.slice('Bearer '.length)
    : null
  const token = session?.access_token ?? fallbackToken
  if (!token) {
    return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })
  }

  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ detail: 'Payload inválido' }, { status: 400 })
  }

  // A5: reenviar Idempotency-Key al backend para que dedup funcione end-to-end.
  const idempotencyKey = req.headers.get('Idempotency-Key') || ''
  const upstreamHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  }
  if (idempotencyKey) upstreamHeaders['Idempotency-Key'] = idempotencyKey

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/conversations/${params.conversationId}/status`,
      {
        method: 'PATCH',
        headers: upstreamHeaders,
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      }
    )

    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch (error: unknown) {
    if (
      error instanceof Error &&
      (error.name === 'AbortError' || error.name === 'TimeoutError')
    ) {
      return NextResponse.json(
        {
          detail:
            'El servicio tardó demasiado en responder (posible cold start de Render Free). Intenta de nuevo en unos segundos.',
        },
        { status: 503 }
      )
    }
    return NextResponse.json(
      { detail: 'No se pudo conectar con el servicio de conversaciones.' },
      { status: 503 }
    )
  }
}
