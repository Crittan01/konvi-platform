import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Users, ShieldCheck } from 'lucide-react'

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

export const metadata = {
  title: 'Usuarios y Acceso — Commerce Ops',
  description: 'Gestiona los miembros del equipo y sus roles de acceso a la consola del tenant.',
}

export default async function TeamPage() {
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
      .neq('role', 'owner')
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

      {/* Roles disponibles */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-5 py-4 border-b border-border bg-muted/20">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <p className="font-semibold text-sm">Roles del sistema</p>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 ml-6">
            Cada rol controla el acceso a módulos y acciones dentro de la consola.
          </p>
        </div>
        <div className="p-5 grid grid-cols-1 sm:grid-cols-3 gap-3">
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
      </div>

      {/* Lista de miembros */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-5 py-4 border-b border-border bg-muted/20">
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-primary" />
            <p className="font-semibold text-sm">Equipo activo</p>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 ml-6">
            Miembros con acceso confirmado a este tenant.
          </p>
        </div>
        <div className="p-5 space-y-1">
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

          {isOwner && (
            <p className="text-xs text-muted-foreground pt-3">
              💡 Para invitar nuevos miembros, crea su cuenta en Supabase Auth y asígnala al tenant mediante la función <code className="font-mono">get_tenant_team</code>.
            </p>
          )}
        </div>
      </div>

    </div>
  )
}
