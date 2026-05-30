/**
 * Health grid — server component que renderiza semáforo per provider.
 *
 * Rev. 109 J.2.11.
 */
import { AlertCircle, CheckCircle2, Circle, AlertTriangle } from 'lucide-react'

interface HealthRow {
  provider: string
  metric: string
  value: string | null
  threshold: string | null
  status: 'healthy' | 'warning' | 'critical' | 'unknown'
  detail: Record<string, unknown>
  observed_at: string
  updated_at: string
}

const PROVIDER_LABELS: Record<string, string> = {
  whatsapp: 'WhatsApp Business',
  wompi: 'Wompi (pagos)',
  envia: 'Envia (despachos)',
  meli: 'MercadoLibre',
  telegram: 'Telegram (notificaciones operador)',
  aveonline: 'Aveonline (despachos)',
}

const PROVIDER_ORDER = ['whatsapp', 'wompi', 'envia', 'meli', 'telegram', 'aveonline']

function StatusIcon({ status }: { status: HealthRow['status'] }) {
  if (status === 'healthy') {
    return <CheckCircle2 className="h-5 w-5 text-emerald-600" />
  }
  if (status === 'warning') {
    return <AlertTriangle className="h-5 w-5 text-amber-600" />
  }
  if (status === 'critical') {
    return <AlertCircle className="h-5 w-5 text-red-600" />
  }
  return <Circle className="h-5 w-5 text-slate-400" />
}

function StatusBadge({ status }: { status: HealthRow['status'] }) {
  const classes = {
    healthy: 'bg-emerald-50 text-emerald-700 border-emerald-700',
    warning: 'bg-amber-50 text-amber-700 border-amber-700',
    critical: 'bg-red-50 text-red-700 border-red-700',
    unknown: 'bg-slate-50 text-slate-600 border-slate-400',
  }
  const labels = {
    healthy: 'OK',
    warning: 'Advertencia',
    critical: 'Crítico',
    unknown: 'Sin datos',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border ${classes[status]}`}>
      {labels[status]}
    </span>
  )
}

function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return `hace ${Math.round(diff)}s`
  if (diff < 3600) return `hace ${Math.round(diff / 60)}min`
  if (diff < 86400) return `hace ${Math.round(diff / 3600)}h`
  return `hace ${Math.round(diff / 86400)}d`
}

export function HealthGrid({ byProvider }: { byProvider: Record<string, HealthRow[]> }) {
  // Ordenar providers según PROVIDER_ORDER, los desconocidos al final.
  const allProviders = Object.keys(byProvider)
  const ordered = [
    ...PROVIDER_ORDER.filter(p => allProviders.includes(p)),
    ...allProviders.filter(p => !PROVIDER_ORDER.includes(p)),
  ]

  if (ordered.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-center text-sm text-muted-foreground">
        Aún no hay datos de salud. Las métricas se recolectan cada 5 minutos
        — recarga en un momento.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {ordered.map(provider => {
        const metrics = byProvider[provider]
        // Worst status del provider = peor de todas sus métricas.
        const worstStatus: HealthRow['status'] = metrics.reduce<HealthRow['status']>((worst, m) => {
          const rank = { critical: 3, warning: 2, healthy: 1, unknown: 0 }
          return rank[m.status] > rank[worst] ? m.status : worst
        }, 'unknown')

        return (
          <section
            key={provider}
            className="rounded-lg border border-border bg-card overflow-hidden"
          >
            <header className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/40">
              <div className="flex items-center gap-2">
                <StatusIcon status={worstStatus} />
                <h2 className="text-sm font-semibold">
                  {PROVIDER_LABELS[provider] || provider}
                </h2>
              </div>
              <StatusBadge status={worstStatus} />
            </header>
            <table className="w-full text-sm">
              <tbody>
                {metrics.map((m, idx) => (
                  <tr
                    key={`${m.provider}-${m.metric}`}
                    className={idx !== metrics.length - 1 ? 'border-b border-border' : ''}
                  >
                    <td className="px-4 py-2.5 align-top w-1/3">
                      <p className="font-medium text-foreground/90">{m.metric}</p>
                      {m.threshold && (
                        <p className="text-[10px] text-muted-foreground mt-0.5">{m.threshold}</p>
                      )}
                    </td>
                    <td className="px-4 py-2.5 align-top">
                      <code className="text-sm font-mono">{m.value || 'N/A'}</code>
                    </td>
                    <td className="px-4 py-2.5 align-top text-right">
                      <StatusBadge status={m.status} />
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {timeAgo(m.observed_at)}
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
    </div>
  )
}
