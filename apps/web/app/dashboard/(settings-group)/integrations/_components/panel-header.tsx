/**
 * Header compartido para paneles de integración (Sem 7 F2 cierre).
 *
 * Reutilizado por /integrations/{whatsapp,mercadolibre,wompi,envia,telegram}.
 * Renderiza breadcrumb + título + estado de conexión + meta secundaria.
 */
import Link from 'next/link'
import { ArrowLeft, type LucideIcon } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'

type Props = {
  /** Icono del provider (componente lucide-react). */
  Icon: LucideIcon
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

      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12) — la línea de
          estado Conectado/Desconectado con los dots va al description verbatim. */}
      <PageHeader
        icon={Icon}
        title={title}
        description={
          connected ? (
            <>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-success-fg inline-block" />
                Conectado
              </span>
              {metaLine && <> · {metaLine}</>}
            </>
          ) : (
            <>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-muted-foreground inline-block" />
                Desconectado
              </span>
              {' · Configura esta integración desde el panel de Integraciones.'}
            </>
          )
        }
      />
    </div>
  )
}
