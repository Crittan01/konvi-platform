import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Plug, CheckCircle2, XCircle, AlertCircle, ExternalLink,
  Bot, SendHorizonal, ShieldCheck, Package, Store,
} from 'lucide-react'

export const metadata = {
  title: 'Integraciones — Configuración — Commerce Ops',
  description: 'Conectores activos para tu negocio.',
}

const MELI_CLIENT_ID    = process.env.MELI_CLIENT_ID ?? ''
const MELI_REDIRECT_URI = process.env.MELI_REDIRECT_URI ?? 'https://commerce-ops-api.onrender.com/api/v1/integrations/meli/callback'
const MELI_AUTH_URL     = process.env.MELI_AUTH_URL ?? 'https://auth.mercadolibre.com.co/authorization'

type Integration  = { provider: string; status: string; meta: Record<string, string> }
type NotifSetting = { channel: string; enabled: boolean; config: Record<string, string> }

export default async function IntegrationsPage({
  searchParams,
}: {
  searchParams: { connected?: string; error?: string; tg_test?: string; tg_msg?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta     = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role     = meta.role ?? 'operator'
  const isOwner  = role === 'owner'
  const canWrite = role === 'owner' || role === 'manager'

  let integrations: Integration[]  = []
  let notifications: NotifSetting[] = []

  if (tenantId) {
    const [intRes, notifRes] = await Promise.all([
      supabase.from('tenant_integrations').select('provider, status, meta').eq('tenant_id', tenantId),
      supabase.from('notification_settings').select('channel, enabled, config').eq('tenant_id', tenantId),
    ])
    integrations  = (intRes.data as Integration[])   || []
    notifications = (notifRes.data as NotifSetting[]) || []
  }

  const providers = ['envia', 'mercadolibre']
  const fullList: Integration[] = providers.map(p =>
    integrations.find(i => i.provider === p) ?? { provider: p, status: 'disconnected', meta: {} }
  )

  const enviaInt  = fullList.find(i => i.provider === 'envia')!
  const meliInt   = fullList.find(i => i.provider === 'mercadolibre')!
  const tgConfig  = notifications.find(n => n.channel === 'telegram')

  const enviaConnected = enviaInt.status === 'connected'
  const meliConnected  = meliInt.status === 'connected'
  const tgConnected    = !!(tgConfig?.enabled && tgConfig?.config?.bot_token && tgConfig?.config?.chat_id)

  const connectedCount = [enviaConnected, meliConnected, tgConnected].filter(Boolean).length

  const meliState   = tenantId ? Buffer.from(tenantId).toString('base64url') : ''
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
      meta: {
        token_preview: `${token.slice(0, 6)}...${token.slice(-4)}`,
        environment: sandbox ? 'sandbox' : 'production',
      },
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

  async function saveTelegram(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const token  = (formData.get('bot_token') as string)?.trim()
    const chatId = (formData.get('chat_id') as string)?.trim()
    await sb.from('notification_settings').upsert({
      tenant_id: m.tenant_id,
      channel:   'telegram',
      enabled:   true,
      config: {
        bot_token:     token,
        chat_id:       chatId,
        // Preview seguro para mostrar en UI sin exponer el token completo
        token_preview: token.length > 12 ? `${token.slice(0, 8)}...${token.slice(-4)}` : '●●●●',
      },
    }, { onConflict: 'tenant_id,channel' })
    revalidatePath('/dashboard/integrations')
  }

  async function disconnectTelegram() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('notification_settings').upsert({
      tenant_id: m.tenant_id,
      channel:   'telegram',
      enabled:   false,
      config:    {},
    }, { onConflict: 'tenant_id,channel' })
    revalidatePath('/dashboard/integrations')
  }

  /**
   * testTelegram — Lee el token DESDE LA DB (no del formulario).
   * Verifica la respuesta de Telegram y redirige con feedback explícito.
   * Nunca expone el token en inputs HTML ocultos.
   */
  async function testTelegram() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const { data: notif } = await sb
      .from('notification_settings')
      .select('config')
      .eq('tenant_id', m.tenant_id)
      .eq('channel', 'telegram')
      .single()

    const cfg    = (notif?.config ?? {}) as Record<string, string>
    const token  = cfg.bot_token
    const chatId = cfg.chat_id

    if (!token || !chatId) {
      redirect('/dashboard/integrations?tg_test=error&tg_msg=Configuraci%C3%B3n+incompleta.+Guarda+el+Bot+Token+y+Chat+ID+primero.')
    }

    let telegramError: string | null = null

    try {
      const res  = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chat_id: chatId,
          text:    '✅ Commerce Ops — Conexión Telegram verificada correctamente.',
        }),
      })
      const json = await res.json() as { ok: boolean; description?: string; error_code?: number }
      if (!json.ok) {
        telegramError = json.description
          ? `[${json.error_code ?? '?'}] ${json.description}`
          : 'Respuesta inválida de Telegram'
      }
    } catch {
      telegramError = 'No se pudo conectar con api.telegram.org — verifica la red del servidor.'
    }

    if (telegramError) {
      redirect(`/dashboard/integrations?tg_test=error&tg_msg=${encodeURIComponent(telegramError)}`)
    }
    redirect('/dashboard/integrations?tg_test=success')
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
          Conectores activos para tu negocio · {connectedCount}/3 conectados
        </p>
      </div>

      {/* Banners */}
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
      {searchParams.tg_test === 'success' && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-sm text-emerald-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Mensaje de prueba enviado al grupo de Telegram correctamente.
        </div>
      )}
      {searchParams.tg_test === 'error' && (
        <div className="flex items-start gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Error al probar Telegram</p>
            {searchParams.tg_msg && (
              <p className="text-xs text-red-400/80 mt-0.5 font-mono">
                {decodeURIComponent(searchParams.tg_msg)}
              </p>
            )}
            {searchParams.tg_msg?.includes('403') && (
              <p className="text-xs text-red-300/90 mt-1.5">
                El grupo fue eliminado o el bot fue expulsado. Desconecta Telegram, crea un nuevo grupo, agrega el bot como miembro y reconecta con el nuevo Chat ID.
              </p>
            )}
            {searchParams.tg_msg?.includes('400') && (
              <p className="text-xs text-red-300/90 mt-1.5">
                El Chat ID no es válido. Asegúrate de que el número es negativo (ej: -1001234567890) y pertenece a un grupo donde está el bot.
              </p>
            )}
            {searchParams.tg_msg?.includes('401') && (
              <p className="text-xs text-red-300/90 mt-1.5">
                El Bot Token es inválido o fue revocado. Desconecta y vuelve a generar el token en @BotFather → /token.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Grid de integraciones */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">

        {/* ── Envia ──────────────────────────────────────────────────────── */}
        <div className={`rounded-xl border bg-card overflow-hidden ${
          enviaConnected ? 'border-emerald-500/30' : 'border-border'
        }`}>
          <div className={`px-5 py-4 border-b ${enviaConnected ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-border bg-muted/20'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-xl bg-orange-500/15 border border-orange-500/20 flex items-center justify-center">
                  <Package className="h-5 w-5 text-orange-400" />
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
          <div className="px-5 py-4 space-y-3">
            <p className="text-xs text-muted-foreground">
              Cotiza envíos con múltiples carriers (Coordinadora, Interrapidisimo, Servientrega, DHL, FedEx...), genera etiquetas y haz tracking.
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
                  <input type="checkbox" name="sandbox" className="h-3.5 w-3.5 rounded" />
                  <span className="text-xs text-muted-foreground">Usar entorno sandbox (pruebas)</span>
                </label>
                <Button type="submit" size="sm" className="w-full h-8 text-xs">Conectar Envia</Button>
              </form>
            ) : (
              <p className="text-xs text-muted-foreground">Solo el Owner puede configurar esta integración.</p>
            )}
          </div>
        </div>

        {/* ── Mercado Libre ───────────────────────────────────────────────── */}
        <div className={`rounded-xl border bg-card overflow-hidden ${
          meliConnected ? 'border-yellow-500/30' : 'border-border'
        }`}>
          <div className={`px-5 py-4 border-b ${meliConnected ? 'border-yellow-500/20 bg-yellow-500/5' : 'border-border bg-muted/20'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-xl bg-yellow-400/15 border border-yellow-400/30 flex items-center justify-center">
                  <Store className="h-5 w-5 text-yellow-400" />
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
                  Serás redirigido a Mercado Libre para autorizar acceso a tu cuenta de vendedor vía OAuth 2.0.
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
              <p className="text-xs text-muted-foreground">Solo el Owner puede configurar esta integración.</p>
            )}
          </div>
        </div>

        {/* ── Telegram ────────────────────────────────────────────────────── */}
        <div className={`rounded-xl border bg-card overflow-hidden ${
          tgConnected ? 'border-sky-500/30' : 'border-border'
        }`}>
          <div className={`px-5 py-4 border-b ${tgConnected ? 'border-sky-500/20 bg-sky-500/5' : 'border-border bg-muted/20'}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={`h-10 w-10 rounded-xl flex items-center justify-center border ${
                  tgConnected ? 'bg-sky-500/20 border-sky-500/30' : 'bg-white/10 border-white/10'
                }`}>
                  <Bot className={`h-5 w-5 ${tgConnected ? 'text-sky-400' : 'text-muted-foreground'}`} />
                </div>
                <div>
                  <p className="font-semibold text-sm">Telegram</p>
                  <p className="text-xs text-muted-foreground">Alertas Operativas</p>
                </div>
              </div>
              <div className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border ${
                tgConnected
                  ? 'bg-sky-500/15 text-sky-400 border-sky-500/30'
                  : 'bg-muted text-muted-foreground border-border'
              }`}>
                {tgConnected ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
                {tgConnected ? 'Conectado' : 'Desconectado'}
              </div>
            </div>
          </div>
          <div className="px-5 py-4 space-y-3">
            <p className="text-xs text-muted-foreground">
              Recibe alertas de pedidos, stock bajo y reclamos en un grupo privado de Telegram. Requiere un bot creado en @BotFather.
            </p>

            {tgConnected ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg bg-muted px-3 py-2">
                    <p className="text-[10px] text-muted-foreground uppercase">Bot Token</p>
                    <p className="text-xs font-mono font-medium mt-0.5">
                      {tgConfig?.config?.token_preview ?? '●●●●●●●●'}
                    </p>
                  </div>
                  <div className="rounded-lg bg-muted px-3 py-2">
                    <p className="text-[10px] text-muted-foreground uppercase">Chat ID</p>
                    <p className="text-xs font-mono font-medium mt-0.5 truncate">
                      {tgConfig?.config?.chat_id ?? '—'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                  <ShieldCheck className="h-3 w-3 shrink-0" />
                  Alertas habilitadas
                </div>
                <div className="flex gap-2">
                  {/* Probar — lee token desde DB, no expone en HTML */}
                  <form action={testTelegram} className="flex-1">
                    <Button type="submit" size="sm" variant="outline" className="w-full h-8 text-xs gap-1.5">
                      <SendHorizonal className="h-3.5 w-3.5" /> Probar
                    </Button>
                  </form>
                  {canWrite && (
                    <form action={disconnectTelegram}>
                      <Button type="submit" size="sm" variant="outline"
                        className="h-8 text-xs text-destructive border-destructive/30 hover:bg-destructive/10">
                        Desconectar
                      </Button>
                    </form>
                  )}
                </div>
              </div>
            ) : canWrite ? (
              <div className="space-y-3">
                {/* Pasos de configuración inline */}
                <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 space-y-2">
                  <p className="text-[10px] font-semibold text-sky-400 uppercase tracking-wider">Pasos de configuración</p>
                  <div className="space-y-2.5">

                    <div className="flex gap-2">
                      <span className="h-4 w-4 rounded-full bg-sky-500/25 text-sky-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">1</span>
                      <p className="text-[11px] text-muted-foreground leading-relaxed">
                        En Telegram busca <span className="font-mono text-foreground">@BotFather</span> → escribe <span className="font-mono text-sky-400">/newbot</span> → sigue los pasos → copia el <strong className="text-foreground font-medium">Bot Token</strong>.
                      </p>
                    </div>

                    <div className="flex gap-2">
                      <span className="h-4 w-4 rounded-full bg-sky-500/25 text-sky-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">2</span>
                      <p className="text-[11px] text-muted-foreground leading-relaxed">
                        Crea un <strong className="text-foreground font-medium">grupo privado</strong> y agrega el bot como miembro.
                      </p>
                    </div>

                    <div className="flex gap-2">
                      <span className="h-4 w-4 rounded-full bg-sky-500/25 text-sky-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">3</span>
                      <div className="text-[11px] text-muted-foreground leading-relaxed space-y-1 min-w-0">
                        <p>Abre en el navegador (reemplaza <span className="text-sky-400 font-mono">TOKEN</span>):</p>
                        <p className="font-mono text-[10px] text-sky-300/80 bg-black/20 rounded px-2 py-1 break-all leading-normal">
                          api.telegram.org/bot<span className="text-sky-400">TOKEN</span>/getUpdates
                        </p>
                        <p>En el JSON busca <span className="font-mono text-foreground">"chat"</span> → <span className="font-mono text-foreground">"id"</span>: número negativo (ej: <span className="font-mono text-sky-400">-5269497288</span>).</p>
                      </div>
                    </div>

                    <div className="flex gap-2">
                      <span className="h-4 w-4 rounded-full bg-sky-500/25 text-sky-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">4</span>
                      <p className="text-[11px] text-muted-foreground leading-relaxed">
                        Ingresa el <strong className="text-foreground font-medium">Bot Token</strong> y el <strong className="text-foreground font-medium">Chat ID</strong> abajo y presiona Conectar.
                      </p>
                    </div>

                  </div>
                </div>

                {/* Formulario */}
                <form action={saveTelegram} className="space-y-3">
                  <div className="space-y-1">
                    <Label className="text-xs" htmlFor="tg-token">Bot Token</Label>
                    <Input id="tg-token" name="bot_token" type="text"
                      placeholder="123456789:AAGXcUg6Tub4XLX0Hu-S3gB0fgnjRIKEZzM"
                      required className="h-8 text-xs font-mono" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs" htmlFor="tg-chat">Chat ID del grupo</Label>
                    <Input id="tg-chat" name="chat_id"
                      placeholder="-5269497288"
                      required className="h-8 text-xs font-mono" />
                  </div>
                  <Button type="submit" size="sm" className="w-full h-8 text-xs gap-1.5">
                    <Bot className="h-3.5 w-3.5" /> Conectar Telegram
                  </Button>
                </form>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">Solo Owner o Manager pueden configurar Telegram.</p>
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
