import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { IntegrationsManager } from './_components/integrations-manager'

export const metadata = {
  title: 'Integraciones — Configuración — Commerce Ops',
  description: 'Conectores activos para tu negocio.',
}

type Integration  = { provider: string; status: string; meta: Record<string, string> }
type NotifSetting = { channel: string; enabled: boolean; config: Record<string, string> }

export default async function IntegrationsPage({
  searchParams,
}: {
  searchParams: {
    connected?: string; error?: string
    tg_test?: string; tg_msg?: string
    wa_test?: string; wa_msg?: string
    envia_test?: string; envia_msg?: string
  }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta     = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role     = meta.role ?? 'operator'
  const isOwner  = role === 'owner'
  const canWrite = role === 'owner' || role === 'manager'

  // Protección por navegación directa — operators no acceden a esta página
  if (role === 'operator') redirect('/dashboard')

  let integrations: Integration[]  = []
  let notifications: NotifSetting[] = []
  let enviaCarrierPrefs: Array<{
    carrier_code: string
    enabled: boolean
    display_label: string | null
    priority: number
    notes: string | null
  }> = []
  // Sem 5 H.2.6 — capabilities Envia per-tenant (label_generation,
  // tracking_polling, pickup, cancel) leídas de F.3 matrix.
  const enviaCapabilities: Record<string, boolean> = {}

  if (tenantId) {
    const [intRes, notifRes, carrRes, capsRes] = await Promise.all([
      supabase.from('tenant_integrations').select('provider, status, meta').eq('tenant_id', tenantId),
      supabase.from('notification_settings').select('channel, enabled, config').eq('tenant_id', tenantId),
      supabase.from('tenant_carriers')
        .select('carrier_code, enabled, display_label, priority, notes')
        .eq('tenant_id', tenantId)
        .eq('provider', 'envia')
        .order('priority', { ascending: true })
        .order('carrier_code', { ascending: true }),
      supabase.from('tenant_provider_capabilities')
        .select('capability, enabled')
        .eq('tenant_id', tenantId)
        .eq('provider', 'envia'),
    ])
    integrations  = (intRes.data as Integration[])   || []
    notifications = (notifRes.data as NotifSetting[]) || []
    enviaCarrierPrefs = (carrRes.data as typeof enviaCarrierPrefs) || []
    for (const r of (capsRes.data as Array<{ capability: string; enabled: boolean }>) || []) {
      enviaCapabilities[r.capability] = r.enabled
    }
  }

  const providers = ['envia', 'mercadolibre', 'whatsapp', 'wompi']
  const fullList: Integration[] = providers.map(p =>
    integrations.find(i => i.provider === p) ?? { provider: p, status: 'disconnected', meta: {} }
  )

  const enviaInt  = fullList.find(i => i.provider === 'envia')!
  const meliInt   = fullList.find(i => i.provider === 'mercadolibre')!
  const waInt     = fullList.find(i => i.provider === 'whatsapp')!
  const wompiInt  = fullList.find(i => i.provider === 'wompi')!
  const tgConfig  = notifications.find(n => n.channel === 'telegram')

  const enviaConnected = enviaInt.status === 'connected'
  const meliConnected  = meliInt.status === 'connected'
  const waConnected    = waInt.status === 'connected'
  const wompiConnected = wompiInt.status === 'connected'
  // bot_token_secret_id (vault) o bot_token (texto plano legacy) indican que el token está configurado
  const tgConnected    = !!(tgConfig?.enabled && (tgConfig?.config?.bot_token_secret_id || tgConfig?.config?.bot_token) && tgConfig?.config?.chat_id)
  const connectedCount = [enviaConnected, meliConnected, waConnected, tgConnected, wompiConnected].filter(Boolean).length

  // ── Server Actions ────────────────────────────────────────────────────────

  async function saveEnviaKey(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const token   = formData.get('api_token') as string
    const sandbox = formData.get('sandbox') === 'on'

    const { data: existing } = await sb.from('tenant_integrations').select('credentials')
      .eq('tenant_id', m.tenant_id).eq('provider', 'envia').maybeSingle()
    const existingSid = (existing?.credentials as Record<string, string>)?.api_token_secret_id

    let secretId: string | null = null
    if (existingSid) {
      await sb.rpc('pgsec_update_secret', { p_id: existingSid, p_secret: token })
      secretId = existingSid
    } else {
      const { data } = await sb.rpc('pgsec_upsert_secret', {
        p_secret: token, p_name: `${m.tenant_id}/envia/api_token`, p_description: 'Envia API token',
      })
      secretId = data as string | null
    }

    await sb.from('tenant_integrations').upsert({
      tenant_id: m.tenant_id, provider: 'envia', status: 'connected',
      credentials: { api_token_secret_id: secretId, sandbox },
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
    const { data: existing } = await sb.from('tenant_integrations').select('credentials')
      .eq('tenant_id', m.tenant_id).eq('provider', 'envia').maybeSingle()
    const sid = (existing?.credentials as Record<string, string>)?.api_token_secret_id
    if (sid) await sb.rpc('pgsec_delete_secret', { p_id: sid })
    await sb.from('tenant_integrations').update({ status: 'disconnected', credentials: {} })
      .eq('tenant_id', m.tenant_id).eq('provider', 'envia')
    revalidatePath('/dashboard/integrations')
  }

  // ── Sem 5 H.2.7 — Carriers preferences per-tenant ──────────────────────────
  async function upsertEnviaCarrier(
    formData: FormData,
  ): Promise<{ ok: boolean; error?: string }> {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos.' }
    }
    const code = ((formData.get('carrier_code') as string) || '').trim()
    if (!code || !code.match(/^[A-Za-z][A-Za-z0-9_-]{1,63}$/)) {
      return { ok: false, error: 'Código de carrier inválido.' }
    }
    const enabled = formData.get('enabled') === 'true'
    const priorityRaw = ((formData.get('priority') as string) || '100').trim()
    const priority = Math.max(0, Math.min(999, parseInt(priorityRaw, 10) || 100))
    const notes = ((formData.get('notes') as string) || '').trim() || null
    const displayLabel =
      ((formData.get('display_label') as string) || '').trim() || null

    const { error } = await sb
      .from('tenant_carriers')
      .upsert(
        {
          tenant_id: m.tenant_id,
          provider: 'envia',
          carrier_code: code,
          enabled,
          display_label: displayLabel,
          priority,
          notes,
        },
        { onConflict: 'tenant_id,provider,carrier_code' },
      )
    if (error) return { ok: false, error: `Error: ${error.message}` }
    revalidatePath('/dashboard/integrations')
    return { ok: true }
  }

  async function resetEnviaCarrierPref(
    formData: FormData,
  ): Promise<{ ok: boolean; error?: string }> {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos.' }
    }
    const code = ((formData.get('carrier_code') as string) || '').trim()
    if (!code) return { ok: false, error: 'Código requerido.' }
    const { error } = await sb
      .from('tenant_carriers')
      .delete()
      .eq('tenant_id', m.tenant_id)
      .eq('provider', 'envia')
      .eq('carrier_code', code)
    if (error) return { ok: false, error: `Error: ${error.message}` }
    revalidatePath('/dashboard/integrations')
    return { ok: true }
  }

  // ── Sem 5 H.2.6 — Capabilities Fase 2 toggles per-tenant ────────────────────
  async function toggleEnviaCapability(
    formData: FormData,
  ): Promise<{ ok: boolean; error?: string }> {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos.' }
    }
    const VALID_CAPS = new Set(['label_generation', 'tracking_polling', 'pickup', 'cancel'])
    const capability = ((formData.get('capability') as string) || '').trim()
    if (!VALID_CAPS.has(capability)) {
      return { ok: false, error: 'Capability inválida.' }
    }
    const enabled = formData.get('enabled') === 'true'
    const { error } = await sb
      .from('tenant_provider_capabilities')
      .upsert(
        {
          tenant_id: m.tenant_id,
          provider: 'envia',
          capability,
          enabled,
          config: {},
        },
        { onConflict: 'tenant_id,provider,capability' },
      )
    if (error) return { ok: false, error: `Error: ${error.message}` }
    revalidatePath('/dashboard/integrations')
    return { ok: true }
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

    // Leer secret_id existente para update vs create
    const { data: existing } = await sb.from('notification_settings').select('config')
      .eq('tenant_id', m.tenant_id).eq('channel', 'telegram').maybeSingle()
    const existingSid = (existing?.config as Record<string, string>)?.bot_token_secret_id

    let secretId: string | null = null
    if (existingSid) {
      await sb.rpc('pgsec_update_secret', { p_id: existingSid, p_secret: token })
      secretId = existingSid
    } else {
      const { data } = await sb.rpc('pgsec_upsert_secret', {
        p_secret: token,
        p_name: `${m.tenant_id}/telegram/bot_token`,
        p_description: 'Telegram bot token',
      })
      secretId = data as string | null
    }

    await sb.from('notification_settings').upsert({
      tenant_id: m.tenant_id, channel: 'telegram', enabled: true,
      config: {
        bot_token_secret_id: secretId,
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
    const { data: existing } = await sb.from('notification_settings').select('config')
      .eq('tenant_id', m.tenant_id).eq('channel', 'telegram').maybeSingle()
    const sid = (existing?.config as Record<string, string>)?.bot_token_secret_id
    if (sid) await sb.rpc('pgsec_delete_secret', { p_id: sid })
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
    const chatId = cfg.chat_id
    // Leer token desde Vault
    const { data: token } = cfg.bot_token_secret_id
      ? await sb.rpc('pgsec_read_secret', { p_id: cfg.bot_token_secret_id })
      : { data: cfg.bot_token ?? null }  // fallback texto plano

    if (!token || !chatId) {
      redirect('/dashboard/integrations?tg_test=error&tg_msg=Configuraci%C3%B3n+incompleta.+Guarda+el+Bot+Token+y+Chat+ID+primero.')
    }

    let telegramError: string | null = null
    try {
      // AbortController manual en lugar de AbortSignal.timeout para mayor compatibilidad
      const controller = new AbortController()
      const timeout    = setTimeout(() => controller.abort(), 15000)
      try {
        const res  = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_id: chatId, text: 'Commerce Ops — Conexión Telegram verificada.' }),
          signal: controller.signal,
        })
        clearTimeout(timeout)
        const json = await res.json() as { ok: boolean; description?: string; error_code?: number }
        if (!json.ok) {
          telegramError = json.description
            ? `[${json.error_code ?? '?'}] ${json.description}`
            : 'Respuesta inválida de Telegram'
        }
      } finally {
        clearTimeout(timeout)
      }
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : 'error desconocido'
      if (detail.includes('abort') || detail.includes('timeout')) {
        telegramError = 'Tiempo de espera agotado. Telegram tardó más de 15s en responder.'
      } else {
        telegramError = `Error al contactar Telegram. Detalle: ${detail}`
      }
    }

    if (telegramError) {
      redirect(`/dashboard/integrations?tg_test=error&tg_msg=${encodeURIComponent(telegramError)}`)
    }
    redirect('/dashboard/integrations?tg_test=success')
  }

  async function testWhatsApp() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    const { data: waRow } = await sb.from('tenant_integrations')
      .select('credentials').eq('tenant_id', m.tenant_id).eq('provider', 'whatsapp').maybeSingle()

    const creds    = (waRow?.credentials as Record<string, string>) ?? {}
    const phoneId  = creds.phone_number_id
    const secretId = creds.access_token_secret_id
    const { data: token } = secretId
      ? await sb.rpc('pgsec_read_secret', { p_id: secretId })
      : { data: null }

    if (!phoneId || !token) {
      redirect('/dashboard/integrations?wa_test=error&wa_msg=Credenciales+incompletas.+Reconecta+WhatsApp.')
    }

    // Patrón correcto: redirect() NO puede ir dentro de try/catch
    // — Next.js lo implementa como throw y el catch lo interceptaría
    let waError: string | null = null
    try {
      const controller = new AbortController()
      const timeout    = setTimeout(() => controller.abort(), 10000)
      try {
        const res  = await fetch(`https://graph.facebook.com/v21.0/${phoneId}`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        })
        clearTimeout(timeout)
        const json = await res.json() as { error?: { message?: string } }
        if (!res.ok) {
          waError = json.error?.message ?? `Error ${res.status}`
        }
      } finally {
        clearTimeout(timeout)
      }
    } catch (err) {
      waError = err instanceof Error ? err.message : 'No se pudo conectar con Meta API'
    }

    if (waError) {
      redirect(`/dashboard/integrations?wa_test=error&wa_msg=${encodeURIComponent(waError)}`)
    }
    redirect('/dashboard/integrations?wa_test=success')
  }

  async function testEnvia() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    const { data: enviaRow } = await sb.from('tenant_integrations')
      .select('credentials, meta').eq('tenant_id', m.tenant_id).eq('provider', 'envia').maybeSingle()

    const secretId  = (enviaRow?.credentials as Record<string, string>)?.api_token_secret_id
    const isSandbox = (enviaRow?.meta as Record<string, string>)?.environment === 'sandbox'
    const baseUrl   = isSandbox ? 'https://queries-test.envia.com' : 'https://queries.envia.com'

    const { data: token, error: vaultErr } = secretId
      ? await sb.rpc('pgsec_read_secret', { p_id: secretId })
      : { data: null, error: null }

    if (!token) {
      const msg = vaultErr ? `Vault error: ${vaultErr.message}` : 'API key no encontrada. Reconecta Envia.'
      redirect(`/dashboard/integrations?envia_test=error&envia_msg=${encodeURIComponent(msg)}`)
    }

    // Patrón correcto: redirect() fuera del try/catch
    let enviaError: string | null = null
    try {
      const controller = new AbortController()
      const timeout    = setTimeout(() => controller.abort(), 15000)
      try {
        const res = await fetch(`${baseUrl}/available-carrier/CO/0`, {
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          signal: controller.signal,
        })
        clearTimeout(timeout)
        if (!res.ok) {
          enviaError = res.status === 401 ? 'API key inválida o expirada' : `Error ${res.status}`
        }
      } finally {
        clearTimeout(timeout)
      }
    } catch (err) {
      enviaError = err instanceof Error ? err.message : 'No se pudo conectar con Envia'
    }

    if (enviaError) {
      redirect(`/dashboard/integrations?envia_test=error&envia_msg=${encodeURIComponent(enviaError)}`)
    }
    redirect('/dashboard/integrations?envia_test=success')
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

    const { data: existing } = await sb.from('tenant_integrations').select('credentials')
      .eq('tenant_id', m.tenant_id).eq('provider', 'whatsapp').maybeSingle()
    const existingSid = (existing?.credentials as Record<string, string>)?.access_token_secret_id

    let secretId: string | null = null
    if (existingSid) {
      await sb.rpc('pgsec_update_secret', { p_id: existingSid, p_secret: token })
      secretId = existingSid
    } else {
      const { data } = await sb.rpc('pgsec_upsert_secret', {
        p_secret: token,
        p_name: `${m.tenant_id}/whatsapp/access_token`,
        p_description: 'WhatsApp access token',
      })
      secretId = data as string | null
    }

    await sb.from('tenant_integrations').upsert({
      tenant_id:   m.tenant_id,
      provider:    'whatsapp',
      status:      'connected',
      credentials: { access_token_secret_id: secretId, phone_number_id: phoneId },
      meta: {
        waba_id:          wabaId,
        phone_id_preview: `${phoneId.slice(0, 6)}...${phoneId.slice(-4)}`,
        token_preview:    token.length > 12 ? `${token.slice(0, 8)}...${token.slice(-4)}` : '●●●●',
      },
    }, { onConflict: 'tenant_id,provider' })
    await sb.from('tenants').update({ meta_waba_id: wabaId }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/integrations')
  }

  async function saveWompi(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    const privateKey  = (formData.get('private_key') as string)?.trim()
    const eventsKey   = (formData.get('events_key') as string)?.trim()
    const environment = (formData.get('environment') as string) === 'production' ? 'production' : 'sandbox'

    if (!privateKey || !eventsKey) return

    const { data: existing } = await sb.from('tenant_integrations').select('credentials')
      .eq('tenant_id', m.tenant_id).eq('provider', 'wompi').maybeSingle()
    const creds = (existing?.credentials as Record<string, string>) ?? {}

    // private_key
    let privateSid: string | null = creds.private_key_secret_id ?? null
    if (privateSid) {
      await sb.rpc('pgsec_update_secret', { p_id: privateSid, p_secret: privateKey })
    } else {
      const { data } = await sb.rpc('pgsec_upsert_secret', {
        p_secret: privateKey, p_name: `${m.tenant_id}/wompi/private_key`, p_description: 'Wompi private key',
      })
      privateSid = data as string | null
    }

    // events_key
    let eventsSid: string | null = creds.events_key_secret_id ?? null
    if (eventsSid) {
      await sb.rpc('pgsec_update_secret', { p_id: eventsSid, p_secret: eventsKey })
    } else {
      const { data } = await sb.rpc('pgsec_upsert_secret', {
        p_secret: eventsKey, p_name: `${m.tenant_id}/wompi/events_key`, p_description: 'Wompi events key',
      })
      eventsSid = data as string | null
    }

    if (!privateSid || !eventsSid) return  // Vault failure — no persistir estado incompleto

    await sb.from('tenant_integrations').upsert({
      tenant_id: m.tenant_id, provider: 'wompi', status: 'connected',
      credentials: { private_key_secret_id: privateSid, events_key_secret_id: eventsSid },
      meta: {
        environment,
        private_key_preview: `${privateKey.slice(0, 8)}...${privateKey.slice(-4)}`,
      },
    }, { onConflict: 'tenant_id,provider' })
    revalidatePath('/dashboard/integrations')
  }

  async function disconnectWompi() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    const { data: existing } = await sb.from('tenant_integrations').select('credentials')
      .eq('tenant_id', m.tenant_id).eq('provider', 'wompi').maybeSingle()
    const creds = (existing?.credentials as Record<string, string>) ?? {}
    if (creds.private_key_secret_id) await sb.rpc('pgsec_delete_secret', { p_id: creds.private_key_secret_id })
    if (creds.events_key_secret_id)  await sb.rpc('pgsec_delete_secret', { p_id: creds.events_key_secret_id })

    await sb.from('tenant_integrations').update({ status: 'disconnected', credentials: {}, meta: {} })
      .eq('tenant_id', m.tenant_id).eq('provider', 'wompi')
    revalidatePath('/dashboard/integrations')
  }

  async function disconnectWhatsApp() {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    const { data: existing } = await sb.from('tenant_integrations').select('credentials')
      .eq('tenant_id', m.tenant_id).eq('provider', 'whatsapp').maybeSingle()
    const sid = (existing?.credentials as Record<string, string>)?.access_token_secret_id
    if (sid) await sb.rpc('pgsec_delete_secret', { p_id: sid })
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
      wompiInt={wompiInt}
      wompiConnected={wompiConnected}
      tgConfig={tgConfig}
      tgConnected={tgConnected}
      connectedCount={connectedCount}
      isOwner={isOwner}
      canWrite={canWrite}
      connectedParam={searchParams.connected}
      errorParam={searchParams.error}
      tgTest={searchParams.tg_test}
      tgMsg={searchParams.tg_msg}
      waTest={searchParams.wa_test}
      waMsg={searchParams.wa_msg}
      enviaTest={searchParams.envia_test}
      enviaMsg={searchParams.envia_msg}
      saveEnviaKey={saveEnviaKey}
      disconnectEnvia={disconnectEnvia}
      enviaCarrierPrefs={enviaCarrierPrefs}
      upsertEnviaCarrier={upsertEnviaCarrier}
      resetEnviaCarrierPref={resetEnviaCarrierPref}
      enviaCapabilities={enviaCapabilities}
      toggleEnviaCapability={toggleEnviaCapability}
      disconnectMeli={disconnectMeli}
      saveWompi={saveWompi}
      disconnectWompi={disconnectWompi}
      saveTelegram={saveTelegram}
      disconnectTelegram={disconnectTelegram}
      testTelegram={testTelegram}
      testWhatsApp={testWhatsApp}
      testEnvia={testEnvia}
      saveWhatsApp={saveWhatsApp}
      disconnectWhatsApp={disconnectWhatsApp}
    />
  )
}
