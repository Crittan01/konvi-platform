import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Settings, Users, Truck, Bell, ShieldCheck, Building2 } from 'lucide-react'
import LogoUpload from './logo-upload'

type TeamMember    = { user_id: string; email: string; role: string; joined_at: string }
type ShippingOrigin = {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string
}
type Tenant = {
  id: string; name: string; meta_waba_id: string | null; status: string
  shipping_origin?: ShippingOrigin | null; logo_url?: string | null
}
type NotifSetting = { channel: string; enabled: boolean; config: Record<string, string> }

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

function Section({ icon: Icon, title, description, children }: {
  icon: React.ElementType
  title: string
  description?: string
  children: React.ReactNode
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

export default async function SettingsPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const isOwner  = role === 'owner'
  const canWrite = role === 'owner' || role === 'manager'

  let tenant: Tenant | null = null
  let team: TeamMember[] = []
  let notifications: NotifSetting[] = []

  if (tenantId) {
    const [tenantRes, teamRes, notifRes] = await Promise.all([
      supabase.from('tenants').select('id, name, meta_waba_id, status, shipping_origin, logo_url').eq('id', tenantId).single(),
      supabase.rpc('get_tenant_team'),
      supabase.from('notification_settings').select('channel, enabled, config').eq('tenant_id', tenantId),
    ])
    tenant        = tenantRes.data as Tenant
    team          = (teamRes.data as TeamMember[]) || []
    notifications = (notifRes.data as NotifSetting[]) || []
  }

  const telegramConfig = notifications.find(n => n.channel === 'telegram')
  const myUserId = user?.id

  // ── Server Actions ─────────────────────────────────────────────────────────

  async function saveTenant(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    await sb.from('tenants').update({ name: formData.get('name') as string }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/settings')
  }

  async function changeRole(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    await sb.from('tenant_users').update({ role: formData.get('role') as string })
      .eq('user_id', formData.get('user_id') as string).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/settings')
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
    revalidatePath('/dashboard/settings')
  }

  async function saveShippingOrigin(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const origin: Record<string, string> = {}
    for (const field of ['name', 'company', 'street', 'city', 'state', 'postal_code', 'country', 'phone']) {
      const val = formData.get(`origin_${field}`) as string
      if (val?.trim()) origin[field] = val.trim()
    }
    await sb.from('tenants').update({ shipping_origin: origin }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/settings')
  }

  async function saveTelegram(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('notification_settings').upsert({
      tenant_id: m.tenant_id,
      channel: 'telegram',
      enabled: formData.get('enabled') === 'on',
      config: {
        bot_token: formData.get('bot_token') as string || '',
        chat_id:   formData.get('chat_id') as string || '',
      },
    }, { onConflict: 'tenant_id,channel' })
    revalidatePath('/dashboard/settings')
  }

  // ── UI ─────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-4xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Settings className="h-5 w-5 text-primary" /> Configuración
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5 capitalize">
            {tenant?.name ?? '—'} · {role}
          </p>
        </div>
      </div>

      {/* ── Información del Tenant ── */}
      <Section icon={Building2} title="Información del negocio" description="Datos básicos de tu organización en la plataforma.">
        {isOwner ? (
          <div className="space-y-5 max-w-md">
            {/* Logo */}
            {tenant && (
              <div className="space-y-1.5">
                <Label className="text-xs">Logo del negocio</Label>
                <LogoUpload tenantId={tenant.id} currentLogoUrl={tenant.logo_url ?? null} />
              </div>
            )}
            <form action={saveTenant} className="space-y-3">
              <div className="space-y-1">
                <Label className="text-xs">Nombre del negocio</Label>
                <Input name="name" defaultValue={tenant?.name ?? ''} required className="h-9" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">WABA ID (Meta)</Label>
                <Input value={tenant?.meta_waba_id ?? 'No configurado'} readOnly className="h-9 bg-muted text-muted-foreground font-mono text-sm" />
                <p className="text-xs text-muted-foreground">Para cambiar el WABA ID contacta a soporte.</p>
              </div>
              <Button type="submit" size="sm">Guardar nombre</Button>
            </form>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 max-w-md">
            <div>
              <p className="text-xs text-muted-foreground mb-0.5">Nombre</p>
              <p className="font-medium text-sm">{tenant?.name}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-0.5">WABA ID</p>
              <p className="font-mono text-sm">{tenant?.meta_waba_id ?? '—'}</p>
            </div>
          </div>
        )}
      </Section>

      {/* ── Equipo ── */}
      <Section icon={Users} title="Equipo" description="Miembros con acceso a esta consola de operaciones.">
        <div className="space-y-1">
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
              💡 Para invitar nuevos miembros, crea su cuenta en Supabase Auth y asígnala al tenant. (IH — pendiente de automatizar.)
            </p>
          )}
        </div>
      </Section>

      {/* ── Dirección de origen ── */}
      {isOwner && (
        <Section icon={Truck} title="Dirección de origen — Envíos"
          description="Dirección desde la que se despachan los pedidos. Default en cotizaciones Envia.">
          <form action={saveShippingOrigin} className="space-y-4 max-w-xl">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Nombre del remitente</Label>
                <Input name="origin_name" defaultValue={tenant?.shipping_origin?.name ?? ''} placeholder="Juan Pérez" className="h-8 text-sm" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Empresa</Label>
                <Input name="origin_company" defaultValue={tenant?.shipping_origin?.company ?? ''} placeholder="Mi Tienda S.A." className="h-8 text-sm" />
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Calle y número</Label>
              <Input name="origin_street" defaultValue={tenant?.shipping_origin?.street ?? ''} placeholder="Av. Insurgentes 123, Col. Roma" className="h-8 text-sm" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Ciudad</Label>
                <Input name="origin_city" defaultValue={tenant?.shipping_origin?.city ?? ''} placeholder="Ciudad de México" className="h-8 text-sm" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Estado / Departamento</Label>
                <Input name="origin_state" defaultValue={tenant?.shipping_origin?.state ?? ''} placeholder="CDMX" className="h-8 text-sm" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Código postal</Label>
                <Input name="origin_postal_code" defaultValue={tenant?.shipping_origin?.postal_code ?? ''} placeholder="06600" className="h-8 text-sm" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">País (ISO)</Label>
                <Input name="origin_country" defaultValue={tenant?.shipping_origin?.country ?? 'MX'} placeholder="MX" maxLength={2} className="h-8 text-sm" />
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Teléfono de contacto</Label>
              <Input name="origin_phone" defaultValue={tenant?.shipping_origin?.phone ?? ''} placeholder="+525512345678" className="h-8 text-sm" />
            </div>
            {tenant?.shipping_origin && (
              <p className="text-xs text-emerald-400 flex items-center gap-1">
                <ShieldCheck className="h-3 w-3" /> Dirección guardada correctamente
              </p>
            )}
            <Button type="submit" size="sm">Guardar dirección</Button>
          </form>
        </Section>
      )}

      {/* ── Notificaciones ── */}
      {canWrite && (
        <Section icon={Bell} title="Notificaciones — Telegram"
          description="Alertas operacionales enviadas a tu canal de Telegram.">
          <form action={saveTelegram} className="space-y-4 max-w-md">
            <label className="flex items-center gap-2.5 cursor-pointer">
              <input type="checkbox" name="enabled" id="tg_enabled"
                defaultChecked={telegramConfig?.enabled ?? false} className="h-4 w-4 rounded" />
              <span className="text-sm">Habilitar alertas por Telegram</span>
            </label>
            <div className="space-y-1">
              <Label className="text-xs">Bot Token</Label>
              <Input name="bot_token" type="password" placeholder="123456:ABC-DEF..."
                defaultValue={telegramConfig?.config?.bot_token ?? ''} className="h-9 text-sm" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Chat ID</Label>
              <Input name="chat_id" placeholder="-100123456789"
                defaultValue={telegramConfig?.config?.chat_id ?? ''} className="h-9 text-sm" />
              <p className="text-xs text-muted-foreground">
                El Chat ID puede ser un grupo (-100xxx) o un canal. Usa @userinfobot para obtenerlo.
              </p>
            </div>
            <Button type="submit" size="sm">Guardar Telegram</Button>
          </form>
        </Section>
      )}
    </div>
  )
}
