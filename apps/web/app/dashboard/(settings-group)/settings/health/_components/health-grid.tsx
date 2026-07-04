/**
 * Health grid — server component que renderiza semáforo per provider.
 *
 * Rev. 109 J.2.11 · F6 2026-07-04:
 *   - Estado de error de fetch dedicado (antes se enmascaraba como empty).
 *   - Indicador de staleness: si el cron muere, el badge deja de mentir "OK".
 *   - Deep-links a /dashboard/integrations/{provider} para remediar.
 *   - Detalle del fallo (error/body) visible en métricas no sanas.
 *   - a11y: thead con scope, iconos aria-hidden, wrapper overflow-x.
 */
import Link from 'next/link'
import { AlertCircle, CheckCircle2, Circle, AlertTriangle, Clock, ExternalLink } from 'lucide-react'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import {
  type HealthRow,
  type HealthStatus,
  PROVIDER_LABELS,
  PROVIDER_ORDER,
  PROVIDER_ROUTE,
  STALE_AFTER_MS,
} from './types'

function isStale(iso: string, now: number): boolean {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return false
  return now - t > STALE_AFTER_MS
}

function StatusIcon({ status }: { status: HealthStatus | 'stale' }) {
  if (status === 'healthy') {
    return <CheckCircle2 className="h-5 w-5 text-emerald-600" aria-hidden="true" />
  }
  if (status === 'warning') {
    return <AlertTriangle className="h-5 w-5 text-amber-600" aria-hidden="true" />
  }
  if (status === 'critical') {
    return <AlertCircle className="h-5 w-5 text-red-600" aria-hidden="true" />
  }
  if (status === 'stale') {
    return <Clock className="h-5 w-5 text-slate-700" aria-hidden="true" />
  }
  return <Circle className="h-5 w-5 text-slate-700" aria-hidden="true" />
}

function StatusBadge({ status }: { status: HealthStatus | 'stale' }) {
  const classes: Record<string, string> = {
    healthy: 'bg-emerald-50 text-emerald-700 border-emerald-700',
    warning: 'bg-amber-50 text-amber-700 border-amber-700',
    critical: 'bg-red-50 text-red-700 border-red-700',
    unknown: 'bg-slate-50 text-slate-600 border-slate-700',
    stale: 'bg-slate-50 text-slate-700 border-slate-700',
  }
  const labels: Record<string, string> = {
    healthy: 'OK',
    warning: 'Advertencia',
    critical: 'Crítico',
    unknown: 'Sin datos',
    stale: 'Sin datos recientes',
  }
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border ${classes[status]}`}
    >
      {labels[status]}
    </span>
  )
}

function timeAgo(iso: string, now: number): string {
  const diff = (now - new Date(iso).getTime()) / 1000
  if (Number.isNaN(diff)) return 'sin fecha'
  if (diff < 60) return `hace ${Math.round(diff)}s`
  if (diff < 3600) return `hace ${Math.round(diff / 60)}min`
  if (diff < 86400) return `hace ${Math.round(diff / 3600)}h`
  return `hace ${Math.round(diff / 86400)}d`
}

/** Texto corto del fallo tomado del JSONB detail (raw responses de las APIs). */
function detailHint(m: HealthRow): string | null {
  const d = m.detail || {}
  const candidate = d.error ?? d.body ?? d.reason
  if (candidate == null) return null
  const text = String(candidate).trim()
  return text ? text.slice(0, 200) : null
}

const REMEDIATION: Record<Exclude<HealthStatus, 'healthy'>, string> = {
  critical: 'Requiere acción inmediata: revisa la integración en su panel.',
  warning: 'Vigila esta métrica; puede escalar a crítico si no se atiende.',
  unknown: 'Sin datos aún; se poblará en el próximo ciclo de recolección.',
}

export function HealthGrid({
  byProvider,
  fetchError = false,
}: {
  byProvider: Record<string, HealthRow[]>
  fetchError?: boolean
}) {
  // Estado de error dedicado: NO confundir un fallo de query con "primer uso".
  if (fetchError) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" aria-hidden="true" />
        <AlertTitle>No pudimos cargar la salud de tus integraciones</AlertTitle>
        <AlertDescription>
          Ocurrió un error al consultar los datos. Usa «Actualizar» en unos
          segundos; si persiste, escríbenos a soporte.
        </AlertDescription>
      </Alert>
    )
  }

  const now = Date.now()
  const allProviders = Object.keys(byProvider)
  const ordered = [
    ...PROVIDER_ORDER.filter((p) => allProviders.includes(p)),
    ...allProviders.filter((p) => !PROVIDER_ORDER.includes(p)),
  ]

  if (ordered.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-center text-sm text-muted-foreground">
        Aún no hay datos de salud. Las métricas se recolectan cada 5 minutos
        — usa «Actualizar» en un momento.
      </div>
    )
  }

  // Banner global: si la observación más reciente ya es stale, el cron murió.
  const freshest = Math.max(
    ...ordered.flatMap((p) => byProvider[p].map((m) => new Date(m.observed_at).getTime()))
      .filter((t) => !Number.isNaN(t)),
  )
  const cronDown = Number.isFinite(freshest) && now - freshest > STALE_AFTER_MS

  return (
    <div className="space-y-4">
      {cronDown && (
        <Alert variant="warning">
          <Clock className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Métricas sin actualizar</AlertTitle>
          <AlertDescription>
            La última recolección fue {timeAgo(new Date(freshest).toISOString(), now)}.
            El monitoreo automático puede estar detenido: los estados de abajo
            reflejan la última lectura conocida, no el estado actual.
          </AlertDescription>
        </Alert>
      )}

      {ordered.map((provider) => {
        const metrics = byProvider[provider]
        // worst status ignorando métricas stale (una lectura vieja no debe
        // pintar de verde ni de rojo el estado actual).
        const worstStatus = metrics.reduce<HealthStatus>((worst, m) => {
          if (isStale(m.observed_at, now)) return worst
          const rank = { critical: 3, warning: 2, healthy: 1, unknown: 0 }
          return rank[m.status] > rank[worst] ? m.status : worst
        }, 'unknown')
        const allStale = metrics.every((m) => isStale(m.observed_at, now))
        const headerStatus: HealthStatus | 'stale' = allStale ? 'stale' : worstStatus
        const route = PROVIDER_ROUTE[provider]

        return (
          <section key={provider} className="rounded-lg border border-border bg-card overflow-hidden">
            <header className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-border bg-muted/40">
              <div className="flex items-center gap-2">
                <StatusIcon status={headerStatus} />
                <h2 className="text-sm font-semibold">{PROVIDER_LABELS[provider] || provider}</h2>
                <StatusBadge status={headerStatus} />
              </div>
              {route && (
                <Link
                  href={route}
                  className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                >
                  Ver integración
                  <ExternalLink className="h-3 w-3" aria-hidden="true" />
                </Link>
              )}
            </header>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="sr-only">
                  <tr>
                    <th scope="col">Métrica</th>
                    <th scope="col">Valor</th>
                    <th scope="col">Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.map((m, idx) => {
                    const stale = isStale(m.observed_at, now)
                    const displayStatus: HealthStatus | 'stale' = stale ? 'stale' : m.status
                    const hint = detailHint(m)
                    const remediation =
                      !stale && m.status !== 'healthy' ? REMEDIATION[m.status] : null
                    return (
                      <tr
                        key={`${m.provider}-${m.metric}`}
                        className={idx !== metrics.length - 1 ? 'border-b border-border' : ''}
                      >
                        <td className="px-4 py-2.5 align-top w-1/3">
                          <p className="font-medium text-foreground/90 break-words">{m.metric}</p>
                          {m.threshold && (
                            <p className="text-[10px] text-muted-foreground mt-0.5">{m.threshold}</p>
                          )}
                        </td>
                        <td className="px-4 py-2.5 align-top">
                          <code className="text-sm font-mono break-words">{m.value || 'N/A'}</code>
                          {hint && (
                            <p className="text-[10px] text-muted-foreground mt-1 break-words">
                              {hint}
                            </p>
                          )}
                          {remediation && (
                            <p className="text-[10px] text-muted-foreground mt-1 break-words">
                              {remediation}
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-2.5 align-top text-right whitespace-nowrap">
                          <StatusBadge status={displayStatus} />
                          <p className="text-[10px] text-muted-foreground mt-0.5">
                            {timeAgo(m.observed_at, now)}
                          </p>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )
      })}
    </div>
  )
}
