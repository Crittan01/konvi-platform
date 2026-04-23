import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

/**
 * GET /api/conversations/[conversationId]/context
 *
 * Endpoint server-side que agrega en una sola respuesta:
 * - Datos del contacto (si existe en contacts por customer_phone)
 * - Últimos 5 pedidos vinculados al contacto o conversación
 * - Conteo de productos activos y productos con bajo stock del tenant
 * - Lista de productos activos con variantes (para panel de catálogo en Inbox)
 *
 * Seguridad:
 * - Autenticación por sesión SSR (getSession server-side) o token Bearer del cliente.
 * - tenant_id viene del JWT del usuario autenticado — no del cliente.
 * - Todas las queries usan service_role con filtro explícito tenant_id.
 */

const UPSTREAM_TIMEOUT_MS = 20000

export async function GET(
  req: NextRequest,
  { params }: { params: { conversationId: string } }
) {
  const supabase = createClient()

  const {
    data: { user },
  } = await supabase.auth.getUser()

  const fallbackAuth = req.headers.get('Authorization') || ''
  const fallbackToken = fallbackAuth.startsWith('Bearer ')
    ? fallbackAuth.slice('Bearer '.length)
    : null

  // Necesitamos token para el upstream API.
  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token ?? fallbackToken

  if (!token || !user) {
    return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })
  }

  const { conversationId } = params
  if (!conversationId) {
    return NextResponse.json({ detail: 'conversationId requerido' }, { status: 400 })
  }

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/conversations/${conversationId}/context`,
      {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
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
        { detail: 'Timeout al cargar contexto. Intenta de nuevo.' },
        { status: 503 }
      )
    }
    return NextResponse.json(
      { detail: 'No se pudo cargar el contexto de la conversación.' },
      { status: 503 }
    )
  }
}
