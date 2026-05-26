/**
 * Aveonline webhook config proxy.
 *
 * Backend endpoints (services/api/routers/integrations.py rev. 108):
 *   GET    /api/v1/integrations/aveonline/webhook            — status
 *   POST   /api/v1/integrations/aveonline/webhook/configure  — primera config
 *   POST   /api/v1/integrations/aveonline/webhook/rotate     — rotación
 *   DELETE /api/v1/integrations/aveonline/webhook            — eliminar
 */
import { NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

async function authToken() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return null
  const { data: { session } } = await supabase.auth.getSession()
  return session?.access_token || null
}

export async function GET() {
  const token = await authToken()
  if (!token) return NextResponse.json({ detail: 'No autenticado' }, { status: 401 })
  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/integrations/aveonline/webhook`,
      {
        method: 'GET',
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(15000),
      },
    )
    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json(
      { detail: 'No se pudo contactar el API para consultar webhook Aveonline.' },
      { status: 502 },
    )
  }
}

export async function DELETE() {
  const token = await authToken()
  if (!token) return NextResponse.json({ detail: 'No autenticado' }, { status: 401 })
  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/integrations/aveonline/webhook`,
      {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(15000),
      },
    )
    if (upstream.status === 204) {
      return new NextResponse(null, { status: 204 })
    }
    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json(
      { detail: 'No se pudo contactar el API para eliminar webhook Aveonline.' },
      { status: 502 },
    )
  }
}
