/**
 * Tab Calidad — WhatsApp.
 *
 * Placeholder visual hoy. Implementación real Sem 11 (MA-6
 * tenant_provider_health dashboard).
 */
import { Activity, TrendingUp, AlertCircle } from 'lucide-react'

type Props = {
  connected: boolean
  credentials: Record<string, string>
}

export default function WhatsAppQuality({ connected }: Props) {
  if (!connected) {
    return (
      <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center">
        <Activity className="h-8 w-8 mx-auto text-muted-foreground/60" />
        <p className="text-sm text-muted-foreground mt-2">
          Conectá WhatsApp en la tab Setup para empezar a ver métricas de calidad.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-amber-700/30 bg-amber-700/5 p-4 flex items-start gap-3">
        <AlertCircle className="h-5 w-5 text-amber-800 mt-0.5 shrink-0" />
        <div className="text-sm text-amber-900">
          <strong>Próximamente (Sem 11).</strong> Métricas de calidad del número
          en tiempo real (rating GREEN/YELLOW/RED), tier de mensajes, historico 30
          días + alertas automáticas a operadores cuando baje la calidad.
        </div>
      </div>

      {/* Preview visual */}
      <section className="rounded-xl border border-border bg-card p-4 space-y-4 opacity-60">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Quality rating (preview)</h3>
        </div>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-700/10 border border-emerald-700/40 text-emerald-900 text-sm font-medium">
            <span className="h-2 w-2 rounded-full bg-emerald-700" />
            GREEN
          </span>
          <span className="text-xs text-muted-foreground">
            Lectura simulada — disponible en producción Sem 11
          </span>
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-4 space-y-2 opacity-60">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Tier de mensajes (preview)</h3>
        </div>
        <div className="text-sm">
          <strong>1.000</strong> mensajes / 24h
        </div>
        <div className="text-xs text-muted-foreground">
          Próximo upgrade: 10.000 / 24h tras 30 días GREEN sostenido
        </div>
      </section>
    </div>
  )
}
