import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Plug, CheckCircle2, XCircle, AlertCircle, ExternalLink } from 'lucide-react'

const MELI_CLIENT_ID   = process.env.MELI_CLIENT_ID ?? ''
const MELI_REDIRECT_URI = process.env.MELI_REDIRECT_URI ?? 'https://commerce-ops-api.onrender.com/api/v1/integrations/meli/callback'
const MELI_AUTH_URL    = process.env.MELI_AUTH_URL ?? 'https://auth.mercadolibre.com.co/authorization'

type Integration = {
  provider: string
  status: string
  meta: Record<string, string>
}

export default async function IntegrationsPage({
  searchParams,
}: {
  searchParams: { connected?: string; error?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const isOwner = role === 'owner'

  let integrations: Integration[] = []

  if (tenantId) {
    const { data } = await supabase
      .from('tenant_integrations')
      .select('provider, status, meta')
      .eq('tenant_id', tenantId)
    integrations = (data as Integration[]) || []
  }

  const providers = ['envia', 'mercadolibre']
  const fullList: Integration[] = providers.map(p =>
    integrations.find(i => i.provider === p) ?? { provider: p, status: 'disconnected', meta: {} }
  )

  const enviaInt = fullList.find(i => i.provider === 'envia')!
  const meliInt  = fullList.find(i => i.provider === 'mercadolibre')!
  const enviaConnected = enviaInt.status === 'connected'
  const meliConnected  = meliInt.status === 'connected'

  const meliState  = tenantId ? Buffer.from(tenantId).toString('base64url') : ''
  const meliAuthUrl = MELI_CLIENT_ID && meliState
    ? `${MELI_AUTH_URL}?response_type=code&client_id=${MELI_CLIENT_ID}&redirect_uri=${encodeURIComponent(MELI_REDIRECT_URI)}&state=${meliState}`
    : null

  // ── Server Actions ────────────────────────────────────────────────────────

  async function saveEnviaKey(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const token   = formData.get('api_token') as string
    const sandbox = formData.get('sandbox') === 'on'
    await sb.from('tenant_integrations').upsert({
      tenant_id: m.tenant_id,
      provider: 'envia',
      status: 'connected',
      credentials: { api_token: token, sandbox },
      meta: { token_preview: `${token.slice(0, 6)}...${token.slice(-4)}`, environment: sandbox ? 'sandbox' : 'production' },
    }, { onConflict: 'tenant_id,provider' })
    revalidatePath('/dashboard/integrations')
  }

  async function disconnectEnvia() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    await sb.from('tenant_integrations').update({ status: 'disconnected', credentials: {} })
      .eq('tenant_id', m.tenant_id).eq('provider', 'envia')
    revalidatePath('/dashboard/integrations')
  }

  async function disconnectMeli() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    await sb.from('tenant_integrations').update({ status: 'disconnected', credentials: {}, meta: {} })
      .eq('tenant_id', m.tenant_id).eq('provider', 'mercadolibre')
    revalidatePath('/dashboard/integrations')
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-5xl">

      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Plug className="h-5 w-5 text-primary" /> Integraciones
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Conectores activos para tu negocio · {[enviaConnected, meliConnected].filter(Boolean).length}/2 conectados
        </p>
      </div>

      {/* Banners de resultado OAuth */}
      {searchParams.connected && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-green-500/30 bg-green-500/10 text-sm text-green-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {searchParams.connected === 'mercadolibre' ? 'Mercado Libre' : searchParams.connected} conectado exitosamente.
        </div>
      )}
      {searchParams.error && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Error al conectar: {searchParams.error}. Intenta de nuevo.
        </div>
      )}

      {/* Tarjetas de integraciones — App Store View */}
      <div className="grid gap-4 sm:grid-cols-2">

        {/* ── Envia ──────────────────────────────────────────────────────── */}
        <div className={`rounded-xl border bg-card overflow-hidden transition-all ${
          enviaConnected ? 'border-emerald-500/30' : 'border-border'
        }`}>
          {/* Card header visual */}
          <div className={`px-5 py-4 border-b ${enviaConnected ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-border bg-muted/20'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-xl bg-white/10 border border-white/10 flex items-center justify-center text-xl">
                  📦
                </div>
                <div>
                  <p className="font-semibold text-sm">Envia</p>
                  <p className="text-xs text-muted-foreground">Shipping & Logistics</p>
                </div>
              </div>
              <div className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border ${
                enviaConnected
                  ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                  : 'bg-muted text-muted-foreground border-border'
              }`}>
                {enviaConnected ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                {enviaConnected ? 'Conectado' : 'Desconectado'}
              </div>
            </div>
          </div>

          {/* Card body */}
          <div className="px-5 py-4 space-y-3">
            <p className="text-xs text-muted-foreground">
              Cotiza envíos con múltiples carriers (DHL, FedEx, Estafeta...), genera etiquetas y haz tracking desde la plataforma.
            </p>

            {enviaConnected ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg bg-muted px-3 py-2">
                    <p className="text-[10px] text-muted-foreground uppercase">Token</p>
                    <p className="text-xs font-mono font-medium mt-0.5">{enviaInt.meta?.token_preview ?? '***'}</p>
                  </div>
                  <div className="rounded-lg bg-muted px-3 py-2">
                    <p className="text-[10px] text-muted-foreground uppercase">Entorno</p>
                    <p className="text-xs font-medium capitalize mt-0.5">{enviaInt.meta?.environment ?? '—'}</p>
                  </div>
                </div>
                {isOwner && (
                  <form action={disconnectEnvia}>
                    <Button type="submit" size="sm" variant="outline"
                      className="w-full h-8 text-xs text-destructive border-destructive/30 hover:bg-destructive/10">
                      Desconectar Envia
                    </Button>
                  </form>
                )}
              </div>
            ) : isOwner ? (
              <form action={saveEnviaKey} className="space-y-3">
                <div className="space-y-1">
                  <Label className="text-xs">API Token de Envia</Label>
                  <Input name="api_token" type="password" placeholder="Bearer token de app.envia.com" required className="h-8 text-xs" />
                </div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" name="sandbox" id="envia_sandbox" className="h-3.5 w-3.5 rounded" />
                  <span className="text-xs text-muted-foreground">Usar entorno sandbox (pruebas)</span>
                </label>
                <Button type="submit" size="sm" className="w-full h-8 text-xs">Conectar Envia</Button>
              </form>
            ) : (
              <p className="text-xs text-muted-foreground">Solo el Owner puede configurar integraciones.</p>
            )}
          </div>
        </div>

        {/* ── Mercado Libre ───────────────────────────────────────────────── */}
        <div className={`rounded-xl border bg-card overflow-hidden transition-all ${
          meliConnected ? 'border-yellow-500/30' : 'border-border'
        }`}>
          <div className={`px-5 py-4 border-b ${meliConnected ? 'border-yellow-500/20 bg-yellow-500/5' : 'border-border bg-muted/20'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-xl bg-yellow-400 flex items-center justify-center text-black font-bold text-xs">
                  ML
                </div>
                <div>
                  <p className="font-semibold text-sm">Mercado Libre</p>
                  <p className="text-xs text-muted-foreground">Marketplace</p>
                </div>
              </div>
              <div className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border ${
                meliConnected
                  ? 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30'
                  : 'bg-muted text-muted-foreground border-border'
              }`}>
                {meliConnected ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                {meliConnected ? 'Conectado' : 'Desconectado'}
              </div>
            </div>
          </div>

          <div className="px-5 py-4 space-y-3">
            <p className="text-xs text-muted-foreground">
              Sincroniza tu catálogo y recibe pedidos de MeLi automáticamente via webhooks. OAuth 2.0 seguro por tenant.
            </p>

            {meliConnected ? (
              <div className="space-y-3">
                <div className="rounded-lg bg-muted px-3 py-2">
                  <p className="text-[10px] text-muted-foreground uppercase">Usuario MeLi ID</p>
                  <p className="text-xs font-mono font-medium mt-0.5">{meliInt.meta?.user_id ?? '—'}</p>
                </div>
                {isOwner && (
                  <form action={disconnectMeli}>
                    <Button type="submit" size="sm" variant="outline"
                      className="w-full h-8 text-xs text-destructive border-destructive/30 hover:bg-destructive/10">
                      Desconectar Mercado Libre
                    </Button>
                  </form>
                )}
              </div>
            ) : isOwner ? (
              <div className="space-y-3">
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5 text-xs text-muted-foreground">
                  Serás redirigido a Mercado Libre para autorizar acceso a tu cuenta de vendedor. El proceso es seguro vía OAuth 2.0.
                </div>
                {meliAuthUrl ? (
                  <a href={meliAuthUrl} className="block">
                    <Button size="sm" className="w-full h-8 text-xs gap-1.5 bg-yellow-500 hover:bg-yellow-400 text-black">
                      <ExternalLink className="h-3.5 w-3.5" /> Conectar con Mercado Libre
                    </Button>
                  </a>
                ) : (
                  <Button size="sm" className="w-full h-8 text-xs" disabled>
                    Conectar con Mercado Libre
                    <span className="ml-2 opacity-60">(configuración pendiente)</span>
                  </Button>
                )}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">Solo el Owner puede configurar integraciones.</p>
            )}
          </div>
        </div>
      </div>

      {/* Próximas integraciones */}
      <div className="rounded-xl border border-dashed border-border p-5">
        <p className="text-sm font-medium text-muted-foreground mb-3">🔜 Próximamente</p>
        <div className="flex flex-wrap gap-2">
          {['Shopify', 'WooCommerce', 'Zapier / Make', 'Stripe'].map(name => (
            <span key={name} className="px-3 py-1 rounded-lg border border-border text-xs text-muted-foreground">
              {name}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
