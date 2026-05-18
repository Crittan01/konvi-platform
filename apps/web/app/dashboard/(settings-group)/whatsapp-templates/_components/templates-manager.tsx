'use client'

import { useMemo, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import {
  MessageSquareText, Plus, Pencil, Trash2, Loader2, CheckCircle2,
  AlertTriangle, ShieldCheck, Copy, Eye, AlertCircle, Clock, CheckSquare,
  XSquare, PauseCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import type {
  WhatsAppTemplate, TemplateCategory, TemplateStatus, ParameterFormat,
} from '../page'

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

const CATEGORY_LABEL: Record<TemplateCategory, string> = {
  UTILITY: 'Utility (transaccional)',
  MARKETING: 'Marketing (requiere consent)',
  AUTHENTICATION: 'Authentication (OTP)',
}

const STATUS_LABEL: Record<TemplateStatus, string> = {
  LOCAL_DRAFT: 'Borrador local',
  PENDING: 'En revisión',
  APPROVED: 'Aprobado',
  REJECTED: 'Rechazado',
  DISABLED: 'Deshabilitado',
  PAUSED: 'Pausado',
}

const STATUS_ICON: Record<TemplateStatus, React.ElementType> = {
  LOCAL_DRAFT: Pencil,
  PENDING: Clock,
  APPROVED: CheckSquare,
  REJECTED: XSquare,
  DISABLED: AlertCircle,
  PAUSED: PauseCircle,
}

// Tailwind shades 700+ por feedback_ui_colors (NO 300-500).
const STATUS_CHIP: Record<TemplateStatus, string> = {
  LOCAL_DRAFT: 'bg-slate-700/10 text-slate-800 border-slate-700/30',
  PENDING:     'bg-amber-700/10 text-amber-900 border-amber-700/40',
  APPROVED:    'bg-emerald-700/10 text-emerald-900 border-emerald-700/40',
  REJECTED:    'bg-rose-700/10 text-rose-900 border-rose-700/40',
  DISABLED:    'bg-slate-700/10 text-slate-800 border-slate-700/30',
  PAUSED:      'bg-amber-700/10 text-amber-900 border-amber-700/40',
}

const QUALITY_CHIP: Record<string, string> = {
  GREEN: 'bg-emerald-700/10 text-emerald-900 border-emerald-700/40',
  YELLOW: 'bg-amber-700/10 text-amber-900 border-amber-700/40',
  RED: 'bg-rose-700/10 text-rose-900 border-rose-700/40',
  UNKNOWN: 'bg-slate-700/10 text-slate-700 border-slate-700/30',
}

const EDITABLE = new Set<TemplateStatus>(['LOCAL_DRAFT', 'REJECTED'])

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
          'Podés pagarlo aquí: {{4}}',
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
  return d.toLocaleDateString('es-CO', { year: 'numeric', month: 'short', day: '2-digit' })
}

function extractBodyPreview(components: WhatsAppTemplate['components']): string {
  const body = components.find(c => c.type === 'BODY')
  if (!body || !body.text) return '(sin BODY)'
  const text = body.text
  return text.length > 140 ? text.slice(0, 137) + '…' : text
}

function buildSubmitCommand(tenantId: string, name: string, language: string): string {
  return (
    `python3.11 scripts/admin/submit_template_to_meta.py \\\n` +
    `  --tenant-id ${tenantId} \\\n` +
    `  --template-name ${name} \\\n` +
    `  --language ${language}`
  )
}

export default function TemplatesManager({
  initialTemplates,
  canWrite,
  tenantId,
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

  const templates = initialTemplates

  // Orden: status FSM "natural" (LOCAL_DRAFT → PENDING → APPROVED →
  // REJECTED → resto) y luego por nombre.
  const STATUS_ORDER: Record<TemplateStatus, number> = {
    LOCAL_DRAFT: 0, PENDING: 1, APPROVED: 2, REJECTED: 3, PAUSED: 4, DISABLED: 5,
  }
  const sortedTemplates = useMemo(() => {
    return [...templates].sort((a, b) => {
      const aOrder = STATUS_ORDER[a.status] ?? 99
      const bOrder = STATUS_ORDER[b.status] ?? 99
      if (aOrder !== bOrder) return aOrder - bOrder
      return a.name.localeCompare(b.name)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates])

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
      setSuccessMsg('Borrador creado. Revisalo y usá el script para submitearlo a Meta.')
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
      {/* Mensaje éxito */}
      {successMsg && (
        <div className="rounded-md border border-emerald-700/40 bg-emerald-700/5 p-3 text-sm text-emerald-900 flex items-start gap-2">
          <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">
          {templates.length === 0
            ? 'Aún no hay plantillas. Creá una para empezar.'
            : `${templates.length} plantillas en este tenant.`}
        </div>
        {canWrite && (
          <Button
            onClick={() => { setCreateOpen(true); setFormError(null) }}
            disabled={pending}
            className="gap-2"
          >
            <Plus className="h-4 w-4" /> Nueva plantilla
          </Button>
        )}
      </div>

      {/* Lista */}
      {sortedTemplates.length === 0 ? (
        <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center">
          <MessageSquareText className="h-8 w-8 mx-auto text-muted-foreground/60" />
          <p className="mt-2 text-sm text-muted-foreground">
            Sin plantillas registradas. Creá un borrador, luego submitealo a Meta vía script
            <code className="mx-1 text-xs">submit_template_to_meta.py</code>
            para review (15min-48h).
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
                        Calidad: {t.quality_rating}
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
                        Meta dijo: {t.status_reason}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      Creado {formatDate(t.created_at)}
                      {t.submitted_at && <> · Submitted {formatDate(t.submitted_at)}</>}
                      {t.approved_at && <> · Aprobado {formatDate(t.approved_at)}</>}
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
                        <ShieldCheck className="h-3.5 w-3.5" /> Submit
                      </Button>
                    )}
                    {canWrite && isEditable && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => { setEditing(t); setFormError(null) }}
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
              Creá un borrador local. El submit a Meta para review es manual
              (ver botón "Submit" en la tarjeta una vez creado).
            </DialogDescription>
          </DialogHeader>
          <form action={handleCreate} className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
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
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="category">Categoría</Label>
                <select
                  id="category" name="category" required
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  defaultValue="UTILITY"
                >
                  <option value="UTILITY">UTILITY — transaccional</option>
                  <option value="MARKETING">MARKETING — requiere consent</option>
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
                rows={14}
                defaultValue={buildComponentsPlaceholder(tenantName)}
                className="font-mono text-xs w-full rounded-md border border-input bg-background px-3 py-2"
              />
              <p className="text-xs text-muted-foreground">
                Array Meta-format. Requerido <strong>1 BODY</strong>. Opcional
                {' '}HEADER · FOOTER · BUTTONS. Validación profunda la hace Meta al submitear.
              </p>
            </div>
            {formError && (
              <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-2 text-sm text-rose-900 flex items-start gap-2">
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
                ? 'Plantilla rechazada por Meta. Corregí components y volvé a submitear.'
                : 'Borrador local — solo editable mientras no esté en Meta.'}
            </DialogDescription>
          </DialogHeader>
          {editing && (
            <form action={handleUpdate} className="space-y-4">
              <input type="hidden" name="id" value={editing.id} />
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="rounded-md border bg-muted/30 p-2">
                  <Label className="text-xs">Nombre (inmutable)</Label>
                  <div className="font-mono mt-0.5">{editing.name}</div>
                </div>
                <div className="rounded-md border bg-muted/30 p-2">
                  <Label className="text-xs">Idioma (inmutable)</Label>
                  <div className="font-mono mt-0.5">{editing.language}</div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
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
                  rows={14}
                  defaultValue={JSON.stringify(editing.components, null, 2)}
                  className="font-mono text-xs w-full rounded-md border border-input bg-background px-3 py-2"
                />
              </div>
              {editing.status_reason && (
                <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-2 text-xs text-rose-900">
                  <strong>Razón del rechazo Meta:</strong> {editing.status_reason}
                </div>
              )}
              {formError && (
                <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-2 text-sm text-rose-900 flex items-start gap-2">
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
                <div className="rounded-md border border-rose-700/40 bg-rose-700/5 p-2 text-sm text-rose-900">
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
              {viewing && CATEGORY_LABEL[viewing.category]} · {viewing?.parameter_format}
            </DialogDescription>
          </DialogHeader>
          {viewing && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-xs text-muted-foreground">Status</div>
                  <span
                    className={`inline-flex items-center gap-1 text-xs font-medium border rounded-full px-2 py-0.5 mt-0.5 ${STATUS_CHIP[viewing.status]}`}
                  >
                    {STATUS_LABEL[viewing.status]}
                  </span>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground">Calidad</div>
                  <span
                    className={`inline-flex items-center text-xs font-medium border rounded-full px-2 py-0.5 mt-0.5 ${QUALITY_CHIP[viewing.quality_rating] ?? QUALITY_CHIP.UNKNOWN}`}
                  >
                    {viewing.quality_rating}
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
                  <strong>Razón Meta:</strong> {viewing.status_reason}
                </div>
              )}
              <div>
                <Label className="text-xs">Components</Label>
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

      {/* ─── Dialog: Submit to Meta (instructivo CLI per ADR-0016 D2) ─── */}
      <Dialog open={!!submitFor} onOpenChange={(o) => { if (!o) setSubmitFor(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Submit a Meta para review</DialogTitle>
            <DialogDescription>
              El submit se ejecuta vía CLI (review Meta 15min-48h + pre-validación
              humana). Copiá el comando y corrélo desde el servidor.
            </DialogDescription>
          </DialogHeader>
          {submitFor && (
            <div className="space-y-3">
              <div className="rounded-md border bg-muted/30 p-3">
                <pre className="font-mono text-xs whitespace-pre-wrap select-all">
                  {buildSubmitCommand(tenantId, submitFor.name, submitFor.language)}
                </pre>
              </div>
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(
                    buildSubmitCommand(tenantId, submitFor.name, submitFor.language),
                  )
                  setSuccessMsg('Comando copiado al portapapeles.')
                  setSubmitFor(null)
                }}
                className="text-xs text-primary underline inline-flex items-center gap-1"
              >
                <Copy className="h-3 w-3" /> Copiar comando
              </button>
              <p className="text-xs text-muted-foreground">
                Cuando termine el review, Meta dispara el webhook
                <code className="mx-1">message_template_status_update</code>
                y esta misma pantalla mostrará el nuevo status (APPROVED / REJECTED).
              </p>
              <DialogFooter>
                <Button onClick={() => setSubmitFor(null)} variant="ghost">Cerrar</Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
