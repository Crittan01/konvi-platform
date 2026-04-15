import { createClient } from '@/utils/supabase/server'
import { createAdminClient } from '@/utils/supabase/admin'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Users, ShieldCheck, UserPlus, Mail, AlertCircle, CheckCircle2, Crown, Briefcase, Headphones } from 'lucide-react'

export const metadata = {
  title: 'Usuarios y Acceso — Commerce Ops',
  description: 'Gestiona los miembros del equipo y sus roles de acceso a la consola del tenant.',
}

// ─── Tipos ───────────────────────────────────────────────────────────────────

type TeamMember = { user_id: string; email: string; role: string; joined_at: string; confirmed: boolean }

// ─── Configuración de Roles ───────────────────────────────────────────────────
//
// "Operador" reemplaza "Agente" para evitar confusión con "Agente IA"
// del módulo IA y Conocimiento.
//
const ROLES = {
  owner: {
    label: 'Administrador',
    icon: Crown,
    color: 'bg-amber-500/10 text-amber-400 border-amber-500/25',
    headerColor: 'border-amber-500/20 bg-amber-500/5',
    textColor: 'text-amber-400',
    iconColor: 'text-amber-400',
    description: 'Acceso total. Configura integraciones, equipo y datos del negocio.',
  },
  manager: {
    label: 'Supervisor',
    icon: Briefcase,
    color: 'bg-blue-500/10 text-blue-400 border-blue-500/25',
    headerColor: 'border-blue-500/20 bg-blue-500/5',
    textColor: 'text-blue-400',
    iconColor: 'text-blue-400',
    description: 'Gestiona operaciones: pedidos, catálogo, inventario, métricas, IA.',
  },
  operator: {
    label: 'Gestor',
    icon: Headphones,
    color: 'bg-slate-500/10 text-slate-400 border-slate-500/25',
    headerColor: 'border-border bg-muted/20',
    textColor: 'text-muted-foreground',
    iconColor: 'text-muted-foreground',
    description: 'Acceso operativo: Inbox, Pedidos, Contactos y Reclamos.',
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

// ─── Página ───────────────────────────────────────────────────────────────────

export default async function TeamPage({
  searchParams,
}: {
  searchParams: { invited?: string; error?: string; tab?: string; resent?: string; role_changed?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const isOwner = role === 'owner'
  const myUserId = user?.id

  let team: TeamMember[] = []
  if (tenantId) {
    const { data, error: teamErr } = await supabase.rpc('get_tenant_team')
    if (teamErr) console.error('[team] get_tenant_team:', teamErr.message, teamErr.code)
    team = (data as TeamMember[]) || []
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
   * Flujo: adminClient.inviteUserByEmail → add_member_to_tenant → trigger inyecta JWT claims
   * El tenant_id viene del JWT del caller, nunca del form.
   */
  async function inviteMember(formData: FormData) {
    'use server'
    const sb = createClient()
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

    // APP_URL (sin prefijo NEXT_PUBLIC_) = variable de runtime, no baked en el build
    const appUrl  = process.env.APP_URL ?? 'https://commerce-ops-web.onrender.com'
    const adminSb = createAdminClient()

    const { data: inviteData, error: inviteError } = await adminSb.auth.admin.inviteUserByEmail(
      email,
      { redirectTo: `${appUrl}/auth/confirm?next=/set-password`, data: { invited_by: u?.id } }
    )

    if (inviteError) {
      // Usuario ya existente en Supabase Auth — asignar directamente al tenant
      if (inviteError.message.includes('already been registered')) {
        const { data: list, error: listError } = await adminSb.auth.admin.listUsers()
        if (listError) {
          console.error('[invite] listUsers error:', listError.message)
          redirect(`/dashboard/team?error=${encodeURIComponent(listError.message)}`)
        }
        const existing = list?.users?.find(x => x.email === email)
        if (!existing) {
          redirect('/dashboard/team?error=usuario-no-encontrado')
        }
        const { error: rpcErr } = await adminSb.rpc('add_member_to_tenant', {
          p_user_id: existing!.id, p_tenant_id: m.tenant_id, p_role: newRole,
        })
        if (rpcErr) {
          console.error('[invite] add_member_to_tenant (existing):', rpcErr.message)
          redirect(`/dashboard/team?error=${encodeURIComponent(rpcErr.message)}`)
        }
      } else {
        console.error('[invite] inviteUserByEmail error:', inviteError.message)
        redirect(`/dashboard/team?error=${encodeURIComponent(inviteError.message)}`)
      }
    } else if (inviteData?.user?.id) {
      const { error: rpcErr } = await adminSb.rpc('add_member_to_tenant', {
        p_user_id: inviteData.user.id, p_tenant_id: m.tenant_id, p_role: newRole,
      })
      if (rpcErr) {
        console.error('[invite] add_member_to_tenant (new):', rpcErr.message)
        redirect(`/dashboard/team?error=${encodeURIComponent(rpcErr.message)}`)
      }
    } else {
      console.error('[invite] inviteUserByEmail returned no user and no error')
      redirect('/dashboard/team?error=respuesta-inesperada')
    }

    revalidatePath('/dashboard/team')
    redirect(`/dashboard/team?invited=${encodeURIComponent(email)}`)
  }

  async function changeRole(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const newRole    = formData.get('role') as string
    const targetId   = formData.get('user_id') as string
    // Guard: owner es único por tenant — no puede asignarse por esta vía
    if (!['manager', 'operator'].includes(newRole)) return
    await sb.from('tenant_users')
      .update({ role: newRole })
      .eq('user_id', targetId)
      .eq('tenant_id', m.tenant_id)
      .neq('role', 'owner') // guard DB: nunca cambiar al propio owner
    // Invalidar sesión del miembro para forzar JWT fresco con el nuevo rol.
    // Sin esto, el usuario mantiene claims viejos hasta que el access token expire (~1h).
    const adminSb = createAdminClient()
    await adminSb.auth.admin.signOut(targetId, 'global')
    revalidatePath('/dashboard/team')
    redirect('/dashboard/team?role_changed=1')
  }

  async function removeMember(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    await sb.from('tenant_users').delete()
      .eq('user_id', formData.get('user_id') as string)
      .eq('tenant_id', m.tenant_id)
      .neq('role', 'owner') // guard: nunca eliminar owner
    revalidatePath('/dashboard/team')
  }

  async function resendInvite(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') {
      redirect('/dashboard/team?error=sin-permiso')
    }
    const email   = formData.get('email') as string
    const appUrl  = process.env.APP_URL ?? 'https://commerce-ops-web.onrender.com'
    const adminSb = createAdminClient()

    // inviteUserByEmail para usuario NO confirmado = reenvía el email de invitación
    // generateLink() solo retorna el link sin enviar email — NO usar para reenvío
    const { error } = await adminSb.auth.admin.inviteUserByEmail(email, {
      redirectTo: `${appUrl}/auth/confirm?next=/set-password`,
    })

    // "already been registered" solo ocurre para usuarios CONFIRMADOS
    // para no-confirmados, Supabase reenvía sin error
    if (error && !error.message.toLowerCase().includes('already')) {
      console.error('[resend] inviteUserByEmail:', error.message)
      redirect(`/dashboard/team?error=${encodeURIComponent(error.message)}`)
    }
    revalidatePath('/dashboard/team')
    redirect(`/dashboard/team?resent=${encodeURIComponent(email)}`)
  }

  // ─── UI ───────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 max-w-3xl">

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

      {/* Banners resultado */}
      {searchParams.invited && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-emerald-500/30 bg-emerald-500/8 text-sm text-emerald-400">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Invitación enviada</p>
            <p className="text-xs text-emerald-400/70 mt-0.5">
              Se envió un email a <strong>{searchParams.invited}</strong> con el enlace de acceso.
            </p>
          </div>
        </div>
      )}
      {searchParams.error && (() => {
        const raw = decodeURIComponent(searchParams.error).toLowerCase()
        const msg = raw.includes('rate') || raw.includes('limit')
          ? 'Demasiados intentos. Espera unos minutos antes de reenviar otra invitación. En producción, configura un SMTP propio en Supabase para eliminar este límite.'
          : raw.includes('sin-permiso') || raw.includes('permission')
          ? 'No tienes permiso para realizar esta acción.'
          : raw.includes('datos-invalidos')
          ? 'Email o rol inválido. Verifica los datos e inténtalo de nuevo.'
          : decodeURIComponent(searchParams.error)

        return (
          <div className="flex items-start gap-3 p-4 rounded-xl border border-red-500/30 bg-red-500/8 text-sm text-red-400">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">Error al procesar la acción</p>
              <p className="text-xs text-red-400/70 mt-0.5">{msg}</p>
            </div>
          </div>
        )
      })()}
      {searchParams.resent && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-emerald-500/30 bg-emerald-500/8 text-sm text-emerald-400">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Invitación reenviada</p>
            <p className="text-xs text-emerald-400/70 mt-0.5">{decodeURIComponent(searchParams.resent)} recibirá un nuevo email con enlace de acceso.</p>
          </div>
        </div>
      )}
      {searchParams.role_changed && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-blue-500/30 bg-blue-500/8 text-sm text-blue-400">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Rol actualizado</p>
            <p className="text-xs text-blue-400/70 mt-0.5">La sesión del miembro fue cerrada. Al iniciar sesión nuevamente tendrá el nuevo rol activo en su JWT.</p>
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
                  className="text-xs rounded-lg border border-input bg-background px-2.5 h-9 focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="manager">Supervisor</option>
                  <option value="operator">Gestor</option>
                </select>
              </div>
              <p className="text-xs text-muted-foreground">
                Solo Supervisor o Gestor. El rol Administrador es único por negocio y no puede invitarse.
              </p>
            </div>
            <Button type="submit" size="sm" className="gap-1.5">
              <UserPlus className="h-3.5 w-3.5" />
              Enviar invitación
            </Button>
          </form>
        </Section>
      )}

      {/* Equipo */}
      <Section icon={Users} title="Equipo" description="Miembros del equipo — confirmados y pendientes de aceptar invitación.">
        {team.length === 0 ? (
          <div className="text-center py-8">
            <Users className="h-8 w-8 text-muted-foreground/30 mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">Aún no hay miembros registrados.</p>
            {isOwner && <p className="text-xs text-muted-foreground/60 mt-1">Usa el formulario de arriba para invitar al primer miembro.</p>}
          </div>
        ) : (
          <div className="divide-y divide-border">
            {team.map(m => {
              const roleCfg = ROLES[m.role as RoleKey]
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
                        {m.user_id === myUserId && (
                          <span className="text-[10px] text-muted-foreground border border-border rounded-full px-1.5 py-0.5 shrink-0">Tú</span>
                        )}
                        {!m.confirmed && (
                          <span className="text-[10px] font-medium text-amber-400 border border-amber-500/30 bg-amber-500/10 rounded-full px-1.5 py-0.5 shrink-0">
                            Pendiente
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Desde {new Date(m.joined_at).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })}
                      </p>
                    </div>
                  </div>

                  {/* Acciones */}
                  <div className="flex items-center gap-2 pl-11 sm:pl-0">
                    {isOwner && m.user_id !== myUserId ? (
                      <>
                        {/* Reenviar invitación — solo para pendientes */}
                        {!m.confirmed && (
                          <form action={resendInvite}>
                            <input type="hidden" name="email" value={m.email} />
                            <Button type="submit" size="sm" variant="outline"
                              className="text-xs h-7 px-2.5 text-amber-400 border-amber-500/30 hover:bg-amber-500/10">
                              Reenviar
                            </Button>
                          </form>
                        )}
                        <form action={changeRole} className="flex items-center gap-1.5">
                          <input type="hidden" name="user_id" value={m.user_id} />
                          <select
                            name="role"
                            defaultValue={m.role === 'owner' ? 'manager' : m.role}
                            className="text-xs rounded-lg border border-input bg-background px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
                          >
                            <option value="manager">Supervisor</option>
                            <option value="operator">Gestor</option>
                          </select>
                          <Button type="submit" size="sm" variant="outline" className="text-xs h-7 px-2.5">Cambiar</Button>
                        </form>
                        {m.role !== 'owner' && (
                          <form action={removeMember}>
                            <input type="hidden" name="user_id" value={m.user_id} />
                            <Button type="submit" size="sm" variant="ghost"
                              className="text-xs h-7 px-2 text-destructive hover:bg-destructive/10">
                              Eliminar
                            </Button>
                          </form>
                        )}
                      </>
                    ) : (
                      <RoleBadge role={m.role} />
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Section>

    </div>
  )
}
