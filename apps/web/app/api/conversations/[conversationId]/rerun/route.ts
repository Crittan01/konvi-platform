import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

/**
 * Proxy rerun IA — POST.
 *
 * Permite al operador re-procesar el último inbound del cliente. El bot
 * genera nuevo outbound con el catálogo/prompt/cupones actualizados.
 *
 * Casos de uso: bot dio respuesta mala → segunda toma. Operador actualizó
 * config y quiere ver el bot con nuevo contexto sin esperar al cliente.
 */

const UPSTREAM_TIMEOUT_MS = 10000

export async function POST(req: NextRequest, props: { params: Promise<{ conversationId: string }> }) {
  const params = await props.params;
  const supabase = await createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const headerAuth = req.headers.get('Authorization') || ''
  const token = session?.access_token ?? (
    headerAuth.startsWith('Bearer ') ? headerAuth.slice('Bearer '.length) : null
  )
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  const { conversationId } = params
  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/conversations/${conversationId}/rerun`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      },
    )
    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json({ detail: 'No se pudo encolar el rerun.' }, { status: 503 })
  }
}
