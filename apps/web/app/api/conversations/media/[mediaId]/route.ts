import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

const UPSTREAM_TIMEOUT_MS = 30000

/**
 * Proxy de media INBOUND de WhatsApp. Un `<img>`/`<audio>` del navegador NO puede mandar el
 * header Authorization: Bearer — por eso el frontend apunta a esta ruta same-origin (autenticada
 * por la cookie de sesión) que reenvía al backend con el Bearer. El backend baja el binario de
 * Meta con el token del tenant (tenant-scoped por media_id) y lo streamea de vuelta.
 *
 * Nota: la ruta estática `media/` tiene prioridad sobre el dinámico `[conversationId]` hermano,
 * así que `/api/conversations/media/{id}` no colisiona con `/api/conversations/{id}/...`.
 */
export async function GET(req: NextRequest, props: { params: Promise<{ mediaId: string }> }) {
  const params = await props.params
  const supabase = await createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
  if (!token) {
    return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })
  }

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/conversations/media/${encodeURIComponent(params.mediaId)}`,
      {
        method: 'GET',
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      },
    )

    if (!upstream.ok) {
      // El backend devuelve JSON de error (404/409/502) — propagar sin exponer binario.
      const err = await upstream.json().catch(() => ({ detail: 'No se pudo obtener el media' }))
      return NextResponse.json(err, { status: upstream.status })
    }

    const body = await upstream.arrayBuffer()
    // Reenviar el Content-Disposition + nosniff que decide el backend (allowlist anti-XSS): un
    // media de tipo activo (html/svg) se sirve como attachment octet-stream y nunca renderiza
    // inline en este origen. Default a attachment si el backend no lo fijó (fail-safe).
    return new NextResponse(body, {
      status: 200,
      headers: {
        'Content-Type': upstream.headers.get('Content-Type') || 'application/octet-stream',
        'Content-Disposition': upstream.headers.get('Content-Disposition') || 'attachment',
        'X-Content-Type-Options': 'nosniff',
        'Cache-Control': upstream.headers.get('Cache-Control') || 'private, max-age=300',
      },
    })
  } catch (error: unknown) {
    if (error instanceof Error && (error.name === 'AbortError' || error.name === 'TimeoutError')) {
      return NextResponse.json({ detail: 'El servicio tardó demasiado en responder.' }, { status: 503 })
    }
    return NextResponse.json({ detail: 'No se pudo conectar con el servicio.' }, { status: 503 })
  }
}
