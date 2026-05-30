/**
 * Primitivas UX unificadas para tabs Setup de paneles de integración
 * (Sem 7 F2 cierre — unificación visual).
 *
 * Patrón canónico (4 secciones siempre en este orden):
 *   1. <SetupSection icon={KeyRound} title="Identidad">       — credenciales
 *   2. <SetupSection icon={Webhook} title="Webhook & Eventos"> — comunicación
 *   3. <ComplianceSection title="Gates activos" gates={...} />  — cumplimiento
 *   4. <DangerZoneSection ... />                                — desconectar
 *
 * Estado disconnected: <EmptyDisconnected ... />.
 * Banner footer migración: <MigrationBanner>...</MigrationBanner>.
 *
 * Helpers:
 *   - <SetupField label="WABA ID" value={...} /> — celda label + value
 *   - <SetupGrid> — grid 2-col responsive
 */
import { AlertCircle, ShieldCheck, ShieldOff } from 'lucide-react'

// ─── Field + Grid helpers ───────────────────────────────────────────────────

export function SetupField({
  label, value, mono = true, italic = false,
}: {
  label: string
  value: React.ReactNode
  mono?: boolean
  italic?: boolean
}) {
  return (
    <div className="space-y-0.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={
          'text-sm' +
          (mono ? ' font-mono' : '') +
          (italic ? ' italic text-muted-foreground' : '')
        }
      >
        {value ?? <span className="text-muted-foreground italic">—</span>}
      </div>
    </div>
  )
}

export function SetupGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">{children}</div>
  )
}

// ─── SetupSection: card neutral para Identidad / Comunicación ──────────────

export function SetupSection({
  icon: Icon, title, badge, children,
}: {
  icon: React.ElementType
  title: string
  /** Pill secundario opcional a la derecha del título (e.g. "Modo: producción"). */
  badge?: string | null
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border border-border bg-card p-4 space-y-4">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary" />
        <h3 className="font-semibold text-foreground">{title}</h3>
        {badge && (
          <span className="ml-auto text-xs text-muted-foreground bg-muted/30 border rounded-full px-2 py-0.5">
            {badge}
          </span>
        )}
      </div>
      {children}
    </section>
  )
}

// ─── ComplianceSection: lista de gates como rows con chip verde ────────────

export type ComplianceGate = {
  label: string
  /** Texto del chip (e.g. "Enforcement activo", "HMAC-SHA256"). */
  value: string
  /** false → chip ámbar (warn). Default true → emerald. */
  ok?: boolean
}

export function ComplianceSection({
  title = 'Gates activos',
  gates,
}: {
  title?: string
  gates: ComplianceGate[]
}) {
  return (
    <section className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-emerald-700" />
        <h3 className="font-semibold text-foreground">{title}</h3>
      </div>
      <div className="space-y-2 text-sm">
        {gates.map((g, i) => {
          const okClass =
            g.ok === false
              ? 'bg-amber-700/10 border border-amber-700/40 text-amber-900'
              : 'bg-emerald-700/10 border border-emerald-700/40 text-emerald-900'
          return (
            <div key={i} className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{g.label}</span>
              <span
                className={
                  'inline-flex items-center gap-1 text-xs rounded-full px-2 py-0.5 shrink-0 ' +
                  okClass
                }
              >
                {g.ok === false ? null : <ShieldCheck className="h-3 w-3" />}
                {g.value}
              </span>
            </div>
          )
        })}
      </div>
    </section>
  )
}

// ─── DangerZoneSection: warning + acción peligrosa ─────────────────────────

export function DangerZoneSection({
  title = 'Zona de riesgo',
  description,
  actionLabel,
  actionDisabled = true,
  onAction,
}: {
  title?: string
  description: React.ReactNode
  actionLabel: string
  /** Si true, el botón queda deshabilitado con tooltip "Disponible próximamente". */
  actionDisabled?: boolean
  /** Server action a invocar (form action). Solo si actionDisabled=false. */
  onAction?: () => void
}) {
  return (
    <section className="rounded-xl border border-rose-700/30 bg-rose-700/5 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <ShieldOff className="h-4 w-4 text-rose-800" />
        <h3 className="font-semibold text-rose-900">{title}</h3>
      </div>
      <div className="text-sm text-rose-900/80">{description}</div>
      <button
        type="button"
        onClick={onAction}
        disabled={actionDisabled}
        title={actionDisabled ? 'Disponible próximamente' : undefined}
        className="text-sm font-medium text-rose-800 hover:text-rose-900 underline disabled:opacity-60 disabled:cursor-not-allowed disabled:no-underline"
      >
        {actionLabel}
        {actionDisabled && ' (próximamente)'}
      </button>
    </section>
  )
}

// ─── MigrationBanner: aviso ámbar al final del tab Setup ───────────────────

export function MigrationBanner({ children }: { children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-amber-700/30 bg-amber-700/5 p-4 flex items-start gap-3">
      <AlertCircle className="h-4 w-4 text-amber-800 mt-0.5 shrink-0" />
      <p className="text-sm text-amber-900">{children}</p>
    </section>
  )
}

// ─── EmptyDisconnected: placeholder cuando no hay integración conectada ────

export function EmptyDisconnected({
  icon: Icon, providerLabel, helpText,
}: {
  icon: React.ElementType
  providerLabel: string
  /** Texto secundario explicando cómo se conecta (1-2 líneas). */
  helpText?: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center space-y-3">
      <Icon className="h-8 w-8 mx-auto text-muted-foreground/60" />
      <p className="text-sm text-muted-foreground">
        <strong>{providerLabel}</strong> aún no está conectado para este tenant.
      </p>
      {helpText && (
        <p className="text-xs text-muted-foreground max-w-md mx-auto">
          {helpText}
        </p>
      )}
    </div>
  )
}
