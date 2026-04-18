import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'

const API_URL = process.env.API_URL ?? 'https://commerce-ops-api.onrender.com'

export async function POST(req: NextRequest) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ detail: 'No autenticado' }, { status: 401 })

  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  let body: unknown
  try { body = await req.json() }
  catch { return NextResponse.json({ detail: 'Payload inválido' }, { status: 400 }) }

  const upstream = await fetch(`${API_URL}/api/v1/orders/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
  })

  const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
  return NextResponse.json(data, { status: upstream.status })
}
