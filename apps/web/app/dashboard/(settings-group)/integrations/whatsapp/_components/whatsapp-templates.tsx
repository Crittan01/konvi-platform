'use client'

import { useEffect, useMemo, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import {
  MessageSquareText, Plus, Pencil, Trash2, Loader2, CheckCircle2,
  AlertTriangle, ShieldCheck, Eye, AlertCircle, Clock, CheckSquare,
  XSquare, PauseCircle, Info, Flag, Gauge,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import type {
  WhatsAppTemplate, TemplateCategory, TemplateStatus, TemplateComponent,
} from '../page'
import { buildTemplatePreview } from '../_lib/template-validation'

type ActionResult = { ok: boolean; error?: string }

type Props = {
  initialTemplates: WhatsAppTemplate[]
  canWrite: boolean
  tenantId: string
  tenantName: string
  createDraftAction: (formData: FormData) => Promise<ActionResult>
  updateDraftAction: (formData: FormData) => Promise<ActionResult>
  deleteDraftAction: (formData: FormData) => Promise<ActionResult>
}

// Nombres de plantilla que HOY tienen envío automático cableado en el worker
// (worker.py). Cualquier otra plantilla que el tenant cree es válida pero solo
// se enviaría manualmente / por flujos futuros — se advierte en la UI.
const AUTO_SEND_TEMPLATES = ['payment_reminder_v1', 'cart_abandoned_24h_v1']

const CATEGORY_LABEL: Record<TemplateCategory, string> = {
  UTILITY: 'Utility (transaccional)',
  MARKETING: 'Marketing (requiere consentimiento)',
  AUTHENTICATION: 'Authentication (OTP)',
}

const STATUS_LABEL: Record<TemplateStatus, string> = {
  LOCAL_DRAFT: 'Borrador local',
  PENDING: 'En revisión',
  APPROVED: 'Aprobada',
  REJECTED: 'Rechazada',
  DISABLED: 'Deshabilitada',
  PAUSED: 'Pausada',
  FLAGGED: 'Marcada por Meta',
  LIMIT_EXCEEDED: 'Límite excedido',
}

const STATUS_ICON: Record<TemplateStatus, React.ElementType> = {
  LOCAL_DRAFT: Pencil,
  PENDING: Clock,
  APPROVED: CheckSquare,
  REJECTED: XSquare,
  DISABLED: AlertCircle,
  PAUSED: PauseCircle,
  FLAGGED: Flag,
  LIMIT_EXCEEDED: Gauge,
}

// Tailwind shades 700+ por feedback_ui_colors (NO 300-500).
const STATUS_CHIP: Record<TemplateStatus, string> = {
  LOCAL_DRAFT: 'bg-slate-700/10 text-slate-800 border-slate-700/30',
  PENDING:     'bg-amber-700/10 text-amber-900 border-amber-700/40',
  APPROVED:    'bg-emerald-700/10 text-emerald-900 border-emerald-700/40',
  REJECTED:    'bg-rose-700/10 text-rose-900 border-rose-700/40',
  DISABLED:    'bg-slate-700/10 text-slate-800 border-slate-700/30',
  PAUSED:      'bg-amber-700/10 text-amber-900 border-amber-700/40',
  FLAGGED:     'bg-rose-700/10 text-rose-900 border-rose-700/40',
  LIMIT_EXCEEDED: 'bg-amber-700/10 text-amber-900 border-amber-700/40',
}

const QUALITY_CHIP: Record<string, string> = {
  GREEN: 'bg-emerald-700/10 text-emerald-900 border-emerald-700/40',
  YELLOW: 'bg-amber-700/10 text-amber-900 border-amber-700/40',
  RED: 'bg-rose-700/10 text-rose-900 border-rose-700/40',
  UNKNOWN: 'bg-slate-700/10 text-slate-700 border-slate-700/30',
}

const QUALITY_LABEL: Record<string, string> = {
  GREEN: 'Alta',
  YELLOW: 'Media',
  RED: 'Baja',
  UNKNOWN: 'Sin datos',
}

const EDITABLE = new Set<TemplateStatus>(['LOCAL_DRAFT', 'REJECTED'])

// Orden FSM "natural" para el listado; fallback 99 para estados no mapeados.
const STATUS_ORDER: Record<TemplateStatus, number> = {
  LOCAL_DRAFT: 0, PENDING: 1, APPROVED: 2, REJECTED: 3,
  FLAGGED: 4, LIMIT_EXCEEDED: 5, PAUSED: 6, DISABLED: 7,
}

// Template starter para crear nuevo — body con 4 placeholders al estilo
// payment_reminder_v1. El FOOTER usa el nombre del tenant interpolado
// (segregación Konvi/tenant: el cliente final ve la marca de su tienda).
function buildComponentsPlaceholder(tenantName: string): string {
  return JSON.stringify(
    [
      {
        type: 'BODY',
        text:
          'Hola {{1}}, te recordamos que tu pedido #{{2}} por {{3}} sigue pendiente de pago. ' +
          'Puedes pagarlo aquí: {{4}}',
        example: { body_text: [['Carlos', 'A1B2C3', '$87.500 COP', 'https://checkout.wompi.co/...']] },
      },
      { type: 'FOOTER', text: `${tenantName} — gracias por tu compra` },
    ],
    null,
    2,
  )
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('es-CO', { timeZone: 'America/Bogota', year: 'numeric', month: 'short', day: '2-digit' })
}

function extractBodyPreview(components: WhatsAppTemplate['components']): string {
  const body = components.find(c => c.type === 'BODY')
  if (!body || !body.text) return '(sin BODY)'
  const text = body.text
  return text.length > 140 ? text.slice(0, 137) + '…' : text
}

// ─── Preview del mensaje como lo vería el cliente en WhatsApp ────────────────
function MessagePreview({ componentsText }: { componentsText: string }) {
  const preview = useMemo(() => {
    try {
      const parsed = JSON.parse(componentsText)
      if (!Array.isArray(parsed)) return null
      return buildTemplatePreview(parsed as TemplateComponent[])
    } catch {
      return null
    }
  }, [componentsText])

  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">Vista previa (como la ve el cliente)</Label>
      {!preview || !preview.bodyText ? (
        <div className="rounded-md border border-dashed border-muted-foreground/30 p-4 text-xs text-muted-foreground text-center">
          El preview aparece cuando el JSON es válido y tiene un BODY con texto.
        </div>
      ) : (
        <div className="rounded-lg border border-emerald-700/30 bg-emerald-700/5 p-3 space-y-1.5">
          {preview.headerFormat && preview.headerFormat !== 'TEXT' && (
            <div className="text-[11px] uppercase tracking-wide text-emerald-900/70">
              [{preview.headerFormat}]
            </div>
          )}
          {preview.headerText && (
            <div className="font-semibold text-sm text-foreground whitespace-pre-wrap">
              {preview.headerText}
            </div>
          )}
          <div className="text-sm text-foreground whitespace-pre-wrap">{preview.bodyText}</div>
          {preview.footerText && (
            <div className="text-xs text-muted-foreground whitespace-pre-wrap">{preview.footerText}</div>
          )}
          {preview.buttonLabels.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {preview.buttonLabels.map((b, i) => (
                <span
                  key={i}
                  className="text-xs text-emerald-900 border border-emerald-700/40 rounded-full px-2 py-0.5"
                >
                  {b}
                </span>
              ))}
            </div>
          )}
          {!preview.usedExample && (
            <p className="text-[11px] text-muted-foreground pt-1">
              Las variables entre «» usan tu texto de <code>example</code> cuando lo definas.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default function WhatsAppTemplates({
  initialTemplates,
  canWrite,
  tenantId: _tenantId,
  tenantName,
  createDraftAction,
  updateDraftAction,
  deleteDraftAction,
}: Props) {
  const router = useRouter()
  const [pending, startTransition] = useTransition()
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<WhatsAppTemplate | null>(null)
  const [deleting, setDeleting] = useState<WhatsAppTemplate | null>(null)
  const [viewing, setViewing] = useState<WhatsAppTemplate | null>(null)
  const [submitFor, setSubmitFor] = useState<WhatsAppTemplate | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  // Texto vivo del editor de components para alimentar el preview en tiempo real.
  const [componentsText, setComponentsText] = useState('')

  const templates = initialTemplates

  // Auto-dismiss del banner de éxito (accesible + no persiste indefinidamente).
  useEffect(() => {
    if (!successMsg) return
    const t = setTimeout(() => setSuccessMsg(null), 6000)
    return () => clearTimeout(t)
  }, [successMsg])

  const sortedTemplates = useMemo(() => {
    return [...templates].sort((a, b) => {
      const aOrder = STATUS_ORDER[a.status] ?? 99
      const bOrder = STATUS_ORDER[b.status] ?? 99
      if (aOrder !== bOrder) return aOrder - bOrder
      return a.name.localeCompare(b.name)
    })
  }, [templates])

  const openCreate = () => {
    setFormError(null)
    setComponentsText(buildComponentsPlaceholder(tenantName))
    setCreateOpen(true)
  }
  const openEdit = (t: WhatsAppTemplate) => {
    setFormError(null)
    setComponentsText(JSON.stringify(t.components, null, 2))
    setEditing(t)
  }

  const handleCreate = (formData: FormData) => {
    setFormError(null)
    setSuccessMsg(null)
    startTransition(async () => {
      const res = await createDraftAction(formData)
      if (!res.ok) {
        setFormError(res.error || 'Error desconocido.')
        return
      }
      setCreateOpen(false)
      setSuccessMsg('Borrador creado. Usa el botón "Enviar a revisión" cuando esté listo.')
      router.refresh()
    })
  }

  const handleUpdate = (formData: FormData) => {
    setFormError(null)
    setSuccessMsg(null)
    startTransition(async () => {
      const res = await updateDraftAction(formData)
      if (!res.ok) {
        setFormError(res.error || 'Error desconocido.')
        return
      }
      setEditing(null)
      setSuccessMsg('Borrador actualizado.')
      router.refresh()
    })
  }

  const handleDelete = (formData: FormData) => {
    setFormError(null)
    setSuccessMsg(null)
    startTransition(async () => {
      const res = await deleteDraftAction(formData)
      if (!res.ok) {
        setFormError(res.error || 'Error desconocido.')
        return
      }
      setDeleting(null)
      setSuccessMsg('Borrador eliminado.')
      router.refresh()
    })
  }

  return (
    <div className="space-y-4">
      {/* Mensaje éxito (accesible + auto-dismiss) */}
      {successMsg && (
        <div
          role="status"
          aria-live="polite"
          className="rounded-md border border-emerald-700/40 bg-emerald-700/5 p-3 text-sm text-emerald-900 flex items-start gap-2"
        >
          <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Ayuda contextual: qué es una plantilla HSM y cuáles se envían solas */}
      <div className="rounded-xl border border-border bg-muted/20 p-4 text-sm space-y-2">
        <div className="flex items-center gap-2 font-semibold text-foreground">
          <Info className="h-4 w-4 text-primary" /> ¿Qué son las plantillas HSM?
        </div>
        <p className="text-muted-foreground">
          Fuera de la ventana de 24h desde el último mensaje del cliente, Meta solo permite
          enviar <strong>plantillas pre-aprobadas</strong> (HSM). Las de tipo{' '}
          <strong>UTILITY</strong> (transaccionales) no requieren consentimiento de marketing;
          las <strong>MARKETING</strong> sí, y consumen tu tier de mensajería.
        </p>
        <p className="text-muted-foreground">
          Envío automático hoy: el bot usa{' '}
          {AUTO_SEND_TEMPLATES.map((n, i) => (
            <span key={n}>
              <code className="text-xs bg-muted px-1 rounded">{n}</code>
              {i < AUTO_SEND_TEMPLATES.length - 1 ? ' y ' : ''}
            </span>
          ))}
          {' '}para recordatorio de pago y carrito abandonado. Otras plantillas quedan
          disponibles pero no se envían solas todavía.
        </p>
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-sm text-muted-foreground">
          {templates.length === 0
            ? 'Aún no hay plantillas. Crea una para empezar.'
            : `${templates.length} ${templates.length === 1 ? 'plantilla' : 'plantillas'} en esta tienda.`}
        </div>
        {canWrite && (
          <Button onClick={openCreate} disabled={pending} className="gap-2">
            <Plus className="h-4 w-4" /> Nueva plantilla
          </Button>
        )}
      </div>

      {/* Lista */}
      {sortedTemplates.length === 0 ? (
        <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center">
          <MessageSquareText className="h-8 w-8 mx-auto text-muted-foreground/60" />
          <p className="mt-2 text-sm text-muted-foreground">
            Sin plantillas registradas. Crea un borrador y luego envíalo a revisión de Meta
            (aprobación entre 15 min y 48 h).
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {sortedTemplates.map(t => {
            const StatusIcon = STATUS_ICON[t.status] ?? AlertCircle
            const isEditable = EDITABLE.has(t.status)
            const isDeletable = t.status === 'LOCAL_DRAFT'
            return (
              <div
                key={t.id}
                className="rounded-xl border border-border bg-card p-4 space-y-2"
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-foreground truncate">
                        {t.name}
                      </h3>
                      <span className="text-xs font-mono text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                        {t.language}
                      </span>
                      <span
                        className={`inline-flex items-center gap-1 text-xs font-medium border rounded-full px-2 py-0.5 ${STATUS_CHIP[t.status] ?? STATUS_CHIP.LOCAL_DRAFT}`}
                      >
                        <StatusIcon className="h-3 w-3" />
                        {STATUS_LABEL[t.status] ?? t.status}
                      </span>
                      <span
                        className={`inline-flex items-center text-xs font-medium border rounded-full px-2 py-0.5 ${QUALITY_CHIP[t.quality_rating] ?? QUALITY_CHIP.UNKNOWN}`}
                      >
                        Calidad: {QUALITY_LABEL[t.quality_rating] ?? t.quality_rating}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      <strong>{CATEGORY_LABEL[t.category] ?? t.category}</strong>
                      {' · '}{t.parameter_format}
                      {t.meta_template_id && (
                        <>
                          {' · '}Meta ID:{' '}
                          <span className="font-mono">{t.meta_template_id}</span>
                        </>
                      )}
                    </p>
                    <p className="text-sm text-foreground/80 line-clamp-2">
                      {extractBodyPreview(t.components)}
                    </p>
                    {t.status_reason && (
                      <p className="text-xs text-rose-900 border-l-2 border-rose-700/40 pl-2">
                        Meta indicó: {t.status_reason}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      Creada {formatDate(t.created_at)}
                      {t.submitted_at && <> · Enviada {formatDate(t.submitted_at)}</>}
                      {t.approved_at && <> · Aprobada {formatDate(t.approved_at)}</>}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setViewing(t)}
                      className="gap-1"
                    >
                      <Eye className="h-3.5 w-3.5" /> Ver
                    </Button>
                    {canWrite && t.status === 'LOCAL_DRAFT' && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => { setSubmitFor(t); setFormError(null) }}
                        className="gap-1"
                      >
                        <ShieldCheck className="h-3.5 w-3.5" /> Enviar a revisión
                      </Button>
                    )}
                    {canWrite && isEditable && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEdit(t)}
                        className="gap-1"
                      >
                        <Pencil className="h-3.5 w-3.5" /> Editar
                      </Button>
                    )}
                    {canWrite && isDeletable && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => { setDeleting(t); setFormError(null) }}
                        className="gap-1 text-rose-800 hover:text-rose-900"
                      >
                        <Trash2 className="h-3.5 w-3.5" /> Eliminar
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* ─── Dialog: Crear ─────────────────────────────────────────────── */}
      <Dialog open={createOpen} onOpenChange={(o) => { if (!o) setCreateOpen(false) }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Nueva plantilla WhatsApp</DialogTitle>
            <DialogDescription>
              Crea un borrador local. Luego envíalo a revisión de Meta con el botón
              "Enviar a revisión" desde la tarjeta.
            </DialogDescription>
          </DialogHeader>
          <form action={handleCreate} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="name">Nombre canónico</Label>
                <Input
                  id="name" name="name" required pattern="^[a-z][a-z0-9_]{2,49}$"
                  placeholder="payment_reminder_v1"
                  title="lowercase + dígitos + underscores, debe empezar con letra, 3-50 chars"
                />
                <p className="text-xs text-muted-foreground">
                  3-50 chars · lowercase · letras/dígitos/<code>_</code>
                </p>
              </div>
              <div className="space-y-1">
                <Label htmlFor="language">Idioma</Label>
                <Input
                  id="language" name="language" required pattern="^[a-z]{2}(_[A-Z]{2})?$"
                  defaultValue="es_CO" placeholder="es_CO"
                />
                <p className="text-xs text-muted-foreground">
                  Formato BCP 47 — <code>es_CO</code> por defecto.
                </p>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="category">Categoría</Label>
                <select
                  id="category" name="category" required
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  defaultValue="UTILITY"
                >
                  <option value="UTILITY">UTILITY — transaccional</option>
                  <option value="MARKETING">MARKETING — requiere consentimiento</option>
                  <option value="AUTHENTICATION">AUTHENTICATION — OTP</option>
                </select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="parameter_format">Parameter format</Label>
                <select
                  id="parameter_format" name="parameter_format"
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  defaultValue="POSITIONAL"
                >
                  <option value="POSITIONAL">POSITIONAL — {`{{1}}, {{2}}, …`}</option>
                  <option value="NAMED">NAMED — {`{{name}}, {{order_id}}, …`}</option>
                </select>
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="components">Components (JSON)</Label>
              <textarea
                id="components" name="components" required
                rows={12}
                value={componentsText}
                onChange={(e) => setComponentsText(e.target.value)}
                className="font-mono text-xs w-full rounded-md border border-input bg-background px-3 py-2"
              />
              <p className="text-xs text-muted-foreground">
                Array formato Meta. Requerido <strong>1 BODY</strong>. Opcional
                {' '}HEADER · FOOTER · BUTTONS. La validación profunda la hace Meta al enviar.
              </p>
            </div>
            <MessagePreview componentsText={componentsText} />
            {formError && (
              <div
                role="alert"
                aria-live="assertive"
                className="rounded-md border border-rose-700/40 bg-rose-700/5 p-2 text-sm text-rose-900 flex items-start gap-2"
              >
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>{formError}</span>
              </div>
            )}
            <DialogFooter>
              <Button
                type="button" variant="ghost"
                onClick={() => setCreateOpen(false)}
                disabled={pending}
              >
                Cancelar
              </Button>
              <Button type="submit" disabled={pending} className="gap-2">
                {pending && <Loader2 className="h-4 w-4 animate-spin" />}
                Crear borrador
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ─── Dialog: Editar ────────────────────────────────────────────── */}
      <Dialog open={!!editing} onOpenChange={(o) => { if (!o) setEditing(null) }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              Editar plantilla — <span className="font-mono">{editing?.name}</span>
            </DialogTitle>
            <DialogDescription>
              {editing?.status === 'REJECTED'
                ? 'Plantilla rechazada por Meta. Corrige los componentes y vuelve a enviarla a revisión.'
                : 'Borrador local — solo editable mientras no esté en Meta.'}
            </DialogDescription>
          </DialogHeader>
          {editing && (
            <form action={handleUpdate} className="space-y-4">
              <input type="hidden" name="id" value={editing.id} />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div className="rounded-md border bg-muted/30 p-2">
                  <Label className="text-xs">Nombre (inmutable)</Label>
                  <div className="font-mono mt-0.5">{editing.name}</div>
                </div>
                <div className="rounded-md border bg-muted/30 p-2">
                  <Label className="text-xs">Idioma (inmutable)</Label>
                  <div className="font-mono mt-0.5">{editing.language}</div>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="edit-category">Categoría</Label>
                  <select
                    id="edit-category" name="category" required
                    defaultValue={editing.category}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="UTILITY">UTILITY</option>
                    <option value="MARKETING">MARKETING</option>
                    <option value="AUTHENTICATION">AUTHENTICATION</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="edit-parameter_format">Parameter format</Label>
                  <select
                    id="edit-parameter_format" name="parameter_format"
                    defaultValue={editing.parameter_format}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="POSITIONAL">POSITIONAL</option>
                    <option value="NAMED">NAMED</option>
                  </select>
                </div>
              </div>
              <div className="space-y-1">
                <Label htmlFor="edit-components">Components (JSON)</Label>
                <textarea
                  id="edit-components" name="components" required
                  rows={12}
                  value={componentsText}
                  onChange={(e) => setComponentsText(e.target.value)}
                  className="font-mono text-xs w-full rounded-md border border-input bg-background px-3 py-2"
                />
              </div>
              <MessagePreview componentsText={componentsText} />
              <div className="rounded-md border border-amber-700/30 bg-amber-700/5 p-2 text-xs text-amber-900">
                Al guardar, la plantilla vuelve a <strong>borrador local</strong> y se desliga
                de cualquier envío anterior a Meta. Deberás enviarla a revisión de nuevo.
              </div>
              {editing.status_reason && (
                <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-2 text-xs text-rose-900">
                  <strong>Razón del rechazo de Meta:</strong> {editing.status_reason}
                </div>
              )}
              {formError && (
                <div
                  role="alert"
                  aria-live="assertive"
                  className="rounded-md border border-rose-700/40 bg-rose-700/5 p-2 text-sm text-rose-900 flex items-start gap-2"
                >
                  <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                  <span>{formError}</span>
                </div>
              )}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={() => setEditing(null)} disabled={pending}>
                  Cancelar
                </Button>
                <Button type="submit" disabled={pending} className="gap-2">
                  {pending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Guardar cambios
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      {/* ─── Dialog: Eliminar ──────────────────────────────────────────── */}
      <Dialog open={!!deleting} onOpenChange={(o) => { if (!o) setDeleting(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Eliminar borrador</DialogTitle>
            <DialogDescription>
              ¿Eliminar definitivamente el borrador{' '}
              <strong className="font-mono">{deleting?.name}</strong>?
              Esta acción no se puede deshacer.
            </DialogDescription>
          </DialogHeader>
          {deleting && (
            <form action={handleDelete} className="space-y-3">
              <input type="hidden" name="id" value={deleting.id} />
              {formError && (
                <div
                  role="alert"
                  aria-live="assertive"
                  className="rounded-md border border-rose-700/40 bg-rose-700/5 p-2 text-sm text-rose-900"
                >
                  {formError}
                </div>
              )}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={() => setDeleting(null)} disabled={pending}>
                  Cancelar
                </Button>
                <Button type="submit" variant="destructive" disabled={pending} className="gap-2">
                  {pending && <Loader2 className="h-4 w-4 animate-spin" />}
                  Eliminar
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      {/* ─── Dialog: Ver detalle ───────────────────────────────────────── */}
      <Dialog open={!!viewing} onOpenChange={(o) => { if (!o) setViewing(null) }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              <span className="font-mono">{viewing?.name}</span>{' '}
              <span className="text-sm text-muted-foreground font-normal">
                ({viewing?.language})
              </span>
            </DialogTitle>
            <DialogDescription>
              {viewing && (CATEGORY_LABEL[viewing.category] ?? viewing.category)} · {viewing?.parameter_format}
            </DialogDescription>
          </DialogHeader>
          {viewing && (
            <div className="space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-xs text-muted-foreground">Estado</div>
                  <span
                    className={`inline-flex items-center gap-1 text-xs font-medium border rounded-full px-2 py-0.5 mt-0.5 ${STATUS_CHIP[viewing.status] ?? STATUS_CHIP.LOCAL_DRAFT}`}
                  >
                    {STATUS_LABEL[viewing.status] ?? viewing.status}
                  </span>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Calidad</div>
                  <span
                    className={`inline-flex items-center text-xs font-medium border rounded-full px-2 py-0.5 mt-0.5 ${QUALITY_CHIP[viewing.quality_rating] ?? QUALITY_CHIP.UNKNOWN}`}
                  >
                    {QUALITY_LABEL[viewing.quality_rating] ?? viewing.quality_rating}
                  </span>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Meta template ID</div>
                  <div className="font-mono text-xs mt-0.5">
                    {viewing.meta_template_id ?? '—'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">WABA</div>
                  <div className="font-mono text-xs mt-0.5 truncate" title={viewing.waba_id}>
                    {viewing.waba_id}
                  </div>
                </div>
              </div>
              {viewing.status_reason && (
                <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-2 text-xs text-rose-900">
                  <strong>Razón de Meta:</strong> {viewing.status_reason}
                </div>
              )}
              <MessagePreview componentsText={JSON.stringify(viewing.components, null, 2)} />
              <div>
                <Label className="text-xs">Components (JSON)</Label>
                <pre className="font-mono text-xs whitespace-pre-wrap rounded-md border bg-muted/30 p-3 max-h-80 overflow-auto">
                  {JSON.stringify(viewing.components, null, 2)}
                </pre>
              </div>
              <DialogFooter>
                <Button onClick={() => setViewing(null)} variant="ghost">Cerrar</Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ─── Dialog: Enviar a revisión de Meta ─────────────────────────── */}
      <Dialog open={!!submitFor} onOpenChange={(o) => { if (!o) setSubmitFor(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enviar a revisión de Meta</DialogTitle>
            <DialogDescription>
              El envío a revisión de Meta lo procesa el equipo de Konvi (pre-validación humana
              antes de consumir el cupo de envíos del WABA, según política de la integración).
            </DialogDescription>
          </DialogHeader>
          {submitFor && (
            <div className="space-y-3 text-sm">
              <div className="rounded-md border bg-muted/30 p-3 space-y-1">
                <div>
                  Plantilla:{' '}
                  <span className="font-mono">{submitFor.name}</span>{' '}
                  <span className="text-muted-foreground">({submitFor.language})</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  Estado actual: borrador local — lista para revisión.
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                Una vez enviada, Meta la revisa entre 15 min y 48 h. Cuando termine, esta
                pantalla mostrará el nuevo estado (Aprobada / Rechazada) automáticamente vía
                webhook <code className="mx-0.5">message_template_status_update</code>. No
                necesitas hacer nada más.
              </p>
              <p className="text-xs text-muted-foreground">
                Si el envío no avanza en 48 h, contacta a soporte de Konvi indicando el nombre
                de la plantilla.
              </p>
              <DialogFooter>
                <Button onClick={() => setSubmitFor(null)} variant="ghost">Entendido</Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
