'use client'

/**
 * T7.4 — Micro-celebraciones de dinero (Spec §4.2, directiva founder: la firma
 * diferencial en TODO el front). Al llegar por realtime una transición de
 * pedido a `confirmed`/`delivered`, se emite UN toast sonner con:
 *   - check animado (`CelebrationCheck` del DS — pop spring una sola vez,
 *     estático bajo reduced-motion),
 *   - monto con count-up sutil (`useCountUp` — bajo reduced-motion muestra el
 *     valor final directo),
 *   - SIN confetti pesado ni loops.
 *
 * Reglas:
 *   - UNA vez por evento: dedupe por `${orderId}:${status}` en la sesión.
 *   - La transición se detecta con el payload UPDATE de postgres_changes
 *     (`orders` tiene REPLICA IDENTITY FULL → `old.status` viaja; sin cambio
 *     real de estado — p. ej. edición de notas — NO se celebra).
 *   - El toast es el canal único de feedback del DS (sonner temado Kaiu).
 */
import { toast } from 'sonner'
import { CheckCircle2, PackageCheck } from 'lucide-react'
import { CelebrationCheck } from '@/components/ui/motion'
import { useCountUp } from '@/lib/use-count-up'

const LABELS: Record<string, string> = {
  confirmed: 'Pago confirmado',
  delivered: 'Pedido entregado',
}

const ICONS: Record<string, typeof CheckCircle2> = {
  confirmed: CheckCircle2,
  delivered: PackageCheck,
}

/** Dedupe de sesión: `${orderId}:${status}` ya celebrados. */
const celebrated = new Set<string>()

interface MoneyEvent {
  orderId: string
  status: 'confirmed' | 'delivered'
  totalAmount: number | null
}

/** Contenido del toast: check animado + label + monto con count-up. */
function MoneyEventToastBody({ status, totalAmount }: { status: string; totalAmount: number | null }) {
  const shown = useCountUp(totalAmount ?? 0, 550)
  const Icon = ICONS[status] ?? CheckCircle2
  return (
    <span className="flex items-center gap-2.5">
      <CelebrationCheck className="inline-flex items-center justify-center h-8 w-8 rounded-full bg-emerald-500/15 text-emerald-600 ring-1 ring-emerald-600/25 shrink-0">
        <Icon className="h-4 w-4" aria-hidden />
      </CelebrationCheck>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-card-foreground">
          {LABELS[status] ?? status}
        </span>
        {totalAmount !== null && (
          <span className="block text-xs text-muted-foreground tabular-nums">
            ${Math.round(shown).toLocaleString('es-CO')}
          </span>
        )}
      </span>
    </span>
  )
}

/**
 * Detecta una transición A `confirmed`/`delivered` en un payload UPDATE de
 * postgres_changes sobre `orders`. Null si no aplica (otro evento/estado,
 * mismo estado, o sin id). `total_amount` llega serializado (string) → Number
 * defensivo (mismo patrón que el KPI de ventas del home).
 */
export function moneyTransitionFromPayload(payload: {
  eventType: string
  old: Record<string, unknown>
  new: Record<string, unknown>
}): MoneyEvent | null {
  if (payload.eventType !== 'UPDATE') return null
  const n = payload.new as { id?: unknown; status?: unknown; total_amount?: unknown }
  const o = payload.old as { status?: unknown }
  if (typeof n?.id !== 'string' || typeof n.status !== 'string') return null
  if (n.status !== 'confirmed' && n.status !== 'delivered') return null
  if (o?.status === n.status) return null // sin transición real (edición, etc.)
  const total = Number(n.total_amount)
  return {
    orderId: n.id,
    status: n.status,
    totalAmount: Number.isFinite(total) ? total : null,
  }
}

/** Celebra un money event: una sola vez por (orden, estado) en la sesión. */
export function celebrateOrderMoneyEvent(ev: MoneyEvent): void {
  const key = `${ev.orderId}:${ev.status}`
  if (celebrated.has(key)) return
  celebrated.add(key)
  toast.custom(
    () => <MoneyEventToastBody status={ev.status} totalAmount={ev.totalAmount} />,
    { duration: 4000 },
  )
}

/** Helper para el handler realtime: payload UPDATE de orders → celebración. */
export function maybeCelebrateFromPayload(payload: {
  eventType: string
  old: Record<string, unknown>
  new: Record<string, unknown>
}): void {
  const ev = moneyTransitionFromPayload(payload)
  if (ev) celebrateOrderMoneyEvent(ev)
}
