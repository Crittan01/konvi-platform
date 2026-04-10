import { createClient } from '@/utils/supabase/server'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Download } from 'lucide-react'

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
  created:        'bg-green-500/15 text-green-400 border border-green-500/30',
  updated:        'bg-blue-500/15 text-blue-400 border border-blue-500/30',
  deleted:        'bg-red-500/15 text-red-400 border border-red-500/30',
  status_changed: 'bg-purple-500/15 text-purple-400 border border-purple-500/30',
  connected:      'bg-green-500/15 text-green-400 border border-green-500/30',
  disconnected:   'bg-muted text-muted-foreground border border-border',
}

function actionColor(action: string): string {
  const key = Object.keys(ACTION_COLORS).find(k => action.includes(k))
  return key ? ACTION_COLORS[key] : 'bg-muted text-muted-foreground border border-border'
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
  searchParams: { entity?: string; page?: string; user?: string; from_date?: string; to_date?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const entityFilter = searchParams.entity ?? ''
  const userFilter   = searchParams.user ?? ''
  const fromDate     = searchParams.from_date ?? ''
  const toDate       = searchParams.to_date ?? ''
  const page         = Math.max(1, parseInt(searchParams.page ?? '1'))
  const pageSize     = 25
  const offset       = (page - 1) * pageSize

  let query = supabase
    .from('audit_log')
    .select('id, user_email, action, entity_type, entity_id, payload, created_at', { count: 'exact' })
    .eq('tenant_id', tenantId)
    .order('created_at', { ascending: false })
    .range(offset, offset + pageSize - 1)

  if (entityFilter) query = query.eq('entity_type', entityFilter)
  if (userFilter)   query = query.ilike('user_email', `%${userFilter}%`)
  if (fromDate)     query = query.gte('created_at', new Date(fromDate).toISOString())
  if (toDate)       query = query.lte('created_at', new Date(toDate + 'T23:59:59').toISOString())

  const { data, count } = await query
  const entries = (data as AuditEntry[]) ?? []
  const totalPages = Math.ceil((count ?? 0) / pageSize)

  // Build export URL preserving active filters
  const exportParams = new URLSearchParams()
  if (entityFilter) exportParams.set('entity', entityFilter)
  if (userFilter)   exportParams.set('user', userFilter)
  if (fromDate)     exportParams.set('from_date', fromDate)
  if (toDate)       exportParams.set('to_date', toDate)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-primary">Auditoría</h1>
          <p className="text-sm text-muted-foreground mt-1">{count ?? 0} eventos registrados</p>
        </div>
        <div className="flex items-center gap-2">
          {role === 'owner' && (
            <a href={`/api/audit/export?${exportParams.toString()}`}>
              <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs">
                <Download className="h-3.5 w-3.5" /> Exportar CSV
              </Button>
            </a>
          )}
          <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
        </div>
      </div>

      {/* Filtros */}
      <Card>
        <CardContent className="p-4">
          <form method="GET" action="/dashboard/audit" className="flex flex-wrap gap-3 items-end">
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Desde</p>
              <Input type="date" name="from_date" defaultValue={fromDate} className="h-8 text-xs w-36" />
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Hasta</p>
              <Input type="date" name="to_date" defaultValue={toDate} className="h-8 text-xs w-36" />
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Usuario</p>
              <Input
                name="user"
                placeholder="email parcial..."
                defaultValue={userFilter}
                className="h-8 text-xs w-44"
              />
            </div>
            {entityFilter && <input type="hidden" name="entity" value={entityFilter} />}
            <Button type="submit" size="sm" className="h-8 text-xs">Filtrar</Button>
            {(fromDate || toDate || userFilter) && (
              <a href={entityFilter ? `/dashboard/audit?entity=${entityFilter}` : '/dashboard/audit'}>
                <Button type="button" size="sm" variant="ghost" className="h-8 text-xs text-muted-foreground">
                  Limpiar
                </Button>
              </a>
            )}
          </form>
        </CardContent>
      </Card>

      {/* Filtros por entidad */}
      <div className="flex gap-2 flex-wrap">
        <a href={`/dashboard/audit?user=${userFilter}&from_date=${fromDate}&to_date=${toDate}`}>
          <Badge variant={!entityFilter ? 'default' : 'outline'} className="cursor-pointer">Todos</Badge>
        </a>
        {Object.entries(ENTITY_LABELS).map(([key, label]) => (
          <a key={key} href={`/dashboard/audit?entity=${key}&user=${userFilter}&from_date=${fromDate}&to_date=${toDate}`}>
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
            <p className="text-sm text-muted-foreground py-4 text-center">Sin eventos en el período o filtro seleccionado.</p>
          ) : (
            <div className="space-y-0 divide-y divide-border">
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
                        <summary className="cursor-pointer text-muted-foreground hover:text-foreground select-none">
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

          {totalPages > 1 && (
            <div className="flex justify-between items-center pt-4 border-t mt-4">
              <p className="text-xs text-muted-foreground">Página {page} de {totalPages}</p>
              <div className="flex gap-2">
                {page > 1 && (
                  <a href={`/dashboard/audit?entity=${entityFilter}&user=${userFilter}&from_date=${fromDate}&to_date=${toDate}&page=${page - 1}`}>
                    <Badge variant="outline" className="cursor-pointer">← Anterior</Badge>
                  </a>
                )}
                {page < totalPages && (
                  <a href={`/dashboard/audit?entity=${entityFilter}&user=${userFilter}&from_date=${fromDate}&to_date=${toDate}&page=${page + 1}`}>
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
