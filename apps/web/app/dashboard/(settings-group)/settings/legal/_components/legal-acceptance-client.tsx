'use client'

import { useState, useTransition } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useConfirm } from '@/components/ui/confirm-dialog'
import { CheckCircle2, AlertCircle, Loader2, ExternalLink } from 'lucide-react'

type Acceptance = {
  id: string
  document_id: string
  document_version: string
  accepted_by_email: string | null
  accepted_at: string
}

type ActionResult = { ok: boolean; error?: string; message?: string }

type Props = {
  currentVersions: Record<string, string>
  documentLabels: Record<string, { label: string; description: string; href: string }>
  acceptedByDoc: Record<string, Acceptance | undefined>
  history: Acceptance[]
  canAccept: boolean
  acceptAction: (fd: FormData) => Promise<ActionResult>
}

export default function LegalAcceptanceClient({
  currentVersions, documentLabels, acceptedByDoc, history, canAccept, acceptAction,
}: Props) {
  const [isPending, startTransition] = useTransition()
  const [busyDoc, setBusyDoc] = useState<string | null>(null)
  const confirmar = useConfirm()

  const handleAccept = async (docId: string, docVersion: string) => {
    if (!(await confirmar({
      title: `Aceptar ${documentLabels[docId].label} (${docVersion})`,
      description:
        'La aceptación queda registrada de forma inmutable con tu email, IP y fecha. ' +
        'Si el documento cambia de versión, tendrás que aceptarlo de nuevo.',
      confirmLabel: 'Aceptar documento',
      cancelLabel: 'Cancelar',
    }))) return
    setBusyDoc(docId)
    const fd = new FormData()
    fd.set('document_id', docId)
    fd.set('document_version', docVersion)
    startTransition(async () => {
      try {
        const r = await acceptAction(fd)
        if (r.ok) toast.success(r.message || 'Aceptación registrada.')
        else toast.error(r.error || 'No se pudo registrar la aceptación.')
      } catch {
        toast.error('Error inesperado al registrar la aceptación.')
      } finally { setBusyDoc(null) }
    })
  }

  const docIds = Object.keys(currentVersions)

  return (
    <div className="space-y-5">
      {/* Estado por documento */}
      <div className="space-y-3">
        {docIds.map(docId => {
          const version = currentVersions[docId]
          const labels = documentLabels[docId]
          const acceptance = acceptedByDoc[docId]
          const accepted = !!acceptance
          const busy = busyDoc === docId && isPending
          return (
            <div
              key={docId}
              className={`rounded-xl border px-4 py-3 ${
                accepted
                  ? 'border-emerald-700/40 bg-emerald-700/5'
                  : 'border-amber-700/40 bg-amber-700/5'
              }`}
            >
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                <div className="flex-1">
                  <div className="font-semibold text-foreground flex items-center gap-2">
                    {accepted
                      ? <CheckCircle2 className="h-4 w-4 text-emerald-700" />
                      : <AlertCircle className="h-4 w-4 text-amber-700" />}
                    {labels.label}
                    <span className="text-xs font-normal text-muted-foreground">({version})</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">{labels.description}</p>
                  {accepted && acceptance && (
                    <p className="text-xs text-emerald-700 mt-1.5">
                      ✓ Aceptado por <strong>{acceptance.accepted_by_email || '(usuario)'}</strong>
                      {' · '}
                      {new Date(acceptance.accepted_at).toLocaleString('es-CO', { timeZone: 'America/Bogota',
                        dateStyle: 'medium', timeStyle: 'short',
                      })}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <a
                    href={labels.href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-blue-700 hover:underline flex items-center gap-1"
                  >
                    Leer documento <ExternalLink className="h-3 w-3" />
                  </a>
                  {!accepted && canAccept && (
                    <Button
                      type="button"
                      onClick={() => void handleAccept(docId, version)}
                      disabled={busy}
                      size="sm"
                      variant="outline"
                      className="h-8 text-xs gap-1.5 border-emerald-700/50 text-emerald-700 hover:bg-emerald-700/10"
                    >
                      {busy
                        ? <><Loader2 className="h-3 w-3 animate-spin" />Aceptando...</>
                        : <>Aceptar {version}</>}
                    </Button>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Histórico completo */}
      {history.length > 0 && (
        <details className="rounded-xl border border-border bg-card/30 px-4 py-3">
          <summary className="cursor-pointer text-sm font-medium text-foreground">
            Histórico completo ({history.length})
          </summary>
          <div className="mt-2 space-y-1 text-xs text-muted-foreground">
            {history.map(h => (
              <div key={h.id} className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-foreground">{h.document_id}</span>
                <span className="text-muted-foreground">@</span>
                <span className="font-mono">{h.document_version}</span>
                <span>·</span>
                <span>{h.accepted_by_email || '(sin email)'}</span>
                <span>·</span>
                <span>{new Date(h.accepted_at).toLocaleString('es-CO', { timeZone: 'America/Bogota' })}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      <div className="rounded-xl border border-blue-700/40 bg-blue-700/5 px-4 py-3 text-xs text-blue-700">
        <strong>¿Por qué aceptar?</strong> El DPA documenta que tú (tenant) eres el Responsable
        del tratamiento ante SIC y la plataforma es Encargado. Sin aceptación formal, una
        eventual auditoría podría cuestionar la cadena de responsabilidad. La aceptación es
        un click-wrap reconocido por la SIC (registro electrónico con timestamp + IP).
      </div>
    </div>
  )
}
