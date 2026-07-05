import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

/**
 * Proxy autenticado hacia POST /api/v1/orders/{id}/payment-link.
 *
 * Genera (o regenera) el link de pago Wompi de un pedido pending / pending_payment
 * y devuelve la checkout_url para copiarla o reenviarla por WhatsApp desde la
 * consola de Pedidos (F2 — cierre del ciclo de cobro sin depender del bot).
 *
 * El backend exige owner/manager (require_write_internal_or_user) y valida el
 * estado del pedido; aquí sólo adjuntamos el JWT del operador.
 */
export async function POST(_req: NextRequest, props: { params: Promise<{ id: string }> }) {
  const params = await props.params
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ detail: 'No autenticado' }, { status: 401 })

  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  const upstream = await fetch(
    `${CORE_API_URL}/api/v1/orders/${params.id}/payment-link`,
    {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      signal: AbortSignal.timeout(25000),
    },
  )

  const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
  return NextResponse.json(data, { status: upstream.status })
}
