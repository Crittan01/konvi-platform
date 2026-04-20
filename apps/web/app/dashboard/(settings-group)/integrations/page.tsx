import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { IntegrationsManager } from './_components/integrations-manager'

export const metadata = {
  title: 'Integraciones — Configuración — Commerce Ops',
  description: 'Conectores activos para tu negocio.',
}

const API_BASE_URL =
  process.env.API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  'https://commerce-ops-api.onrender.com'

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

  const providers = ['envia', 'mercadolibre', 'whatsapp']
  const fullList: Integration[] = providers.map(p =>
    integrations.find(i => i.provider === p) ?? { provider: p, status: 'disconnected', meta: {} }
  )

  const enviaInt  = fullList.find(i => i.provider === 'envia')!
  const meliInt   = fullList.find(i => i.provider === 'mercadolibre')!
  const waInt     = fullList.find(i => i.provider === 'whatsapp')!
  const tgConfig  = notifications.find(n => n.channel === 'telegram')

  const enviaConnected = enviaInt.status === 'connected'
  const meliConnected  = meliInt.status === 'connected'
  const waConnected    = waInt.status === 'connected'
  const tgConnected    = !!(tgConfig?.enabled && tgConfig?.config?.bot_token && tgConfig?.config?.chat_id)
  const connectedCount = [enviaConnected, meliConnected, waConnected, tgConnected].filter(Boolean).length

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
      tenant_id: m.tenant_id, provider: 'envia', status: 'connected',
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

  async function saveTelegram(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const token  = (formData.get('bot_token') as string)?.trim()
    const chatId = (formData.get('chat_id') as string)?.trim()
    await sb.from('notification_settings').upsert({
      tenant_id: m.tenant_id, channel: 'telegram', enabled: true,
      config: {
        bot_token:     token,
        chat_id:       chatId,
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
      tenant_id: m.tenant_id, channel: 'telegram', enabled: false, config: {},
    }, { onConflict: 'tenant_id,channel' })
    revalidatePath('/dashboard/integrations')
  }

  async function testTelegram() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const { data: notif } = await sb
      .from('notification_settings').select('config')
      .eq('tenant_id', m.tenant_id).eq('channel', 'telegram').single()

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
        body: JSON.stringify({ chat_id: chatId, text: '✅ Commerce Ops — Conexión Telegram verificada correctamente.' }),
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

  async function saveWhatsApp(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const wabaId  = (formData.get('waba_id') as string)?.trim()
    const phoneId = (formData.get('phone_number_id') as string)?.trim()
    const token   = (formData.get('access_token') as string)?.trim()
    await sb.from('tenant_integrations').upsert({
      tenant_id:   m.tenant_id,
      provider:    'whatsapp',
      status:      'connected',
      credentials: { access_token: token, phone_number_id: phoneId },
      meta: {
        waba_id:          wabaId,
        phone_id_preview: `${phoneId.slice(0, 6)}...${phoneId.slice(-4)}`,
        token_preview:    token.length > 12 ? `${token.slice(0, 8)}...${token.slice(-4)}` : '●●●●',
      },
    }, { onConflict: 'tenant_id,provider' })
    await sb.from('tenants').update({ meta_waba_id: wabaId }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/integrations')
  }

  async function disconnectWhatsApp() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    await sb.from('tenant_integrations').update({ status: 'disconnected', credentials: {}, meta: {} })
      .eq('tenant_id', m.tenant_id).eq('provider', 'whatsapp')
    await sb.from('tenants').update({ meta_waba_id: null }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/integrations')
  }

  return (
    <IntegrationsManager
      waInt={waInt}
      waConnected={waConnected}
      enviaInt={enviaInt}
      enviaConnected={enviaConnected}
      meliInt={meliInt}
      meliConnected={meliConnected}
      tgConfig={tgConfig}
      tgConnected={tgConnected}
      connectedCount={connectedCount}
      apiBaseUrl={API_BASE_URL}
      isOwner={isOwner}
      canWrite={canWrite}
      connectedParam={searchParams.connected}
      errorParam={searchParams.error}
      tgTest={searchParams.tg_test}
      tgMsg={searchParams.tg_msg}
      saveEnviaKey={saveEnviaKey}
      disconnectEnvia={disconnectEnvia}
      disconnectMeli={disconnectMeli}
      saveTelegram={saveTelegram}
      disconnectTelegram={disconnectTelegram}
      testTelegram={testTelegram}
      saveWhatsApp={saveWhatsApp}
      disconnectWhatsApp={disconnectWhatsApp}
    />
  )
}
