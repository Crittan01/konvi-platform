/**
 * Tab Calidad — WhatsApp.
 *
 * Lee la señal de calidad y el tier de mensajería que el connector persiste en
 * tenant_integrations.credentials vía el webhook phone_number_quality_update
 * (template_events.persist_phone_quality_update escribe `tier` y `quality_signal`).
 *
 * Sin webhook aún recibido, los campos no existen → estado "sin datos todavía".
 */
import { Activity, TrendingUp, AlertCircle } from 'lucide-react'

type Props = {
  connected: boolean
  credentials: Record<string, string>
}

// Meta reporta el messaging limit como TIER_* (unique recipients / 24h).
const TIER_LIMITS: Record<string, string> = {
  TIER_50: '50 destinatarios únicos / 24h',
  TIER_250: '250 destinatarios únicos / 24h',
  TIER_1K: '1.000 destinatarios únicos / 24h',
  TIER_10K: '10.000 destinatarios únicos / 24h',
  TIER_100K: '100.000 destinatarios únicos / 24h',
  TIER_UNLIMITED: 'Sin límite',
}

// quality_signal viene de eventos FLAGGED / UNFLAGGED del número.
const QUALITY_UI: Record<string, { label: string; cls: string; dot: string }> = {
  UNFLAGGED: {
    label: 'Saludable',
    cls: 'bg-emerald-700/10 border-emerald-700/40 text-emerald-900',
    dot: 'bg-emerald-700',
  },
  FLAGGED: {
    label: 'Marcado por Meta',
    cls: 'bg-rose-700/10 border-rose-700/40 text-rose-900',
    dot: 'bg-rose-700',
  },
}

export default function WhatsAppQuality({ connected, credentials }: Props) {
  if (!connected) {
    return (
      <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center">
        <Activity className="h-8 w-8 mx-auto text-muted-foreground/60" />
        <p className="text-sm text-muted-foreground mt-2">
          Conecta WhatsApp en la pestaña Setup para empezar a ver métricas de calidad.
        </p>
      </div>
    )
  }

  const tierRaw = (credentials.tier || '').toUpperCase()
  const qualityRaw = (credentials.quality_signal || '').toUpperCase()
  const tierLabel = tierRaw ? (TIER_LIMITS[tierRaw] ?? tierRaw) : null
  const quality = qualityRaw ? QUALITY_UI[qualityRaw] : null
  const hasData = Boolean(tierLabel || quality)

  return (
    <div className="space-y-5">
      {!hasData && (
        <div className="rounded-xl border border-amber-700/30 bg-amber-700/5 p-4 flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-amber-800 mt-0.5 shrink-0" />
          <div className="text-sm text-amber-900">
            Aún no hemos recibido señales de calidad de Meta para este número.
            Los datos aparecen cuando Meta emite el primer evento
            {' '}<span className="font-mono text-xs">phone_number_quality_update</span>
            {' '}(tras enviar mensajes reales).
          </div>
        </div>
      )}

      {/* Quality signal */}
      <section className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Estado del número</h3>
        </div>
        {quality ? (
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border text-sm font-medium ${quality.cls}`}>
              <span className={`h-2 w-2 rounded-full ${quality.dot}`} />
              {quality.label}
            </span>
            {qualityRaw === 'FLAGGED' && (
              <span className="text-xs text-rose-900">
                Reduce envíos proactivos: Meta puede restringir el número.
              </span>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Sin señal de calidad todavía.</p>
        )}
      </section>

      {/* Tier de mensajes */}
      <section className="rounded-xl border border-border bg-card p-4 space-y-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Tier de mensajería</h3>
        </div>
        {tierLabel ? (
          <>
            <div className="text-sm text-foreground font-medium">{tierLabel}</div>
            <div className="text-xs text-muted-foreground">
              El tier lo ajusta Meta según la calidad sostenida del número. Aplica a mensajes
              iniciados por el negocio (plantillas MARKETING); las respuestas dentro de la
              ventana de 24h no consumen tier.
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Sin tier reportado todavía.</p>
        )}
      </section>
    </div>
  )
}
