import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Button, buttonVariants } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { Download, ClipboardList, AlertTriangle, Info, RotateCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { bogotaLocalToUTC } from '@/lib/date-window'
import {
  ENTITY_LABELS,
  ENTITY_CHIP_ORDER,
  actionColor,
  actionLabel,
  entityLabel,
  humanizePayload,
} from './audit-labels'

export const dynamic = 'force-dynamic'

const EXPORT_CAP = 5000

type AuditEntry = {
  id: string
  user_email: string | null
  action: string
  entity_type: string
  entity_id: string | null
  payload: Record<string, unknown> | null
  created_at: string
}

/** Fecha 'YYYY-MM-DD' del operador (hora Colombia) → borde inferior UTC (00:00 Bogotá). */
function bogotaDayStartUTC(date: string): string | null {
  return date ? bogotaLocalToUTC(`${date}T00:00`) : null
}
/** Fecha 'YYYY-MM-DD' del operador → borde superior UTC (23:59:59.999 Bogotá, inclusivo). */
function bogotaDayEndUTC(date: string): string | null {
  if (!date) return null
  const start = bogotaLocalToUTC(`${date}T00:00`)
  if (!start) return null
  // +1 día - 1ms para incluir todo el día calendario Colombia
  return new Date(new Date(start).getTime() + 24 * 60 * 60 * 1000 - 1).toISOString()
}

/** Timestamp UTC → 'dd mmm HH:mm' en hora Colombia (nunca TZ del servidor). */
function formatBogota(utc: string): string {
  const d = new Date(utc)
  const date = d.toLocaleDateString('es-CO', { day: '2-digit', month: 'short', timeZone: 'America/Bogota' })
  const time = d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Bogota' })
  return `${date} ${time}`
}

export default async function AuditPage(
  props: {
    searchParams: Promise<{ entity?: string; page?: string; user?: string; from_date?: string; to_date?: string }>
  }
) {
  const searchParams = await props.searchParams
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  // Guard server-side (matriz 2026-07-02): Auditoría = owner (dato sensible: quién cambió qué). Sin esto se abre por URL.
  if (role !== 'owner') redirect('/dashboard')

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const entityFilter = searchParams.entity ?? ''
  const userFilter   = searchParams.user ?? ''
  const fromDate     = searchParams.from_date ?? ''
  const toDate       = searchParams.to_date ?? ''
  const parsedPage   = parseInt(searchParams.page ?? '1', 10)
  const page         = Number.isFinite(parsedPage) && parsedPage > 0 ? parsedPage : 1  // page=NaN/abc → 1
  const pageSize     = 25
  const offset       = (page - 1) * pageSize
  const hasFilters   = Boolean(entityFilter || userFilter || fromDate || toDate)

  let query = supabase
    .from('audit_log')
    .select('id, user_email, action, entity_type, entity_id, payload, created_at', { count: 'exact' })
    .eq('tenant_id', tenantId)
    .order('created_at', { ascending: false })
    .range(offset, offset + pageSize - 1)

  if (entityFilter) query = query.eq('entity_type', entityFilter)
  if (userFilter)   query = query.ilike('user_email', `%${userFilter}%`)
  const fromUTC = bogotaDayStartUTC(fromDate)
  const toUTC   = bogotaDayEndUTC(toDate)
  if (fromUTC) query = query.gte('created_at', fromUTC)
  if (toUTC)   query = query.lte('created_at', toUTC)

  const { data, count, error } = await query
  const entries = (data as AuditEntry[] | null) ?? []
  const totalPages = Math.ceil((count ?? 0) / pageSize)
  const total = count ?? 0

  // Surfacear fallo de lectura: NUNCA caer a "Sin eventos" (falso-0) ante un error de DB/RLS.
  if (error) {
    console.error('[audit] read failed', { tenantId, entityFilter, userFilter, fromDate, toDate, page, error: error.message })
  }

  // Preserva filtros vigentes en enlaces (chips, paginación, export) con URL-encoding.
  const buildHref = (overrides: Partial<Record<'entity' | 'user' | 'from_date' | 'to_date' | 'page', string>>) => {
    const p = new URLSearchParams()
    const eff = { entity: entityFilter, user: userFilter, from_date: fromDate, to_date: toDate, ...overrides }
    if (eff.entity)    p.set('entity', eff.entity)
    if (eff.user)      p.set('user', eff.user)
    if (eff.from_date) p.set('from_date', eff.from_date)
    if (eff.to_date)   p.set('to_date', eff.to_date)
    if (eff.page)      p.set('page', eff.page)
    const qs = p.toString()
    return qs ? `/dashboard/audit?${qs}` : '/dashboard/audit'
  }

  const exportParams = new URLSearchParams()
  if (entityFilter) exportParams.set('entity', entityFilter)
  if (userFilter)   exportParams.set('user', userFilter)
  if (fromDate)     exportParams.set('from_date', fromDate)
  if (toDate)       exportParams.set('to_date', toDate)

  const chips = [{ key: '', label: 'Todos' }, ...ENTITY_CHIP_ORDER.map(k => ({ key: k, label: ENTITY_LABELS[k] }))]

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-primary" aria-hidden /> Auditoría
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {error ? 'Registro de cambios del equipo' : `${total} evento${total === 1 ? '' : 's'} registrado${total === 1 ? '' : 's'}`}
          </p>
        </div>
        {!error && (
          <a
            href={`/api/audit/export?${exportParams.toString()}`}
            className={cn(buttonVariants({ size: 'sm', variant: 'outline' }), 'h-8 gap-1.5 text-xs')}
          >
            <Download className="h-3.5 w-3.5" aria-hidden /> Exportar CSV
          </a>
        )}
      </div>

      {/* Ayuda contextual */}
      <details className="rounded-xl border border-border bg-card">
        <summary className="cursor-pointer select-none px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground flex items-center gap-1.5">
          <Info className="h-3.5 w-3.5" aria-hidden /> ¿Qué registra la auditoría?
        </summary>
        <div className="px-4 pb-3 text-xs text-muted-foreground space-y-1.5 border-t border-border pt-2.5">
          <p>Cada cambio hecho por tu equipo desde el panel queda registrado automáticamente: pedidos, productos, contactos, reclamos, integraciones, cupones, compras, configuración y accesos.</p>
          <p>Las fechas se muestran en hora Colombia. La exportación a CSV respeta los filtros activos y está limitada a los {EXPORT_CAP.toLocaleString('es-CO')} eventos más recientes.</p>
        </div>
      </details>

      {/* Aviso de cap de export */}
      {!error && total > EXPORT_CAP && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" aria-hidden />
          <AlertTitle>La exportación se limita a {EXPORT_CAP.toLocaleString('es-CO')} eventos</AlertTitle>
          <AlertDescription>
            Hay {total.toLocaleString('es-CO')} eventos con los filtros actuales. El CSV incluirá solo los {EXPORT_CAP.toLocaleString('es-CO')} más recientes.
            Acota el rango de fechas para exportar el período que necesitas completo.
          </AlertDescription>
        </Alert>
      )}

      {/* Filtros */}
      <div className="rounded-xl border border-border bg-card p-4">
        <form method="GET" action="/dashboard/audit"
          className="grid grid-cols-2 sm:grid-cols-4 gap-3 items-end">
          <div className="space-y-1">
            <Label htmlFor="audit-from" className="text-xs text-muted-foreground">Desde</Label>
            <Input id="audit-from" type="date" name="from_date" defaultValue={fromDate} className="h-8 text-xs" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="audit-to" className="text-xs text-muted-foreground">Hasta</Label>
            <Input id="audit-to" type="date" name="to_date" defaultValue={toDate} className="h-8 text-xs" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="audit-user" className="text-xs text-muted-foreground">Usuario</Label>
            <Input id="audit-user" name="user" placeholder="email parcial..." defaultValue={userFilter} className="h-8 text-xs" />
          </div>
          {entityFilter && <input type="hidden" name="entity" value={entityFilter} />}
          <div className="flex gap-2">
            <Button type="submit" size="sm" className="h-8 text-xs flex-1">Filtrar</Button>
            {(fromDate || toDate || userFilter) && (
              <a
                href={entityFilter ? buildHref({ user: '', from_date: '', to_date: '' }) : '/dashboard/audit'}
                className={cn(buttonVariants({ size: 'sm', variant: 'ghost' }), 'h-8 text-xs flex-1 text-muted-foreground')}
              >
                Limpiar
              </a>
            )}
          </div>
        </form>
      </div>

      {/* Chips entidad — scrollable en mobile */}
      <nav aria-label="Filtrar por tipo de entidad" className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1">
        {chips.map(opt => {
          const active = entityFilter === opt.key
          return (
            <a key={opt.key || 'all'}
              href={buildHref({ entity: opt.key, page: '' })}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'flex-shrink-0 px-3 py-1 rounded-lg text-xs font-medium border transition-all',
                active
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'border-border text-muted-foreground hover:text-foreground',
              )}
            >
              {opt.label}
            </a>
          )
        })}
      </nav>

      {/* Estado de error de lectura — retry, NO empty-state */}
      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden />
          <AlertTitle>No se pudo cargar el registro de auditoría</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>Hubo un problema al consultar los eventos. Esto no significa que no haya actividad registrada.</p>
            <a
              href={buildHref({ page: String(page) })}
              className={cn(buttonVariants({ size: 'sm', variant: 'outline' }), 'h-8 gap-1.5 text-xs')}
            >
              <RotateCw className="h-3.5 w-3.5" aria-hidden /> Reintentar
            </a>
          </AlertDescription>
        </Alert>
      ) : (
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border bg-muted/20">
          <p className="text-sm font-medium">
            {entityFilter ? entityLabel(entityFilter) : 'Todos los eventos'}
          </p>
        </div>

        {entries.length === 0 ? (
          <div className="py-12 px-6 text-center space-y-1.5">
            {hasFilters ? (
              <>
                <p className="text-sm text-foreground font-medium">Sin eventos para estos filtros</p>
                <p className="text-xs text-muted-foreground">Ajusta el rango de fechas, el usuario o el tipo de entidad.</p>
              </>
            ) : (
              <>
                <p className="text-sm text-foreground font-medium">Aún no hay actividad registrada</p>
                <p className="text-xs text-muted-foreground">
                  Los cambios que tú y tu equipo hagan desde el panel (pedidos, productos, contactos, configuración…) aparecerán aquí automáticamente.
                </p>
              </>
            )}
          </div>
        ) : (
          <div className="divide-y divide-border">
            {entries.map(entry => {
              const detail = humanizePayload(entry.payload)
              return (
              <div key={entry.id}
                className="px-4 py-3 flex flex-col sm:flex-row gap-1.5 sm:gap-4 items-start hover:bg-muted/20 transition-colors">
                {/* Timestamp (hora Colombia) */}
                <div className="shrink-0 sm:w-32 text-[11px] text-muted-foreground font-mono pt-0.5">
                  {formatBogota(entry.created_at)}
                </div>
                {/* Contenido */}
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={cn('text-[11px] font-medium px-2 py-0.5 rounded-full', actionColor(entry.action))}>
                      {actionLabel(entry.action)}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {entityLabel(entry.entity_type)}
                      {entry.entity_id && (
                        <span className="font-mono ml-1 opacity-50">#{entry.entity_id.slice(-6)}</span>
                      )}
                    </span>
                  </div>
                  {entry.user_email && (
                    <p className="text-[11px] text-muted-foreground">{entry.user_email}</p>
                  )}
                  {detail.length > 0 && (
                    <details className="text-xs">
                      <summary className="cursor-pointer text-muted-foreground hover:text-primary select-none transition-colors">
                        Ver detalle
                      </summary>
                      <dl className="mt-1.5 p-2.5 bg-muted rounded-lg text-[11px] max-h-40 overflow-auto grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                        {detail.map(({ key, value }, i) => (
                          <div key={i} className="contents">
                            <dt className="text-muted-foreground capitalize">{key}</dt>
                            <dd className="font-mono break-all">{value}</dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  )}
                </div>
              </div>
              )
            })}
          </div>
        )}

        {/* Paginación */}
        {totalPages > 1 && (
          <div className="flex justify-between items-center px-4 py-3 border-t border-border">
            <p className="text-xs text-muted-foreground">Pág. {page} / {totalPages}</p>
            <div className="flex gap-2">
              {page > 1 && (
                <a href={buildHref({ page: String(page - 1) })}
                  className="px-3 py-1 rounded-lg text-xs border border-border hover:bg-accent transition-colors">
                  ← Anterior
                </a>
              )}
              {page < totalPages && (
                <a href={buildHref({ page: String(page + 1) })}
                  className="px-3 py-1 rounded-lg text-xs border border-border hover:bg-accent transition-colors">
                  Siguiente →
                </a>
              )}
            </div>
          </div>
        )}
      </div>
      )}
    </div>
  )
}
