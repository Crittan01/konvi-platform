import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

/**
 * Proxy a FastAPI POST /api/v1/ai-agents/suggest
 *
 * Rev. 109 ADR-0017 — la UI multi-agente llama este proxy. El proxy
 * inyecta el JWT del usuario (vía supabase session) y reenvía al
 * orchestrator API que ejecuta el cascade Gemini para generar el draft.
 */

const UPSTREAM_TIMEOUT_MS = 30_000

export async function POST(req: NextRequest) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) {
    return NextResponse.json({ detail: 'No autenticado' }, { status: 401 })
  }

  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
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
    const upstream = await fetch(`${CORE_API_URL}/api/v1/ai-agents/suggest`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    })

    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch (error: unknown) {
    if (
      error instanceof Error &&
      (error.name === 'AbortError' || error.name === 'TimeoutError')
    ) {
      return NextResponse.json(
        { detail: 'Timeout: la IA tomó más de 30s. Intenta de nuevo.' },
        { status: 503 },
      )
    }
    return NextResponse.json(
      { detail: 'No se pudo conectar con el servicio de IA.' },
      { status: 503 },
    )
  }
}
