/**
 * Helpers de formato + lógica pura del Inbox.
 *
 * Refactor 2026-05-29 — extraído del monolito `page.tsx`.
 * Puro: server+client safe, testable sin DOM.
 */
import {
  AGENTIC_STATE_LABELS,
  SLA_BREACH_MS,
  STATUS_PRIORITY,
  TZ_CO,
} from './constants'
import type { AgenticState, ConvGroup, Conversation, ProductVariation } from './types'

// Normaliza y formatea teléfono sin importar si el raw ya trae '+' o espacios.
export const formatPhone = (raw: string): string => {
  const digits = (raw || '').replace(/\D/g, '')
  if (digits.startsWith('57') && digits.length === 12)
    return `+57 ${digits.slice(2, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`
  return digits ? `+${digits}` : (raw || '')
}

export const agenticStateLabel = (s: AgenticState): string =>
  AGENTIC_STATE_LABELS[s] ?? s

export const getAgenticStateBadgeColor = (s: AgenticState): string => {
  // Paleta neutra (no shades 300-500 fluorescentes per feedback_ui_colors).
  switch (s) {
    case 'GREETING':
    case 'EXPLORING':
      return 'bg-slate-100 text-slate-700 border-slate-200'
    case 'CART_BUILDING':
      return 'bg-blue-50 text-blue-700 border-blue-200'
    case 'PII_COLLECTION':
      return 'bg-amber-50 text-amber-700 border-amber-200'
    case 'SHIPPING_QUOTE':
    case 'CARRIER_SELECTION':
      return 'bg-violet-50 text-violet-700 border-violet-200'
    case 'PAYMENT':
      return 'bg-orange-50 text-orange-700 border-orange-200'
    case 'POST_PAYMENT':
      return 'bg-emerald-50 text-emerald-700 border-emerald-200'
    case 'HUMAN_HANDOFF':
      return 'bg-rose-50 text-rose-700 border-rose-200'
    default:
      return 'bg-slate-100 text-slate-700 border-slate-200'
  }
}

export const timeAgo = (dateStr: string) => {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'ahora'
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

export const formatDate = (d: string) => {
  try {
    return new Date(d).toLocaleDateString('es-CO', {
      day: '2-digit', month: 'short', year: 'numeric', timeZone: TZ_CO,
    })
  } catch { return d }
}

export const formatDateTime = (d: string) => {
  try {
    return new Date(d).toLocaleString('es-CO', {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: TZ_CO,
    })
  } catch { return d }
}

export const formatMoney = (v: number) =>
  new Intl.NumberFormat('es-CO', {
    style: 'currency', currency: 'COP', minimumFractionDigits: 0,
  }).format(v)

export function variationLabel(v: ProductVariation): string {
  if (v.attributes && Object.keys(v.attributes).length > 0) {
    return Object.entries(v.attributes).map(([k, val]) => `${k}: ${val}`).join(', ')
  }
  return v.sku || 'Estándar'
}

// Rev. 109 — heuristic SLA breach detection (front-side, sin query extra).
// El worker hace el chequeo real cada 10min + envía notif Telegram + persiste
// audit row. Esta función es para UI render — operador ve breach AHORA.
export function isSlaBreach(conv: Conversation): boolean {
  if (conv.status !== 'human_takeover') return false
  const lastTs = conv.last_interaction_at ?? conv.created_at
  return Date.now() - new Date(lastTs).getTime() >= SLA_BREACH_MS
}

// Rev. 109 founder 2026-05-28 — agrupación por phone.
// Prioridad de la conv "primary" del grupo:
//   1) status='bot_active' (activa hoy)
//   2) status='human_takeover' (operador atendiendo)
//   3) más reciente por last_interaction_at
export function groupConvsByPhone(convs: Conversation[]): ConvGroup[] {
  const byPhone = new Map<string, Conversation[]>()
  for (const c of convs) {
    const key = c.customer_phone || '?'
    const arr = byPhone.get(key) ?? []
    arr.push(c)
    byPhone.set(key, arr)
  }
  const groups: ConvGroup[] = []
  // forEach() en vez de for-of directo: tsconfig del proyecto NO tiene
  // downlevelIteration y target ES5 — iterar Map<,> directo rompe
  // `next build` (baseline 2026-05-29).
  byPhone.forEach((list, phone) => {
    const sorted = [...list].sort((a, b) => {
      // Primero por status priority (bot_active gana), luego por timestamp desc.
      const pa = STATUS_PRIORITY[a.status] ?? 99
      const pb = STATUS_PRIORITY[b.status] ?? 99
      if (pa !== pb) return pa - pb
      const ta = new Date(a.last_interaction_at ?? a.created_at).getTime()
      const tb = new Date(b.last_interaction_at ?? b.created_at).getTime()
      return tb - ta
    })
    const [primary, ...others] = sorted
    groups.push({ phone, primary, others })
  })
  // Ordenar grupos por última actividad de su primary (más reciente primero).
  groups.sort((a, b) => {
    const ta = new Date(a.primary.last_interaction_at ?? a.primary.created_at).getTime()
    const tb = new Date(b.primary.last_interaction_at ?? b.primary.created_at).getTime()
    return tb - ta
  })
  return groups
}
