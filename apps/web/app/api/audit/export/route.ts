import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'

export async function GET(request: NextRequest) {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }

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
    .limit(5000)

  if (entity)    query = query.eq('entity_type', entity)
  if (userEmail) query = query.ilike('user_email', `%${userEmail}%`)
  if (fromDate)  query = query.gte('created_at', new Date(fromDate).toISOString())
  if (toDate)    query = query.lte('created_at', new Date(toDate + 'T23:59:59').toISOString())

  const { data } = await query
  const rows = data ?? []

  const ENTITY_LABELS: Record<string, string> = {
    order: 'Pedido', product: 'Producto', contact: 'Contacto',
    kb_document: 'Knowledge Base', integration: 'Integración',
    settings: 'Configuración', inventory: 'Inventario',
  }

  const header = ['Fecha', 'Usuario', 'Acción', 'Entidad', 'ID', 'Detalle']
  const csvRows = rows.map((r: {
    created_at: string; user_email: string | null; action: string;
    entity_type: string; entity_id: string | null; payload: unknown
  }) => [
    new Date(r.created_at).toLocaleString('es-CO'),
    r.user_email ?? '',
    r.action,
    ENTITY_LABELS[r.entity_type] ?? r.entity_type,
    r.entity_id ?? '',
    r.payload ? JSON.stringify(r.payload).replace(/"/g, '""') : '',
  ].map(v => `"${v}"`).join(','))

  const csv = [header.join(','), ...csvRows].join('\n')

  return new NextResponse(csv, {
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="auditoria_${new Date().toISOString().slice(0, 10)}.csv"`,
    },
  })
}
