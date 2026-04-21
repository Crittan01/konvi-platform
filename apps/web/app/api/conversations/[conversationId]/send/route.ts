import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'

const API_URL = process.env.API_URL ?? 'https://commerce-ops-api.onrender.com'
const UPSTREAM_TIMEOUT_MS = 30000

export async function POST(
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

  const idempotencyKey = req.headers.get('Idempotency-Key')

  try {
    const upstream = await fetch(
      `${API_URL}/api/v1/conversations/${params.conversationId}/send`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
        },
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
