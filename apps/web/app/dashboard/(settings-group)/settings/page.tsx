import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Settings, Truck, ShieldCheck, Building2, SlidersHorizontal, Palette,
} from 'lucide-react'
import LogoUpload from './logo-upload'
import ShippingOriginForm from './shipping-origin-form'

export const metadata = {
  title: 'General — Configuración — Commerce Ops',
  description: 'Configuración general del negocio: datos, logo y dirección de despacho.',
}

// ─── Tipos ───────────────────────────────────────────────────────────────────

type ShippingOrigin = {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string; dane_code?: string
}
type Tenant = {
  id: string; name: string; status: string
  shipping_origin?: ShippingOrigin | null; logo_url?: string | null
  low_stock_threshold?: number | null
  nit?: string | null
  email_contacto?: string | null
  telefono_contacto?: string | null
}
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
  const isOwner = role === 'owner'

  let tenant: Tenant | null = null

  if (tenantId) {
    const { data } = await supabase.from('tenants')
      .select('id, name, status, shipping_origin, logo_url, low_stock_threshold, nit, email_contacto, telefono_contacto')
      .eq('id', tenantId).single()
    tenant = data as Tenant
  }

  // ─── Server Actions ───────────────────────────────────────────────────────

  async function saveTenant(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    await sb.from('tenants').update({
      name:              (formData.get('name') as string)?.trim() || undefined,
      nit:               (formData.get('nit') as string)?.trim()  || null,
      email_contacto:    (formData.get('email_contacto') as string)?.trim() || null,
      telefono_contacto: (formData.get('telefono_contacto') as string)?.trim() || null,
    }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/settings')
    revalidatePath('/dashboard')
  }

  async function saveOperativa(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const threshold = parseInt(formData.get('low_stock_threshold') as string, 10)
    if (Number.isInteger(threshold) && threshold >= 1 && threshold <= 999) {
      await sb.from('tenants').update({ low_stock_threshold: threshold }).eq('id', m.tenant_id)
    }
    revalidatePath('/dashboard/settings')
    revalidatePath('/dashboard')
  }

  async function saveShippingOrigin(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const fields = ['name', 'company', 'street', 'city', 'state', 'postal_code', 'country', 'phone', 'dane_code']
    const origin: Record<string, string> = {}
    for (const f of fields) {
      const val = (formData.get(`origin_${f}`) as string)?.trim()
      if (val) origin[f] = val
    }
    // CO runtime: mantener postal_code y dane_code alineados para Envia quote.
    if (origin.dane_code && !origin.postal_code) origin.postal_code = origin.dane_code
    if (origin.postal_code && !origin.dane_code) origin.dane_code = origin.postal_code
    await sb.from('tenants').update({ shipping_origin: origin }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/settings')
  }

  // ─── UI ───────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 max-w-7xl">

      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Settings className="h-5 w-5 text-primary" />
          General
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Datos de tu negocio y configuración operativa
        </p>
      </div>

      {/*
        ── Layout de 2 columnas en desktop ──────────────────────────────────
        Columna izquierda (2/3): Identidad + Dirección de envío
        Columna derecha  (1/3): Resumen + Configuración Operativa
      */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* ── Columna izquierda ── */}
        <div className="lg:col-span-2 space-y-5">

          {/* Identidad del negocio */}
          <FormSection icon={Building2} title="Identidad del negocio"
            description="Nombre, logo y datos legales del negocio.">
            {isOwner ? (
              <div className="space-y-5">
                {/* Logo */}
                {tenant && (
                  <div>
                    <Label className="text-xs font-medium mb-2 block">Logo del negocio</Label>
                    <LogoUpload tenantId={tenant.id} currentLogoUrl={tenant.logo_url ?? null} />
                  </div>
                )}

                {/* Campos de identidad */}
                <form action={saveTenant} className="space-y-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium" htmlFor="tenant-name">
                        Nombre del negocio <span className="text-destructive">*</span>
                      </Label>
                      <Input id="tenant-name" name="name" defaultValue={tenant?.name ?? ''} required className="h-9" />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium" htmlFor="tenant-nit">NIT / Razón social</Label>
                      <Input id="tenant-nit" name="nit"
                        defaultValue={tenant?.nit ?? ''}
                        placeholder="900.123.456-7"
                        className="h-9" />
                      <p className="text-[10px] text-muted-foreground">Opcional — persona natural puede omitirlo</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium" htmlFor="email-contacto">
                        Email de contacto <span className="text-destructive">*</span>
                      </Label>
                      <Input id="email-contacto" name="email_contacto" type="email"
                        defaultValue={tenant?.email_contacto ?? ''}
                        placeholder="contacto@minegocio.com"
                        required
                        className="h-9" />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium" htmlFor="celular-contacto">
                        Celular de contacto <span className="text-destructive">*</span>
                      </Label>
                      <div className="flex items-center gap-1.5">
                        <span className="h-9 px-2.5 rounded-md border border-input bg-muted/50 text-xs text-muted-foreground flex items-center shrink-0">+57</span>
                        <Input id="celular-contacto" name="telefono_contacto"
                          type="tel"
                          defaultValue={tenant?.telefono_contacto ?? ''}
                          placeholder="3121234567"
                          pattern="3[0-9]{9}"
                          maxLength={10}
                          required
                          className="h-9" />
                      </div>
                      <p className="text-[10px] text-muted-foreground">10 dígitos, ej: 3121234567</p>
                    </div>
                  </div>
                  <Button type="submit" size="sm">Guardar cambios</Button>
                </form>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4">
                <ReadOnlyField label="Nombre" value={tenant?.name ?? ''} />
                <ReadOnlyField label="NIT" value={tenant?.nit ?? '—'} />
                <ReadOnlyField label="Email" value={tenant?.email_contacto ?? '—'} />
                <ReadOnlyField label="Celular" value={tenant?.telefono_contacto ? `+57 ${tenant.telefono_contacto}` : '—'} />
              </div>
            )}
          </FormSection>

          {/* Dirección de origen — solo Owner */}
          {isOwner && (
            <FormSection icon={Truck} title="Dirección de origen — Envíos"
              description="Dirección desde donde se despachan los pedidos. Usada por defecto en cotizaciones Envia.">
              <ShippingOriginForm
                initialData={tenant?.shipping_origin}
                action={saveShippingOrigin}
              />
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
            </div>
          </div>

          {/* Configuración Operativa — umbral de stock bajo */}
          {isOwner && (
            <FormSection icon={SlidersHorizontal} title="Configuración Operativa"
              description="Parámetros globales que afectan el comportamiento del sistema.">
              <form action={saveOperativa} className="space-y-3">
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
                  <p className="text-[11px] text-muted-foreground">
                    Alerta en Inventario cuando stock ≤ este número.
                  </p>
                </div>
                <Button type="submit" size="sm" variant="outline">Guardar</Button>
              </form>
            </FormSection>
          )}

          {/* Nota sobre tema oscuro/claro */}
          <div className="rounded-xl border border-border border-dashed p-4">
            <p className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1.5"><Palette className="h-3.5 w-3.5" /> Tema de la interfaz</p>
            <p className="text-xs text-muted-foreground/70 leading-relaxed">
              La consola usa tema oscuro por defecto. El selector de tema claro/oscuro estará disponible como preferencia de usuario en una próxima actualización.
            </p>
          </div>

        </div>
      </div>
    </div>
  )
}
