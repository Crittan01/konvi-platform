import { createClient } from '@/utils/supabase/server'
import { createAdminClient } from '@/utils/supabase/admin'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Users, ShieldCheck, UserPlus, Mail, AlertCircle, CheckCircle2 } from 'lucide-react'

export const metadata = {
  title: 'Usuarios y Acceso — Commerce Ops',
  description: 'Gestiona los miembros del equipo y sus roles de acceso a la consola del tenant.',
}

type TeamMember = { user_id: string; email: string; role: string; joined_at: string }

const ROLE_LABELS: Record<string, string> = {
  owner:   '👑 Owner',
  manager: '🛠️ Manager',
  agent:   '🎧 Agente',
}

const ROLE_COLORS: Record<string, string> = {
  owner:   'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  manager: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  agent:   'bg-muted text-muted-foreground border-border',
}

// ── Helpers de Section ────────────────────────────────────────────────────────

function Section({ icon: Icon, title, description, children }: {
  icon: React.ElementType; title: string; description?: string; children: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="px-5 py-4 border-b border-border bg-muted/20">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-primary" />
          <p className="font-semibold text-sm">{title}</p>
        </div>
        {description && <p className="text-xs text-muted-foreground mt-0.5 ml-6">{description}</p>}
      </div>
      <div className="p-5">{children}</div>
    </div>
  )
}

export default async function TeamPage({
  searchParams,
}: {
  searchParams: { invited?: string; error?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const isOwner = role === 'owner'
  const myUserId = user?.id

  let team: TeamMember[] = []

  if (tenantId) {
    const { data } = await supabase.rpc('get_tenant_team')
    team = (data as TeamMember[]) || []
  }

  // ── Server Actions ─────────────────────────────────────────────────────────

  /**
   * inviteMember — Server Action (Owner only)
   *
   * Flujo:
   * 1. Verifica caller es owner
   * 2. adminClient.auth.admin.inviteUserByEmail(email) → Supabase envía email de invitación
   * 3. Llama add_member_to_tenant(user_id, tenant_id, role) → trigger inyecta JWT claims
   * 4. Revalida la página
   *
   * Seguridad:
   * - Solo se ejecuta en SSR (Server Action) — nunca expuesto al cliente
   * - adminClient usa Service Role Key — bypasea RLS pero solo en este contexto controlado
   * - El tenant_id viene de app_metadata del usuario autenticado, nunca del form
   */
  async function inviteMember(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }

    // Guard: solo owner puede invitar
    if (!m.tenant_id || m.role !== 'owner') return

    const email    = (formData.get('email') as string)?.trim().toLowerCase()
    const newRole  = formData.get('role') as string

    if (!email || !['manager', 'agent'].includes(newRole)) return

    try {
      // Determinar redirectTo — URL del frontend en producción
      const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000'

      const adminSb = createAdminClient()

      // Invitar usuario — Supabase envía email con magic link
      const { data: inviteData, error: inviteError } = await adminSb.auth.admin.inviteUserByEmail(
        email,
        {
          redirectTo: `${appUrl}/auth/confirm`,
          data: {
            // Metadata adicional — el trigger lo leerá desde tenant_users
            invited_by: u?.id,
          },
        }
      )

      if (inviteError) {
        // Si ya existe el usuario, aún podemos asignarlo al tenant
        if (!inviteError.message.includes('already been registered')) {
          return // Error real — el feedback se ve en los searchParams
        }
        // Usuario ya existe — buscar su ID por email
        const { data: existingUsers } = await adminSb.auth.admin.listUsers()
        const existingUser = existingUsers?.users?.find(u => u.email === email)
        if (!existingUser) return

        // Asignar al tenant via función SECURITY DEFINER
        await adminSb.rpc('add_member_to_tenant', {
          p_user_id:   existingUser.id,
          p_tenant_id: m.tenant_id,
          p_role:      newRole,
        })
      } else if (inviteData?.user?.id) {
        // Usuario nuevo invitado — asignar al tenant
        await adminSb.rpc('add_member_to_tenant', {
          p_user_id:   inviteData.user.id,
          p_tenant_id: m.tenant_id,
          p_role:      newRole,
        })
      }

      revalidatePath('/dashboard/team')
    } catch {
      // Error silencioso — el usuario verá el estado en la UI
    }
  }

  async function changeRole(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    await sb.from('tenant_users').update({ role: formData.get('role') as string })
      .eq('user_id', formData.get('user_id') as string).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/team')
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
      .neq('role', 'owner')  // Guard: nunca eliminar al owner
    revalidatePath('/dashboard/team')
  }

  // ── UI ─────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-3xl">

      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Users className="h-5 w-5 text-primary" /> Usuarios y Acceso
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Miembros con acceso a esta consola · {team.length} {team.length === 1 ? 'usuario' : 'usuarios'}
        </p>
      </div>

      {/* Banners de resultado */}
      {searchParams.invited && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-green-500/30 bg-green-500/10 text-sm text-green-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Invitación enviada a <strong>{searchParams.invited}</strong>. El usuario recibirá un email para activar su acceso.
        </div>
      )}
      {searchParams.error && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {searchParams.error}
        </div>
      )}

      {/* Roles disponibles */}
      <Section icon={ShieldCheck} title="Roles del sistema" description="Cada rol controla el acceso a módulos y acciones dentro de la consola.">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-3">
            <p className="text-xs font-semibold text-yellow-400 mb-1">👑 Owner</p>
            <p className="text-xs text-muted-foreground">Acceso total. Configura integraciones, equipo y datos del negocio.</p>
          </div>
          <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-3">
            <p className="text-xs font-semibold text-blue-400 mb-1">🛠️ Manager</p>
            <p className="text-xs text-muted-foreground">Gestiona operaciones: pedidos, catálogo, inventario, métricas.</p>
          </div>
          <div className="rounded-lg border border-border bg-muted/20 p-3">
            <p className="text-xs font-semibold text-muted-foreground mb-1">🎧 Agente</p>
            <p className="text-xs text-muted-foreground">Solo acceso a Inbox, Pedidos, Contactos y Reclamos.</p>
          </div>
        </div>
      </Section>

      {/* Invite nuevo miembro — solo Owner */}
      {isOwner && (
        <Section icon={UserPlus} title="Invitar nuevo miembro" description="El usuario recibirá un email para crear su cuenta y acceder a esta consola.">
          <form action={inviteMember} className="space-y-4 max-w-md">
            <div className="space-y-1">
              <Label className="text-xs">Email del nuevo miembro</Label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Mail className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    name="email"
                    type="email"
                    placeholder="agente@mitienda.com"
                    required
                    className="h-9 pl-8 text-sm"
                  />
                </div>
                <select
                  name="role"
                  defaultValue="agent"
                  className="text-xs rounded-lg border border-input bg-background px-2.5 h-9 focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="manager">Manager</option>
                  <option value="agent">Agente</option>
                </select>
              </div>
              <p className="text-xs text-muted-foreground">
                Solo puedes invitar como Manager o Agente. El rol Owner es único por tenant.
              </p>
            </div>
            <Button type="submit" size="sm" className="gap-1.5">
              <UserPlus className="h-3.5 w-3.5" />
              Enviar invitación
            </Button>
          </form>
        </Section>
      )}

      {/* Lista de miembros activos */}
      <Section icon={Users} title="Equipo activo" description="Miembros con acceso confirmado a este tenant.">
        <div className="space-y-1">
          {team.length === 0 && (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No hay miembros registrados. Invita al primer miembro arriba.
            </p>
          )}
          {team.map(m => (
            <div key={m.user_id}
              className="flex flex-col sm:flex-row sm:items-center justify-between py-3 border-b border-border last:border-0 gap-2">
              <div>
                <div className="flex items-center gap-2">
                  <div className="h-7 w-7 rounded-full bg-primary/15 flex items-center justify-center text-xs font-bold text-primary">
                    {m.email.charAt(0).toUpperCase()}
                  </div>
                  <p className="font-medium text-sm">{m.email}</p>
                  {m.user_id === myUserId && (
                    <span className="text-[11px] text-muted-foreground border border-border rounded-full px-2 py-0.5">Tú</span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground ml-9 mt-0.5">
                  Desde {new Date(m.joined_at).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })}
                </p>
              </div>

              <div className="flex items-center gap-2 ml-9 sm:ml-0">
                {isOwner && m.user_id !== myUserId ? (
                  <>
                    <form action={changeRole} className="flex items-center gap-1.5">
                      <input type="hidden" name="user_id" value={m.user_id} />
                      <select name="role" defaultValue={m.role}
                        className="text-xs rounded-lg border border-input bg-background px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary">
                        <option value="owner">Owner</option>
                        <option value="manager">Manager</option>
                        <option value="agent">Agente</option>
                      </select>
                      <Button type="submit" size="sm" variant="outline" className="text-xs h-7">Cambiar</Button>
                    </form>
                    {m.role !== 'owner' && (
                      <form action={removeMember}>
                        <input type="hidden" name="user_id" value={m.user_id} />
                        <Button type="submit" size="sm" variant="ghost"
                          className="text-xs h-7 text-destructive hover:text-destructive hover:bg-destructive/10">
                          Eliminar
                        </Button>
                      </form>
                    )}
                  </>
                ) : (
                  <span className={`text-[11px] font-medium px-2.5 py-1 rounded-full border ${ROLE_COLORS[m.role] ?? 'bg-muted text-muted-foreground border-border'}`}>
                    {ROLE_LABELS[m.role] ?? m.role}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </Section>

    </div>
  )
}
