/**
 * Constantes de configuración del Inbox.
 *
 * Refactor 2026-05-29 — extraído del monolito `page.tsx`.
 * Puro: server+client safe.
 */
import type { FilterStatus } from './types'

// Rev. 109 founder 2026-05-28 — SLA threshold para escalación human_takeover.
// Debe coincidir con worker.py HUMAN_TAKEOVER_SLA_HOURS (default 2h).
// El operador puede agregar `NEXT_PUBLIC_HUMAN_TAKEOVER_SLA_HOURS=N` para override
// si en el futuro el backend cambia. Hoy 2h es estándar.
export const SLA_BREACH_HOURS =
  Number(process.env.NEXT_PUBLIC_HUMAN_TAKEOVER_SLA_HOURS || 2)
export const SLA_BREACH_MS = SLA_BREACH_HOURS * 60 * 60 * 1000

export const ORDER_STATUS_LABEL: Record<string, string> = {
  pending:    'Pendiente',
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

export const ORDER_STATUS_COLOR: Record<string, string> = {
  pending:    'bg-yellow-500/10 text-yellow-700 border-yellow-500/20',
  confirmed:  'bg-blue-500/10 text-blue-700 border-blue-500/20',
  processing: 'bg-purple-500/10 text-purple-700 border-purple-500/20',
  shipped:    'bg-sky-500/10 text-sky-700 border-sky-500/20',
  delivered:  'bg-emerald-500/10 text-emerald-700 border-emerald-500/20',
  cancelled:  'bg-red-500/10 text-red-600 border-red-500/20',
}

// ─── Status conversación ──────────────────────────────────────────────────────
// A4: cada estado lleva un description que se muestra como tooltip HTML nativo
// en los badges. Permite que un operador no técnico entienda el significado y
// las transiciones permitidas sin abrir documentación externa.
export const STATUS_CONFIG = {
  bot_active: {
    label: 'Bot activo',
    color: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20',
    dot: 'bg-emerald-500',
    description: 'Bot activo: el asistente IA responde automáticamente con catálogo, KB y FSM de venta. Toma el control con "Tomar control" si necesitas intervenir.',
  },
  human_takeover: {
    label: 'Agente humano',
    color: 'bg-amber-500/10 text-amber-700 border-amber-500/20',
    dot: 'bg-amber-500',
    description: 'Agente humano: un operador tomó el control y el bot está pausado. Para devolver al bot, usa "Volver al bot" aquí o desde Telegram envía /resolver {id}.',
  },
  closed: {
    label: 'Cerrada',
    color: 'bg-slate-500/10 text-slate-700 border-slate-500/20',
    dot: 'bg-slate-500',
    description: 'Cerrada: la conversación quedó archivada por inactividad o resolución manual. Si el cliente vuelve a escribir, se reabre automáticamente como Bot activo.',
  },
  opted_out: {
    label: 'Opt-out',
    color: 'bg-rose-500/10 text-rose-700 border-rose-500/20',
    dot: 'bg-rose-500',
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
