/**
 * POST /api/ai/preview
 * Genera una respuesta de prueba del bot con RAG real + config actual del tenant.
 *
 * G20 (drift D3): proxy a FastAPI POST /api/v1/ai/preview — el cómputo Gemini
 * vive en el servicio `api` (GEMINI_API_KEY ya NO existe en el web). La URL
 * pública no cambia: bot-preview.tsx sigue llamando aquí. Se conservan las
 * validaciones locales (sesión, tenant, mensaje) y el shape de respuesta que
 * el componente espera ({response, kb_used, kb_count, agent_name} o {error}).
 */
import { type NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

const UPSTREAM_TIMEOUT_MS = 30_000

/** Traduce el error de FastAPI ({detail}) al shape que el componente lee ({error}). */
function upstreamError(data: unknown): string {
  const d = (data ?? {}) as { detail?: unknown; error?: unknown }
  if (typeof d.error === 'string') return d.error
  if (typeof d.detail === 'string') return d.detail
  if (Array.isArray(d.detail) && d.detail.length) {
    const first = d.detail[0] as { msg?: string }
    if (typeof first?.msg === 'string') return first.msg
  }
  return 'Error del servidor'
}

export async function POST(request: NextRequest) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'No autenticado' }, { status: 401 })

  const m = (user.app_metadata ?? {}) as { tenant_id?: string }
  if (!m.tenant_id) return NextResponse.json({ error: 'Sin tenant' }, { status: 403 })

  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
  if (!token) return NextResponse.json({ error: 'Sesión expirada' }, { status: 401 })

  let message = ''
  let agentId = ''
  try {
    const body = await request.json()
    message = (body.message as string)?.trim() ?? ''
    // Multi-agente: el operador puede elegir QUÉ agente probar. Si no envía
    // agent_id (o el UI tiene 1 solo agente), el api prueba el default.
    agentId = typeof body.agent_id === 'string' ? body.agent_id.trim() : ''
  } catch {
    return NextResponse.json({ error: 'Body inválido' }, { status: 400 })
  }
  if (!message) return NextResponse.json({ error: 'Mensaje requerido' }, { status: 400 })
  if (message.length > 500) return NextResponse.json({ error: 'Mensaje demasiado largo (máx 500 chars)' }, { status: 400 })

  try {
    const upstream = await fetch(`${CORE_API_URL}/api/v1/ai/preview`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ message, ...(agentId ? { agent_id: agentId } : {}) }),
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    })

    const data = await upstream.json().catch(() => ({}))
    if (!upstream.ok) {
      return NextResponse.json({ error: upstreamError(data) }, { status: upstream.status })
    }
    return NextResponse.json(data)
  } catch (error: unknown) {
    if (
      error instanceof Error &&
      (error.name === 'AbortError' || error.name === 'TimeoutError')
    ) {
      return NextResponse.json(
        { error: 'El servicio de IA tardó demasiado en responder. Intenta de nuevo.' },
        { status: 503 },
      )
    }
    return NextResponse.json(
      { error: 'No se pudo conectar con el servicio de IA.' },
      { status: 503 },
    )
  }
}
