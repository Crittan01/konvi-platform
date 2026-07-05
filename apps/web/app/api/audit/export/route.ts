import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { bogotaLocalToUTC } from '@/lib/date-window'
import { entityLabel, actionLabel } from '@/app/dashboard/(analytics)/audit/audit-labels'

const EXPORT_CAP = 5000

/** Neutraliza inyección de fórmulas CSV: celdas que abren con =,+,-,@,tab,CR se prefijan con ' (Excel/Sheets no las evalúan). */
function csvSafe(value: string): string {
  const v = value ?? ''
  const needsGuard = /^[=+\-@\t\r]/.test(v)
  const guarded = needsGuard ? `'${v}` : v
  return `"${guarded.replace(/"/g, '""')}"`
}

export async function GET(request: NextRequest) {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }

  if (!meta.tenant_id || meta.role !== 'owner') {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 403 })
  }

  const sp = request.nextUrl.searchParams
  const entity    = sp.get('entity')    ?? ''
  const userEmail = sp.get('user')      ?? ''
  const fromDate  = sp.get('from_date') ?? ''
  const toDate    = sp.get('to_date')   ?? ''

  let query = supabase
    .from('audit_log')
    .select('id, user_email, action, entity_type, entity_id, payload, created_at')
    .eq('tenant_id', meta.tenant_id)
    .order('created_at', { ascending: false })
    .limit(EXPORT_CAP)

  if (entity)    query = query.eq('entity_type', entity)
  if (userEmail) query = query.ilike('user_email', `%${userEmail}%`)
  // Bordes de día en hora Colombia (no TZ del servidor): 00:00 y 23:59:59.999 Bogotá.
  if (fromDate) {
    const fromUTC = bogotaLocalToUTC(`${fromDate}T00:00`)
    if (fromUTC) query = query.gte('created_at', fromUTC)
  }
  if (toDate) {
    const start = bogotaLocalToUTC(`${toDate}T00:00`)
    if (start) query = query.lte('created_at', new Date(new Date(start).getTime() + 24 * 60 * 60 * 1000 - 1).toISOString())
  }

  const { data, error } = await query

  // Surfacear el fallo: NO devolver 200 con CSV vacío (indistinguible de "no hay datos").
  if (error) {
    console.error('[audit/export] read failed', { tenantId: meta.tenant_id, entity, userEmail, fromDate, toDate, error: error.message })
    return NextResponse.json({ error: 'No se pudo generar la exportación. Intenta de nuevo.' }, { status: 502 })
  }

  const rows = data ?? []

  // Registro del acceso (PII, Habeas Data Art. 9): el export saca hasta 5000
  // eventos con datos personales y debe dejar huella. El write es privilegiado
  // (pii_access_log tiene INSERT solo para service_role, append-only), así que
  // se delega a la RPC SECURITY DEFINER `log_audit_export`. Best-effort: si la
  // migración aún no está aplicada (feature-detect) o falla, NO se bloquea la
  // descarga — solo se pierde la traza, comportamiento degradado seguro.
  try {
    const filters: Record<string, string> = {}
    if (entity)    filters.entity    = entity
    if (userEmail) filters.user      = userEmail
    if (fromDate)  filters.from_date = fromDate
    if (toDate)    filters.to_date   = toDate
    const fwd = request.headers.get('x-forwarded-for')
    const ip = (fwd ? fwd.split(',')[0] : request.headers.get('x-real-ip'))?.trim() ?? null
    const { error: logError } = await supabase.rpc('log_audit_export', {
      p_row_count:  rows.length,
      p_filters:    filters,
      p_ip:         ip,
      p_user_agent: request.headers.get('user-agent'),
    })
    if (logError) {
      console.warn('[audit/export] access log skipped', { tenantId: meta.tenant_id, error: logError.message })
    }
  } catch (e) {
    console.warn('[audit/export] access log threw', { tenantId: meta.tenant_id, error: String(e) })
  }

  const header = ['Fecha (Colombia)', 'Usuario', 'Acción', 'Entidad', 'ID', 'Detalle']
  const csvRows = rows.map((r: {
    created_at: string; user_email: string | null; action: string;
    entity_type: string; entity_id: string | null; payload: unknown
  }) => [
    new Date(r.created_at).toLocaleString('es-CO', { timeZone: 'America/Bogota' }),
    r.user_email ?? '',
    actionLabel(r.action),
    entityLabel(r.entity_type),
    r.entity_id ?? '',
    r.payload ? JSON.stringify(r.payload) : '',
  ].map(v => csvSafe(String(v))).join(','))

  // BOM para que Excel abra UTF-8 (tildes es-CO) correctamente.
  const csv = '﻿' + [header.join(','), ...csvRows].join('\r\n')

  return new NextResponse(csv, {
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="auditoria_${new Date().toISOString().slice(0, 10)}.csv"`,
      'Cache-Control': 'no-store',
    },
  })
}
