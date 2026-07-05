import { MapPin } from 'lucide-react'
import { getStatusMeta } from './status-badge'

// ─── Tipos ────────────────────────────────────────────────────────────────────
// Evento físico del envío reportado por el courier (webhook Aveonline §6.2).
// Fuente: tabla shipment_tracking_events (migración 20260529000000).
export type TrackingEvent = {
  id: string
  shipment_id: string | null
  raw_status: string | null
  internal_status: string
  description: string | null
  occurred_at: string | null
  received_at: string
}

// Color del punto del timeline por estado canónico (internal_status).
// No reutilizamos la clase completa de STATUS_META (que es chip bg+text+border);
// aquí solo necesitamos el color sólido del punto.
const DOT_COLOR: Record<string, string> = {
  pending:    'bg-amber-700',
  labeled:    'bg-blue-700',
  picked_up:  'bg-purple-700',
  in_transit: 'bg-indigo-700',
  delivered:  'bg-emerald-700',
  exception:  'bg-orange-700',
  returned:   'bg-rose-700',
  cancelled:  'bg-red-700',
}

function fmt(ts: string | null): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('es-CO', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

/**
 * Timeline de tracking de un envío. Server component (sin JS de cliente):
 * usa <details> nativo para colapsar. Los eventos vienen ordenados del más
 * reciente al más antiguo (received_at DESC). Eventos huérfanos
 * (shipment_id NULL) se filtran aguas arriba en page.tsx.
 */
export function ShipmentTimeline({ events }: { events: TrackingEvent[] }) {
  if (!events || events.length === 0) return null

  return (
    <details className="mt-3 pt-3 border-t border-border/60 group">
      <summary className="cursor-pointer select-none text-xs font-medium text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1.5">
        <MapPin className="h-3.5 w-3.5" />
        Seguimiento del transportador ({events.length}
        {events.length === 1 ? ' evento' : ' eventos'})
      </summary>

      <ol className="mt-3 space-y-0 pl-1">
        {events.map((ev, idx) => {
          const meta   = getStatusMeta(ev.internal_status)
          const dot    = DOT_COLOR[ev.internal_status] ?? 'bg-muted-foreground'
          const isLast = idx === events.length - 1
          const when   = fmt(ev.occurred_at) || fmt(ev.received_at)
          return (
            <li key={ev.id} className="relative flex gap-3 pb-4">
              {/* Línea vertical del timeline */}
              {!isLast && (
                <span
                  aria-hidden="true"
                  className="absolute left-[5px] top-3 bottom-0 w-px bg-border"
                />
              )}
              {/* Punto */}
              <span
                aria-hidden="true"
                className={`relative z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dot}`}
              />
              <div className="min-w-0 flex-1 -mt-0.5">
                <p className="text-xs font-medium text-foreground">
                  {meta.label}
                  {ev.raw_status && ev.raw_status.toLowerCase() !== meta.label.toLowerCase() && (
                    <span className="ml-1.5 font-normal text-muted-foreground">
                      · {ev.raw_status}
                    </span>
                  )}
                </p>
                {ev.description && (
                  <p className="text-xs text-muted-foreground mt-0.5">{ev.description}</p>
                )}
                {when && <p className="text-[11px] text-muted-foreground/80 mt-0.5">{when}</p>}
              </div>
            </li>
          )
        })}
      </ol>
    </details>
  )
}
