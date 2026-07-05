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
  quoted:     { label: 'Cotizado',        color: 'bg-yellow-500/15 text-yellow-700 border-yellow-700/30' },
  labeled:    { label: 'Etiquetado',      color: 'bg-blue-500/15 text-blue-700 border-blue-700/30' },
  picked_up:  { label: 'Recolectado',     color: 'bg-purple-500/15 text-purple-700 border-purple-700/30' },
  in_transit: { label: 'En tránsito',     color: 'bg-indigo-500/15 text-indigo-700 border-indigo-700/30' },
  delivered:  { label: 'Entregado',       color: 'bg-green-500/15 text-green-700 border-green-700/30' },
  cancelled:  { label: 'Cancelado',       color: 'bg-red-500/15 text-red-700 border-red-700/30' },
  pending:    {
    label: 'Pendiente',
    color: 'bg-amber-500/15 text-amber-700 border-amber-700/30',
    hint:  'El carrier aún no confirma la recolección del paquete.',
  },
  exception:  {
    label: 'Novedad',
    color: 'bg-orange-500/15 text-orange-700 border-orange-700/30',
    hint:  'El carrier reportó una novedad. Revisa el detalle en Aveonline y contacta al cliente si es necesario.',
  },
  returned:   {
    label: 'Devuelto',
    color: 'bg-rose-500/15 text-rose-700 border-rose-700/30',
    hint:  'El paquete está siendo devuelto al origen.',
  },
  simulated:  {
    label: 'Simulado',
    color: 'bg-slate-500/15 text-slate-700 border-slate-700/30',
    hint:  'Guía generada en modo simulación (sin envío real). Solo para pruebas.',
  },
  pending_generation: {
    label: 'Guía pendiente',
    color: 'bg-red-500/15 text-red-700 border-red-700/30',
    hint:  'La guía no se pudo generar automáticamente. Reintenta la generación desde Ventas → Pedidos.',
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
