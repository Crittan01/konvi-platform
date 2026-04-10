import { createClient } from '@/utils/supabase/server'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const ENTITY_LABELS: Record<string, string> = {
  order:       'Pedido',
  product:     'Producto',
  contact:     'Contacto',
  kb_document: 'Knowledge Base',
  integration: 'Integración',
  settings:    'Configuración',
  inventory:   'Inventario',
}

const ACTION_COLORS: Record<string, string> = {
  created:        'bg-green-100 text-green-800',
  updated:        'bg-blue-100 text-blue-800',
  deleted:        'bg-red-100 text-red-800',
  status_changed: 'bg-purple-100 text-purple-800',
  connected:      'bg-green-100 text-green-800',
  disconnected:   'bg-gray-100 text-gray-800',
}

function actionColor(action: string): string {
  const key = Object.keys(ACTION_COLORS).find(k => action.includes(k))
  return key ? ACTION_COLORS[key] : 'bg-gray-100 text-gray-800'
}

function formatAction(action: string): string {
  return action.replace('.', ' → ').replace(/_/g, ' ')
}

type AuditEntry = {
  id: string
  user_email: string | null
  action: string
  entity_type: string
  entity_id: string | null
  payload: Record<string, unknown> | null
  created_at: string
}

export default async function AuditPage({
  searchParams,
}: {
  searchParams: { entity?: string; page?: string }
}) {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const entityFilter = searchParams.entity ?? ''
  const page = Math.max(1, parseInt(searchParams.page ?? '1'))
  const pageSize = 25
  const offset = (page - 1) * pageSize

  let query = supabase
    .from('audit_log')
    .select('id, user_email, action, entity_type, entity_id, payload, created_at', { count: 'exact' })
    .eq('tenant_id', tenantId)
    .order('created_at', { ascending: false })
    .range(offset, offset + pageSize - 1)

  if (entityFilter) {
    query = query.eq('entity_type', entityFilter)
  }

  const { data, count } = await query
  const entries = (data as AuditEntry[]) ?? []
  const totalPages = Math.ceil((count ?? 0) / pageSize)

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-primary">Auditoría</h1>
          <p className="text-sm text-muted-foreground mt-1">{count ?? 0} eventos registrados</p>
        </div>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      {/* Filtros */}
      <div className="flex gap-2 flex-wrap">
        <a href="/dashboard/audit">
          <Badge variant={!entityFilter ? 'default' : 'outline'} className="cursor-pointer">Todos</Badge>
        </a>
        {Object.entries(ENTITY_LABELS).map(([key, label]) => (
          <a key={key} href={`/dashboard/audit?entity=${key}`}>
            <Badge variant={entityFilter === key ? 'default' : 'outline'} className="cursor-pointer">{label}</Badge>
          </a>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {entityFilter ? `${ENTITY_LABELS[entityFilter] ?? entityFilter} — eventos` : 'Todos los eventos'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {entries.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">Sin eventos registrados aún.</p>
          ) : (
            <div className="space-y-0 divide-y">
              {entries.map(entry => (
                <div key={entry.id} className="py-3 flex gap-4 items-start">
                  <div className="shrink-0 w-36 text-xs text-muted-foreground pt-0.5">
                    {new Date(entry.created_at).toLocaleDateString('es-MX', {
                      day: '2-digit', month: 'short', year: '2-digit',
                    })}
                    {' '}
                    {new Date(entry.created_at).toLocaleTimeString('es-MX', {
                      hour: '2-digit', minute: '2-digit',
                    })}
                  </div>
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${actionColor(entry.action)}`}>
                        {formatAction(entry.action)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {ENTITY_LABELS[entry.entity_type] ?? entry.entity_type}
                        {entry.entity_id && (
                          <span className="font-mono ml-1 opacity-60">#{entry.entity_id.slice(-6)}</span>
                        )}
                      </span>
                    </div>
                    {entry.user_email && (
                      <p className="text-xs text-muted-foreground">{entry.user_email}</p>
                    )}
                    {entry.payload && Object.keys(entry.payload).length > 0 && (
                      <details className="text-xs">
                        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                          Ver detalle
                        </summary>
                        <pre className="mt-1 p-2 bg-muted rounded text-xs overflow-auto max-h-32">
                          {JSON.stringify(entry.payload, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Paginación */}
          {totalPages > 1 && (
            <div className="flex justify-between items-center pt-4 border-t mt-4">
              <p className="text-xs text-muted-foreground">Página {page} de {totalPages}</p>
              <div className="flex gap-2">
                {page > 1 && (
                  <a href={`/dashboard/audit?entity=${entityFilter}&page=${page - 1}`}>
                    <Badge variant="outline" className="cursor-pointer">← Anterior</Badge>
                  </a>
                )}
                {page < totalPages && (
                  <a href={`/dashboard/audit?entity=${entityFilter}&page=${page + 1}`}>
                    <Badge variant="outline" className="cursor-pointer">Siguiente →</Badge>
                  </a>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
