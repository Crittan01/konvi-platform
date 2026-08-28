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
import { PageHeader } from '@/components/ui/page-header'
import WhatsAppTabs from './_components/whatsapp-tabs'
import WhatsAppSetup from './_components/whatsapp-setup'
import WhatsAppTemplates from './_components/whatsapp-templates'
import WhatsAppQuality from './_components/whatsapp-quality'
import WhatsAppOptOuts from './_components/whatsapp-optouts'

export const metadata = {
  title: 'WhatsApp — Integraciones',
  description: 'Gestión del canal WhatsApp Business: setup, plantillas, calidad.',
}

// ─── Tipos (re-exportados de la versión anterior /whatsapp-templates) ───────
// Enums + validadores viven en ./_lib/template-validation (lógica pura, testeada
// con vitest). Se re-exportan aquí para no romper `import ... from '../page'`.
import {
  VALID_CATEGORIES,
  VALID_PARAMETER_FORMATS,
  EDITABLE_STATUSES,
  NAME_PATTERN,
  LANGUAGE_PATTERN,
  parseComponentsJSON,
  type TemplateCategory,
  type TemplateStatus,
  type ParameterFormat,
  type TemplateComponent,
} from './_lib/template-validation'

export type {
  TemplateCategory, TemplateStatus, ParameterFormat, TemplateComponent,
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

export type OptOutRow = {
  id: string
  phone: string
  name: string | null
  consent_revoked_at: string
}

// ─── Audit log helper (paridad con claims/categories/purchases) ─────────────
// Las server actions de este panel escriben directo a Supabase (no pasan por el
// API router), así que el audit_log se inserta aquí mismo. RLS: audit_log usa
// app_current_tenant() que resuelve del JWT del usuario (mismo mecanismo que
// whatsapp_templates), por lo que el insert user-scoped pasa el WITH CHECK.
async function writeAuditLog(
  sb: Awaited<ReturnType<typeof createClient>>,
  args: {
    tenantId: string
    userId: string | null
    userEmail: string | null
    action: string
    entityId: string | null
    payload: Record<string, unknown>
  },
): Promise<void> {
  try {
    await sb.from('audit_log').insert({
      tenant_id: args.tenantId,
      user_id: args.userId,
      user_email: args.userEmail,
      action: args.action,
      entity_type: 'whatsapp_template',
      entity_id: args.entityId,
      payload: args.payload,
    })
  } catch (e) {
    // El audit no debe tumbar la operación de negocio; log y seguir.
    console.error('[whatsapp-templates] audit_log insert falló', e)
  }
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

  const { data: inserted, error } = await sb.from('whatsapp_templates').insert({
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
  }).select('id').maybeSingle()

  if (error) {
    if (error.code === '23505') {
      return {
        ok: false,
        error: `Ya existe una plantilla con nombre "${name}" en idioma "${language}".`,
      }
    }
    return { ok: false, error: `Error al crear plantilla: ${error.message}` }
  }

  await writeAuditLog(sb, {
    tenantId: meta.tenant_id,
    userId: user?.id ?? null,
    userEmail: user?.email ?? null,
    action: 'whatsapp_template.created',
    entityId: (inserted?.id as string) ?? null,
    payload: { name, language, category, parameter_format },
  })

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

  // Editar reabre el ciclo: el template vuelve a LOCAL_DRAFT y se DESLIGA de la
  // submission Meta anterior. Nulear meta_template_id/submitted_at/approved_at
  // evita que un webhook tardío del submit viejo (que matchea por meta_template_id)
  // pise el draft nuevo — paridad con el helper canónico whatsapp_templates.py.
  const { error } = await sb
    .from('whatsapp_templates')
    .update({
      category,
      parameter_format,
      components: parsed.value,
      status: 'LOCAL_DRAFT',
      status_reason: null,
      meta_template_id: null,
      submitted_at: null,
      approved_at: null,
    })
    .eq('id', id)
    .eq('tenant_id', meta.tenant_id)

  if (error) return { ok: false, error: `Error al actualizar: ${error.message}` }

  await writeAuditLog(sb, {
    tenantId: meta.tenant_id,
    userId: user?.id ?? null,
    userEmail: user?.email ?? null,
    action: 'whatsapp_template.updated',
    entityId: id,
    payload: { category, parameter_format, previous_status: existing.status },
  })

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

  await writeAuditLog(sb, {
    tenantId: meta.tenant_id,
    userId: user?.id ?? null,
    userEmail: user?.email ?? null,
    action: 'whatsapp_template.deleted',
    entityId: id,
    payload: { name: existing.name },
  })

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
        .order('name', { ascending: true })
        .limit(200),  // cota defensiva: un tenant no debería tener >200 plantillas
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

  // Opt-outs: contactos que revocaron consentimiento (STOP) — el bot ya bloquea
  // outbound para ellos. Se listan solo cuando la tab está activa (evita query ociosa).
  let optOuts: OptOutRow[] = []
  if (tenantId && tab === 'optouts') {
    const { data: ooData } = await supabase
      .from('contacts')
      .select('id, phone, name, consent_revoked_at')
      .eq('tenant_id', tenantId)
      .not('consent_revoked_at', 'is', null)
      .order('consent_revoked_at', { ascending: false })
      .limit(200)
    optOuts = (ooData as OptOutRow[] | null) ?? []
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

      {/* Header — cabecera de módulo con identidad (firma Kaiu, T7.12). La
          línea de estado Conectado/Desconectado con los dots va al description
          verbatim (mismo patrón que PanelHeader). */}
      <PageHeader
        icon={MessageSquareText}
        title="WhatsApp Business"
        description={
          connected ? (
            <>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-emerald-700 inline-block" />
                Conectado
              </span>
              {wabaId && <> · WABA {wabaId}</>}
              {displayPhone && <> · {displayPhone}</>}
              {' · '}{counts.approved}/{counts.total} plantillas aprobadas
            </>
          ) : (
            <>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-slate-700 inline-block" />
                Desconectado
              </span>
              {' · Configura WhatsApp en la pestaña Setup para empezar.'}
            </>
          )
        }
      />

      {/* Banner sin WABA configurado */}
      {!wabaConfigured && tab === 'plantillas' && (
        <div className="rounded-md border border-amber-700/40 bg-amber-700/5 p-3 text-sm text-amber-900">
          <AlertTriangle className="inline h-4 w-4 mr-1" />
          {!connected
            ? 'WhatsApp aún no está conectado. Ve a la pestaña Setup para conectar.'
            : 'WhatsApp conectado pero falta el waba_id. Completa Setup primero.'}
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
        <WhatsAppOptOuts optOuts={optOuts} connected={connected} />
      )}
    </div>
  )
}
