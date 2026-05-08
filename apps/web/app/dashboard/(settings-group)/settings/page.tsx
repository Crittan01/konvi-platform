import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Input } from '@/components/ui/input'
import { saveTenant, savePresenciaDigital, saveShippingOrigin, saveFilosofia, saveHorarioAsesor } from './actions'
import { Label } from '@/components/ui/label'
import { SubmitButton } from '@/components/ui/submit-button'
import {
  Settings, Truck, Building2, Globe, Clock,
  CheckCircle2, XCircle, Sparkles, Bot,
} from 'lucide-react'
import LogoUpload from './logo-upload'
import ShippingOriginForm from './shipping-origin-form'
import StorePresenceForm from './store-presence-form'
import { DaysSelector } from './days-selector'

export const metadata = {
  title: 'General — Configuración — Konvi',
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
type StoreLocation = { name?: string; city?: string; state?: string; street?: string; phone?: string; email?: string }
type SupportSchedule = { days: number[]; open: string; close: string }
type Tenant = {
  id: string; name: string; status: string
  shipping_origin?: ShippingOrigin | null; logo_url?: string | null
  nit?: string | null
  email_contacto?: string | null
  telefono_contacto?: string | null
  store_type?: 'fisica' | 'virtual' | 'fisica_virtual' | null
  social_links?: SocialLinks | null
  store_locations?: StoreLocation[] | null
  mision?: string | null
  vision?: string | null
  valores?: string | null
  tono_comunicacion?: string | null
  support_schedule?: SupportSchedule | null
  after_hours_message?: string | null
  escalation_role?: 'asesor' | 'especialista' | 'consultor' | 'agente' | null
}
// ─── Componentes reutilizables ────────────────────────────────────────────────

function FormSection({ icon: Icon, title, description, children, id }: {
  icon: React.ElementType; title: string; description?: string; children: React.ReactNode; id?: string
}) {
  return (
    <div id={id} className="rounded-xl border border-border bg-card overflow-hidden scroll-mt-4">
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

  // Protección por navegación directa — solo owners acceden a esta página
  if (!isOwner) redirect('/dashboard')

  let tenant: Tenant | null = null

  if (tenantId) {
    const { data } = await supabase.from('tenants')
      .select('id, name, status, shipping_origin, logo_url, nit, email_contacto, telefono_contacto, store_type, social_links, store_locations, mision, vision, valores, tono_comunicacion, support_schedule, after_hours_message, escalation_role')
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
          <FormSection id="section-identidad" icon={Building2} title="Identidad del negocio"
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
                      <Input id="tenant-name" name="name"
                        defaultValue={tenant?.name ?? ''}
                        required
                        maxLength={100}
                        className="h-9" />
                      <p className="text-[10px] text-muted-foreground">
                        Máx 100 caracteres — aparece en mensajes WhatsApp y guías de envío.
                      </p>
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium" htmlFor="tenant-nit">NIT / CC</Label>
                      <Input id="tenant-nit" name="nit"
                        defaultValue={tenant?.nit ?? ''}
                        placeholder="900.123.456-7 o cédula"
                        className="h-9" />
                      <p className="text-[10px] text-muted-foreground">
                        Empresa: NIT · Persona natural: CC · Opcional
                      </p>
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

          {/* Filosofía del negocio — alimenta automáticamente al bot */}
          {isOwner && (
            <FormSection id="section-filosofia" icon={Sparkles} title="Filosofía del negocio"
              description="Define la IDENTIDAD de tu marca: qué hace tu negocio, por qué existe y cómo se expresa. El asistente IA inyecta estos datos automáticamente para hablar con coherencia.">
              <div className="flex items-center gap-1.5 mb-1 text-[11px] font-medium text-primary/70 bg-primary/5 border border-primary/15 rounded-lg px-3 py-2">
                <Bot className="h-3.5 w-3.5 shrink-0" />
                Identidad del negocio (qué/por qué). El COMPORTAMIENTO del bot (cómo responde, ejemplos) se configura en IA y Conocimiento → Agentes IA.
              </div>
              <form action={saveFilosofia} className="space-y-4">
                {/* Tono de comunicación */}
                <div className="space-y-2">
                  <Label className="text-xs font-medium">Tono de comunicación</Label>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                    {([
                      { value: 'formal',       label: 'Formal',       desc: 'Respetuoso, corporativo' },
                      { value: 'profesional',  label: 'Profesional',  desc: 'Preciso, sin coloquialismos' },
                      { value: 'amigable',     label: 'Amigable',     desc: 'Cercano y accesible' },
                      { value: 'cercano',      label: 'Cercano',      desc: 'Casual, como un amigo' },
                      { value: 'juvenil',      label: 'Juvenil',      desc: 'Dinámico, con emojis' },
                    ] as const).map(({ value, label, desc }) => (
                      <label key={value}
                        className="flex flex-col gap-0.5 rounded-lg border border-border p-2.5 cursor-pointer transition-colors hover:border-primary/40 has-[:checked]:border-primary has-[:checked]:bg-primary/5">
                        <input type="radio" name="tono_comunicacion" value={value}
                          defaultChecked={(tenant?.tono_comunicacion ?? 'amigable') === value}
                          className="sr-only" />
                        <span className="text-xs font-semibold">{label}</span>
                        <span className="text-[10px] text-muted-foreground">{desc}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {/* Misión */}
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="mision">Misión</Label>
                    <textarea id="mision" name="mision"
                      defaultValue={tenant?.mision ?? ''}
                      maxLength={280}
                      placeholder={'Ej: "Conectar a los colombianos con tecnología de calidad a precio justo, directamente desde el fabricante."'}
                      rows={4}
                      className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none" />
                    <p className="text-[10px] text-muted-foreground">¿Por qué existe tu negocio? Máx 280 chars.</p>
                  </div>
                  {/* Visión */}
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="vision">Visión</Label>
                    <textarea id="vision" name="vision"
                      defaultValue={tenant?.vision ?? ''}
                      maxLength={280}
                      placeholder={'Ej: "Ser la tienda de tecnología más recomendada de Colombia para 2028."'}
                      rows={4}
                      className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none" />
                    <p className="text-[10px] text-muted-foreground">¿Dónde quieres llegar? Máx 280 chars.</p>
                  </div>
                  {/* Valores */}
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="valores">Valores</Label>
                    <textarea id="valores" name="valores"
                      defaultValue={tenant?.valores ?? ''}
                      maxLength={280}
                      placeholder={'Ej: "Confianza, Calidad, Transparencia y Cercanía con el cliente."'}
                      rows={4}
                      className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none" />
                    <p className="text-[10px] text-muted-foreground">¿Qué principios te guían? Máx 280 chars.</p>
                  </div>
                </div>
                <p className="text-[10px] text-muted-foreground/70">
                  Todos los campos son opcionales. El asistente IA usa estos datos para responder preguntas sobre la marca.
                </p>
                <SubmitButton size="sm">Guardar filosofía</SubmitButton>
              </form>
            </FormSection>
          )}

          {/* Presencia digital — client component con show/hide dinámico */}
          {isOwner && (
            <FormSection id="section-presencia" icon={Globe} title="Presencia y ubicaciones"
              description="Tipo de operación, sedes físicas y canales digitales. El asistente IA usa esta información para responder preguntas de clientes sin escalar.">
              <StorePresenceForm
                initialStoreType={(tenant?.store_type ?? 'fisica') as 'fisica' | 'virtual' | 'fisica_virtual'}
                initialLocations={(tenant?.store_locations as Array<{name:string;city:string;state:string;street:string;phone?:string}>) ?? []}
                initialSocialLinks={(tenant?.social_links as Record<string,string>) ?? {}}
                action={savePresenciaDigital}
              />
            </FormSection>
          )}

          {/* Horario y disponibilidad */}
          {(() => {
            const sched = tenant?.support_schedule as { days?: number[]; open?: string; close?: string } | null
            return isOwner && (
              <FormSection id="section-horario" icon={Clock} title="Horario y disponibilidad"
                description="Configura cuándo hay asesores disponibles. El bot informará a clientes que escriban fuera de ese horario.">
                <form action={saveHorarioAsesor} className="space-y-4">

                  {/* Indicador: bot 24/7 */}
                  <div className="flex items-center gap-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-3 py-2">
                    <span className="h-2 w-2 rounded-full bg-emerald-400 shrink-0" />
                    <span className="text-xs text-emerald-400 font-medium">Bot de ventas: activo 24/7 (automático)</span>
                  </div>

                  {/* Horario de asesor humano — client component para interactividad */}
                  <div className="space-y-2">
                    <Label className="text-xs font-medium">Días de atención con asesor</Label>
                    <DaysSelector initialDays={sched?.days} />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium" htmlFor="support-open">Hora de apertura</Label>
                      <Input id="support-open" name="support_open" type="time"
                        defaultValue={sched?.open ?? '09:00'} className="h-9 text-sm" />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium" htmlFor="support-close">Hora de cierre</Label>
                      <Input id="support-close" name="support_close" type="time"
                        defaultValue={sched?.close ?? '18:00'} className="h-9 text-sm" />
                    </div>
                  </div>
                  <p className="text-[10px] text-muted-foreground">Hora Colombia (UTC−5). Cuando un cliente pida atención fuera de este horario, el bot enviará el mensaje de abajo.</p>

                  {/* Mensaje fuera de horario */}
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="after-hours">
                      Mensaje fuera de horario <span className="text-muted-foreground font-normal">(opcional)</span>
                    </Label>
                    <textarea id="after-hours" name="after_hours_message"
                      defaultValue={tenant?.after_hours_message ?? ''}
                      placeholder={'Ej: ¡Hola! En este momento nuestro equipo descansa.\nTe respondemos mañana entre las 8:00 AM y 6:00 PM.\n¡Gracias por escribirnos!'}
                      rows={3}
                      className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none" />
                    <p className="text-[10px] text-muted-foreground">Tip: escríbelo como tú le hablarías al cliente — natural y cálido. El bot lo envía automáticamente antes de escalar.</p>
                  </div>

                  {/* Rev. 68 — escalation_role configurable */}
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium" htmlFor="escalation-role">
                      ¿Cómo llamas a quien atiende personalmente?
                    </Label>
                    <select
                      id="escalation-role"
                      name="escalation_role"
                      defaultValue={tenant?.escalation_role ?? 'asesor'}
                      className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      <option value="asesor">Asesor (default — comercial)</option>
                      <option value="especialista">Especialista (servicios profesionales, salud)</option>
                      <option value="consultor">Consultor (B2B, asesoría)</option>
                      <option value="agente">Agente (call center, soporte)</option>
                    </select>
                    <p className="text-[10px] text-muted-foreground">
                      El bot usa este término al escalar a un humano (ej. &quot;Te paso con un {tenant?.escalation_role ?? 'asesor'} que te ayudará&quot;).
                    </p>
                  </div>

                  <SubmitButton size="sm">Guardar horario</SubmitButton>
                </form>
              </FormSection>
            )
          })()}

          {/* Dirección de despacho — solo para cotizaciones Envia */}
          {isOwner && (
            <FormSection id="section-despacho" icon={Truck} title="Dirección de despacho principal — Envia"
              description="Dirección desde donde salen físicamente los paquetes (puede ser bodega, no necesariamente una sede pública). Usada por Envia para calcular costos y tiempos de envío.">
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
            const sedesCount    = (tenant?.store_locations as unknown[])?.length ?? 0
            const socialCount   = Object.values(tenant?.social_links ?? {}).filter(Boolean).length
            const hasHorario    = !!(tenant?.support_schedule)
            const hasDespacho   = !!tenant?.shipping_origin?.city
            const hasFilosofia  = !!(tenant?.mision || tenant?.valores)

            type Row = { label: string; value: string; ok?: boolean; anchor?: string }
            const rows: Row[] = [
              {
                label: 'Estado',
                value: tenant?.status === 'active' ? 'Activo' : tenant?.status ?? '—',
                ok: tenant?.status === 'active',
                anchor: 'section-identidad',
              },
              {
                label: 'Tipo de tienda',
                value: storeTypeLabel[tenant?.store_type ?? 'fisica'] ?? '—',
                ok: !!tenant?.store_type,
                anchor: 'section-presencia',
              },
              ...(tenant?.store_type !== 'virtual' ? [{
                label: 'Sedes físicas',
                value: sedesCount > 0 ? `${sedesCount} configurada${sedesCount > 1 ? 's' : ''}` : 'Sin configurar',
                ok: sedesCount > 0,
                anchor: 'section-presencia',
              }] : []),
              ...(tenant?.store_type !== 'fisica' ? [{
                label: 'Redes sociales',
                value: socialCount > 0 ? `${socialCount} canal${socialCount > 1 ? 'es' : ''}` : 'Sin configurar',
                ok: socialCount > 0,
                anchor: 'section-presencia',
              }] : []),
              {
                label: 'Filosofía',
                value: hasFilosofia ? 'Configurada' : 'Sin configurar',
                ok: hasFilosofia,
                anchor: 'section-filosofia',
              },
              {
                label: 'Horario asesor',
                value: hasHorario ? 'Configurado' : 'Sin configurar',
                ok: hasHorario,
                anchor: 'section-horario',
              },
              {
                label: 'Despacho Envia',
                value: hasDespacho ? 'Configurado' : 'Sin configurar',
                ok: hasDespacho,
                anchor: 'section-despacho',
              },
            ]

            return (
              <div className="rounded-xl border border-border bg-card p-5 space-y-3">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Resumen</p>
                <div className="space-y-1.5">
                  {rows.map(({ label, value, ok, anchor }) => {
                    const content = (
                      <>
                        <span className="text-xs text-muted-foreground shrink-0 group-hover:text-foreground/70 transition-colors">{label}</span>
                        <span className={`text-xs font-medium flex items-center gap-1 text-right ${
                          ok === true ? 'text-emerald-400' : ok === false ? 'text-muted-foreground/60' : ''
                        }`}>
                          {ok === true && <CheckCircle2 className="h-3 w-3 shrink-0" />}
                          {ok === false && <XCircle className="h-3 w-3 shrink-0" />}
                          {value}
                        </span>
                      </>
                    )
                    return anchor ? (
                      <a key={label} href={`#${anchor}`}
                        className="flex justify-between items-center gap-2 group rounded px-1 -mx-1 py-0.5 hover:bg-muted/40 transition-colors cursor-pointer">
                        {content}
                      </a>
                    ) : (
                      <div key={label} className="flex justify-between items-center gap-2 px-1 py-0.5">
                        {content}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })()}



        </div>
      </div>
    </div>
  )
}
