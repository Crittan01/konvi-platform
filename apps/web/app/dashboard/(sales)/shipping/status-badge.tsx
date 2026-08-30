'use client'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Info } from 'lucide-react'

// Catálogo canónico de estados de `shipments.status`.
// Incluye TODOS los valores que los escritores reales producen:
//  - Flujo cotizador/guía: quoted, labeled, picked_up, in_transit, delivered, cancelled
//  - Webhook Aveonline (fn_record_shipment_tracking_event): pending, exception, returned
//  - Wompi webhook: simulated (guía simulada), pending_generation (guía falló)
// Antes estos 5 últimos se renderizaban como texto crudo en inglés con color fallback.
export type StatusMeta = { label: string; color: string; hint?: string }

// Catálogo canónico compartido — reutilizado por StatusBadge y el timeline de
// tracking (shipment-timeline.tsx) para no divergir en labels es-CO/colores.
export const STATUS_META: Record<string, StatusMeta> = {
  quoted:     { label: 'Cotizado',        color: 'bg-warning-bg text-warning-fg border-warning-border' },
  labeled:    { label: 'Etiquetado',      color: 'bg-info-bg text-info-fg border-info-border' },
  picked_up:  { label: 'Recolectado',     color: 'bg-ai-bg text-ai-fg border-ai-border' },
  in_transit: { label: 'En tránsito',     color: 'bg-ai-bg text-ai-fg border-ai-border' },
  delivered:  { label: 'Entregado',       color: 'bg-success-bg text-success-fg border-success-border' },
  cancelled:  { label: 'Cancelado',       color: 'bg-danger-bg text-danger-fg border-danger-border' },
  pending:    {
    label: 'Pendiente',
    color: 'bg-warning-bg text-warning-fg border-warning-border',
    hint:  'El carrier aún no confirma la recolección del paquete.',
  },
  exception:  {
    label: 'Novedad',
    color: 'bg-warning-bg text-warning-fg border-warning-border',
    hint:  'El carrier reportó una novedad. Revisa el detalle en Aveonline y contacta al cliente si es necesario.',
  },
  returned:   {
    label: 'Devuelto',
    color: 'bg-danger-bg text-danger-fg border-danger-border',
    hint:  'El paquete está siendo devuelto al origen.',
  },
  simulated:  {
    label: 'Simulado',
    color: 'bg-muted text-muted-foreground border-border',
    hint:  'Guía generada en modo simulación (sin envío real). Solo para pruebas.',
  },
  pending_generation: {
    label: 'Guía pendiente',
    color: 'bg-danger-bg text-danger-fg border-danger-border',
    hint:  'La guía no se pudo generar automáticamente. Reintenta la generación desde Ventas → Pedidos.',
  },
  generating: {
    label: 'Generando guía',
    color: 'bg-warning-bg text-warning-fg border-warning-border',
    hint:  'La guía se está generando. Si queda en este estado, la generación se interrumpió (posible timeout de Aveonline): verifica en Aveonline si la guía existe antes de reintentar, para no duplicar el cobro.',
  },
}

export function getStatusMeta(status: string): StatusMeta {
  return STATUS_META[status] ?? {
    label: status,
    color: 'bg-muted text-muted-foreground border-border',
  }
}

export function StatusBadge({ status }: { status: string }) {
  const meta = getStatusMeta(status)

  const chip = (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full border ${meta.color}`}
    >
      {meta.label}
      {meta.hint && <Info className="h-3 w-3 opacity-70" aria-hidden="true" />}
    </span>
  )

  if (!meta.hint) return chip

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="cursor-help"
            aria-label={`${meta.label}: ${meta.hint}`}
          >
            {chip}
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-xs">{meta.hint}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
