import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { Bot, BookOpen, Sparkles } from 'lucide-react'
import { BotPreview } from './bot-preview'
import { ReadinessCard } from './readiness-card'
import { AgentsList } from './agents-list'

const TONO_LABEL: Record<string, string> = {
  amigable: 'Amigable y cercano',
  formal: 'Formal y profesional',
  neutro: 'Neutro',
  energico: 'Enérgico y motivador',
}

export default async function AiAgentsPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const canWrite = ['owner', 'manager'].includes(meta.role ?? '')

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const [{ data }, { data: tenant }, { data: kbStats }, { data: catalogStats }, { data: integrations }] = await Promise.all([
    // Rev. 109 ADR-0017 — multi-agente. order is_default desc para que
    // el primero retornado sea siempre el default cuando existan varios.
    supabase.from('ai_agents')
      .select('id, name, role_description, strict_guardrails, role, is_default, fallback_for_roles')
      .eq('tenant_id', tenantId)
      .order('is_default', { ascending: false })
      .order('name', { ascending: true }),
    supabase.from('tenants').select(
      'mision, vision, valores, tono_comunicacion, support_schedule, store_locations, shipping_origin, nit, email_contacto, telefono_contacto'
    ).eq('id', tenantId).maybeSingle(),
    supabase.from('kb_documents')
      .select('is_active, embedding, category')
      .eq('tenant_id', tenantId),
    supabase.from('products')
      // F7 (twin): products usa status (no is_active, inexistente) → el query erraba,
      // catalogStats quedaba null y el panel 'Estado del bot' marcaba SIN catálogo aunque
      // hubiera productos. Mismo root cause que el preview del agente.
      .select('id', { count: 'exact', head: false })
      .eq('tenant_id', tenantId)
      .eq('status', 'active')
      .limit(1),
    supabase.from('tenant_integrations')
      .select('provider, status')
      .eq('tenant_id', tenantId)
      .in('provider', ['wompi', 'aveonline']),
  ])

  const kbDocs     = (kbStats ?? []) as Array<{ is_active: boolean; embedding: string | null; category: string }>
  const activeDocs  = kbDocs.filter(d => d.is_active).length
  const indexedDocs = kbDocs.filter(d => d.is_active && d.embedding).length
  const totalDocs   = kbDocs.length

  // Rev. 71 — cobertura crítica por categoría: el bot anti-aluci necesita
  // mínimo 1 doc activo en politicas/envios/pagos para responder con verdad.
  const kbCriticalCoverage = {
    politicas: kbDocs.filter(d => d.is_active && d.category === 'politicas').length,
    envios:    kbDocs.filter(d => d.is_active && d.category === 'envios').length,
    pagos:     kbDocs.filter(d => d.is_active && d.category === 'pagos').length,
  }

  // Rev. 109 ADR-0017 — multi-agente. data ahora es array (no single).
  const agentsList = (data ?? []) as Array<{
    id?: string
    name: string
    role_description: string
    strict_guardrails: boolean
    role?: string | null
    is_default?: boolean | null
  }>
  const agent = agentsList[0] || {
    name: 'Vendedor Oficial',
    role_description: 'Eres el agente de atención al cliente de esta tienda por WhatsApp. Te encargas de asistir e informar cordialmente.',
    strict_guardrails: true,
    role: 'sales',
  }

  const hasFilosofia = !!(tenant?.mision || tenant?.valores)
  // Rev. 68 — checks adicionales para Estado del bot ampliado.
  const hasTono = !!tenant?.tono_comunicacion
  const hasSedesHorario = !!(
    (Array.isArray(tenant?.store_locations) && tenant!.store_locations.length > 0) ||
    (tenant?.shipping_origin && (tenant.shipping_origin as { city?: string })?.city)
  ) && !!tenant?.support_schedule
  const hasCatalog = Array.isArray(catalogStats) && catalogStats.length > 0
  // Rev. 71 — identidad legal mínima para que el bot responda con verdad si
  // el cliente pregunta (NIT/email/teléfono corporativo).
  const hasIdentidadLegal = !!(tenant?.nit || tenant?.email_contacto || tenant?.telefono_contacto)
  const integrationsRows = (integrations ?? []) as Array<{ provider: string; status: string }>
  const wompiConnected = integrationsRows.some(i => i.provider === 'wompi' && i.status === 'connected')
  const aveonlineConnected = integrationsRows.some(i => i.provider === 'aveonline' && i.status === 'connected')

  // ─── Server actions consolidadas (CRUD agente) ──────────────────────
  // Rev. 109 ADR-0017 cierre — antes había 2 server actions duplicadas
  // (form inline solo para default + insert directo desde drawer en
  // client). Ahora 3 acciones explícitas: createAgent / updateAgent /
  // deleteAgent. La UI invoca según contexto (drawer crear vs editar).

  async function createAgent(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos' }
    }
    const name = (formData.get('name') as string || '').trim()
    const roleVal = (formData.get('role') as string || 'sales').trim()
    const role_description = (formData.get('role_description') as string || '').trim()
    if (!name) return { ok: false, error: 'El nombre del agente es obligatorio' }
    if (!role_description) return { ok: false, error: 'El prompt maestro es obligatorio' }
    if (role_description.length > 2500) return { ok: false, error: 'Máximo 2500 caracteres' }

    // Validación rol único: el rol debe estar libre (excepto si no hay
    // ningún agente — primer agente se crea como default sales).
    const { data: existing } = await sb
      .from('ai_agents')
      .select('id, role, is_default')
      .eq('tenant_id', m.tenant_id)
    const existingArr = existing ?? []
    const roleTaken = existingArr.some(a => (a.role ?? 'sales') === roleVal)
    if (roleTaken) {
      return {
        ok: false,
        error: `Ya tienes un agente con rol ${roleVal}. Solo 1 agente por rol.`,
      }
    }

    // Si no hay agentes, el primero es default. Si ya hay default,
    // los nuevos son is_default=false (1 default por tenant garantizado
    // por partial unique index).
    const hasDefault = existingArr.some(a => a.is_default === true)
    const { error: e1 } = await sb.from('ai_agents').insert({
      tenant_id: m.tenant_id,
      name, role: roleVal, role_description,
      strict_guardrails: true,
      is_default: !hasDefault,
    })
    if (e1) return { ok: false, error: e1.message }
    revalidatePath('/dashboard/ai-agents')
    return { ok: true }
  }

  async function updateAgent(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos' }
    }
    const id = (formData.get('id') as string || '').trim()
    const name = (formData.get('name') as string || '').trim()
    const roleVal = (formData.get('role') as string || 'sales').trim()
    const role_description = (formData.get('role_description') as string || '').trim()
    const strict_guardrails = formData.get('strict_guardrails') !== null
    if (!id || !name || !role_description) {
      return { ok: false, error: 'Datos incompletos' }
    }
    if (role_description.length > 2500) return { ok: false, error: 'Máximo 2500 caracteres' }

    // Si el rol cambia, validar que el nuevo rol no esté tomado por OTRO agente.
    const { data: current } = await sb
      .from('ai_agents')
      .select('role, is_default')
      .eq('id', id)
      .eq('tenant_id', m.tenant_id)
      .maybeSingle()
    if (!current) return { ok: false, error: 'Agente no encontrado' }

    const isDefault = current.is_default === true
    // El default tiene rol bloqueado en 'sales' — protege coherencia.
    const finalRole = isDefault ? (current.role ?? 'sales') : roleVal
    if (!isDefault && finalRole !== current.role) {
      const { data: peers } = await sb
        .from('ai_agents')
        .select('id, role')
        .eq('tenant_id', m.tenant_id)
        .neq('id', id)
      const roleTaken = (peers ?? []).some(p => (p.role ?? 'sales') === finalRole)
      if (roleTaken) {
        return {
          ok: false,
          error: `Ya tienes un agente con rol ${finalRole}.`,
        }
      }
    }

    // Rev. 109 fallback_for_roles — solo aplica al default. Para non-default
    // ignoramos (el rol del agente especialista define qué cubre).
    const CANONICAL_ROLES = ['sales', 'support', 'marketing', 'claims'] as const
    const rawFallbackRoles = formData.getAll('fallback_for_roles') as string[]
    const fallbackRoles = isDefault
      ? rawFallbackRoles.filter((r): r is (typeof CANONICAL_ROLES)[number] =>
          (CANONICAL_ROLES as readonly string[]).includes(r),
        )
      : null

    const updatePayload: Record<string, unknown> = {
      name, role: finalRole, role_description, strict_guardrails,
    }
    if (fallbackRoles !== null) {
      updatePayload.fallback_for_roles = fallbackRoles
    }

    const { error: e1 } = await sb
      .from('ai_agents')
      .update(updatePayload)
      .eq('id', id)
      .eq('tenant_id', m.tenant_id)
    if (e1) return { ok: false, error: e1.message }
    revalidatePath('/dashboard/ai-agents')
    return { ok: true }
  }

  async function deleteAgent(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos' }
    }
    const id = (formData.get('id') as string || '').trim()
    if (!id) return { ok: false, error: 'ID requerido' }

    // No permitir borrar el default — el tenant siempre necesita 1 agente.
    const { data: target } = await sb
      .from('ai_agents')
      .select('is_default')
      .eq('id', id)
      .eq('tenant_id', m.tenant_id)
      .maybeSingle()
    if (!target) return { ok: false, error: 'Agente no encontrado' }
    if (target.is_default) {
      return {
        ok: false,
        error: 'No puedes borrar el agente default. Edítalo si necesitas cambios.',
      }
    }

    const { error: e1 } = await sb
      .from('ai_agents')
      .delete()
      .eq('id', id)
      .eq('tenant_id', m.tenant_id)
    if (e1) return { ok: false, error: e1.message }
    revalidatePath('/dashboard/ai-agents')
    return { ok: true }
  }

  return (
    <div className="space-y-6 max-w-7xl">

      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <h1 className="text-xl sm:text-2xl font-bold flex items-center gap-2 text-foreground">
            <Bot className="h-5 w-5 text-primary" /> Configuración de la Inteligencia Artificial
          </h1>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full border border-green-700/30 bg-green-500/10 text-green-700">
            Zero-Hallucinations Activo
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Ajusta la personalidad, rol y los límites estrictos de tu asistente virtual de WhatsApp.
        </p>
      </div>

      <ReadinessCard
        hasFilosofia={hasFilosofia}
        hasTono={hasTono}
        hasSedesHorario={hasSedesHorario}
        hasCatalog={hasCatalog}
        totalDocs={totalDocs}
        activeDocs={activeDocs}
        indexedDocs={indexedDocs}
        agentName={agent.name}
        hasPrompt={!!agent.role_description && agent.role_description.length > 20}
        wompiConnected={wompiConnected}
        aveonlineConnected={aveonlineConnected}
        hasIdentidadLegal={hasIdentidadLegal}
        kbCriticalCoverage={kbCriticalCoverage}
      />

      <div className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/5 to-background p-6">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-purple-500/15 border border-purple-500/25 flex items-center justify-center shrink-0">
            <Sparkles className="h-6 w-6 text-purple-500" />
          </div>
          <div>
            <p className="font-semibold text-foreground">Anti-Spam & RAG en Tiempo Real</p>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              La IA solo puede nutrirse de la base de conocimientos y catálogos explícitos.
              Además, está controlada por guardrails de Meta (WhatsApp) que le obligan a emitir mensajes cortos.
            </p>
          </div>
        </div>
      </div>

      {/* Card: Filosofía del negocio — contexto inyectado automáticamente */}
      <div className={`rounded-xl border p-5 space-y-3 ${hasFilosofia ? 'border-emerald-700/25 bg-emerald-500/5' : 'border-amber-700/25 bg-amber-500/5'}`}>
        <div className="flex items-center gap-2">
          <BookOpen className={`h-4 w-4 ${hasFilosofia ? 'text-emerald-700' : 'text-amber-700'}`} />
          <p className="text-sm font-semibold">
            Filosofía del negocio — inyectada automáticamente al bot
          </p>
        </div>
        {hasFilosofia ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
            {tenant?.mision && (
              <div>
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide mb-1">Misión</p>
                <p className="text-foreground leading-relaxed">{tenant.mision}</p>
              </div>
            )}
            {tenant?.vision && (
              <div>
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide mb-1">Visión</p>
                <p className="text-foreground leading-relaxed">{tenant.vision}</p>
              </div>
            )}
            {tenant?.valores && (
              <div>
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide mb-1">Valores</p>
                <p className="text-foreground leading-relaxed">{tenant.valores}</p>
              </div>
            )}
            {tenant?.tono_comunicacion && (
              <div>
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide mb-1">Tono de marca</p>
                <p className="text-foreground">{TONO_LABEL[tenant.tono_comunicacion] ?? tenant.tono_comunicacion}</p>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-amber-700">
            No has configurado la Filosofía del negocio todavía.{' '}
            <a href="/dashboard/settings" className="underline hover:no-underline">
              Configúrala en Ajustes → General
            </a>{' '}
            para que el bot conozca tu marca.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Esta información se combina con el Prompt Maestro abajo. No la repitas — usa el Prompt para definir
          cómo actúa el bot en ventas: su nombre, qué ofrece primero, cómo cierra.
        </p>
      </div>

      {/* Rev. 109 ADR-0017 — gestión consolidada multi-agente (CRUD).
          Reemplazó el form inline legacy que solo editaba el default. */}
      <AgentsList
        agents={agentsList}
        canWrite={canWrite}
        createAgent={createAgent}
        updateAgent={updateAgent}
        deleteAgent={deleteAgent}
      />

      <BotPreview />
    </div>
  )
}
