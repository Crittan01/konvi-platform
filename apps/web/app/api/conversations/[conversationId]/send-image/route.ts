/**
 * Proxy send-image — POST.
 *
 * Rev. 109 P0-2 — outbound humano con attachment imagen.
 *
 * Flujo:
 *   1. UI sube imagen a Supabase Storage 'tenant-media' vía supabase-js
 *      (session del operador, RLS impone tenant_id).
 *   2. UI obtiene URL pública del bucket.
 *   3. UI llama este endpoint con { image_url, caption? }.
 *   4. Backend valida HTTPS + ventana 24h, persiste message tipo imagen,
 *      encola via pgmq con image_link payload.
 *   5. Worker consume, llama send_whatsapp_message(image_link=...).
 */
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

const UPSTREAM_TIMEOUT_MS = 30000

export async function POST(
  req: NextRequest,
  { params }: { params: { conversationId: string } },
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
      `${CORE_API_URL}/api/v1/conversations/${params.conversationId}/send-image`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      },
    )

    const data = await upstream.json().catch(() => ({
      detail: 'Error del servidor al enviar la imagen',
    }))
    return NextResponse.json(data, { status: upstream.status })
  } catch (error: unknown) {
    if (error instanceof Error && error.name === 'TimeoutError') {
      return NextResponse.json(
        { detail: 'Timeout enviando la imagen al servidor.' },
        { status: 504 },
      )
    }
    return NextResponse.json(
      { detail: 'No se pudo enviar la imagen.' },
      { status: 503 },
    )
  }
}
