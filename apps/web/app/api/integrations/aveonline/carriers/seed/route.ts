/**
 * Aveonline carriers SEED — descubre carriers desde Aveonline API.
 *
 * Backend: POST /api/v1/integrations/aveonline/carriers/seed
 */
import { NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

export async function POST() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ detail: 'No autenticado' }, { status: 401 })
  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
  if (!token) return NextResponse.json({ detail: 'Sesión expirada' }, { status: 401 })

  try {
    const upstream = await fetch(
      `${CORE_API_URL}/api/v1/integrations/aveonline/carriers/seed`,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(30000),
      },
    )
    const data = await upstream.json().catch(() => ({ detail: 'Error del servidor' }))
    return NextResponse.json(data, { status: upstream.status })
  } catch {
    return NextResponse.json(
      { detail: 'No se pudo contactar el API para sincronizar carriers Aveonline.' },
      { status: 502 },
    )
  }
}
