import { createClient } from '@/utils/supabase/server'
import { Input } from '@/components/ui/input'
import { saveTenant, saveOperativa, savePresenciaDigital, saveHorario, saveShippingOrigin } from './actions'
import { Label } from '@/components/ui/label'
import { SubmitButton } from '@/components/ui/submit-button'
import {
  Settings, Truck, Building2, SlidersHorizontal, Globe, Clock,
  CheckCircle2, XCircle,
} from 'lucide-react'
import LogoUpload from './logo-upload'
import ShippingOriginForm from './shipping-origin-form'
import StorePresenceForm from './store-presence-form'

export const metadata = {
  title: 'General — Configuración — Commerce Ops',
  description: 'Configuración general del negocio: datos, logo y dirección de despacho.',
}

// ─── Tipos ───────────────────────────────────────────────────────────────────

type ShippingOrigin = {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string; dane_code?: string
}
type SocialLinks = {
  instagram?: string; facebook?: string; tiktok?: string; youtube?: string; website?: string
}
type StoreLocation = { name?: string; city?: string; state?: string; street?: string }
type Tenant = {
  id: string; name: string; status: string
  shipping_origin?: ShippingOrigin | null; logo_url?: string | null
  low_stock_threshold?: number | null
  nit?: string | null
  email_contacto?: string | null
  telefono_contacto?: string | null
  store_type?: 'fisica' | 'virtual' | 'fisica_virtual' | null
  social_links?: SocialLinks | null
  store_locations?: StoreLocation[] | null
  business_hours?: string | null
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
      .select('id, name, status, shipping_origin, logo_url, low_stock_threshold, nit, email_contacto, telefono_contacto, store_type, social_links, store_locations, business_hours')
      .eq('id', tenantId).single()
    tenant = data as Tenant
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
                  <SubmitButton size="sm">Guardar cambios</SubmitButton>
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

          {/* Presencia digital — client component con show/hide dinámico */}
          {isOwner && (
            <FormSection icon={Globe} title="Presencia y ubicaciones"
              description="Tipo de operación, sedes físicas y canales digitales. El asistente IA usa esta información para responder preguntas de clientes sin escalar.">
              <StorePresenceForm
                initialStoreType={(tenant?.store_type ?? 'fisica') as 'fisica' | 'virtual' | 'fisica_virtual'}
                initialLocations={(tenant?.store_locations as Array<{name:string;city:string;state:string;street:string}>) ?? []}
                initialSocialLinks={(tenant?.social_links as Record<string,string>) ?? {}}
                action={savePresenciaDigital}
              />
            </FormSection>
          )}

          {/* Horario de atención */}
          {isOwner && (
            <FormSection icon={Clock} title="Horario de atención"
              description="El asistente IA responde preguntas como '¿cuándo abren?' usando este texto.">
              <form action={saveHorario} className="space-y-3">
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium" htmlFor="business-hours">Horario</Label>
                  <textarea
                    id="business-hours"
                    name="business_hours"
                    defaultValue={tenant?.business_hours ?? ''}
                    placeholder={'Lunes a Viernes: 8am – 6pm\nSábados: 9am – 2pm\nDomingos: Cerrado'}
                    rows={3}
                    className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
                  />
                  <p className="text-[10px] text-muted-foreground">Texto libre — el bot lo repite al cliente tal cual.</p>
                </div>
                <SubmitButton size="sm">Guardar horario</SubmitButton>
              </form>
            </FormSection>
          )}

          {/* Dirección de despacho — solo para cotizaciones Envia */}
          {isOwner && (
            <FormSection icon={Truck} title="Opciones de despacho — Envia"
              description="Dirección de origen para cotizaciones de envío. Selecciona una sede configurada para auto-completar los campos.">
              <ShippingOriginForm
                initialData={tenant?.shipping_origin}
                action={saveShippingOrigin}
                tenantName={tenant?.name ?? undefined}
                tenantPhone={tenant?.telefono_contacto ?? undefined}
                storeLocations={(tenant?.store_locations as Array<{name?:string;city?:string;state?:string;street?:string}>) ?? []}
              />
            </FormSection>
          )}
        </div>

        {/* ── Columna derecha ── */}
        <div className="space-y-5">

          {/* Resumen de configuración */}
          {(() => {
            const storeTypeLabel: Record<string, string> = {
              fisica: 'Solo física', virtual: 'Solo virtual', fisica_virtual: 'Física y virtual',
            }
            const sedesCount  = (tenant?.store_locations as unknown[])?.length ?? 0
            const socialCount = Object.values(tenant?.social_links ?? {}).filter(Boolean).length
            const hasHorario  = !!tenant?.business_hours?.trim()
            const hasDespacho = !!tenant?.shipping_origin?.city

            type Row = { label: string; value: string; ok?: boolean }
            const rows: Row[] = [
              {
                label: 'Estado',
                value: tenant?.status === 'active' ? 'Activo' : tenant?.status ?? '—',
                ok: tenant?.status === 'active',
              },
              {
                label: 'Stock bajo en',
                value: `≤ ${tenant?.low_stock_threshold ?? 5} uds`,
              },
              {
                label: 'Tipo de tienda',
                value: storeTypeLabel[tenant?.store_type ?? 'fisica'] ?? '—',
                ok: !!tenant?.store_type,
              },
              ...(tenant?.store_type !== 'virtual' ? [{
                label: 'Sedes físicas',
                value: sedesCount > 0 ? `${sedesCount} configurada${sedesCount > 1 ? 's' : ''}` : 'Sin configurar',
                ok: sedesCount > 0,
              }] : []),
              ...(tenant?.store_type !== 'fisica' ? [{
                label: 'Redes sociales',
                value: socialCount > 0 ? `${socialCount} canal${socialCount > 1 ? 'es' : ''}` : 'Sin configurar',
                ok: socialCount > 0,
              }] : []),
              {
                label: 'Horario',
                value: hasHorario ? 'Configurado' : 'Sin configurar',
                ok: hasHorario,
              },
              {
                label: 'Despacho Envia',
                value: hasDespacho ? 'Configurado' : 'Sin configurar',
                ok: hasDespacho,
              },
            ]

            return (
              <div className="rounded-xl border border-border bg-card p-5 space-y-3">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Resumen</p>
                <div className="space-y-2">
                  {rows.map(({ label, value, ok }) => (
                    <div key={label} className="flex justify-between items-center gap-2">
                      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
                      <span className={`text-xs font-medium flex items-center gap-1 text-right ${
                        ok === true ? 'text-emerald-400' : ok === false ? 'text-muted-foreground/60' : ''
                      }`}>
                        {ok === true && <CheckCircle2 className="h-3 w-3 shrink-0" />}
                        {ok === false && <XCircle className="h-3 w-3 shrink-0" />}
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )
          })()}

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
                <SubmitButton size="sm">Guardar</SubmitButton>
              </form>
            </FormSection>
          )}


        </div>
      </div>
    </div>
  )
}
