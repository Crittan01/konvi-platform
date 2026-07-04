/**
 * dashboard-logic — lógica pura (sin server deps) del home operativo, extraída
 * para poder cubrirla con tests (F4 2026-07-04). page.tsx es un server component
 * y no es unit-importable (arrastra next/headers), así que la agrupación por día
 * en hora Colombia y el gating de quick links por rol viven aquí.
 */
import { bogotaDayKeys } from '@/lib/date-window'

// ─── Quick links (gating por rol) ──────────────────────────────────────────────

export interface QuickLink {
  href: string
  label: string
  icon: string
  desc: string
}

/**
 * Enlaces de acceso rápido del home, filtrados por rol.
 *  - operator: solo operación diaria (inbox, pedidos, contactos)
 *  - manager: + catálogo y métricas (canWrite)
 *  - owner: + integraciones
 */
export function buildQuickLinks(role: string): QuickLink[] {
  const canWrite = role === 'owner' || role === 'manager'
  return [
    { href: '/dashboard/inbox', label: 'Inbox AI', icon: 'MessageSquare', desc: 'Conversaciones WhatsApp', show: true },
    { href: '/dashboard/orders', label: 'Pedidos', icon: 'Package', desc: 'Gestionar pedidos', show: true },
    { href: '/dashboard/contacts', label: 'Contactos', icon: 'Users', desc: 'Base de clientes', show: true },
    { href: '/dashboard/catalog', label: 'Catálogo', icon: 'ShoppingCart', desc: 'Productos activos', show: canWrite },
    { href: '/dashboard/metrics', label: 'Métricas', icon: 'BarChart2', desc: 'KPIs del negocio', show: canWrite },
    // Copy neutro: el shipping activo es Aveonline (ADR-0019), NO Envia. Se evita
    // nombrar un provider incorrecto; el naming canónico está en needs_founder.
    { href: '/dashboard/integrations', label: 'Integraciones', icon: 'Plug', desc: 'Envíos, pagos y canales', show: role === 'owner' },
  ]
    .filter(l => l.show)
    .map(({ show: _show, ...rest }) => rest)
}

// ─── Agrupación de mensajes por día (hora Colombia) ────────────────────────────

const DAY_LABELS = ['Do', 'Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá']

export interface MessageDayBucket {
  /** 'YYYY-MM-DD' del día en hora Colombia. */
  key: string
  /** Etiqueta corta del día de la semana ('Lu', 'Ma', …). */
  label: string
  /** Límite inferior de la ventana del día en ISO-UTC (00:00 Colombia). */
  fromUTC: string
  /** Límite superior exclusivo en ISO-UTC (00:00 Colombia del día siguiente). */
  toUTC: string
}

const DAY_MS = 24 * 60 * 60 * 1000

/**
 * Los últimos `days` días de CALENDARIO Colombia como ventanas [fromUTC, toUTC).
 * Se usa para emitir un count exacto por día (bounded, sin traer filas) en vez de
 * agrupar en JS un fetch-all que PostgREST trunca a 1000 sin avisar.
 */
export function messageDayBuckets(days = 7, now: Date = new Date()): MessageDayBucket[] {
  return bogotaDayKeys(days, now).map(key => {
    const from = new Date(`${key}T00:00:00-05:00`)
    // getUTCDay sobre la fecha-calendario Colombia da el día de semana correcto.
    const weekday = new Date(`${key}T00:00:00Z`).getUTCDay()
    return {
      key,
      label: DAY_LABELS[weekday],
      fromUTC: from.toISOString(),
      toUTC: new Date(from.getTime() + DAY_MS).toISOString(),
    }
  })
}

// ─── Estados de pedido conocidos (para count-por-estado, sin fetch-all) ─────────

export const ORDER_STATUSES = [
  'pending',
  'pending_payment',
  'confirmed',
  'processing',
  'shipped',
  'delivered',
  'cancelled',
] as const
