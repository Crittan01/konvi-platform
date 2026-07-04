'use client'

/**
 * Closure form — cliente componente del flow Cerrar cuenta.
 *
 * Renderiza diferente según estado:
 *  - active: 2 secciones (Exportar / Solicitar eliminación)
 *  - soft_deleted_grace_period: banner amber + Cancelar eliminación + countdown
 *  - hard_deleted: not-reachable (page redirect a /dashboard antes)
 */
import { useEffect, useRef, useState, useTransition } from 'react'
import { AlertTriangle, Download, Trash2, X, Loader2, CheckCircle2, ChevronRight } from 'lucide-react'
import {
  requestTenantExport,
  requestTenantDeletion,
  cancelTenantDeletion,
} from '../actions'

interface OffboardingStatus {
  tenant_id: string
  state: 'active' | 'soft_deleted_grace_period' | 'hard_deleted'
  deletion_requested_at: string | null
  deletion_scheduled_for: string | null
  deletion_reason: string | null
  deleted_at: string | null
  is_recoverable: boolean
}

interface Props {
  tenantId: string
  tenantName: string
  status: OffboardingStatus | null
}

export function ClosureForm({ tenantName, status }: Props) {
  const [pending, startTransition] = useTransition()
  const [feedback, setFeedback] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  // Estado del modal "solicitar eliminación".
  const [showRequestModal, setShowRequestModal] = useState(false)
  const [confirmationPhrase, setConfirmationPhrase] = useState('')
  const [reason, setReason] = useState('')
  const modalRef = useRef<HTMLDivElement>(null)
  const firstFieldRef = useRef<HTMLInputElement>(null)

  // a11y del modal destructivo: Escape para cerrar, foco inicial al 1er campo y
  // focus-trap con Tab (antes el foco se quedaba tras el overlay).
  useEffect(() => {
    if (!showRequestModal) return
    firstFieldRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !pending) { setShowRequestModal(false); return }
      if (e.key !== 'Tab') return
      const root = modalRef.current
      if (!root) return
      const focusables = root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      if (focusables.length === 0) return
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [showRequestModal, pending])

  const expectedPhrase = `ELIMINAR ${tenantName}`
  const phraseOk = confirmationPhrase.trim() === expectedPhrase
  const reasonOk = reason.trim().length >= 10

  // ── Action handlers ─────────────────────────────────────────────────────

  const handleExport = () => {
    setFeedback(null)
    startTransition(async () => {
      const result = await requestTenantExport()
      if (!result.ok) {
        setFeedback({ kind: 'err', text: result.error })
        return
      }
      // Trigger download del JSON.
      const blob = new Blob([JSON.stringify(result.data, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `konvi-export-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      // El backend trunca a 10.000 filas por tabla (MAX_ROWS_PER_TABLE) y lo marca
      // en summary.truncated_tables. Antes solo vivía dentro del JSON: el usuario
      // creía tener "TODA" su información sin saber que faltaban filas.
      const truncated = (result.data as { summary?: { truncated_tables?: string[] } })
        ?.summary?.truncated_tables
      if (truncated && truncated.length > 0) {
        setFeedback({
          kind: 'ok',
          text:
            `Export descargado (contiene PII, guárdalo seguro). Aviso: algunas tablas ` +
            `superan 10.000 filas y se truncaron a ese máximo (${truncated.join(', ')}). ` +
            `Para un export completo escríbenos a soporte.`,
        })
      } else {
        setFeedback({
          kind: 'ok',
          text: 'Export descargado. Guárdalo en lugar seguro — contiene PII.',
        })
      }
    })
  }

  const handleRequest = () => {
    if (!phraseOk || !reasonOk) return
    setFeedback(null)
    startTransition(async () => {
      const result = await requestTenantDeletion(confirmationPhrase.trim(), reason.trim())
      if (!result.ok) {
        setFeedback({ kind: 'err', text: result.error })
        return
      }
      setShowRequestModal(false)
      setConfirmationPhrase('')
      setReason('')
      setFeedback({ kind: 'ok', text: result.message })
    })
  }

  const handleCancel = () => {
    setFeedback(null)
    startTransition(async () => {
      const result = await cancelTenantDeletion()
      if (!result.ok) {
        setFeedback({ kind: 'err', text: result.error })
        return
      }
      setFeedback({ kind: 'ok', text: result.message })
    })
  }

  // ── Render según estado ─────────────────────────────────────────────────

  if (status?.state === 'soft_deleted_grace_period') {
    const scheduledFor = status.deletion_scheduled_for
      ? new Date(status.deletion_scheduled_for)
      : null
    const daysRemaining = scheduledFor
      ? Math.ceil((scheduledFor.getTime() - Date.now()) / (1000 * 60 * 60 * 24))
      : 0
    return (
      <div className="space-y-4">
        <div className="rounded-lg border border-amber-700 bg-amber-50 p-4 space-y-2">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-700 mt-0.5 shrink-0" />
            <div className="flex-1">
              <h2 className="text-sm font-semibold text-amber-900">
                Eliminación en curso
              </h2>
              <p className="text-sm text-amber-800 mt-1">
                Tu cuenta será eliminada permanentemente el{' '}
                <strong>{scheduledFor?.toLocaleDateString('es-CO')}</strong>{' '}
                ({daysRemaining} día{daysRemaining !== 1 ? 's' : ''} restante).
                Durante el grace period la cuenta está en lectura-solo.
              </p>
              {status.deletion_reason && (
                <p className="text-xs text-amber-700 mt-2">
                  <strong>Razón:</strong> {status.deletion_reason}
                </p>
              )}
              <p className="text-xs text-amber-700 mt-2">
                Tus credenciales de integraciones (Wompi/Aveonline/Meta/MeLi/
                Telegram) fueron invalidadas. Si cancelas, deberás
                reconectarlas.
              </p>
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={handleCancel}
          disabled={pending}
          className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-md border border-border bg-card hover:bg-accent text-foreground disabled:opacity-50"
        >
          {pending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Cancelando…
            </>
          ) : (
            <>
              <X className="h-4 w-4" /> Cancelar eliminación
            </>
          )}
        </button>

        {feedback && <FeedbackBanner feedback={feedback} />}
      </div>
    )
  }

  // Estado active — 2 secciones.
  return (
    <div className="space-y-6">
      {feedback && <FeedbackBanner feedback={feedback} />}

      {/* Sección 1 — Export */}
      <section className="rounded-lg border border-border bg-card p-5 space-y-3">
        <div className="flex items-start gap-3">
          <Download className="h-5 w-5 text-foreground mt-0.5 shrink-0" />
          <div className="flex-1">
            <h2 className="text-base font-semibold">Exportar todos mis datos</h2>
            <p className="text-sm text-muted-foreground mt-1">
              Descarga un JSON con TODA la información del tenant: contactos,
              conversaciones, mensajes, pedidos, pagos, audit log + portabilidad
              (Ley 1581 Art. 19). Recomendado antes de eliminar la cuenta.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleExport}
          disabled={pending}
          className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-4 py-2 rounded-md bg-foreground text-background hover:opacity-90 disabled:opacity-50"
        >
          {pending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Generando…
            </>
          ) : (
            <>
              <Download className="h-4 w-4" /> Descargar export JSON
            </>
          )}
        </button>
      </section>

      {/* Sección 2 — Solicitar eliminación */}
      <section className="rounded-lg border border-red-700 bg-red-50 p-5 space-y-3">
        <div className="flex items-start gap-3">
          <Trash2 className="h-5 w-5 text-red-700 mt-0.5 shrink-0" />
          <div className="flex-1">
            <h2 className="text-base font-semibold text-red-900">
              Solicitar eliminación de cuenta
            </h2>
            <p className="text-sm text-red-800 mt-1">
              Inicia el proceso de cierre permanente de tu cuenta Konvi:
            </p>
            <ul className="text-sm text-red-800 mt-2 space-y-1 list-disc list-inside">
              <li>Período de gracia de <strong>30 días</strong> — cancelable.</li>
              <li>Tus integraciones (Wompi/Aveonline/Meta/MeLi/Telegram) se invalidan inmediatamente.</li>
              <li>Audit log + consent se preservan 5 años (Ley 1581 Art. 22).</li>
              <li>Tras 30d, eliminación PERMANENTE e irreversible.</li>
            </ul>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setShowRequestModal(true)}
          disabled={pending}
          className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-4 py-2 rounded-md bg-red-700 text-white hover:bg-red-800 disabled:opacity-50"
        >
          <Trash2 className="h-4 w-4" /> Iniciar eliminación
          <ChevronRight className="h-4 w-4" />
        </button>
      </section>

      {/* Modal Solicitar Eliminación */}
      {showRequestModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="closure-modal-title"
          onClick={() => { if (!pending) setShowRequestModal(false) }}
        >
          <div
            ref={modalRef}
            onClick={e => e.stopPropagation()}
            className="w-full max-w-lg rounded-lg border border-red-700 bg-card shadow-xl"
          >
            <header className="flex items-center justify-between p-4 border-b border-border">
              <h2 id="closure-modal-title" className="text-base font-semibold text-red-900 inline-flex items-center gap-2">
                <AlertTriangle className="h-5 w-5" /> Confirmar eliminación
              </h2>
              <button
                type="button"
                onClick={() => setShowRequestModal(false)}
                disabled={pending}
                aria-label="Cerrar"
                className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-accent disabled:opacity-50"
              >
                <X className="h-4 w-4" />
              </button>
            </header>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">
                  Escribe exactamente <code className="font-mono bg-muted px-1.5 py-0.5 rounded">ELIMINAR {tenantName}</code> para confirmar
                </label>
                <input
                  ref={firstFieldRef}
                  type="text"
                  value={confirmationPhrase}
                  onChange={e => setConfirmationPhrase(e.target.value)}
                  disabled={pending}
                  placeholder={`ELIMINAR ${tenantName}`}
                  className={`w-full px-3 py-2 rounded-md border bg-background font-mono text-sm ${
                    confirmationPhrase && !phraseOk
                      ? 'border-red-700'
                      : phraseOk
                        ? 'border-green-600'
                        : 'border-border'
                  }`}
                />
                {confirmationPhrase && !phraseOk && (
                  <p className="text-xs text-red-600 mt-1">
                    Debe coincidir EXACTAMENTE (incluyendo mayúsculas + nombre del tenant).
                  </p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">
                  Razón del cierre (obligatoria, mínimo 10 caracteres)
                </label>
                <textarea
                  value={reason}
                  onChange={e => setReason(e.target.value)}
                  disabled={pending}
                  rows={3}
                  placeholder="Ej: Cierre operativo del negocio · Migración a otra plataforma · Pruebas finalizadas"
                  className={`w-full px-3 py-2 rounded-md border bg-background text-sm ${
                    reason && !reasonOk ? 'border-red-700' : 'border-border'
                  }`}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  {reason.length} caracteres {reasonOk ? '✓' : `(mínimo 10)`}
                </p>
              </div>
            </div>
            <footer className="flex items-center justify-end gap-2 p-4 border-t border-border">
              <button
                type="button"
                onClick={() => setShowRequestModal(false)}
                disabled={pending}
                className="px-3 py-1.5 rounded-md border border-border hover:bg-accent text-sm disabled:opacity-50"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleRequest}
                disabled={pending || !phraseOk || !reasonOk}
                className="px-3 py-1.5 rounded-md bg-red-700 text-white hover:bg-red-800 text-sm inline-flex items-center gap-1.5 disabled:opacity-50"
              >
                {pending ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Procesando…
                  </>
                ) : (
                  <>
                    <Trash2 className="h-3.5 w-3.5" /> Iniciar eliminación 30d
                  </>
                )}
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  )
}

function FeedbackBanner({ feedback }: { feedback: { kind: 'ok' | 'err'; text: string } }) {
  if (feedback.kind === 'ok') {
    return (
      <div className="rounded-md border border-green-700 bg-green-50 p-3 flex items-start gap-2">
        <CheckCircle2 className="h-4 w-4 text-green-700 mt-0.5 shrink-0" />
        <p className="text-sm text-green-800">{feedback.text}</p>
      </div>
    )
  }
  return (
    <div className="rounded-md border border-red-700 bg-red-50 p-3 flex items-start gap-2">
      <AlertTriangle className="h-4 w-4 text-red-700 mt-0.5 shrink-0" />
      <p className="text-sm text-red-800">{feedback.text}</p>
    </div>
  )
}
