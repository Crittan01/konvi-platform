import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Button, buttonVariants } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { EmptyState } from '@/components/ui/empty-state'
import { Download, ClipboardList, AlertTriangle, Info, RotateCw, ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/utils'
import { bogotaLocalToUTC } from '@/lib/date-window'
import {
  ENTITY_LABELS,
  ENTITY_CHIP_ORDER,
  actionColor,
  actionLabel,
  entityLabel,
  humanizePayload,
  piiPurposeLabel,
  piiFieldLabel,
  describeActor,
} from './audit-labels'

export const dynamic = 'force-dynamic'

const EXPORT_CAP = 5000
type View = 'changes' | 'access'

type AuditEntry = {
  id: string
  user_email: string | null
  action: string
  entity_type: string
  entity_id: string | null
  payload: Record<string, unknown> | null
  created_at: string
}

type PiiAccessEntry = {
  id: string
  contact_id: string | null
  accessed_by: string
  actor_user_id: string | null
  purpose: string
  fields_accessed: string[] | null
  ip_address: string | null
  accessed_at: string
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

/** Propósitos de alto impacto legal (export/reportes) resaltados en ámbar; el resto en azul. Solo shades 700/800 (regla de paleta). */
const SENSITIVE_PURPOSES = new Set(['data_export', 'sar_export', 'sar_export_printable', 'sic_report'])
function purposeColor(purpose: string): string {
  return SENSITIVE_PURPOSES.has(purpose)
    ? 'bg-amber-500/10 text-amber-800 border border-amber-700/25'
    : 'bg-blue-500/10 text-blue-800 border border-blue-700/25'
}

export default async function AuditPage(
  props: {
    searchParams: Promise<{ entity?: string; page?: string; user?: string; from_date?: string; to_date?: string; view?: string }>
  }
) {
  const searchParams = await props.searchParams
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  // Guard server-side (matriz 2026-07-02): Auditoría = owner (dato sensible: quién cambió/accedió qué). Sin esto se abre por URL.
  if (role !== 'owner') redirect('/dashboard')

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const view: View = searchParams.view === 'access' ? 'access' : 'changes'
  const entityFilter = view === 'changes' ? (searchParams.entity ?? '') : ''
  const userFilter   = searchParams.user ?? ''
  const fromDate     = searchParams.from_date ?? ''
  const toDate       = searchParams.to_date ?? ''
  const parsedPage   = parseInt(searchParams.page ?? '1', 10)
  const page         = Number.isFinite(parsedPage) && parsedPage > 0 ? parsedPage : 1  // page=NaN/abc → 1
  const pageSize     = 25
  const offset       = (page - 1) * pageSize
  const hasFilters   = Boolean(entityFilter || userFilter || fromDate || toDate)

  const fromUTC = bogotaDayStartUTC(fromDate)
  const toUTC   = bogotaDayEndUTC(toDate)

  // ── Fetch según la vista activa ──────────────────────────────────────────
  let entries: AuditEntry[] = []
  let accessEntries: PiiAccessEntry[] = []
  let count = 0
  let error: { message: string } | null = null

  if (view === 'changes') {
    let query = supabase
      .from('audit_log')
      .select('id, user_email, action, entity_type, entity_id, payload, created_at', { count: 'exact' })
      .eq('tenant_id', tenantId)
      .order('created_at', { ascending: false })
      .range(offset, offset + pageSize - 1)
    if (entityFilter) query = query.eq('entity_type', entityFilter)
    if (userFilter)   query = query.ilike('user_email', `%${userFilter}%`)
    if (fromUTC) query = query.gte('created_at', fromUTC)
    if (toUTC)   query = query.lte('created_at', toUTC)
    const res = await query
    entries = (res.data as AuditEntry[] | null) ?? []
    count = res.count ?? 0
    error = res.error
    if (error) {
      console.error('[audit] read failed', { tenantId, entityFilter, userFilter, fromDate, toDate, page, error: error.message })
    }
  } else {
    // Accesos a PII (Habeas Data Art. 9). El cliente user PUEDE leer pii_access_log
    // vía RLS (membresía tenant_users); el INSERT sigue siendo solo service_role.
    let query = supabase
      .from('pii_access_log')
      .select('id, contact_id, accessed_by, actor_user_id, purpose, fields_accessed, ip_address, accessed_at', { count: 'exact' })
      .eq('tenant_id', tenantId)
      .order('accessed_at', { ascending: false })
      .range(offset, offset + pageSize - 1)
    if (userFilter) query = query.ilike('accessed_by', `%${userFilter}%`)
    if (fromUTC) query = query.gte('accessed_at', fromUTC)
    if (toUTC)   query = query.lte('accessed_at', toUTC)
    const res = await query
    accessEntries = (res.data as PiiAccessEntry[] | null) ?? []
    count = res.count ?? 0
    error = res.error
    if (error) {
      console.error('[audit/access] read failed', { tenantId, userFilter, fromDate, toDate, page, error: error.message })
    }
  }

  const totalPages = Math.ceil(count / pageSize)
  const total = count

  // Preserva filtros + vista vigentes en enlaces (tabs, chips, paginación, export) con URL-encoding.
  const buildHref = (overrides: Partial<Record<'entity' | 'user' | 'from_date' | 'to_date' | 'page' | 'view', string>>) => {
    const p = new URLSearchParams()
    const eff = { view, entity: entityFilter, user: userFilter, from_date: fromDate, to_date: toDate, ...overrides }
    if (eff.view === 'access') p.set('view', 'access')
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

  const tabs: Array<{ key: View; label: string; icon: typeof ClipboardList }> = [
    { key: 'changes', label: 'Cambios', icon: ClipboardList },
    { key: 'access',  label: 'Accesos a datos personales', icon: ShieldCheck },
  ]

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-primary" aria-hidden /> Auditoría
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {error
              ? (view === 'changes' ? 'Registro de cambios del equipo' : 'Registro de accesos a datos personales')
              : view === 'changes'
                ? `${total} evento${total === 1 ? '' : 's'} registrado${total === 1 ? '' : 's'}`
                : `${total} acceso${total === 1 ? '' : 's'} a datos personales`}
          </p>
        </div>
        {view === 'changes' && !error && (
          <a
            href={`/api/audit/export?${exportParams.toString()}`}
            className={cn(buttonVariants({ size: 'sm', variant: 'outline' }), 'h-8 gap-1.5 text-xs')}
          >
            <Download className="h-3.5 w-3.5" aria-hidden /> Exportar CSV
          </a>
        )}
      </div>

      {/* Tabs de vista — cambios (audit_log) vs accesos a PII (pii_access_log) */}
      <nav aria-label="Vista de auditoría" className="flex gap-1 border-b border-border">
        {tabs.map(t => {
          const active = view === t.key
          const Icon = t.icon
          return (
            <a
              key={t.key}
              href={buildHref({ view: t.key, page: '', entity: '', user: '', from_date: '', to_date: '' })}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors',
                active
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden /> {t.label}
            </a>
          )
        })}
      </nav>

      {/* Ayuda contextual */}
      <details className="rounded-xl border border-border bg-card">
        <summary className="cursor-pointer select-none px-4 py-2.5 text-xs text-muted-foreground hover:text-foreground flex items-center gap-1.5">
          <Info className="h-3.5 w-3.5" aria-hidden /> {view === 'changes' ? '¿Qué registra la auditoría?' : '¿Qué es el registro de accesos?'}
        </summary>
        <div className="px-4 pb-3 text-xs text-muted-foreground space-y-1.5 border-t border-border pt-2.5">
          {view === 'changes' ? (
            <>
              <p>Cada cambio hecho por tu equipo desde el panel queda registrado automáticamente: pedidos, productos, contactos, reclamos, integraciones, cupones, compras, configuración y accesos.</p>
              <p>Las fechas se muestran en hora Colombia. La exportación a CSV respeta los filtros activos y está limitada a los {EXPORT_CAP.toLocaleString('es-CO')} eventos más recientes.</p>
            </>
          ) : (
            <>
              <p>Registro de cuándo se accedió a datos personales de tus contactos (nombre, teléfono, documento…), por quién y con qué propósito. Cumple el deber de trazabilidad de la Ley 1581 (Habeas Data, Art. 9).</p>
              <p>Incluye accesos de tu equipo, del bot y de integraciones. Las fechas se muestran en hora Colombia.</p>
            </>
          )}
        </div>
      </details>

      {/* Aviso de cap de export (solo vista de cambios) */}
      {view === 'changes' && !error && total > EXPORT_CAP && (
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
          {view === 'access' && <input type="hidden" name="view" value="access" />}
          <div className="space-y-1">
            <Label htmlFor="audit-from" className="text-xs text-muted-foreground">Desde</Label>
            <Input id="audit-from" type="date" name="from_date" defaultValue={fromDate} className="h-8 text-xs" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="audit-to" className="text-xs text-muted-foreground">Hasta</Label>
            <Input id="audit-to" type="date" name="to_date" defaultValue={toDate} className="h-8 text-xs" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="audit-user" className="text-xs text-muted-foreground">{view === 'changes' ? 'Usuario' : 'Actor'}</Label>
            <Input id="audit-user" name="user" placeholder={view === 'changes' ? 'email parcial...' : 'user, agent, integración...'} defaultValue={userFilter} className="h-8 text-xs" />
          </div>
          {entityFilter && <input type="hidden" name="entity" value={entityFilter} />}
          <div className="flex gap-2">
            <Button type="submit" size="sm" className="h-8 text-xs flex-1">Filtrar</Button>
            {(fromDate || toDate || userFilter) && (
              <a
                href={entityFilter ? buildHref({ user: '', from_date: '', to_date: '' }) : buildHref({ user: '', from_date: '', to_date: '', page: '' })}
                className={cn(buttonVariants({ size: 'sm', variant: 'ghost' }), 'h-8 text-xs flex-1 text-muted-foreground')}
              >
                Limpiar
              </a>
            )}
          </div>
        </form>
      </div>

      {/* Chips entidad — solo vista de cambios */}
      {view === 'changes' && (
        <nav aria-label="Filtrar por tipo de entidad" className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1">
          {chips.map(opt => {
            const active = entityFilter === opt.key
            return (
              <a key={opt.key || 'all'}
                href={buildHref({ entity: opt.key, page: '' })}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'shrink-0 px-3 py-1 rounded-lg text-xs font-medium border transition-all',
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
      )}

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
            {view === 'access'
              ? 'Accesos a datos personales'
              : entityFilter ? entityLabel(entityFilter) : 'Todos los eventos'}
          </p>
        </div>

        {/* ── Vista: Accesos a PII ─────────────────────────────────────────── */}
        {view === 'access' ? (
          accessEntries.length === 0 ? (
            <EmptyState
              variant="plain"
              className="py-12 px-6"
              title={hasFilters ? 'Sin accesos para estos filtros' : 'Aún no hay accesos registrados'}
              description={
                hasFilters
                  ? 'Ajusta el rango de fechas o el actor.'
                  : 'Cuando tu equipo, el bot o una integración consulten datos personales de tus contactos, el acceso quedará registrado aquí.'
              }
            />
          ) : (
            <div className="divide-y divide-border">
              {accessEntries.map(e => {
                const actor = describeActor(e.accessed_by)
                const fields = e.fields_accessed ?? []
                return (
                  <div key={e.id}
                    className="px-4 py-3 flex flex-col sm:flex-row gap-1.5 sm:gap-4 items-start hover:bg-muted/20 transition-colors">
                    <div className="shrink-0 sm:w-32 text-[11px] text-muted-foreground font-mono pt-0.5">
                      {formatBogota(e.accessed_at)}
                    </div>
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={cn('text-[11px] font-medium px-2 py-0.5 rounded-full', purposeColor(e.purpose))}>
                          {piiPurposeLabel(e.purpose)}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {e.contact_id
                            ? <>Contacto <span className="font-mono ml-0.5 opacity-50">#{e.contact_id.slice(-6)}</span></>
                            : 'Listado de contactos'}
                        </span>
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        <span className="text-foreground/70">{actor.kind}</span>
                        {actor.detail && <span className="font-mono ml-1 opacity-60">{actor.detail}</span>}
                      </p>
                      {fields.length > 0 && (
                        <div className="flex flex-wrap gap-1 pt-0.5">
                          {fields.map((f, i) => (
                            <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border">
                              {piiFieldLabel(f)}
                            </span>
                          ))}
                        </div>
                      )}
                      {e.ip_address && (
                        <p className="text-[10px] text-muted-foreground/70 font-mono">IP {e.ip_address}</p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )
        ) : /* ── Vista: Cambios (audit_log) ──────────────────────────────── */
        entries.length === 0 ? (
          <EmptyState
            variant="plain"
            className="py-12 px-6"
            title={hasFilters ? 'Sin eventos para estos filtros' : 'Aún no hay actividad registrada'}
            description={
              hasFilters
                ? 'Ajusta el rango de fechas, el usuario o el tipo de entidad.'
                : 'Los cambios que tú y tu equipo hagan desde el panel (pedidos, productos, contactos, configuración…) aparecerán aquí automáticamente.'
            }
          />
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
