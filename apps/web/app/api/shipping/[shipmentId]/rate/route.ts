import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

export async function PATCH(
  req: NextRequest,
  { params }: { params: { shipmentId: string } }
) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ detail: 'No autenticado' }, { status: 401 })

  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  let body: unknown
  try { body = await req.json() }
  catch { return NextResponse.json({ detail: 'Payload inválido' }, { status: 400 }) }

  const idempotencyKey = req.headers.get('Idempotency-Key')

  const upstream = await fetch(`${CORE_API_URL}/api/v1/shipping/${params.shipmentId}/rate`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10000),
  })

  const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
  return NextResponse.json(data, { status: upstream.status })
}
