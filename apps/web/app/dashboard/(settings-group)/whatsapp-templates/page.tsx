/**
 * Plantillas WhatsApp — UI Tenant Console (Sem 7 F2 item 5 / ADR-0016).
 *
 * CRUD de templates HSM (Highly Structured Messages) que el tenant usa
 * para mensajería fuera de la ventana CSW 24h Meta (payment_reminder,
 * cart_abandoned, order_shipped, etc.).
 *
 * Lifecycle FSM (ver ADR-0016 D2):
 *   LOCAL_DRAFT → PENDING → APPROVED | REJECTED | DISABLED | PAUSED
 *
 * Esta UI cubre:
 *   - List templates per tenant (status, quality_rating, lifecycle)
 *   - Crear LOCAL_DRAFT (admin define components Meta-format)
 *   - Editar LOCAL_DRAFT / REJECTED (components + category + parameter_format)
 *   - Eliminar LOCAL_DRAFT (audit-safe: solo si nunca llegó a Meta)
 *
 * Submit a Meta queda fuera de la UI por decisión D2 — se ejecuta vía
 * `scripts/admin/submit_template_to_meta.py` (review 15min-48h + pre-
 * validación humana). La UI muestra el comando exacto para que el
 * operador lo corra cuando esté listo.
 *
 * Routing: /dashboard/whatsapp-templates (grupo Configuración).
 * RBAC: owner / manager pueden CRUD; operator redirect (no acceso).
 */
import { createClient } from '@/utils/supabase/server'
import {
  getCachedUser, getCachedTenantMeta, getCachedTenantName,
} from '@/utils/supabase/cached-user'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { MessageSquareText, AlertTriangle } from 'lucide-react'
import TemplatesManager from './_components/templates-manager'

export const metadata = {
  title: 'Plantillas WhatsApp — Configuración',
  description:
    'Gestión de templates HSM aprobados por Meta para mensajería fuera de CSW 24h.',
}

// ─── Tipos ───────────────────────────────────────────────────────────────────

export type TemplateCategory = 'UTILITY' | 'MARKETING' | 'AUTHENTICATION'
export type TemplateStatus =
  | 'LOCAL_DRAFT' | 'PENDING' | 'APPROVED' | 'REJECTED' | 'DISABLED' | 'PAUSED'
export type ParameterFormat = 'POSITIONAL' | 'NAMED'

export type TemplateComponent = {
  type: 'HEADER' | 'BODY' | 'FOOTER' | 'BUTTONS'
  text?: string
  format?: string
  buttons?: Array<Record<string, unknown>>
  example?: Record<string, unknown>
}

export type WhatsAppTemplate = {
  id: string
  waba_id: string
  name: string
  language: string
  category: TemplateCategory
  components: TemplateComponent[]
  parameter_format: ParameterFormat
  status: TemplateStatus
  quality_rating: string
  meta_template_id: string | null
  status_reason: string | null
  submitted_at: string | null
  approved_at: string | null
  created_at: string
  updated_at: string
}

const VALID_CATEGORIES = new Set<TemplateCategory>([
  'UTILITY', 'MARKETING', 'AUTHENTICATION',
])
const VALID_PARAMETER_FORMATS = new Set<ParameterFormat>([
  'POSITIONAL', 'NAMED',
])
const EDITABLE_STATUSES = new Set<TemplateStatus>(['LOCAL_DRAFT', 'REJECTED'])

// Meta exige lowercase + dígitos + underscores, debe empezar con letra,
// 3-50 chars. Espejo NAME_PATTERN del helper Python (`whatsapp_templates.py:61`).
const NAME_PATTERN = /^[a-z][a-z0-9_]{2,49}$/
// Locale BCP 47 simplificado: es / es_CO / en_US.
const LANGUAGE_PATTERN = /^[a-z]{2}(_[A-Z]{2})?$/

// ─── Validators backend (espejan helper Python `whatsapp_templates.py`) ──────

function validateComponents(components: TemplateComponent[]): string | null {
  if (!Array.isArray(components) || components.length === 0) {
    return 'components debe ser una lista no vacía.'
  }
  const validTypes = new Set(['HEADER', 'BODY', 'FOOTER', 'BUTTONS'])
  const seenTypes = new Set<string>()
  let bodyCount = 0
  for (let i = 0; i < components.length; i++) {
    const c = components[i]
    if (typeof c !== 'object' || c === null) {
      return `components[${i}] debe ser un objeto.`
    }
    const t = (c.type || '').toUpperCase()
    if (!validTypes.has(t)) {
      return `components[${i}].type "${t}" inválido. Válidos: HEADER, BODY, FOOTER, BUTTONS.`
    }
    if (t !== 'BUTTONS' && seenTypes.has(t)) {
      return `components[${i}]: type "${t}" duplicado. Solo BUTTONS puede repetirse.`
    }
    seenTypes.add(t)
    if (t === 'BODY') {
      bodyCount++
      if (!(c.text || '').trim()) {
        return `components[${i}] BODY requiere campo 'text' no vacío.`
      }
    }
  }
  if (bodyCount !== 1) {
    return 'components requiere exactamente 1 BODY.'
  }
  return null
}

function parseComponentsJSON(raw: string): { ok: true; value: TemplateComponent[] }
                                          | { ok: false; error: string } {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { ok: false, error: 'components: JSON inválido. Revisá llaves y comillas.' }
  }
  if (!Array.isArray(parsed)) {
    return { ok: false, error: 'components: debe ser un array JSON.' }
  }
  const err = validateComponents(parsed as TemplateComponent[])
  if (err) return { ok: false, error: err }
  return { ok: true, value: parsed as TemplateComponent[] }
}

// ─── Server actions ──────────────────────────────────────────────────────────

async function createDraftAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos para crear templates.' }
  }

  const name = ((formData.get('name') as string) || '').trim().toLowerCase()
  const language = ((formData.get('language') as string) || 'es_CO').trim()
  const category = (((formData.get('category') as string) || '').toUpperCase()) as TemplateCategory
  const parameter_format = (((formData.get('parameter_format') as string) || 'POSITIONAL')
    .toUpperCase()) as ParameterFormat
  const componentsRaw = ((formData.get('components') as string) || '').trim()

  if (!NAME_PATTERN.test(name)) {
    return {
      ok: false,
      error:
        'Nombre inválido. Meta exige lowercase + dígitos + underscores, ' +
        'debe empezar con letra, 3-50 chars (ej. payment_reminder_v1).',
    }
  }
  if (!LANGUAGE_PATTERN.test(language)) {
    return { ok: false, error: 'Language inválido. Formato esperado: "es" o "es_CO".' }
  }
  if (!VALID_CATEGORIES.has(category)) {
    return { ok: false, error: 'Categoría inválida. Válidas: UTILITY, MARKETING, AUTHENTICATION.' }
  }
  if (!VALID_PARAMETER_FORMATS.has(parameter_format)) {
    return { ok: false, error: 'parameter_format inválido. Válidos: POSITIONAL, NAMED.' }
  }

  const parsed = parseComponentsJSON(componentsRaw)
  if (!parsed.ok) return { ok: false, error: parsed.error }

  // Resolver waba_id desde tenant_integrations (NO se le pide al usuario).
  const { data: integ, error: integErr } = await sb
    .from('tenant_integrations')
    .select('credentials, status')
    .eq('tenant_id', meta.tenant_id)
    .eq('provider', 'whatsapp')
    .maybeSingle()
  if (integErr) {
    return { ok: false, error: `No pude leer integración WhatsApp: ${integErr.message}` }
  }
  if (!integ || integ.status !== 'connected') {
    return {
      ok: false,
      error:
        'WhatsApp no está conectado. Configurá la integración en /dashboard/integrations ' +
        'antes de crear templates.',
    }
  }
  const credentials = (integ.credentials || {}) as Record<string, string>
  const waba_id = credentials.waba_id
  if (!waba_id) {
    return {
      ok: false,
      error:
        'tenant_integrations.credentials.waba_id no configurado. ' +
        'Configurá WABA ID en Integraciones antes de crear templates.',
    }
  }

  const { error } = await sb.from('whatsapp_templates').insert({
    tenant_id: meta.tenant_id,
    waba_id,
    name,
    language,
    category,
    parameter_format,
    components: parsed.value,
    status: 'LOCAL_DRAFT',
    quality_rating: 'UNKNOWN',
    created_by: user?.id ?? null,
  })

  if (error) {
    if (error.code === '23505') {
      return {
        ok: false,
        error: `Ya existe un template con nombre "${name}" en idioma "${language}" para este tenant.`,
      }
    }
    return { ok: false, error: `Error al crear template: ${error.message}` }
  }

  revalidatePath('/dashboard/whatsapp-templates')
  return { ok: true }
}

async function updateDraftAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos.' }
  }

  const id = ((formData.get('id') as string) || '').trim()
  if (!id) return { ok: false, error: 'ID de template requerido.' }

  // Lookup status para gate de edición.
  const { data: existing } = await sb
    .from('whatsapp_templates')
    .select('status')
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)
    .maybeSingle()
  if (!existing) return { ok: false, error: 'Template no encontrado.' }
  if (!EDITABLE_STATUSES.has(existing.status as TemplateStatus)) {
    return {
      ok: false,
      error:
        `No se puede editar template en estado ${existing.status}. ` +
        'Solo LOCAL_DRAFT y REJECTED permiten edición. Para los demás, ' +
        'creá un nuevo template (ej. name_v2).',
    }
  }

  const category = (((formData.get('category') as string) || '').toUpperCase()) as TemplateCategory
  const parameter_format = (((formData.get('parameter_format') as string) || 'POSITIONAL')
    .toUpperCase()) as ParameterFormat
  const componentsRaw = ((formData.get('components') as string) || '').trim()

  if (!VALID_CATEGORIES.has(category)) {
    return { ok: false, error: 'Categoría inválida.' }
  }
  if (!VALID_PARAMETER_FORMATS.has(parameter_format)) {
    return { ok: false, error: 'parameter_format inválido.' }
  }
  const parsed = parseComponentsJSON(componentsRaw)
  if (!parsed.ok) return { ok: false, error: parsed.error }

  const { error } = await sb
    .from('whatsapp_templates')
    .update({
      category,
      parameter_format,
      components: parsed.value,
      // Si volvía de REJECTED, volver a LOCAL_DRAFT para nuevo intento.
      status: 'LOCAL_DRAFT',
      status_reason: null,
    })
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)

  if (error) return { ok: false, error: `Error al actualizar: ${error.message}` }

  revalidatePath('/dashboard/whatsapp-templates')
  return { ok: true }
}

/**
 * DELETE — Solo permitido si status=LOCAL_DRAFT (NO submitted a Meta).
 *
 * Templates en PENDING/APPROVED/REJECTED/DISABLED/PAUSED tienen historia
 * en Meta + posiblemente en `messages` outbound previos. Preservar audit.
 */
async function deleteDraftAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos.' }
  }

  const id = ((formData.get('id') as string) || '').trim()
  if (!id) return { ok: false, error: 'ID requerido.' }

  const { data: existing } = await sb
    .from('whatsapp_templates')
    .select('status, name')
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)
    .maybeSingle()
  if (!existing) return { ok: false, error: 'Template no encontrado.' }
  if (existing.status !== 'LOCAL_DRAFT') {
    return {
      ok: false,
      error:
        `Solo templates en LOCAL_DRAFT pueden eliminarse (preservar audit). ` +
        `Este está en ${existing.status}. Si querés "retirarlo", deshabilitalo ` +
        'desde el panel Meta Business.',
    }
  }

  const { error } = await sb
    .from('whatsapp_templates')
    .delete()
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)

  if (error) return { ok: false, error: `Error al eliminar: ${error.message}` }

  revalidatePath('/dashboard/whatsapp-templates')
  return { ok: true }
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default async function WhatsAppTemplatesPage() {
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const tenantName = (await getCachedTenantName()) ?? 'Tu tienda'

  // Protección por navegación directa — operators no acceden.
  if (role === 'operator') redirect('/dashboard')

  const canWrite = role === 'owner' || role === 'manager'
  const supabase = createClient()

  let templates: WhatsAppTemplate[] = []
  let wabaConfigured = false
  if (tenantId) {
    const [tplRes, integRes] = await Promise.all([
      supabase
        .from('whatsapp_templates')
        .select(
          'id, waba_id, name, language, category, components, parameter_format, ' +
          'status, quality_rating, meta_template_id, status_reason, submitted_at, ' +
          'approved_at, created_at, updated_at'
        )
        .eq('tenant_id', tenantId)
        .order('status', { ascending: true })
        .order('name', { ascending: true }),
      supabase
        .from('tenant_integrations')
        .select('credentials, status')
        .eq('tenant_id', tenantId)
        .eq('provider', 'whatsapp')
        .maybeSingle(),
    ])
    templates = (tplRes.data as WhatsAppTemplate[] | null) ?? []
    const integ = integRes.data as { credentials?: Record<string, string>; status?: string } | null
    wabaConfigured = !!(
      integ &&
      integ.status === 'connected' &&
      integ.credentials &&
      integ.credentials.waba_id
    )
  }

  const counts = {
    total: templates.length,
    approved: templates.filter(t => t.status === 'APPROVED').length,
    pending: templates.filter(t => t.status === 'PENDING').length,
    drafts: templates.filter(t => t.status === 'LOCAL_DRAFT').length,
    rejected: templates.filter(t => t.status === 'REJECTED').length,
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <MessageSquareText className="h-5 w-5 text-primary" /> Plantillas WhatsApp
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {counts.total} plantillas · {counts.approved} aprobadas · {counts.pending} en revisión ·
          {' '}{counts.drafts} borradores · {counts.rejected} rechazadas.
          Estas plantillas se usan para contactar clientes <strong>fuera</strong> de la ventana
          de 24h Meta (recordatorios de pago, carritos abandonados, etc.).
        </p>
      </div>

      {!wabaConfigured && (
        <div className="rounded-md border border-amber-700/40 bg-amber-700/5 p-3 text-sm text-amber-900">
          <AlertTriangle className="inline h-4 w-4 mr-1" />
          WhatsApp aún no está conectado o falta el <code>waba_id</code>.
          Configurá la integración en{' '}
          <a href="/dashboard/integrations" className="underline">Integraciones</a>{' '}
          antes de crear plantillas.
        </div>
      )}

      {!canWrite && (
        <div className="rounded-md border border-amber-700/40 bg-amber-700/5 p-3 text-sm text-amber-900">
          <AlertTriangle className="inline h-4 w-4 mr-1" />
          Solo el rol Administrador o Supervisor puede crear/editar plantillas.
        </div>
      )}

      <TemplatesManager
        initialTemplates={templates}
        canWrite={canWrite && wabaConfigured}
        tenantId={tenantId ?? ''}
        tenantName={tenantName}
        createDraftAction={createDraftAction}
        updateDraftAction={updateDraftAction}
        deleteDraftAction={deleteDraftAction}
      />
    </div>
  )
}
