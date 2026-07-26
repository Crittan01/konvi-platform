import { createClient } from '@/utils/supabase/server'
import { createAdminClient } from '@/utils/supabase/admin'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import * as Sentry from '@sentry/nextjs'
import { SubmitButton } from '@/components/ui/submit-button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Users, ShieldCheck, UserPlus, Mail, AlertCircle, CheckCircle2, Crown, Briefcase, Headphones, RefreshCw } from 'lucide-react'
import { WEB_APP_URL } from '@/lib/runtime-env'
import RemoveMemberButton from './remove-member-button'
import ChangeRoleButton from './change-role-button'
import InactivateMemberButton from './inactivate-member-button'
import { TeamUrlCleaner } from './url-cleaner'
import { mapTeamError } from './error-copy'

export const metadata = {
  title: 'Usuarios y Acceso',
  description: 'Gestiona los miembros del equipo y sus roles de acceso a la consola del tenant.',
}

// ─── Tipos ───────────────────────────────────────────────────────────────────

type TeamMember = {
  user_id:   string
  email:     string
  role:      string
  status:    string   // 'active' | 'inactive'
  joined_at: string
  confirmed: boolean
}

// ─── Configuración de Roles ───────────────────────────────────────────────────
//
// "Operador" reemplaza "Agente" para evitar confusión con "Agente IA"
// del módulo IA y Conocimiento.
//
const ROLES = {
  owner: {
    label: 'Administrador',
    icon: Crown,
    color: 'bg-amber-500/10 text-amber-700 border-amber-700/25',
    headerColor: 'border-amber-700/20 bg-amber-500/5',
    textColor: 'text-amber-700',
    iconColor: 'text-amber-700',
    description: 'Acceso total. Configura integraciones, equipo y datos del negocio.',
  },
  manager: {
    label: 'Supervisor',
    icon: Briefcase,
    color: 'bg-blue-500/10 text-blue-700 border-blue-700/25',
    headerColor: 'border-blue-700/20 bg-blue-500/5',
    textColor: 'text-blue-700',
    iconColor: 'text-blue-700',
    description: 'Gestiona la operación: pedidos, contactos, catálogo, promociones, canales, métricas y base de conocimiento.',
  },
  operator: {
    label: 'Gestor',
    icon: Headphones,
    color: 'bg-slate-500/10 text-slate-700 border-slate-700/25',
    headerColor: 'border-border bg-muted/20',
    textColor: 'text-muted-foreground',
    iconColor: 'text-muted-foreground',
    description: 'Acceso operativo del día a día: Inbox, Pedidos, Contactos, Reclamos y Cotizador de envíos.',
  },
} as const

type RoleKey = keyof typeof ROLES

function RoleBadge({ role }: { role: string }) {
  const cfg = ROLES[role as RoleKey]
  if (!cfg) return <span className="text-xs text-muted-foreground">{role}</span>
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded-full border ${cfg.color}`}>
      <Icon className="h-3 w-3 shrink-0" /> {cfg.label}
    </span>
  )
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({ icon: Icon, title, description, children, className = '' }: {
  icon: React.ElementType; title: string; description?: string
  children: React.ReactNode; className?: string
}) {
  return (
    <div className={`rounded-xl border border-border bg-card overflow-hidden ${className}`}>
      <div className="px-5 py-4 border-b border-border bg-muted/20">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-primary shrink-0" />
          <p className="font-semibold text-sm">{title}</p>
        </div>
        {description && <p className="text-xs text-muted-foreground mt-0.5 ml-6">{description}</p>}
      </div>
      <div className="p-5">{children}</div>
    </div>
  )
}

// ─── Audit log helper (paridad con whatsapp/ai-agents/claims) ─────────────────
//
// Las server actions de este panel escriben directo a Supabase (no pasan por el
// API router auditado — ver needs_founder "doble implementación"), así que el
// audit_log se inserta aquí mismo con el cliente user-scoped: audit_log usa
// app_current_tenant() del JWT del owner, por lo que el WITH CHECK pasa.
async function writeTeamAudit(
  sb: Awaited<ReturnType<typeof createClient>>,
  args: {
    tenantId: string
    userId: string | null
    userEmail: string | null
    action: string          // 'team.member_invited' | 'team.role_changed' | ...
    entityId: string | null // user_id o email del afectado
    payload: Record<string, unknown>
  },
): Promise<void> {
  try {
    await sb.from('audit_log').insert({
      tenant_id:   args.tenantId,
      user_id:     args.userId,
      user_email:  args.userEmail,
      action:      args.action,
      entity_type: 'team_member',
      entity_id:   args.entityId,
      payload:     args.payload,
    })
  } catch (e) {
    // El audit no debe tumbar la operación de negocio; log + Sentry y seguir.
    console.error('[team] audit_log insert falló', { action: args.action, tenantId: args.tenantId, error: e })
    Sentry.captureException(e, { extra: { where: 'team.audit_log', action: args.action, tenantId: args.tenantId } })
  }
}

// ─── Rate-limit aplicativo per-tenant para invitaciones ───────────────────────
//
// Complementa (no reemplaza) el límite SMTP compartido de Supabase: cuenta los
// eventos de invitación/reenvío del tenant en la ventana reciente vía audit_log.
// Best-effort: si el conteo falla, NO bloquea la operación (fail-open) para no
// convertir un problema de observabilidad en indisponibilidad.
const INVITE_WINDOW_SECONDS = 60
const INVITE_MAX_PER_WINDOW = 5

async function inviteRateLimited(
  sb: Awaited<ReturnType<typeof createClient>>,
  tenantId: string,
): Promise<boolean> {
  try {
    const since = new Date(Date.now() - INVITE_WINDOW_SECONDS * 1000).toISOString()
    const { count, error } = await sb
      .from('audit_log')
      .select('id', { count: 'exact', head: true })
      .eq('tenant_id', tenantId)
      .in('action', ['team.member_invited', 'team.invite_resent'])
      .gte('created_at', since)
    if (error) return false
    return (count ?? 0) >= INVITE_MAX_PER_WINDOW
  } catch {
    return false
  }
}

// ─── Lookup de usuario existente por email (paginado) ─────────────────────────
//
// supabase-js no expone getUserByEmail; auth.admin.listUsers() es global
// (cross-tenant) y pagina de a `perPage` (default 50). Resolver con la primera
// página + .find() rompe en silencio en cuanto auth.users supera 50 usuarios:
// el usuario existente "no se encuentra" aunque exista. Paginamos y cortamos
// apenas hay match (mejor caso: 1 página) para no traer toda la tabla.
async function findUserByEmail(
  adminSb: ReturnType<typeof createAdminClient>,
  email: string,
): Promise<{ id: string } | null> {
  const target = email.trim().toLowerCase()
  const perPage = 1000
  for (let page = 1; page <= 1000; page++) {
    const { data, error } = await adminSb.auth.admin.listUsers({ page, perPage })
    if (error) {
      console.error('[team] listUsers error:', error.message)
      Sentry.captureException(error, { extra: { where: 'team.findUserByEmail', page } })
      return null
    }
    const users = data?.users ?? []
    const hit = users.find(x => x.email?.toLowerCase() === target)
    if (hit) return { id: hit.id }
    if (users.length < perPage) break // última página
  }
  return null
}

// ─── Página ───────────────────────────────────────────────────────────────────

export default async function TeamPage(
  props: {
    searchParams: Promise<{ invited?: string; added?: string; removed?: string; inactivated?: string; activated?: string; error?: string; tab?: string; resent?: string; role_changed?: string }>
  }
) {
  const searchParams = await props.searchParams;
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const isOwner = role === 'owner'
  const myUserId = user?.id

  // Protección por navegación directa — solo owners acceden a esta página
  if (!isOwner) redirect('/dashboard')

  let team: TeamMember[] = []
  let teamLoadFailed = false
  if (tenantId) {
    const { data, error: teamErr } = await supabase.rpc('get_tenant_team')
    if (teamErr) {
      // No enmascarar el fallo como "equipo vacío": eso miente al operador.
      teamLoadFailed = true
      console.error('[team] get_tenant_team:', teamErr.message, teamErr.code)
      Sentry.captureException(teamErr, { extra: { where: 'team.get_tenant_team', tenantId } })
    }
    team = (data as TeamMember[]) || []
  } else {
    teamLoadFailed = true
  }

  // ─── Counts por rol ───────────────────────────────────────────────────────

  const counts = {
    owner:    team.filter(m => m.role === 'owner').length,
    manager:  team.filter(m => m.role === 'manager').length,
    operator: team.filter(m => m.role === 'operator').length,
  }

  // ─── Server Actions ───────────────────────────────────────────────────────

  /**
   * inviteMember — solo Owner
   * Flujo: adminClient.inviteUserByEmail → add_member_to_tenant.
   * El custom_access_token_hook (no un trigger) inyecta los claims tenant_id/role
   * en el próximo login del invitado. El tenant_id viene del JWT del caller,
   * nunca del form.
   */
  async function inviteMember(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') {
      redirect('/dashboard/team?error=sin-permiso')
    }

    const email   = (formData.get('email') as string)?.trim().toLowerCase()
    const newRole = formData.get('role') as string
    if (!email || !['manager', 'operator'].includes(newRole)) {
      redirect('/dashboard/team?error=datos-invalidos')
    }

    // Rate-limit aplicativo per-tenant (además del límite SMTP compartido).
    if (await inviteRateLimited(sb, m.tenant_id)) {
      redirect('/dashboard/team?error=rate-limit')
    }

    // Validar que el email no sea ya miembro del tenant
    const { data: currentTeam } = await sb.rpc('get_tenant_team')
    if ((currentTeam as Array<{email: string}> | null)?.some(m => m.email === email)) {
      redirect('/dashboard/team?error=ya-es-miembro')
    }

    // APP_URL (sin prefijo NEXT_PUBLIC_) = variable de runtime, no baked en el build
    const appUrl  = WEB_APP_URL
    const adminSb = createAdminClient()

    // Nombre del negocio → user_metadata del invitado, disponible en la plantilla de
    // email como {{ .Data.tenant_name }}. Sin esto, en multi-tenant el invitado no sabe
    // a QUÉ negocio se le invita (gap branding). Lectura RLS-scoped al tenant del owner.
    const { data: tenantRow } = await sb.from('tenants').select('name').eq('id', m.tenant_id).single()
    const tenantName = tenantRow?.name ?? undefined

    const { data: inviteData, error: inviteError } = await adminSb.auth.admin.inviteUserByEmail(
      email,
      {
        redirectTo: `${appUrl}/auth/callback?next=/set-password`,
        data: { invited_by: u?.id, tenant_name: tenantName, invited_role: newRole },
      }
    )

    let wasExistingUser = false
    let addedUserId: string | null = null

    if (inviteError) {
      // Usuario ya existente en Supabase Auth — asignar directamente al tenant (sin email)
      if (inviteError.message.includes('already been registered')) {
        wasExistingUser = true
        const existing = await findUserByEmail(adminSb, email)
        if (!existing) {
          redirect('/dashboard/team?error=usuario-no-encontrado')
        }
        addedUserId = existing!.id
        // Single-tenant membership (ADR-0030): un usuario pertenece a UN solo
        // negocio. Si esta cuenta ya es miembro de OTRO tenant, no la reasignamos
        // (evita membresía cruzada + JWT no-determinista). El RPC add_member_to_tenant
        // también lo rechaza a nivel DB (defensa en profundidad); esta pre-validación
        // sólo sirve para dar copy amigable en lugar del error genérico.
        const { data: otherTenant } = await adminSb
          .from('tenant_users')
          .select('tenant_id')
          .eq('user_id', existing!.id)
          .neq('tenant_id', m.tenant_id)
          .limit(1)
        if (otherTenant?.length) {
          redirect('/dashboard/team?error=ya-en-otro-negocio')
        }
        const { error: rpcErr } = await adminSb.rpc('add_member_to_tenant', {
          p_user_id: existing!.id, p_tenant_id: m.tenant_id, p_role: newRole,
        })
        if (rpcErr) {
          console.error('[invite] add_member_to_tenant (existing):', rpcErr.message)
          Sentry.captureException(rpcErr, { extra: { where: 'team.invite.add_existing', tenantId: m.tenant_id } })
          redirect('/dashboard/team?error=respuesta-inesperada')
        }
      } else {
        console.error('[invite] inviteUserByEmail error:', inviteError.message)
        Sentry.captureException(inviteError, { extra: { where: 'team.invite.inviteUserByEmail', tenantId: m.tenant_id } })
        const isRate = inviteError.message.toLowerCase().includes('rate') || inviteError.message.toLowerCase().includes('limit')
        redirect(`/dashboard/team?error=${isRate ? 'rate-limit' : 'respuesta-inesperada'}`)
      }
    } else if (inviteData?.user?.id) {
      addedUserId = inviteData.user.id
      const { error: rpcErr } = await adminSb.rpc('add_member_to_tenant', {
        p_user_id: inviteData.user.id, p_tenant_id: m.tenant_id, p_role: newRole,
      })
      if (rpcErr) {
        console.error('[invite] add_member_to_tenant (new):', rpcErr.message)
        Sentry.captureException(rpcErr, { extra: { where: 'team.invite.add_new', tenantId: m.tenant_id } })
        redirect('/dashboard/team?error=respuesta-inesperada')
      }
    } else {
      console.error('[invite] inviteUserByEmail returned no user and no error')
      Sentry.captureException(new Error('inviteUserByEmail returned no user and no error'), { extra: { where: 'team.invite', tenantId: m.tenant_id } })
      redirect('/dashboard/team?error=respuesta-inesperada')
    }

    await writeTeamAudit(sb, {
      tenantId: m.tenant_id, userId: u?.id ?? null, userEmail: u?.email ?? null,
      action: 'team.member_invited', entityId: addedUserId ?? email,
      payload: { email, role: newRole, was_existing_user: wasExistingUser },
    })

    revalidatePath('/dashboard/team')
    // Distinguir: usuario nuevo (email enviado) vs usuario existente (acceso directo, sin email)
    if (wasExistingUser) {
      redirect(`/dashboard/team?added=${encodeURIComponent(email)}`)
    }
    redirect(`/dashboard/team?invited=${encodeURIComponent(email)}`)
  }

  async function changeRole(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    // Claims stale / sesión sin permiso → feedback explícito (no cierre silencioso del dialog).
    if (!m.tenant_id || m.role !== 'owner') redirect('/dashboard/team?error=sin-permiso')
    const newRole  = formData.get('role') as string
    const targetId = formData.get('user_id') as string
    if (!['manager', 'operator'].includes(newRole)) redirect('/dashboard/team?error=rol-invalido')

    // Actualizar tenant_users — el Custom Access Token Hook leerá el nuevo rol en el próximo JWT.
    // .neq('role','owner') preserva el guard anti-degradar-al-último-owner: nunca se puede
    // cambiar (ni bajar) el rol de un owner desde esta acción.
    const { data: changed } = await sb.from('tenant_users')
      .update({ role: newRole })
      .eq('user_id', targetId)
      .eq('tenant_id', m.tenant_id)
      .neq('role', 'owner')
      .select('user_id')
    // F82: abortar si el target NO pertenece al tenant del caller (0 filas) ANTES de cualquier
    // op admin con service_role (global sobre auth.users, NO scoped por tenant → destrucción cross-tenant).
    if (!changed?.length) redirect('/dashboard/team?error=miembro-no-encontrado')

    // signOut fuerza al miembro a re-autenticarse → hook inyecta claims frescos de inmediato
    const adminSb = createAdminClient()
    await adminSb.auth.admin.signOut(targetId, 'global')

    await writeTeamAudit(sb, {
      tenantId: m.tenant_id, userId: u?.id ?? null, userEmail: u?.email ?? null,
      action: 'team.role_changed', entityId: targetId,
      payload: { new_role: newRole },
    })

    revalidatePath('/dashboard/team')
    redirect('/dashboard/team?role_changed=1')
  }

  async function removeMember(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') redirect('/dashboard/team?error=sin-permiso')

    const targetId = formData.get('user_id') as string

    // 1. Eliminar del tenant — el hook ya no inyectará tenant_id sin esta fila.
    //    .neq('role','owner') = guard anti-eliminar-al-owner.
    const { data: removed } = await sb.from('tenant_users').delete()
      .eq('user_id', targetId)
      .eq('tenant_id', m.tenant_id)
      .neq('role', 'owner')
      .select('user_id')
    // F82: abortar si el target NO pertenece al tenant del caller (0 filas) ANTES de las ops
    // admin service_role (deleteUser/signOut son globales sobre auth.users → destrucción cross-tenant).
    if (!removed?.length) redirect('/dashboard/team?error=miembro-no-encontrado')

    const adminSb = createAdminClient()

    // 2. signOut global — revoca sesión activa inmediatamente
    //    El hook ya no encontrará tenant_users activo → JWT sin tenant_id en próximo login
    await adminSb.auth.admin.signOut(targetId, 'global')

    // 3. Soft-delete en auth.users SOLO si el usuario ya no pertenece a ningún otro tenant.
    //    ADR-0030 impone membresía single-tenant (UNIQUE(user_id)) → en estado consistente
    //    nunca habrá otras membresías y este chequeo pasa a deleteUser. Se conserva como
    //    defensa en profundidad: si el migration aún no está aplicado y un usuario tuviera
    //    filas en otro tenant, deleteUser (global sobre auth.users) destruiría su cuenta allí;
    //    en ese caso solo lo desvinculamos de ESTE tenant.
    let accountDeleted = false
    const { data: otherMemberships } = await adminSb
      .from('tenant_users')
      .select('tenant_id')
      .eq('user_id', targetId)
      .limit(1)
    if (!otherMemberships?.length) {
      // Sin otras membresías → seguro anonimizar. Preserva el ID para audit trails.
      //    Si necesita volver, se le puede re-invitar (recibe nuevo enlace de onboarding).
      await adminSb.auth.admin.deleteUser(targetId, true)
      accountDeleted = true
    }

    await writeTeamAudit(sb, {
      tenantId: m.tenant_id, userId: u?.id ?? null, userEmail: u?.email ?? null,
      action: 'team.member_removed', entityId: targetId,
      payload: { account_soft_deleted: accountDeleted },
    })

    revalidatePath('/dashboard/team')
    redirect('/dashboard/team?removed=1')
  }

  async function inactivateMember(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') redirect('/dashboard/team?error=sin-permiso')

    const targetId = formData.get('user_id') as string
    const reason   = (formData.get('reason') as string)?.trim() || null

    // 1. Marcar como inactivo en tenant_users — el hook no inyectará claims
    const { data: inactivated } = await sb.from('tenant_users').update({
      status:             'inactive',
      inactivated_at:     new Date().toISOString(),
      inactivated_reason: reason,
      inactivated_by:     u!.id,
    }).eq('user_id', targetId).eq('tenant_id', m.tenant_id).neq('role', 'owner').select('user_id')
    // F82: abortar si el target NO pertenece al tenant del caller (0 filas) ANTES del ban
    // service_role (updateUserById es global sobre auth.users → ban cross-tenant).
    if (!inactivated?.length) redirect('/dashboard/team?error=miembro-no-encontrado')

    const adminSb = createAdminClient()

    // 2. Ban nativo de Supabase Auth — bloquea login y refresh de token
    //    "876600h" ≈ 100 años (ban indefinido reversible con ban_duration: 'none')
    await adminSb.auth.admin.updateUserById(targetId, {
      ban_duration: '876600h',
    })

    // 3. signOut global — corta la sesión activa inmediatamente (no esperar expiración del JWT)
    await adminSb.auth.admin.signOut(targetId, 'global')

    await writeTeamAudit(sb, {
      tenantId: m.tenant_id, userId: u?.id ?? null, userEmail: u?.email ?? null,
      action: 'team.member_inactivated', entityId: targetId,
      payload: { reason },
    })

    revalidatePath('/dashboard/team')
    redirect('/dashboard/team?inactivated=1')
  }

  async function activateMember(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') redirect('/dashboard/team?error=sin-permiso')

    const targetId = formData.get('user_id') as string

    // 1. Restaurar en tenant_users — el hook inyectará claims en próximo login
    const { data: activated } = await sb.from('tenant_users').update({
      status:             'active',
      inactivated_at:     null,
      inactivated_reason: null,
      inactivated_by:     null,
    }).eq('user_id', targetId).eq('tenant_id', m.tenant_id).select('user_id')
    // F82: abortar si el target NO pertenece al tenant del caller (0 filas) ANTES del unban
    // service_role (updateUserById es global sobre auth.users → unban cross-tenant).
    if (!activated?.length) redirect('/dashboard/team?error=miembro-no-encontrado')

    // 2. Levantar el ban nativo de Supabase Auth — permite login de nuevo
    const adminSb = createAdminClient()
    await adminSb.auth.admin.updateUserById(targetId, {
      ban_duration: 'none',
    })

    await writeTeamAudit(sb, {
      tenantId: m.tenant_id, userId: u?.id ?? null, userEmail: u?.email ?? null,
      action: 'team.member_activated', entityId: targetId,
      payload: {},
    })

    revalidatePath('/dashboard/team')
    redirect('/dashboard/team?activated=1')
  }

  async function resendInvite(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') {
      redirect('/dashboard/team?error=sin-permiso')
    }
    const email = (formData.get('email') as string)?.trim().toLowerCase()
    if (!email) redirect('/dashboard/team?error=datos-invalidos')

    // Cotejar el email contra el equipo del tenant: sin esto, un owner podría disparar
    // inviteUserByEmail a CUALQUIER dirección (crea usuarios auth huérfanos y convierte a
    // Konvi en remitente de spam/phishing). Solo se reenvía a miembros pendientes de aceptar.
    const { data: currentTeam } = await sb.rpc('get_tenant_team')
    const member = (currentTeam as Array<{ email: string; confirmed: boolean }> | null)
      ?.find(t => t.email.toLowerCase() === email)
    if (!member) redirect('/dashboard/team?error=miembro-no-encontrado')
    if (member!.confirmed) redirect('/dashboard/team?error=datos-invalidos')

    // Rate-limit aplicativo per-tenant (además del límite SMTP compartido).
    if (await inviteRateLimited(sb, m.tenant_id)) {
      redirect('/dashboard/team?error=rate-limit')
    }

    const appUrl  = WEB_APP_URL
    const adminSb = createAdminClient()

    // Reenvío branded: repone el nombre del negocio en la plantilla (mismo criterio que
    // la invitación inicial). {{ .Data.tenant_name }} en el template.
    const { data: tenantRow } = await sb.from('tenants').select('name').eq('id', m.tenant_id).single()
    const tenantName = tenantRow?.name ?? undefined

    // inviteUserByEmail para usuario NO confirmado = reenvía el email de invitación
    // generateLink() solo retorna el link sin enviar email — NO usar para reenvío
    const { error } = await adminSb.auth.admin.inviteUserByEmail(email, {
      redirectTo: `${appUrl}/auth/callback?next=/set-password`,
      data: { invited_by: u?.id, tenant_name: tenantName },
    })

    // "already been registered" solo ocurre para usuarios CONFIRMADOS
    // para no-confirmados, Supabase reenvía sin error
    if (error && !error.message.toLowerCase().includes('already')) {
      console.error('[resend] inviteUserByEmail:', error.message)
      Sentry.captureException(error, { extra: { where: 'team.resendInvite', tenantId: m.tenant_id } })
      const isRate = error.message.toLowerCase().includes('rate') || error.message.toLowerCase().includes('limit')
      redirect(`/dashboard/team?error=${isRate ? 'rate-limit' : 'respuesta-inesperada'}`)
    }

    await writeTeamAudit(sb, {
      tenantId: m.tenant_id, userId: u?.id ?? null, userEmail: u?.email ?? null,
      action: 'team.invite_resent', entityId: email,
      payload: { email },
    })

    revalidatePath('/dashboard/team')
    redirect(`/dashboard/team?resent=${encodeURIComponent(email)}`)
  }

  // ─── UI ───────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 max-w-7xl">

      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Users className="h-5 w-5 text-primary" />
          Usuarios y Acceso
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {team.length} {team.length === 1 ? 'miembro' : 'miembros'} con acceso a esta consola
        </p>
      </div>

      {/* Limpia la URL automáticamente después de 4s */}
      <TeamUrlCleaner hasResult={!!(searchParams.invited || searchParams.added || searchParams.removed || searchParams.inactivated || searchParams.activated || searchParams.error || searchParams.resent || searchParams.role_changed)} />

      {/* Banners resultado */}
      {searchParams.invited && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-emerald-700/30 bg-emerald-500/8 text-sm text-emerald-700">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Invitación enviada</p>
            <p className="text-xs text-emerald-700/70 mt-0.5">
              Se envió un email a <strong>{searchParams.invited}</strong> con el enlace de acceso.
              Si no llega en unos minutos, revisa la carpeta de spam o usa &quot;Reenviar&quot;.
            </p>
          </div>
        </div>
      )}
      {searchParams.added && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-emerald-700/30 bg-emerald-500/8 text-sm text-emerald-700">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Acceso otorgado</p>
            <p className="text-xs text-emerald-700/70 mt-0.5">
              <strong>{searchParams.added}</strong> ya tenía cuenta y fue agregado al equipo directamente.
              No se envió email — puede iniciar sesión ahora.
            </p>
          </div>
        </div>
      )}
      {searchParams.error && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-red-700/30 bg-red-500/8 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Error al procesar la acción</p>
            <p className="text-xs text-red-700/70 mt-0.5">{mapTeamError(decodeURIComponent(searchParams.error))}</p>
          </div>
        </div>
      )}
      {searchParams.inactivated && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-amber-700/30 bg-amber-500/8 text-sm text-amber-700">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Miembro inactivado</p>
            <p className="text-xs text-amber-700/70 mt-0.5">
              El acceso fue suspendido y la sesión cerrada. Puedes activarlo de nuevo cuando sea necesario.
            </p>
          </div>
        </div>
      )}
      {searchParams.activated && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-emerald-700/30 bg-emerald-500/8 text-sm text-emerald-700">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Miembro activado</p>
            <p className="text-xs text-emerald-700/70 mt-0.5">
              El acceso fue restaurado. El miembro podrá iniciar sesión nuevamente.
            </p>
          </div>
        </div>
      )}
      {searchParams.removed && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-emerald-700/30 bg-emerald-500/8 text-sm text-emerald-700">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Miembro eliminado</p>
            <p className="text-xs text-emerald-700/70 mt-0.5">
              El usuario fue removido del equipo y su sesión activa fue cerrada inmediatamente.
            </p>
          </div>
        </div>
      )}
      {searchParams.resent && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-emerald-700/30 bg-emerald-500/8 text-sm text-emerald-700">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Invitación reenviada</p>
            <p className="text-xs text-emerald-700/70 mt-0.5">{decodeURIComponent(searchParams.resent)} recibirá un nuevo email con enlace de acceso.</p>
          </div>
        </div>
      )}
      {searchParams.role_changed && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-blue-700/30 bg-blue-500/8 text-sm text-blue-700">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Rol actualizado</p>
            <p className="text-xs text-blue-700/70 mt-0.5">La sesión del miembro fue cerrada. Al iniciar sesión nuevamente tendrá el nuevo rol activo en su JWT.</p>
          </div>
        </div>
      )}

      {/* Roles del sistema — tarjetas visuales */}
      <Section icon={ShieldCheck} title="Roles del sistema" description="Define qué puede hacer cada miembro en la consola.">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {(Object.entries(ROLES) as [RoleKey, typeof ROLES[RoleKey]][]).map(([key, cfg]) => {
            const Icon = cfg.icon
            return (
              <div key={key} className={`rounded-xl border p-4 ${cfg.headerColor}`}>
                <div className="flex items-center gap-2 mb-2">
                  <Icon className={`h-4 w-4 shrink-0 ${cfg.iconColor}`} />
                  <p className={`text-sm font-semibold ${cfg.textColor}`}>{cfg.label}</p>
                  <span className="ml-auto text-xs text-muted-foreground font-mono">
                    {counts[key] ?? 0}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{cfg.description}</p>
              </div>
            )
          })}
        </div>
      </Section>

      {/* Invitar nuevo miembro — solo Owner */}
      {isOwner && (
        <Section icon={UserPlus} title="Invitar nuevo miembro"
          description="El usuario recibirá un email para crear su cuenta y acceder a esta consola.">
          <form action={inviteMember} className="space-y-4 max-w-md">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium">Email del nuevo miembro</Label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Mail className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                  <Input
                    id="invite-email"
                    name="email"
                    type="email"
                    placeholder="nombre@empresa.com"
                    required
                    autoComplete="off"
                    className="h-9 pl-8 text-sm"
                  />
                </div>
                <select
                  name="role"
                  defaultValue="operator"
                  aria-label="Rol del nuevo miembro"
                  className="text-xs rounded-lg border border-input bg-background px-2.5 h-9 focus:outline-hidden focus:ring-1 focus:ring-primary"
                >
                  <option value="manager">Supervisor</option>
                  <option value="operator">Gestor</option>
                </select>
              </div>
              <p className="text-xs text-muted-foreground">
                Solo Supervisor o Gestor. El rol Administrador es único por negocio y no puede invitarse.
              </p>
            </div>
            <SubmitButton size="sm" pendingText="Enviando..." savedText="¡Invitación enviada!" className="gap-1.5">
              <UserPlus className="h-3.5 w-3.5" />
              Enviar invitación
            </SubmitButton>
          </form>
        </Section>
      )}

      {/* Equipo */}
      <Section icon={Users} title="Equipo" description="Miembros del equipo — confirmados y pendientes de aceptar invitación.">
        {teamLoadFailed ? (
          // No mentir con "equipo vacío" cuando el RPC falló: estado de error explícito + retry.
          <div className="flex flex-col items-center text-center py-8 gap-3">
            <AlertCircle className="h-8 w-8 text-red-700/60" />
            <div>
              <p className="text-sm font-medium text-red-700">No se pudo cargar el equipo</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-sm">
                Hubo un problema al leer los miembros de tu equipo. Puede ser temporal; vuelve a intentarlo.
              </p>
            </div>
            <a
              href="/dashboard/team"
              className="inline-flex items-center gap-1.5 text-xs font-medium h-8 px-3 rounded-lg border border-border bg-card hover:bg-muted/40 transition-colors text-foreground"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Reintentar
            </a>
          </div>
        ) : team.length === 0 ? (
          <div className="text-center py-8">
            <Users className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">Aún no hay miembros registrados.</p>
            {isOwner && <p className="text-xs text-muted-foreground/60 mt-1">Usa el formulario de arriba para invitar al primer miembro.</p>}
          </div>
        ) : (
          <div className="divide-y divide-border">
            {team.map(m => {
              return (
                <div key={m.user_id} className="flex flex-col sm:flex-row sm:items-center gap-3 py-3">
                  {/* Avatar + info */}
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="h-8 w-8 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center text-xs font-bold text-primary shrink-0">
                      {m.email.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-medium text-sm truncate">{m.email}</p>
                        {/* Rol visible SIEMPRE — incluido pendiente e inactivo, para que el owner
                            vea (y pueda corregir vía re-invitación) qué rol tendrá cada miembro. */}
                        <RoleBadge role={m.role} />
                        {m.user_id === myUserId && (
                          <span className="text-[10px] text-muted-foreground border border-border rounded-full px-1.5 py-0.5 shrink-0">Tú</span>
                        )}
                        {!m.confirmed && (
                          <span className="text-[10px] font-medium text-amber-700 border border-amber-700/30 bg-amber-500/10 rounded-full px-1.5 py-0.5 shrink-0">
                            Pendiente
                          </span>
                        )}
                        {m.confirmed && m.status === 'inactive' && (
                          <span className="text-[10px] font-medium text-muted-foreground border border-border bg-muted/40 rounded-full px-1.5 py-0.5 shrink-0">
                            Inactivo
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Desde {new Date(m.joined_at).toLocaleDateString('es-CO', { timeZone: 'America/Bogota', day: '2-digit', month: 'short', year: 'numeric' })}
                      </p>
                    </div>
                  </div>

                  {/* Acciones según estado. Solo owners llegan a esta página (redirect arriba);
                      un owner no se auto-gestiona, y un segundo owner (m.role==='owner') no es
                      degradable/eliminable — guard anti-degradar-al-último-owner. */}
                  {isOwner && m.user_id !== myUserId && m.role !== 'owner' && (
                    <div className="flex items-center gap-2 pl-11 sm:pl-0">
                      {/* PENDIENTE: solo reenviar o eliminar */}
                      {!m.confirmed && (
                        <form action={resendInvite}>
                          <input type="hidden" name="email" value={m.email} />
                          <SubmitButton size="sm" variant="outline" pendingText="..." savedText="Enviado"
                            className="text-xs h-7 px-2.5 text-amber-700 border-amber-700/30 hover:bg-amber-500/10">
                            Reenviar
                          </SubmitButton>
                        </form>
                      )}

                      {/* INACTIVO: solo activar o eliminar */}
                      {m.confirmed && m.status === 'inactive' && (
                        <form action={activateMember}>
                          <input type="hidden" name="user_id" value={m.user_id} />
                          <SubmitButton size="sm" variant="outline" pendingText="..." savedText="Activado"
                            className="text-xs h-7 px-2.5 text-emerald-700 border-emerald-700/30 hover:bg-emerald-500/10">
                            Activar
                          </SubmitButton>
                        </form>
                      )}

                      {/* ACTIVO: cambiar rol + inactivar */}
                      {m.confirmed && m.status === 'active' && (
                        <>
                          <ChangeRoleButton
                            userId={m.user_id}
                            memberEmail={m.email}
                            currentRole={m.role}
                            action={changeRole}
                          />
                          <InactivateMemberButton
                            userId={m.user_id}
                            memberEmail={m.email}
                            action={inactivateMember}
                          />
                        </>
                      )}

                      {/* Eliminar — disponible para activo, inactivo y pendiente */}
                      <RemoveMemberButton
                        userId={m.user_id}
                        memberEmail={m.email}
                        action={removeMember}
                      />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Section>

    </div>
  )
}
