/**
 * Constantes de configuración del Inbox.
 *
 * Refactor 2026-05-29 — extraído del monolito `page.tsx`.
 * Puro: server+client safe.
 */
import type { FilterStatus, MessageContentType } from './types'

// 2026-07-04 (F7) — content_type que NO deben renderizarse como burbuja en el
// chat. Son filas internas (snapshots del orchestrator) o de auditoría
// append-only (escalación / breach de SLA que estampan los crons). Antes se
// pintaban como burbujas vacías. Se excluyen en el fetch (use-messages) y en el
// handler Realtime. Mantener alineado con el union de MessageContentType.
export const NON_RENDERABLE_CONTENT_TYPES: readonly MessageContentType[] = [
  'context_snapshot',
  'escalation_audit',
  'sla_breach_audit',
] as const

// Forma que espera el filtro PostgREST `.not('content_type', 'in', '(...)')`.
export const NON_RENDERABLE_CONTENT_TYPES_PG =
  `(${NON_RENDERABLE_CONTENT_TYPES.join(',')})`

// Rev. 109 founder 2026-05-28 — SLA threshold para escalación human_takeover.
// Debe coincidir con worker.py HUMAN_TAKEOVER_SLA_HOURS (default 2h).
// El operador puede agregar `NEXT_PUBLIC_HUMAN_TAKEOVER_SLA_HOURS=N` para override
// si en el futuro el backend cambia. Hoy 2h es estándar.
export const SLA_BREACH_HOURS =
  Number(process.env.NEXT_PUBLIC_HUMAN_TAKEOVER_SLA_HOURS || 2)
export const SLA_BREACH_MS = SLA_BREACH_HOURS * 60 * 60 * 1000

export const ORDER_STATUS_LABEL: Record<string, string> = {
  pending:    'Pendiente',
  pending_payment: 'Esperando pago',  // F62: estado con que el bot crea órdenes con link Wompi
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

export const ORDER_STATUS_COLOR: Record<string, string> = {
  pending:    'bg-warning-bg text-warning-fg border-warning-border',
  pending_payment: 'bg-warning-bg text-warning-fg border-warning-border',  // F62
  confirmed:  'bg-info-bg text-info-fg border-info-border',
  processing: 'bg-ai-bg text-ai-fg border-ai-border',
  shipped:    'bg-info-bg text-info-fg border-info-border',
  delivered:  'bg-success-bg text-success-fg border-success-border',
  cancelled:  'bg-danger-bg text-danger-fg border-danger-border',
}

// ─── Status conversación ──────────────────────────────────────────────────────
// A4: cada estado lleva un description que se muestra como tooltip HTML nativo
// en los badges. Permite que un operador no técnico entienda el significado y
// las transiciones permitidas sin abrir documentación externa.
export const STATUS_CONFIG = {
  bot_active: {
    label: 'Bot activo',
    color: 'bg-success-bg text-success-fg border-success-border',
    dot: 'bg-success-fg',
    description: 'Bot activo: el asistente IA responde automáticamente con catálogo, KB y FSM de venta. Toma el control con "Tomar control" si necesitas intervenir.',
  },
  human_takeover: {
    label: 'Agente humano',
    color: 'bg-warning-bg text-warning-fg border-warning-border',
    dot: 'bg-warning-fg',
    description: 'Agente humano: un operador tomó el control y el bot está pausado. Para devolver al bot, usa "Volver al bot" aquí o desde Telegram envía /resolver {id}.',
  },
  closed: {
    label: 'Cerrada',
    color: 'bg-muted text-muted-foreground border-border',
    dot: 'bg-muted-foreground',
    description: 'Cerrada: la conversación quedó archivada por inactividad o resolución manual. Si el cliente vuelve a escribir, se reabre automáticamente como Bot activo.',
  },
  opted_out: {
    label: 'Opt-out',
    color: 'bg-danger-bg text-danger-fg border-danger-border',
    dot: 'bg-danger-fg',
    description: 'Cliente revocó consent vía STOP/BAJA/CANCELAR (rev. 105 H.4.1). No recibirá mensajes proactivos. Si vuelve a escribir voluntariamente, el bot puede responder dentro de la ventana de 24h, pero outbound proactivo (templates HSM) sigue bloqueado por consent_revoked_at.',
  },
}

// Rev. 109 founder 2026-05-29 — filtros simplificados de 7 → 4 chips.
//
// Justificación: la decisión cognitiva del operador es de 3 caminos:
//   1) "Lo que tengo que atender HOY" → Activas (default).
//   2) "Lo que me está rompiendo SLA AHORA" → ⏰ SLA breach.
//   3) "Compliance/auditoría puntual" → Opt-out.
//   + Fallback drill-down → Todas (incluye cerradas).
//
// Eliminados:
// Rev. 109 founder 2026-05-30 — re-confirmados 4 chips canónicos.
// Bot/Agente/Cerradas eliminados como redundantes:
//   - Bot/Agente: el operador ya ve agentic_state per conversación.
//   - Cerradas: cubierto por toggle "Ver archivadas" (>90d) + filtro Todas.
// 4 chips reflejan las 4 mentalidades distintas del operador:
//   1) "Lo que tengo que atender HOY" → Activas (default).
//   2) "Lo que me está rompiendo SLA AHORA" → ⏰ SLA breach.
//   3) "Compliance/auditoría puntual" → Opt-out.
//   4) Escape hatch ver todo → Todas.
export const FILTER_OPTIONS: { value: FilterStatus; label: string }[] = [
  { value: 'active',     label: 'Activas' },
  { value: 'sla_breach', label: '⏰ Vencidas' },
  { value: 'opted_out',  label: 'No contactar' },
  { value: 'all',        label: 'Todas' },
]

// Rev. 109 — agentic_state badge UI (Day 5).
export const AGENTIC_STATE_LABELS: Record<string, string> = {
  GREETING: 'Saludo',
  EXPLORING: 'Explorando',
  CART_BUILDING: 'Carrito',
  PII_COLLECTION: 'Datos',
  SHIPPING_QUOTE: 'Cotizando',
  CARRIER_SELECTION: 'Transp.',
  PAYMENT: 'Pago',
  POST_PAYMENT: 'Post-pago',
  HUMAN_HANDOFF: 'Humano',
}

// Rev. 109 — prioridad de status para elegir conv "primary" del grupo por phone.
// bot_active gana sobre human_takeover sobre opted_out sobre closed.
export const STATUS_PRIORITY: Record<string, number> = {
  bot_active: 0,
  human_takeover: 1,
  opted_out: 2,
  closed: 3,
}

export const TZ_CO = 'America/Bogota'
