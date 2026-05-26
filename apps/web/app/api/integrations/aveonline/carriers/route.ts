/**
 * Aveonline carriers preferences proxy.
 *
 * Backend (services/api/routers/integrations.py rev. 108):
 *   GET  /api/v1/integrations/aveonline/carriers  → list prefs
 *   PUT  /api/v1/integrations/aveonline/carriers  → bulk upsert
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
      `${CORE_API_URL}/api/v1/integrations/aveonline/carriers`,
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
      { detail: 'No se pudo contactar el API.' },
      { status: 502 },
    )
  }
}

export async function PUT(req: Request) {
  const token = await authToken()
  if (!token) return NextResponse.json({ detail: 'No autenticado' }, { status: 401 })
  try {
    const body = await req.text()
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/integrations/aveonline/carriers`,
      {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body,
        signal: AbortSignal.timeout(30000),
      },
    )
    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json(
      { detail: 'No se pudo contactar el API.' },
      { status: 502 },
    )
  }
}
