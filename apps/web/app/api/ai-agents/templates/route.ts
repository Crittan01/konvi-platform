import { NextRequest, NextResponse } from 'next/server'
import { CORE_API_URL } from '@/lib/runtime-env'

/**
 * Proxy a FastAPI GET /api/v1/ai-agents/templates
 *
 * Rev. 109 ADR-0017 — endpoint público sin auth (templates son globales,
 * no leaks de info per-tenant). El proxy mantiene la convención de
 * URL relativa `/api/...` en el frontend.
 */

export async function GET(_req: NextRequest) {
  try {
    const upstream = await fetch(`${CORE_API_URL}/api/v1/ai-agents/templates`, {
      method: 'GET',
      signal: AbortSignal.timeout(10_000),
    })
    const data = await upstream.json().catch(() => ([]))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json(
      { detail: 'No se pudo cargar templates de agentes.' },
      { status: 503 },
    )
  }
}
