/**
 * Header compartido para paneles de integración (Sem 7 F2 cierre).
 *
 * Reutilizado por /integrations/{whatsapp,mercadolibre,wompi,envia,telegram}.
 * Renderiza breadcrumb + título + estado de conexión + meta secundaria.
 */
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'

type Props = {
  /** Icono del provider (componente lucide-react). */
  Icon: React.ElementType
  title: string
  connected: boolean
  /** Texto secundario a la derecha del status (e.g. "WABA 1234 · Tier 1k/24h"). */
  metaLine?: string | null
}

export default function PanelHeader({ Icon, title, connected, metaLine }: Props) {
  return (
    <div className="space-y-3">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link
          href="/dashboard/integrations"
          className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Volver a Integraciones
        </Link>
      </div>

      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Icon className="h-5 w-5 text-primary" /> {title}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {connected ? (
            <>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-emerald-700 inline-block" />
                Connected
              </span>
              {metaLine && <> · {metaLine}</>}
            </>
          ) : (
            <>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-slate-700 inline-block" />
                Disconnected
              </span>
              {' · Configurá esta integración desde el panel de Integraciones.'}
            </>
          )}
        </p>
      </div>
    </div>
  )
}
