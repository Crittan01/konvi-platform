import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Settings, Truck, Bell, ShieldCheck, Building2 } from 'lucide-react'
import LogoUpload from './logo-upload'

export const metadata = {
  title: 'General — Configuración — Commerce Ops',
  description: 'Configuración general del negocio: datos, logo, dirección de despacho y notificaciones.',
}

type ShippingOrigin = {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string
}
type Tenant = {
  id: string; name: string; meta_waba_id: string | null; status: string
  shipping_origin?: ShippingOrigin | null; logo_url?: string | null
}
type NotifSetting = { channel: string; enabled: boolean; config: Record<string, string> }

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
  let notifications: NotifSetting[] = []

  if (tenantId) {
    const [tenantRes, notifRes] = await Promise.all([
      supabase.from('tenants').select('id, name, meta_waba_id, status, shipping_origin, logo_url').eq('id', tenantId).single(),
      supabase.from('notification_settings').select('channel, enabled, config').eq('tenant_id', tenantId),
    ])
    tenant        = tenantRes.data as Tenant
    notifications = (notifRes.data as NotifSetting[]) || []
  }

  const telegramConfig = notifications.find(n => n.channel === 'telegram')

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
            <Settings className="h-5 w-5 text-primary" /> General
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5 capitalize">
            {tenant?.name ?? '—'} · Datos del negocio y notificaciones
          </p>
        </div>
      </div>

      {/* ── Información del Tenant ── */}
      <Section icon={Building2} title="Información del negocio" description="Datos básicos de tu organización en la plataforma.">
        {isOwner ? (
          <div className="space-y-5 max-w-md">
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
                <Input name="origin_city" defaultValue={tenant?.shipping_origin?.city ?? ''} placeholder="Bogotá" className="h-8 text-sm" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Departamento</Label>
                <Input name="origin_state" defaultValue={tenant?.shipping_origin?.state ?? ''} placeholder="Cundinamarca" className="h-8 text-sm" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Código postal</Label>
                <Input name="origin_postal_code" defaultValue={tenant?.shipping_origin?.postal_code ?? ''} placeholder="110111" className="h-8 text-sm" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">País (ISO)</Label>
                <Input name="origin_country" defaultValue={tenant?.shipping_origin?.country ?? 'CO'} placeholder="CO" maxLength={2} className="h-8 text-sm" />
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Teléfono de contacto</Label>
              <Input name="origin_phone" defaultValue={tenant?.shipping_origin?.phone ?? ''} placeholder="+573001234567" className="h-8 text-sm" />
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
