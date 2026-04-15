import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Settings, Truck, Bell, ShieldCheck, Building2, AlertCircle } from 'lucide-react'
import LogoUpload from './logo-upload'

export const metadata = {
  title: 'General — Configuración — Commerce Ops',
  description: 'Configuración general del negocio: datos, logo, dirección de despacho y notificaciones.',
}

// ─── Tipos ───────────────────────────────────────────────────────────────────

type ShippingOrigin = {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string
}
type Tenant = {
  id: string; name: string; meta_waba_id: string | null; status: string
  shipping_origin?: ShippingOrigin | null; logo_url?: string | null
  low_stock_threshold?: number | null
}
type NotifSetting = { channel: string; enabled: boolean; config: Record<string, string> }

// ─── Componentes reutilizables ────────────────────────────────────────────────

function FormSection({ icon: Icon, title, description, children }: {
  icon: React.ElementType; title: string; description?: string; children: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="flex items-center gap-2 px-5 py-3.5 border-b border-border bg-muted/20">
        <Icon className="h-4 w-4 text-primary shrink-0" />
        <div>
          <p className="font-semibold text-sm leading-none">{title}</p>
          {description && <p className="text-xs text-muted-foreground mt-0.5">{description}</p>}
        </div>
      </div>
      <div className="p-5">{children}</div>
    </div>
  )
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium font-mono">{value || '—'}</p>
    </div>
  )
}

// ─── Página ───────────────────────────────────────────────────────────────────

export default async function SettingsPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const isOwner  = role === 'owner'
  const canWrite = role === 'owner' || role === 'manager'

  let tenant: Tenant | null = null
  let notifications: NotifSetting[] = []

  if (tenantId) {
    const [tenantRes, notifRes] = await Promise.all([
      supabase.from('tenants')
        .select('id, name, meta_waba_id, status, shipping_origin, logo_url, low_stock_threshold')
        .eq('id', tenantId).single(),
      supabase.from('notification_settings')
        .select('channel, enabled, config').eq('tenant_id', tenantId),
    ])
    tenant        = tenantRes.data as Tenant
    notifications = (notifRes.data as NotifSetting[]) || []
  }

  const telegramConfig = notifications.find(n => n.channel === 'telegram')

  // ─── Server Actions ───────────────────────────────────────────────────────

  async function saveTenant(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const threshold = parseInt(formData.get('low_stock_threshold') as string, 10)
    await sb.from('tenants').update({
      name: formData.get('name') as string,
      ...(Number.isInteger(threshold) && threshold >= 1 && threshold <= 999
        ? { low_stock_threshold: threshold } : {}),
    }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/settings')
    revalidatePath('/dashboard')
  }

  async function saveShippingOrigin(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const fields = ['name', 'company', 'street', 'city', 'state', 'postal_code', 'country', 'phone']
    const origin: Record<string, string> = {}
    for (const f of fields) {
      const val = (formData.get(`origin_${f}`) as string)?.trim()
      if (val) origin[f] = val
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
        bot_token: (formData.get('bot_token') as string) || '',
        chat_id:   (formData.get('chat_id') as string) || '',
      },
    }, { onConflict: 'tenant_id,channel' })
    revalidatePath('/dashboard/settings')
  }

  // ─── UI ───────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 max-w-5xl">

      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Settings className="h-5 w-5 text-primary" />
          General
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Datos de tu negocio, configuración operativa y notificaciones
        </p>
      </div>

      {/*
        ── Layout de 2 columnas en desktop ──────────────────────────────────
        Columna izquierda (2/3): Identidad + Dirección de envío
        Columna derecha  (1/3): Operaciones + Notificaciones
      */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* ── Columna izquierda ── */}
        <div className="lg:col-span-2 space-y-5">

          {/* Identidad del negocio */}
          <FormSection icon={Building2} title="Identidad del negocio"
            description="Nombre y logo que aparecen en la consola y en las comunicaciones.">
            {isOwner ? (
              <div className="space-y-5">
                {/* Logo */}
                {tenant && (
                  <div>
                    <Label className="text-xs font-medium mb-2 block">Logo del negocio</Label>
                    <LogoUpload tenantId={tenant.id} currentLogoUrl={tenant.logo_url ?? null} />
                  </div>
                )}

                {/* Nombre + guardar */}
                <form action={saveTenant} className="space-y-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium" htmlFor="tenant-name">Nombre del negocio</Label>
                      <Input id="tenant-name" name="name" defaultValue={tenant?.name ?? ''} required className="h-9" />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium" htmlFor="low-stock">Umbral stock bajo</Label>
                      <div className="flex items-center gap-2">
                        <Input
                          id="low-stock"
                          name="low_stock_threshold"
                          type="number" min={1} max={999}
                          defaultValue={tenant?.low_stock_threshold ?? 5}
                          className="h-9 w-24"
                        />
                        <span className="text-xs text-muted-foreground">unidades</span>
                      </div>
                      <p className="text-[11px] text-muted-foreground">Alerta cuando stock ≤ este número</p>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium">WABA ID (Meta)</Label>
                    <div className="flex items-center gap-2">
                      <Input
                        value={tenant?.meta_waba_id ?? 'No configurado'}
                        readOnly
                        className="h-9 bg-muted text-muted-foreground font-mono text-xs flex-1"
                      />
                      <span className="text-[11px] text-muted-foreground whitespace-nowrap">Solo lectura</span>
                    </div>
                    <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                      <AlertCircle className="h-3 w-3 shrink-0" />
                      Para cambiar el WABA ID contacta a soporte.
                    </p>
                  </div>
                  <Button type="submit" size="sm">Guardar cambios</Button>
                </form>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4">
                <ReadOnlyField label="Nombre" value={tenant?.name ?? ''} />
                <ReadOnlyField label="WABA ID" value={tenant?.meta_waba_id ?? 'No configurado'} />
              </div>
            )}
          </FormSection>

          {/* Dirección de origen — solo Owner */}
          {isOwner && (
            <FormSection icon={Truck} title="Dirección de origen — Envíos"
              description="Dirección desde donde se despachan los pedidos. Usada por defecto en cotizaciones Envia.">
              <form action={saveShippingOrigin} className="space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="origin-name">Nombre del remitente</Label>
                    <Input id="origin-name" name="origin_name"
                      defaultValue={tenant?.shipping_origin?.name ?? ''}
                      placeholder="Juan Pérez" className="h-8 text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="origin-company">Empresa</Label>
                    <Input id="origin-company" name="origin_company"
                      defaultValue={tenant?.shipping_origin?.company ?? ''}
                      placeholder="Mi Tienda S.A." className="h-8 text-sm" />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium" htmlFor="origin-street">Calle y número</Label>
                  <Input id="origin-street" name="origin_street"
                    defaultValue={tenant?.shipping_origin?.street ?? ''}
                    placeholder="Av. Principal 123" className="h-8 text-sm" />
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="col-span-2 space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="origin-city">Ciudad</Label>
                    <Input id="origin-city" name="origin_city"
                      defaultValue={tenant?.shipping_origin?.city ?? ''}
                      placeholder="Bogotá" className="h-8 text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="origin-cp">C.P.</Label>
                    <Input id="origin-cp" name="origin_postal_code"
                      defaultValue={tenant?.shipping_origin?.postal_code ?? ''}
                      placeholder="110111" className="h-8 text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="origin-country">País</Label>
                    <Input id="origin-country" name="origin_country"
                      defaultValue={tenant?.shipping_origin?.country ?? 'CO'}
                      placeholder="CO" maxLength={2} className="h-8 text-sm" />
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="origin-state">Departamento</Label>
                    <Input id="origin-state" name="origin_state"
                      defaultValue={tenant?.shipping_origin?.state ?? ''}
                      placeholder="Cundinamarca" className="h-8 text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="origin-phone">Teléfono</Label>
                    <Input id="origin-phone" name="origin_phone"
                      defaultValue={tenant?.shipping_origin?.phone ?? ''}
                      placeholder="+573001234567" className="h-8 text-sm" />
                  </div>
                </div>
                {tenant?.shipping_origin && (
                  <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                    <ShieldCheck className="h-3 w-3" /> Dirección guardada
                  </div>
                )}
                <Button type="submit" size="sm">Guardar dirección</Button>
              </form>
            </FormSection>
          )}
        </div>

        {/* ── Columna derecha ── */}
        <div className="space-y-5">

          {/* Estado del negocio — info rápida */}
          <div className="rounded-xl border border-border bg-card p-5 space-y-3">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Resumen</p>
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-xs text-muted-foreground">Estado</span>
                <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full ${
                  tenant?.status === 'active'
                    ? 'bg-emerald-500/15 text-emerald-400'
                    : 'bg-muted text-muted-foreground'
                }`}>
                  <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                    tenant?.status === 'active' ? 'bg-emerald-400' : 'bg-muted-foreground'
                  }`} />
                  {tenant?.status === 'active' ? 'Activo' : tenant?.status ?? '—'}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-muted-foreground">Stock bajo en</span>
                <span className="text-xs font-mono font-medium">≤ {tenant?.low_stock_threshold ?? 5} uds</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-muted-foreground">WABA ID</span>
                <span className="text-xs font-mono text-muted-foreground truncate max-w-[100px]">
                  {tenant?.meta_waba_id ? `${tenant.meta_waba_id.slice(0, 8)}…` : '—'}
                </span>
              </div>
            </div>
          </div>

          {/* Notificaciones Telegram */}
          {canWrite && (
            <FormSection icon={Bell} title="Alertas — Telegram"
              description="Recibe notificaciones operativas en tu canal de Telegram.">
              <form action={saveTelegram} className="space-y-4">
                <label className="flex items-center gap-2.5 cursor-pointer">
                  <input type="checkbox" name="enabled" id="tg-enabled"
                    defaultChecked={telegramConfig?.enabled ?? false}
                    className="h-4 w-4 rounded accent-primary" />
                  <span className="text-sm">Habilitar alertas</span>
                </label>
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium" htmlFor="bot-token">Bot Token</Label>
                  <Input id="bot-token" name="bot_token" type="password"
                    placeholder="123456789:ABC-DEF..."
                    defaultValue={telegramConfig?.config?.bot_token ?? ''}
                    className="h-9 text-sm font-mono" />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium" htmlFor="chat-id">Chat ID</Label>
                  <Input id="chat-id" name="chat_id"
                    placeholder="-100123456789"
                    defaultValue={telegramConfig?.config?.chat_id ?? ''}
                    className="h-9 text-sm font-mono" />
                  <p className="text-[11px] text-muted-foreground">
                    Usa @userinfobot en Telegram para obtener tu Chat ID.
                  </p>
                </div>
                {telegramConfig?.enabled && (
                  <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                    <ShieldCheck className="h-3 w-3" /> Telegram conectado
                  </div>
                )}
                <Button type="submit" size="sm">Guardar</Button>
              </form>
            </FormSection>
          )}

          {/* Nota sobre tema oscuro/claro */}
          <div className="rounded-xl border border-border border-dashed p-4">
            <p className="text-xs font-medium text-muted-foreground mb-1">🎨 Tema de la interfaz</p>
            <p className="text-xs text-muted-foreground/70 leading-relaxed">
              La consola usa tema oscuro por defecto. El selector de tema claro/oscuro estará disponible como preferencia de usuario en una próxima actualización.
            </p>
          </div>

        </div>
      </div>
    </div>
  )
}
