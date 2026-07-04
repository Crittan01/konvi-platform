/**
 * Panel WhatsApp — restructura Integraciones Sem 7 F2 cierre.
 *
 * Cada integración tiene su propio panel con tabs:
 *   - Setup: credenciales, WABA, status, opt-out enforcement
 *   - Plantillas: CRUD templates HSM (moved from /dashboard/whatsapp-templates)
 *   - Calidad: quality rating + tier rate limit (futuro MA-6 Sem 11)
 *   - Opt-outs: lista de contactos opt-out (futuro)
 *
 * Routing: /dashboard/integrations/whatsapp?tab=setup|plantillas|calidad|optouts
 * RBAC: owner/manager. Operator redirect.
 */
import Link from 'next/link'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'
import {
  getCachedUser, getCachedTenantMeta, getCachedTenantName,
} from '@/utils/supabase/cached-user'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { MessageSquareText, ArrowLeft, AlertTriangle } from 'lucide-react'
import WhatsAppTabs from './_components/whatsapp-tabs'
import WhatsAppSetup from './_components/whatsapp-setup'
import WhatsAppTemplates from './_components/whatsapp-templates'
import WhatsAppQuality from './_components/whatsapp-quality'

export const metadata = {
  title: 'WhatsApp — Integraciones',
  description: 'Gestión del canal WhatsApp Business: setup, plantillas, calidad.',
}

// ─── Tipos (re-exportados de la versión anterior /whatsapp-templates) ───────

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
const NAME_PATTERN = /^[a-z][a-z0-9_]{2,49}$/
const LANGUAGE_PATTERN = /^[a-z]{2}(_[A-Z]{2})?$/

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

// ─── Server actions templates (movidas de /whatsapp-templates) ──────────────

async function createDraftAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos para crear plantillas.' }
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
      error: 'WhatsApp no está conectado. Configurá la integración en la tab Setup primero.',
    }
  }
  const credentials = (integ.credentials || {}) as Record<string, string>
  const waba_id = credentials.waba_id
  if (!waba_id) {
    return {
      ok: false,
      error: 'tenant_integrations.credentials.waba_id no configurado. Completá Setup primero.',
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
        error: `Ya existe una plantilla con nombre "${name}" en idioma "${language}".`,
      }
    }
    return { ok: false, error: `Error al crear plantilla: ${error.message}` }
  }

  revalidatePath('/dashboard/integrations/whatsapp')
  return { ok: true }
}

async function updateDraftAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) {
    return { ok: false, error: 'Sin permisos.' }
  }

  const id = ((formData.get('id') as string) || '').trim()
  if (!id) return { ok: false, error: 'ID de plantilla requerido.' }

  const { data: existing } = await sb
    .from('whatsapp_templates')
    .select('status')
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)
    .maybeSingle()
  if (!existing) return { ok: false, error: 'Plantilla no encontrada.' }
  if (!EDITABLE_STATUSES.has(existing.status as TemplateStatus)) {
    return {
      ok: false,
      error:
        `No se puede editar plantilla en estado ${existing.status}. ` +
        'Solo LOCAL_DRAFT y REJECTED permiten edición.',
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
      status: 'LOCAL_DRAFT',
      status_reason: null,
    })
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)

  if (error) return { ok: false, error: `Error al actualizar: ${error.message}` }

  revalidatePath('/dashboard/integrations/whatsapp')
  return { ok: true }
}

async function deleteDraftAction(
  formData: FormData,
): Promise<{ ok: boolean; error?: string }> {
  'use server'
  const sb = await createClient()
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
  if (!existing) return { ok: false, error: 'Plantilla no encontrada.' }
  if (existing.status !== 'LOCAL_DRAFT') {
    return {
      ok: false,
      error:
        `Solo plantillas en LOCAL_DRAFT pueden eliminarse (preservar audit). ` +
        `Esta está en ${existing.status}.`,
    }
  }

  const { error } = await sb
    .from('whatsapp_templates')
    .delete()
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)

  if (error) return { ok: false, error: `Error al eliminar: ${error.message}` }

  revalidatePath('/dashboard/integrations/whatsapp')
  return { ok: true }
}

// ─── Page ────────────────────────────────────────────────────────────────────

type Tab = 'setup' | 'plantillas' | 'calidad' | 'optouts'
const VALID_TABS: Tab[] = ['setup', 'plantillas', 'calidad', 'optouts']

export default async function WhatsAppIntegrationPage(
  props: {
    searchParams: Promise<{ tab?: string }>
  }
) {
  const searchParams = await props.searchParams;
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  if (role === 'operator') redirect('/dashboard')
  const canWrite = role === 'owner' || role === 'manager'
  const tenantName = (await getCachedTenantName()) ?? 'Tu tienda'

  const requestedTab = (searchParams.tab || 'setup').toLowerCase()
  const tab: Tab = VALID_TABS.includes(requestedTab as Tab)
    ? (requestedTab as Tab)
    : 'setup'

  const supabase = await createClient()

  // Lookup integration + templates en paralelo
  let integration: {
    status: string
    credentials: Record<string, string>
    meta_data: Record<string, unknown>
  } | null = null
  let templates: WhatsAppTemplate[] = []

  if (tenantId) {
    const [integRes, tplRes] = await Promise.all([
      supabase
        .from('tenant_integrations')
        .select('status, credentials, meta')
        .eq('tenant_id', tenantId)
        .eq('provider', 'whatsapp')
        .maybeSingle(),
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
    ])
    const integData = integRes.data as {
      status?: string; credentials?: Record<string, string>; meta?: Record<string, unknown>
    } | null
    if (integData) {
      integration = {
        status: integData.status ?? 'disconnected',
        credentials: integData.credentials ?? {},
        meta_data: integData.meta ?? {},
      }
    }
    templates = (tplRes.data as WhatsAppTemplate[] | null) ?? []
  }

  const connected = integration?.status === 'connected'
  const wabaId = integration?.credentials?.waba_id ?? null
  const wabaConfigured = connected && !!wabaId
  const displayPhone = integration?.credentials?.display_phone_number ?? null
  const counts = {
    total: templates.length,
    approved: templates.filter(t => t.status === 'APPROVED').length,
    pending: templates.filter(t => t.status === 'PENDING').length,
    drafts: templates.filter(t => t.status === 'LOCAL_DRAFT').length,
    rejected: templates.filter(t => t.status === 'REJECTED').length,
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link
          href="/dashboard/integrations"
          className="inline-flex items-center gap-1 hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Volver a Integraciones
        </Link>
      </div>

      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <MessageSquareText className="h-5 w-5 text-primary" /> WhatsApp Business
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {connected ? (
            <>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-emerald-700 inline-block" />
                Connected
              </span>
              {wabaId && <> · WABA {wabaId}</>}
              {displayPhone && <> · {displayPhone}</>}
              {' · '}{counts.approved}/{counts.total} plantillas aprobadas
            </>
          ) : (
            <>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-slate-700 inline-block" />
                Disconnected
              </span>
              {' · Configurá WhatsApp en la tab Setup para empezar.'}
            </>
          )}
        </p>
      </div>

      {/* Banner sin WABA configurado */}
      {!wabaConfigured && tab === 'plantillas' && (
        <div className="rounded-md border border-amber-700/40 bg-amber-700/5 p-3 text-sm text-amber-900">
          <AlertTriangle className="inline h-4 w-4 mr-1" />
          {!connected
            ? 'WhatsApp aún no está conectado. Andá a la tab Setup para conectar.'
            : 'WhatsApp conectado pero falta el waba_id. Completá Setup primero.'}
        </div>
      )}

      {/* Tabs */}
      <WhatsAppTabs activeTab={tab} />

      {/* Tab content */}
      {tab === 'setup' && (
        <WhatsAppSetup
          connected={connected}
          credentials={integration?.credentials ?? {}}
          canWrite={canWrite}
          tenantId={tenantId ?? ''}
          apiUrl={CORE_API_URL}
        />
      )}

      {tab === 'plantillas' && (
        <WhatsAppTemplates
          initialTemplates={templates}
          canWrite={canWrite && wabaConfigured}
          tenantId={tenantId ?? ''}
          tenantName={tenantName}
          createDraftAction={createDraftAction}
          updateDraftAction={updateDraftAction}
          deleteDraftAction={deleteDraftAction}
        />
      )}

      {tab === 'calidad' && (
        <WhatsAppQuality
          connected={connected}
          credentials={integration?.credentials ?? {}}
        />
      )}

      {tab === 'optouts' && (
        <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center">
          <p className="text-sm text-muted-foreground">
            Lista de opt-outs (clientes que pidieron no recibir mensajes).
            <br />
            <span className="text-xs">Disponible próximamente (Sem 11).</span>
          </p>
        </div>
      )}
    </div>
  )
}
