import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Download, ClipboardList } from 'lucide-react'

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
  if (!user) redirect('/login')
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'

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

  const exportParams = new URLSearchParams()
  if (entityFilter) exportParams.set('entity', entityFilter)
  if (userFilter)   exportParams.set('user', userFilter)
  if (fromDate)     exportParams.set('from_date', fromDate)
  if (toDate)       exportParams.set('to_date', toDate)

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-primary" /> Auditoría
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">{count ?? 0} eventos registrados</p>
        </div>
        {role === 'owner' && (
          <a href={`/api/audit/export?${exportParams.toString()}`}>
            <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs">
              <Download className="h-3.5 w-3.5" /> Exportar CSV
            </Button>
          </a>
        )}
      </div>

      {/* Filtros */}
      <div className="rounded-xl border border-border bg-card p-4">
        <form method="GET" action="/dashboard/audit"
          className="grid grid-cols-2 sm:grid-cols-4 gap-3 items-end">
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Desde</p>
            <Input type="date" name="from_date" defaultValue={fromDate} className="h-8 text-xs" />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Hasta</p>
            <Input type="date" name="to_date" defaultValue={toDate} className="h-8 text-xs" />
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">Usuario</p>
            <Input name="user" placeholder="email parcial..." defaultValue={userFilter} className="h-8 text-xs" />
          </div>
          {entityFilter && <input type="hidden" name="entity" value={entityFilter} />}
          <div className="flex gap-2">
            <Button type="submit" size="sm" className="h-8 text-xs flex-1">Filtrar</Button>
            {(fromDate || toDate || userFilter) && (
              <a href={entityFilter ? `/dashboard/audit?entity=${entityFilter}` : '/dashboard/audit'} className="flex-1">
                <Button type="button" size="sm" variant="ghost" className="h-8 text-xs w-full text-muted-foreground">
                  Limpiar
                </Button>
              </a>
            )}
          </div>
        </form>
      </div>

      {/* Chips entidad — scrollable en mobile */}
      <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1">
        {[{ key: '', label: 'Todos' }, ...Object.entries(ENTITY_LABELS).map(([k, l]) => ({ key: k, label: l }))].map(opt => (
          <a key={opt.key}
            href={`/dashboard/audit?${opt.key ? `entity=${opt.key}&` : ''}user=${userFilter}&from_date=${fromDate}&to_date=${toDate}`}
            className={`flex-shrink-0 px-3 py-1 rounded-lg text-xs font-medium border transition-all ${
              entityFilter === opt.key
                ? 'bg-primary/15 text-primary border-primary/40'
                : 'border-border text-muted-foreground hover:text-foreground'
            }`}
          >
            {opt.label}
          </a>
        ))}
      </div>

      {/* Log */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border bg-muted/20">
          <p className="text-sm font-medium">
            {entityFilter ? ENTITY_LABELS[entityFilter] ?? entityFilter : 'Todos los eventos'}
          </p>
        </div>

        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground py-12 text-center">
            Sin eventos en el período o filtro seleccionado.
          </p>
        ) : (
          <div className="divide-y divide-border">
            {entries.map(entry => (
              <div key={entry.id}
                className="px-4 py-3 flex flex-col sm:flex-row gap-1.5 sm:gap-4 items-start hover:bg-muted/20 transition-colors">
                {/* Timestamp */}
                <div className="shrink-0 sm:w-32 text-[11px] text-muted-foreground font-mono pt-0.5">
                  {new Date(entry.created_at).toLocaleDateString('es-CO', { day: '2-digit', month: 'short' })}
                  {' '}{new Date(entry.created_at).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                </div>
                {/* Contenido */}
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full border ${actionColor(entry.action)}`}>
                      {formatAction(entry.action)}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {ENTITY_LABELS[entry.entity_type] ?? entry.entity_type}
                      {entry.entity_id && (
                        <span className="font-mono ml-1 opacity-50">#{entry.entity_id.slice(-6)}</span>
                      )}
                    </span>
                  </div>
                  {entry.user_email && (
                    <p className="text-[11px] text-muted-foreground">{entry.user_email}</p>
                  )}
                  {entry.payload && Object.keys(entry.payload).length > 0 && (
                    <details className="text-xs">
                      <summary className="cursor-pointer text-muted-foreground hover:text-primary select-none transition-colors">
                        Ver detalle
                      </summary>
                      <pre className="mt-1.5 p-2.5 bg-muted rounded-lg text-[11px] overflow-auto max-h-32 font-mono">
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
          <div className="flex justify-between items-center px-4 py-3 border-t border-border">
            <p className="text-xs text-muted-foreground">Pág. {page} / {totalPages}</p>
            <div className="flex gap-2">
              {page > 1 && (
                <a href={`/dashboard/audit?entity=${entityFilter}&user=${userFilter}&from_date=${fromDate}&to_date=${toDate}&page=${page - 1}`}
                  className="px-3 py-1 rounded-lg text-xs border border-border hover:bg-accent transition-colors">
                  ← Anterior
                </a>
              )}
              {page < totalPages && (
                <a href={`/dashboard/audit?entity=${entityFilter}&user=${userFilter}&from_date=${fromDate}&to_date=${toDate}&page=${page + 1}`}
                  className="px-3 py-1 rounded-lg text-xs border border-border hover:bg-accent transition-colors">
                  Siguiente →
                </a>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
