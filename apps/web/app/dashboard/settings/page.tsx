import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import LogoUpload from './logo-upload'

type TeamMember = { user_id: string; email: string; role: string; joined_at: string }
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
  owner: 'Owner',
  manager: 'Manager',
  agent: 'Agente',
}

export default async function SettingsPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const isOwner = role === 'owner'
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
    tenant = tenantRes.data as Tenant
    team = (teamRes.data as TeamMember[]) || []
    notifications = (notifRes.data as NotifSetting[]) || []
  }

  const telegramConfig = notifications.find(n => n.channel === 'telegram')
  const myUserId = user?.id

  // ── Server Actions ────────────────────────────────────────────────────────

  async function saveTenant(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    await sb.from('tenants').update({
      name: formData.get('name') as string,
    }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/settings')
  }

  async function changeRole(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    await sb.from('tenant_users').update({
      role: formData.get('role') as string,
    })
      .eq('user_id', formData.get('user_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/settings')
  }

  async function removeMember(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    await sb.from('tenant_users')
      .delete()
      .eq('user_id', formData.get('user_id') as string)
      .eq('tenant_id', m.tenant_id)
      .neq('role', 'owner')
    revalidatePath('/dashboard/settings')
  }

  async function saveShippingOrigin(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
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
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    await sb.from('notification_settings').upsert({
      tenant_id: m.tenant_id,
      channel: 'telegram',
      enabled: formData.get('enabled') === 'on',
      config: {
        bot_token: formData.get('bot_token') as string || '',
        chat_id: formData.get('chat_id') as string || '',
      },
    }, { onConflict: 'tenant_id,channel' })
    revalidatePath('/dashboard/settings')
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Configuración</h1>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      {/* Sección: Tenant */}
      <Card>
        <CardHeader>
          <CardTitle>Información del Tenant</CardTitle>
          <CardDescription>Datos básicos de tu organización en la plataforma.</CardDescription>
        </CardHeader>
        <CardContent>
          {isOwner ? (
            <div className="space-y-6 max-w-md">
              {/* Logo */}
              <div className="space-y-2">
                <Label>Logo del negocio</Label>
                {tenant && (
                <LogoUpload tenantId={tenant.id} currentLogoUrl={tenant.logo_url ?? null} />
              )}
              </div>

              <form action={saveTenant} className="space-y-4">
                <div className="space-y-2">
                  <Label>Nombre del negocio</Label>
                  <Input name="name" defaultValue={tenant?.name ?? ''} required />
                </div>
                <div className="space-y-2">
                  <Label>WABA ID (Meta)</Label>
                  <Input value={tenant?.meta_waba_id ?? 'No configurado'} readOnly className="bg-muted" />
                  <p className="text-xs text-muted-foreground">Para cambiar el WABA ID contacta a soporte.</p>
                </div>
                <Button type="submit">Guardar nombre</Button>
              </form>
            </div>
          ) : (
            <div className="space-y-3 max-w-md">
              <div>
                <p className="text-sm font-medium text-muted-foreground">Nombre</p>
                <p className="font-medium">{tenant?.name}</p>
              </div>
              <div>
                <p className="text-sm font-medium text-muted-foreground">WABA ID</p>
                <p className="font-mono text-sm">{tenant?.meta_waba_id ?? '—'}</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sección: Equipo */}
      <Card>
        <CardHeader>
          <CardTitle>Equipo</CardTitle>
          <CardDescription>Miembros con acceso a esta consola.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {team.map((m) => (
              <div key={m.user_id} className="flex items-center justify-between py-2 border-b last:border-0">
                <div>
                  <p className="font-medium text-sm">{m.email}</p>
                  <p className="text-xs text-muted-foreground">
                    Desde {new Date(m.joined_at).toLocaleDateString('es-MX')}
                    {m.user_id === myUserId && ' · Tú'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {isOwner && m.user_id !== myUserId ? (
                    <>
                      <form action={changeRole} className="flex items-center gap-1">
                        <input type="hidden" name="user_id" value={m.user_id} />
                        <select
                          name="role"
                          defaultValue={m.role}
                          className="text-xs rounded border border-input bg-background px-2 py-1"
                        >
                          <option value="owner">Owner</option>
                          <option value="manager">Manager</option>
                          <option value="agent">Agente</option>
                        </select>
                        <Button type="submit" size="sm" variant="outline" className="text-xs h-7">
                          Cambiar
                        </Button>
                      </form>
                      {m.role !== 'owner' && (
                        <form action={removeMember}>
                          <input type="hidden" name="user_id" value={m.user_id} />
                          <Button type="submit" size="sm" variant="ghost" className="text-xs h-7 text-destructive hover:text-destructive">
                            Eliminar
                          </Button>
                        </form>
                      )}
                    </>
                  ) : (
                    <Badge variant="secondary" className="text-xs">
                      {ROLE_LABELS[m.role] ?? m.role}
                    </Badge>
                  )}
                </div>
              </div>
            ))}
            {isOwner && (
              <p className="text-xs text-muted-foreground pt-2">
                Para invitar nuevos miembros, crea su cuenta en Supabase Auth y asígnala al tenant. (IH — pendiente de automatizar en Fase 11.)
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Sección: Dirección de origen (envíos) */}
      {isOwner && (
        <Card>
          <CardHeader>
            <CardTitle>Dirección de origen — Envíos</CardTitle>
            <CardDescription>
              Dirección desde la que se despachan los pedidos. Se usa como default en las cotizaciones de Envia.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form action={saveShippingOrigin} className="space-y-4 max-w-md">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>Nombre del remitente</Label>
                  <Input name="origin_name" defaultValue={tenant?.shipping_origin?.name ?? ''} placeholder="Juan Pérez" />
                </div>
                <div className="space-y-2">
                  <Label>Empresa</Label>
                  <Input name="origin_company" defaultValue={tenant?.shipping_origin?.company ?? ''} placeholder="Mi Tienda S.A." />
                </div>
              </div>
              <div className="space-y-2">
                <Label>Calle y número</Label>
                <Input name="origin_street" defaultValue={tenant?.shipping_origin?.street ?? ''} placeholder="Av. Insurgentes 123, Col. Roma" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>Ciudad</Label>
                  <Input name="origin_city" defaultValue={tenant?.shipping_origin?.city ?? ''} placeholder="Ciudad de México" />
                </div>
                <div className="space-y-2">
                  <Label>Estado / Departamento</Label>
                  <Input name="origin_state" defaultValue={tenant?.shipping_origin?.state ?? ''} placeholder="CDMX" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>Código postal</Label>
                  <Input name="origin_postal_code" defaultValue={tenant?.shipping_origin?.postal_code ?? ''} placeholder="06600" />
                </div>
                <div className="space-y-2">
                  <Label>País (ISO)</Label>
                  <Input name="origin_country" defaultValue={tenant?.shipping_origin?.country ?? 'MX'} placeholder="MX" maxLength={2} />
                </div>
              </div>
              <div className="space-y-2">
                <Label>Teléfono de contacto</Label>
                <Input name="origin_phone" defaultValue={tenant?.shipping_origin?.phone ?? ''} placeholder="+525512345678" />
              </div>
              {tenant?.shipping_origin && (
                <p className="text-xs text-primary">✓ Dirección guardada</p>
              )}
              <Button type="submit">Guardar dirección</Button>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Sección: Notificaciones */}
      {canWrite && (
        <Card>
          <CardHeader>
            <CardTitle>Notificaciones</CardTitle>
            <CardDescription>Alertas operacionales. R-08: Telegram pendiente de integrar en Fase 11.</CardDescription>
          </CardHeader>
          <CardContent>
            <form action={saveTelegram} className="space-y-4 max-w-md">
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  name="enabled"
                  id="tg_enabled"
                  defaultChecked={telegramConfig?.enabled ?? false}
                  className="h-4 w-4"
                />
                <Label htmlFor="tg_enabled">Habilitar alertas por Telegram</Label>
              </div>
              <div className="space-y-2">
                <Label>Bot Token</Label>
                <Input
                  name="bot_token"
                  type="password"
                  placeholder="123456:ABC-DEF..."
                  defaultValue={telegramConfig?.config?.bot_token ?? ''}
                />
              </div>
              <div className="space-y-2">
                <Label>Chat ID</Label>
                <Input
                  name="chat_id"
                  placeholder="-100123456789"
                  defaultValue={telegramConfig?.config?.chat_id ?? ''}
                />
              </div>
              <Button type="submit">Guardar Telegram</Button>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
