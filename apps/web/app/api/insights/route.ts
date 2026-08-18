/**
 * /api/insights — panel de análisis IA del dashboard (AiInsightPanel).
 *
 * G20 (drift D3): proxy a FastAPI /api/v1/insights — la agregación Supabase y
 * el prompt a Gemini viven ahora en el servicio `api` (GEMINI_API_KEY ya NO
 * existe en el web). La URL pública no cambia: el panel sigue llamando aquí.
 *
 *   POST {module}       → POST /api/v1/insights   (genera el análisis)
 *   GET  ?module=…      → GET  /api/v1/insights   (último análisis persistido, F4)
 *
 * Se conservan las validaciones locales (sesión, tenant, rol owner/manager,
 * módulo válido) y el shape de respuesta que el componente espera
 * (InsightResult | {insight} | {error}). El rate-limit (10/h), la
 * persistencia en ai_insights y el audit trail viven ahora en el router del api.
 */
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

type InsightModule = 'inventory' | 'orders' | 'contacts' | 'metrics'
const VALID_MODULES: InsightModule[] = ['inventory', 'orders', 'contacts', 'metrics']

// Agregación + cascade Gemini: el web daba 30s a la llamada Gemini sola; se
// amplía a 45s para absorber cold start del api sin cortar respuestas válidas.
const UPSTREAM_TIMEOUT_MS = 45_000

/** Traduce el error de FastAPI ({detail}) al shape que el panel lee ({error}). */
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

/** Sesión + tenant + rol de escritura (owner/manager) + access_token para el api. */
async function requireWriteSession():
  Promise<{ token: string } | NextResponse> {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'No autorizado' }, { status: 401 })

  const meta = (user.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id) return NextResponse.json({ error: 'Tenant no configurado' }, { status: 403 })
  if (!['owner', 'manager'].includes(meta.role ?? ''))
    return NextResponse.json({ error: 'Sin permisos' }, { status: 403 })

  const { data: { session } } = await supabase.auth.getSession()
  if (!session?.access_token)
    return NextResponse.json({ error: 'Sesión expirada' }, { status: 401 })
  return { token: session.access_token }
}

function upstreamUnavailable(error: unknown): NextResponse {
  if (
    error instanceof Error &&
    (error.name === 'AbortError' || error.name === 'TimeoutError')
  ) {
    return NextResponse.json(
      { error: 'El análisis tardó demasiado. Intenta de nuevo en unos segundos.' },
      { status: 503 },
    )
  }
  return NextResponse.json(
    { error: 'No se pudo conectar con el servicio de análisis.' },
    { status: 503 },
  )
}

export async function POST(req: NextRequest) {
  const auth = await requireWriteSession()
  if (auth instanceof NextResponse) return auth

  let body: { module?: string }
  try {
    body = await req.json() as { module?: string }
  } catch {
    return NextResponse.json({ error: 'Body inválido' }, { status: 400 })
  }
  if (!VALID_MODULES.includes(body.module as InsightModule))
    return NextResponse.json({ error: 'Módulo no válido' }, { status: 400 })

  try {
    const upstream = await fetch(`${CORE_API_URL}/api/v1/insights`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${auth.token}`,
      },
      body: JSON.stringify({ module: body.module }),
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    })

    const data = await upstream.json().catch(() => ({}))
    if (!upstream.ok) {
      return NextResponse.json({ error: upstreamError(data) }, { status: upstream.status })
    }
    return NextResponse.json(data)
  } catch (err) {
    console.error('[insights] proxy POST upstream falló:', { module: body.module, err })
    return upstreamUnavailable(err)
  }
}

// ── GET: último análisis persistido por módulo (decisión F4) ───────────────────
// El panel lo consulta al montar para restaurar el último insight sin gastar
// tokens. Devuelve { insight: null } si no hay (o ante error de red — el panel
// cae a idle, paridad con el comportamiento anterior).
export async function GET(req: NextRequest) {
  const auth = await requireWriteSession()
  if (auth instanceof NextResponse) return auth

  const moduleParam = new URL(req.url).searchParams.get('module')
  if (!VALID_MODULES.includes(moduleParam as InsightModule))
    return NextResponse.json({ error: 'Módulo no válido' }, { status: 400 })

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/insights?module=${encodeURIComponent(moduleParam as string)}`,
      {
        method: 'GET',
        headers: { 'Authorization': `Bearer ${auth.token}` },
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      },
    )

    const data = await upstream.json().catch(() => ({}))
    if (!upstream.ok) {
      return NextResponse.json({ error: upstreamError(data) }, { status: upstream.status })
    }
    return NextResponse.json(data)
  } catch (err) {
    console.error('[insights] proxy GET upstream falló:', { module: moduleParam, err })
    return NextResponse.json({ insight: null })
  }
}
