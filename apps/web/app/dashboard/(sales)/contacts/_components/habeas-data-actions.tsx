'use client'

// Rev. 102 — Componente unificado de acciones Habeas Data por contacto.
// Incluye:
//   1. Header con icono (?) que abre dialog explicativo de los 4 derechos.
//   2. 4 botones (Reporte JSON / PDF / Portabilidad / Anonimizar).
//   3. Dialog de confirmación específico por acción antes de ejecutar.
//   4. Disclaimer con estructura visual organizada (no párrafo plano).
//
// Razón del refactor: el usuario notó que (a) las acciones registran en
// audit_log y eso amerita confirmación explícita; (b) el operador no
// siempre entiende qué hace cada botón; (c) la nota al pie como párrafo
// plano se pierde visualmente.

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import {
  ShieldCheck, Download, FileText, Printer, ShieldOff,
  HelpCircle, Loader2, AlertTriangle, CheckCircle2, XCircle,
} from 'lucide-react'

type SarType = 'export' | 'portability' | 'erase'

type SarResult = {
  ok: boolean
  status: number
  type: string
  payload?: unknown
  error?: string
}

type Props = {
  contactId: string
  contactDisplayName: string
  sarAction: (fd: FormData) => Promise<SarResult>
  sarPrintableAction?: (fd: FormData) => Promise<{
    ok: boolean
    status: number
    html?: string
    error?: string
  }>
  /**
   * Rev. 102 — Optimistic UX. Cuando un erase tiene éxito en el server,
   * el parent puede actualizar su estado local de inmediato (e.g.,
   * remover/anonimizar la card visualmente) sin esperar a que el RSC
   * payload de router.refresh() llegue. Necesario porque router.refresh()
   * puede tardar y/o no provocar re-render visible del Server Component
   * padre cuando se llama desde un Client Component nested.
   */
  onEraseSuccess?: (contactId: string) => void
  /**
   * Rev. 102 — Si el contact ya fue anonimizado (consent_given=false +
   * consent_revoked_at no null), el botón "Anonimizar" se renderiza
   * disabled. Re-anonimizar es no-op funcional pero ensucia el audit
   * log con eventos duplicados Y sobrescribe la fecha original de la
   * anonimización (información legal valiosa).
   */
  isAnonymized?: boolean
  anonymizedAt?: string | null
}

type ActionKind = 'json' | 'pdf' | 'portability' | 'erase'

// Rev. 102 — copy en lenguaje plano para el operador del tenant.
// Nada de nombres de tabla, columnas o flags técnicos. Si el operador
// quiere detalle técnico, lo encontrará en docs/legal/* o ADR-0003.
const ACTION_META: Record<ActionKind, {
  label: string
  article: string
  description: string
  icon: typeof Download
  isDestructive: boolean
  consequences: string[]
  audits: string[]
}> = {
  json: {
    label: 'Reporte (JSON)',
    article: 'Art. 14 — Derecho de acceso',
    description:
      'Descarga un archivo con todos los datos del titular: información personal, ' +
      'pedidos, historial de consentimiento y subprocesadores. Útil para responder ' +
      'a una solicitud del cliente o de la SIC.',
    icon: Download,
    isDestructive: false,
    consequences: [
      'No modifica ningún dato del contacto.',
      'Se descarga un archivo en tu navegador.',
    ],
    audits: [
      'Queda registro permanente de que pediste este reporte (con la fecha y tu usuario).',
      'Se anota qué campos se incluyeron y desde qué computador se solicitó.',
    ],
  },
  pdf: {
    label: 'Reporte (PDF)',
    article: 'Art. 14 — Derecho de acceso (formato imprimible)',
    description:
      'Abre el mismo reporte en una nueva pestaña, listo para imprimir. ' +
      'Útil cuando necesitas un PDF firmable o presentable a la SIC.',
    icon: Printer,
    isDestructive: false,
    consequences: [
      'No modifica ningún dato del contacto.',
      'Abre nueva pestaña; tú haces Cmd/Ctrl + P → "Guardar como PDF".',
    ],
    audits: [
      'Queda registro permanente de que generaste este PDF (con la fecha y tu usuario).',
      'Se anota desde qué computador se solicitó.',
    ],
  },
  portability: {
    label: 'Portabilidad',
    article: 'Art. 19 — Derecho de portabilidad',
    description:
      'Genera el mismo reporte que el JSON, pero rotulado legalmente como ' +
      '"portabilidad" — para cuando el cliente quiere migrar sus datos a otra ' +
      'plataforma. Para la SIC el motivo legal registrado es distinto al acceso.',
    icon: FileText,
    isDestructive: false,
    consequences: [
      'No modifica ningún dato del contacto.',
      'Se descarga un archivo en tu navegador.',
    ],
    audits: [
      'Queda registro permanente de que el cliente solicitó portabilidad.',
      'Sirve como prueba ante la SIC si el cliente luego reclama.',
    ],
  },
  erase: {
    label: 'Anonimizar',
    article: 'Art. 15 — Derecho de supresión',
    description:
      'Borra los datos personales del titular (nombre, email, documento, dirección y notas). ' +
      'Conserva solo el teléfono porque es el canal de WhatsApp. Esta acción NO se puede deshacer.',
    icon: ShieldOff,
    isDestructive: true,
    consequences: [
      'Esta acción es IRREVERSIBLE — los datos personales se borran del sistema.',
      'Se borran: nombre, email, documento de identidad, dirección y notas.',
      'Se conserva el teléfono (necesario para identificar la conversación de WhatsApp).',
      'El consentimiento queda marcado como revocado con fecha de hoy.',
      'Si el cliente vuelve a comprar, deberás pedirle de nuevo sus datos y consentimiento.',
    ],
    audits: [
      'Queda registro permanente de la supresión (con la fecha y tu usuario).',
      'Este registro NO se puede borrar — es la prueba de que cumpliste la solicitud.',
      'Si el tenant tiene email configurado, se le notifica automáticamente.',
    ],
  },
}

export default function HabeasDataActions({
  contactId, contactDisplayName, sarAction, sarPrintableAction, onEraseSuccess,
  isAnonymized = false, anonymizedAt = null,
}: Props) {
  const router = useRouter()
  const [isPending, startTransition] = useTransition()
  const [running, setRunning] = useState<ActionKind | null>(null)
  const [pendingAction, setPendingAction] = useState<ActionKind | null>(null)
  const [infoOpen, setInfoOpen] = useState(false)
  // Rev. 102 (D) — motivo opcional para Anonimizar. Reemplaza el texto
  // hardcodeado "Solicitud de supresión vía SAR" si el operador llena.
  const [eraseReason, setEraseReason] = useState('')

  // Rev. 102 — Dialog de resultado (sustituye window.alert).
  // Solo para Anonimizar (success — confirmación visual irreversible) y
  // para errores en cualquier acción. Los reads exitosos no requieren
  // dialog: la descarga del archivo o nueva pestaña ya es feedback.
  const [resultDialog, setResultDialog] = useState<{
    kind: 'success' | 'error'
    title: string
    message: string
    detail?: string
  } | null>(null)

  const showError = (title: string, message: string, detail?: string) =>
    setResultDialog({ kind: 'error', title, message, detail })

  const executeAction = async (kind: ActionKind) => {
    setRunning(kind)
    try {
      if (kind === 'pdf') {
        if (!sarPrintableAction) return
        const fd = new FormData()
        fd.set('contact_id', contactId)
        const res = await sarPrintableAction(fd)
        if (!res.ok || !res.html) {
          showError(
            'No se pudo generar el reporte PDF',
            'El servidor reportó un error al componer el reporte.',
            `Código ${res.status}${res.error ? ' · ' + res.error : ''}`,
          )
          return
        }
        const blob = new Blob([res.html], { type: 'text/html' })
        const url = URL.createObjectURL(blob)
        const w = window.open(url, '_blank', 'noopener,noreferrer')
        if (!w) {
          showError(
            'El navegador bloqueó la nueva pestaña',
            'Habilita los popups de este sitio y vuelve a intentarlo.',
          )
        }
        setTimeout(() => URL.revokeObjectURL(url), 60_000)
        return
      }
      const sarType: SarType = kind === 'json' ? 'export' : kind === 'portability' ? 'portability' : 'erase'
      const fd = new FormData()
      fd.set('contact_id', contactId)
      fd.set('sar_type', sarType)
      // Rev. 102 (D) — pasar motivo personalizado de erase al server.
      if (sarType === 'erase' && eraseReason.trim()) {
        fd.set('reason', eraseReason.trim())
      }
      const res = await sarAction(fd)
      if (!res.ok) {
        const detail =
          typeof res.payload === 'object' && res.payload && 'detail' in res.payload
            ? (res.payload as { detail?: string }).detail
            : res.error
        showError(
          'La acción no se pudo completar',
          'El servidor rechazó la solicitud. Reintenta en unos segundos; si persiste, contacta soporte.',
          `Código ${res.status}${detail ? ' · ' + detail : ''}`,
        )
        return
      }
      if (sarType === 'export' || sarType === 'portability') {
        const json = JSON.stringify(res.payload, null, 2)
        const blob = new Blob([json], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `habeas-data-${sarType}-${contactId.slice(0, 8)}-${Date.now()}.json`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        // Reads exitosos no requieren Dialog — la descarga es feedback.
      } else if (sarType === 'erase') {
        // Rev. 102 — combo:
        //   1) onEraseSuccess(contactId): optimistic update del parent
        //      (oculta/anonimiza la card LOCALMENTE de inmediato).
        //   2) router.refresh(): pide RSC payload nuevo al server para
        //      sincronizar el estado real en background.
        // Sin (1), el user veía datos viejos hasta refrescar manualmente
        // porque router.refresh() solo no provocaba re-render visible.
        if (onEraseSuccess) onEraseSuccess(contactId)
        router.refresh()
        setResultDialog({
          kind: 'success',
          title: 'Datos personales anonimizados',
          message:
            'Se borraron los datos personales del titular (nombre, email, documento, dirección y notas). ' +
            'Quedó registro permanente de la operación para auditoría legal.',
          detail: contactDisplayName,
        })
      }
    } finally {
      setRunning(null)
    }
  }

  const handleClick = (kind: ActionKind) => () => {
    setPendingAction(kind)
  }

  const handleConfirm = () => {
    if (!pendingAction) return
    const kind = pendingAction
    setPendingAction(null)
    startTransition(async () => {
      await executeAction(kind)
      // Reset motivo tras submit (success o error).
      if (kind === 'erase') setEraseReason('')
    })
  }

  return (
    <div className="pt-3 mt-3 border-t border-border space-y-3">
      {/* Header con (?) info */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700 uppercase tracking-wide">
          <ShieldCheck className="h-3 w-3" />
          Habeas Data — Derechos del titular
        </div>
        <Dialog open={infoOpen} onOpenChange={setInfoOpen}>
          <DialogTrigger asChild>
            <button
              type="button"
              className="text-muted-foreground hover:text-emerald-700 transition-colors"
              title="¿Para qué sirve cada acción?"
            >
              <HelpCircle className="h-4 w-4" />
            </button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
            <DialogHeader>
              <DialogTitle>Acciones Habeas Data — guía rápida</DialogTitle>
              <DialogDescription>
                Ley 1581 de 2012 Colombia. El tenant (tu negocio) es responsable
                ante la Superintendencia de Industria y Comercio (SIC). Cada
                acción queda registrada de forma permanente para que puedas
                demostrar cumplimiento.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 text-sm overflow-y-auto pr-1 flex-1">
              {(Object.keys(ACTION_META) as ActionKind[]).map(kind => {
                const m = ACTION_META[kind]
                const Icon = m.icon
                return (
                  <div
                    key={kind}
                    className={`rounded-lg border p-3 ${
                      m.isDestructive
                        ? 'border-amber-700/40 bg-amber-700/5'
                        : 'border-emerald-700/40 bg-emerald-700/5'
                    }`}
                  >
                    <div className={`flex items-center gap-2 font-semibold ${
                      m.isDestructive ? 'text-amber-700' : 'text-emerald-700'
                    }`}>
                      <Icon className="h-4 w-4" />
                      {m.label}
                      <span className="text-xs font-normal text-muted-foreground">{m.article}</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1.5">{m.description}</p>
                    <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
                      <div>
                        <p className="font-semibold text-foreground mb-1">Qué pasa:</p>
                        <ul className="list-disc list-inside space-y-0.5 text-muted-foreground">
                          {m.consequences.map(c => <li key={c}>{c}</li>)}
                        </ul>
                      </div>
                      <div>
                        <p className="font-semibold text-foreground mb-1">Lo que queda guardado:</p>
                        <ul className="list-disc list-inside space-y-0.5 text-muted-foreground">
                          {m.audits.map(a => <li key={a}>{a}</li>)}
                        </ul>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
            <DialogFooter className="mt-2 pt-2 border-t border-border">
              <Button onClick={() => setInfoOpen(false)} size="sm">Cerrar</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Botones */}
      <div className="flex items-center gap-2 flex-wrap">
        {(Object.keys(ACTION_META) as ActionKind[]).map(kind => {
          const m = ACTION_META[kind]
          if (kind === 'pdf' && !sarPrintableAction) return null
          const Icon = m.icon
          const isRunning = running === kind
          // Rev. 102 — botón Anonimizar deshabilitado si el contact ya
          // está anonimizado. Re-anonimizar es no-op funcional pero
          // sobrescribiría la fecha original (info legal valiosa) y
          // ensuciaría audit log con eventos duplicados.
          const isEraseOnAnonymized = kind === 'erase' && isAnonymized
          const buttonDisabled = isPending || running !== null || isEraseOnAnonymized
          const buttonTitle = isEraseOnAnonymized
            ? `Este contacto ya fue anonimizado${
                anonymizedAt ? ` el ${new Date(anonymizedAt).toLocaleDateString('es-CO')}` : ''
              }. Acción no disponible.`
            : m.description
          const hoverClasses = m.isDestructive
            ? 'hover:bg-amber-700/10 hover:text-amber-800 hover:border-amber-700'
            : 'hover:bg-emerald-700/10 hover:text-emerald-800 hover:border-emerald-700'
          return (
            <Button
              key={kind}
              type="button"
              disabled={buttonDisabled}
              size="sm"
              variant="outline"
              title={buttonTitle}
              className={`h-8 text-xs gap-1.5 px-3 border-emerald-700/50 text-emerald-700 ${hoverClasses} disabled:opacity-50 disabled:cursor-not-allowed`}
              onClick={handleClick(kind)}
            >
              {isRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Icon className="h-3 w-3" />}
              {m.label}
            </Button>
          )
        })}
      </div>

      {/* Dialog de confirmación específico por acción */}
      <Dialog open={pendingAction !== null} onOpenChange={(o) => !o && setPendingAction(null)}>
        <DialogContent className="max-w-md">
          {pendingAction && (() => {
            const m = ACTION_META[pendingAction]
            const Icon = m.icon
            return (
              <>
                <DialogHeader>
                  <DialogTitle className={`flex items-center gap-2 ${
                    m.isDestructive ? 'text-amber-700' : 'text-emerald-700'
                  }`}>
                    {m.isDestructive ? <AlertTriangle className="h-5 w-5" /> : <Icon className="h-5 w-5" />}
                    Confirmar: {m.label}
                  </DialogTitle>
                  <DialogDescription>{m.article}</DialogDescription>
                </DialogHeader>
                <div className="space-y-3 text-sm">
                  <p className="text-muted-foreground">
                    Acción sobre <strong className="text-foreground">{contactDisplayName}</strong>.
                  </p>
                  <p>{m.description}</p>
                  <div className="rounded-md border border-border bg-muted/30 p-2.5 text-xs">
                    <p className="font-semibold mb-1">Qué pasará:</p>
                    <ul className="list-disc list-inside space-y-0.5 text-muted-foreground">
                      {m.consequences.map(c => <li key={c}>{c}</li>)}
                    </ul>
                  </div>
                  <div className="rounded-md border border-border bg-muted/30 p-2.5 text-xs">
                    <p className="font-semibold mb-1">Lo que queda guardado:</p>
                    <ul className="list-disc list-inside space-y-0.5 text-muted-foreground">
                      {m.audits.map(a => <li key={a}>{a}</li>)}
                    </ul>
                  </div>
                  {m.isDestructive && (
                    <div className="rounded-md border border-amber-700/40 bg-amber-700/5 p-2.5 text-xs text-amber-700">
                      <strong>Esta acción es IRREVERSIBLE.</strong> Una vez ejecutada, los datos
                      personales NO se pueden recuperar. El audit log conservará prueba de lo ocurrido.
                    </div>
                  )}
                  {/* Rev. 102 (D) — motivo OBLIGATORIO para Anonimizar.
                      Acción irreversible amerita audit con contexto concreto. */}
                  {pendingAction === 'erase' && (
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-foreground">
                        Motivo de la supresión <span className="text-destructive">*</span>
                      </label>
                      <input
                        type="text"
                        value={eraseReason}
                        onChange={e => setEraseReason(e.target.value.slice(0, 200))}
                        minLength={10}
                        maxLength={200}
                        required
                        placeholder="Ej: titular pidió por WhatsApp 2026-05-01"
                        className="w-full h-8 px-2 text-xs rounded-md border border-input bg-background"
                      />
                      <p className="text-[10px] text-muted-foreground">
                        Mínimo 10 caracteres. Queda en el audit log inmutable como prueba ante SIC.
                      </p>
                    </div>
                  )}
                </div>
                <DialogFooter className="gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setPendingAction(null)}
                    size="sm"
                  >
                    Cancelar
                  </Button>
                  <Button
                    type="button"
                    onClick={handleConfirm}
                    size="sm"
                    disabled={
                      // Rev. 102 (D) — bloquear si motivo no cumple minLength.
                      pendingAction === 'erase' && eraseReason.trim().length < 10
                    }
                    className={
                      m.isDestructive
                        ? 'bg-amber-700 hover:bg-amber-800 text-white disabled:bg-amber-700/40'
                        : 'bg-emerald-700 hover:bg-emerald-800 text-white'
                    }
                  >
                    {m.isDestructive ? 'Sí, anonimizar' : `Sí, ${m.label.toLowerCase()}`}
                  </Button>
                </DialogFooter>
              </>
            )
          })()}
        </DialogContent>
      </Dialog>

      {/* Disclaimer en lenguaje plano */}
      <p className="text-[10px] text-muted-foreground/70">
        Cada acción queda registrada de forma permanente para auditoría
        (no se puede borrar — es la prueba de que cumpliste con la solicitud).
        Click en (?) para ver el detalle de cada derecho.
      </p>

      {/* Rev. 102 — Dialog de resultado (sustituye window.alert). */}
      <Dialog
        open={resultDialog !== null}
        onOpenChange={(o) => !o && setResultDialog(null)}
      >
        <DialogContent className="max-w-md">
          {resultDialog && (
            <>
              <DialogHeader>
                <DialogTitle className={`flex items-center gap-2 ${
                  resultDialog.kind === 'success' ? 'text-emerald-700' : 'text-red-700'
                }`}>
                  {resultDialog.kind === 'success'
                    ? <CheckCircle2 className="h-5 w-5" />
                    : <XCircle className="h-5 w-5" />}
                  {resultDialog.title}
                </DialogTitle>
                {resultDialog.detail && (
                  <DialogDescription>{resultDialog.detail}</DialogDescription>
                )}
              </DialogHeader>
              <p className="text-sm text-muted-foreground">{resultDialog.message}</p>
              <DialogFooter>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => setResultDialog(null)}
                  className={
                    resultDialog.kind === 'success'
                      ? 'bg-emerald-700 hover:bg-emerald-800 text-white'
                      : ''
                  }
                  variant={resultDialog.kind === 'error' ? 'outline' : 'default'}
                >
                  Entendido
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
