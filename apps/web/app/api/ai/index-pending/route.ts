/**
 * POST /api/ai/index-pending
 * Genera embeddings para todos los documentos KB activos sin embedding del tenant.
 *
 * G20 (drift D3): proxy a FastAPI POST /api/v1/ai/index-pending — el cómputo de
 * embeddings vive en el servicio `api` (GEMINI_API_KEY ya NO existe en el web).
 * La URL pública no cambia: index-pending-banner.tsx sigue llamando aquí.
 *
 * Se conserva la validación local de sesión/rol (mismo copy hacia el banner) y
 * el shape de respuesta ({indexed, total} o {error}). El rate-limit (6/h) y el
 * audit trail viven ahora en el router del api.
 */
import { type NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

export const maxDuration = 60  // API Route puede tomar hasta 60s

// Cada embed puede tomar ~1s (con retries del cascade, más). 55s deja margen
// bajo maxDuration para una corrida con varios docs pendientes.
const UPSTREAM_TIMEOUT_MS = 55_000

/** Traduce el error de FastAPI ({detail}) al shape que el banner lee ({error}). */
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

export async function POST(_request: NextRequest) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'No autenticado' }, { status: 401 })

  const m = (user.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id) return NextResponse.json({ error: 'Sin tenant' }, { status: 403 })
  // Paridad con /api/v1/knowledge-base/{id}/reindex: solo roles de escritura.
  if (!['owner', 'manager'].includes(m.role ?? '')) {
    return NextResponse.json({ error: 'No tienes permiso para preparar documentos.' }, { status: 403 })
  }

  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
  if (!token) return NextResponse.json({ error: 'Sesión expirada' }, { status: 401 })

  try {
    const upstream = await fetch(`${CORE_API_URL}/api/v1/ai/index-pending`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
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
        { error: 'La preparación de documentos tardó demasiado. Reintenta en unos minutos.' },
        { status: 503 },
      )
    }
    return NextResponse.json(
      { error: 'No se pudo conectar con el servicio de IA.' },
      { status: 503 },
    )
  }
}
