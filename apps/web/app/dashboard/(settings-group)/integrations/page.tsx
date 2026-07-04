import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { CORE_API_URL } from '@/lib/runtime-env'
import { IntegrationsManager } from './_components/integrations-manager'
import {
  connectAveonline as connectAveonlineCore,
  disconnectAveonline as disconnectAveonlineCore,
  testAveonline as testAveonlineCore,
} from '@/lib/aveonline-actions'

export const metadata = {
  title: 'Integraciones — Configuración',
  description: 'Conectores activos para tu negocio.',
}

type Integration  = { provider: string; status: string; meta: Record<string, string> }
type NotifSetting = { channel: string; enabled: boolean; config: Record<string, string> }

export default async function IntegrationsPage(
  props: {
    searchParams: Promise<{
      connected?: string; error?: string
      meli_same_user?: string  // baseline 2026-05-29 — campo faltante en type detectado al validar `next build`
      tg_test?: string; tg_msg?: string
      wa_test?: string; wa_msg?: string
      ave_test?: string; ave_msg?: string
    }>
  }
) {
  const searchParams = await props.searchParams;
  const supabase = await createClient()
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
  // Aveonline carriers + capabilities en panel dedicado /integrations/aveonline.

  // Métricas para hub (Iter 2): WhatsApp templates count.
  let templatesApproved = 0
  let templatesTotal = 0

  if (tenantId) {
    // Conteos con head:true (COUNT server-side) en vez de traer todas las filas
    // para contar en JS — criterio explícito de no full-fetch para contar.
    const [intRes, notifRes, tplTotalRes, tplApprovedRes] = await Promise.all([
      supabase.from('tenant_integrations').select('provider, status, meta').eq('tenant_id', tenantId),
      supabase.from('notification_settings').select('channel, enabled, config').eq('tenant_id', tenantId),
      supabase.from('whatsapp_templates')
        .select('id', { count: 'exact', head: true })
        .eq('tenant_id', tenantId),
      supabase.from('whatsapp_templates')
        .select('id', { count: 'exact', head: true })
        .eq('tenant_id', tenantId)
        .eq('status', 'APPROVED'),
    ])
    integrations  = (intRes.data as Integration[])   || []
    notifications = (notifRes.data as NotifSetting[]) || []
    templatesTotal = tplTotalRes.count ?? 0
    templatesApproved = tplApprovedRes.count ?? 0
  }

  const providers = ['aveonline', 'mercadolibre', 'whatsapp', 'wompi']
  const fullList: Integration[] = providers.map(p =>
    integrations.find(i => i.provider === p) ?? { provider: p, status: 'disconnected', meta: {} }
  )

  const aveonlineInt  = fullList.find(i => i.provider === 'aveonline')!
  const meliInt       = fullList.find(i => i.provider === 'mercadolibre')!
  const waInt         = fullList.find(i => i.provider === 'whatsapp')!
  const wompiInt      = fullList.find(i => i.provider === 'wompi')!
  const tgConfig      = notifications.find(n => n.channel === 'telegram')

  const aveonlineConnected = aveonlineInt.status === 'connected'
  const meliConnected  = meliInt.status === 'connected'
  const waConnected    = waInt.status === 'connected'
  const wompiConnected = wompiInt.status === 'connected'
  // bot_token_secret_id (vault) o bot_token (texto plano legacy) indican que el token está configurado
  const tgConnected    = !!(tgConfig?.enabled && (tgConfig?.config?.bot_token_secret_id || tgConfig?.config?.bot_token) && tgConfig?.config?.chat_id)
  const connectedCount = [aveonlineConnected, meliConnected, waConnected, tgConnected, wompiConnected].filter(Boolean).length

  // ── Server Actions ────────────────────────────────────────────────────────

  // Nota rev. 109: saveEnviaKey + disconnectEnvia eliminados. Aveonline tiene
  // sus propios server actions en /integrations/aveonline/.

  async function disconnectMeli() {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return
    // F104: llamar al endpoint DELETE (revoca el token en MeLi + BORRA los secretos de Vault + persiste
    // meta.last_disconnected_user_id). El update directo dejaba los tokens OAuth vivos y HUÉRFANOS en
    // Vault (se perdía el puntero secret_id al vaciar credentials) y MeLi seguía enviando webhooks al
    // tenant "desconectado".
    const { data: { session } } = await sb.auth.getSession()
    if (!session) return
    const res = await fetch(`${CORE_API_URL}/api/v1/integrations/meli`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${session.access_token}` },
    })
    if (!res.ok && res.status !== 204) {
      console.error('[disconnectMeli] core API', res.status)
      redirect(`/dashboard/integrations?error=${encodeURIComponent('No se pudo desconectar MeLi')}`)
    }
    revalidatePath('/dashboard/integrations')
  }

  async function saveTelegram(formData: FormData) {
    'use server'
    const sb = await createClient()
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

    if (!secretId) {
      // Vault falló — NO persistir una fila 'habilitada' con secret_id null
      // (quedaría inservible: token no recuperable pero preview visible).
      console.error('[saveTelegram] Vault upsert falló', { tenant: m.tenant_id })
      redirect(`/dashboard/integrations?error=${encodeURIComponent('No se pudo guardar el Bot Token de Telegram de forma segura (Vault). Intenta de nuevo.')}`)
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
    const sb = await createClient()
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
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const [notifRes, tenantRes] = await Promise.all([
      sb.from('notification_settings').select('config')
        .eq('tenant_id', m.tenant_id).eq('channel', 'telegram').single(),
      sb.from('tenants').select('name').eq('id', m.tenant_id).maybeSingle(),
    ])

    const cfg    = (notifRes.data?.config ?? {}) as Record<string, string>
    const chatId = cfg.chat_id
    // Tenant-centric: el mensaje test va desde el bot del tenant, no el de
    // Konvi. Cliente final = operador del tenant → ve la marca de SU tienda.
    const tenantName = (tenantRes.data?.name ?? 'Tu tienda').trim()
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
          body: JSON.stringify({ chat_id: chatId, text: `${tenantName} — Conexión Telegram verificada.` }),
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
    const sb = await createClient()
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
        const res  = await fetch(`https://graph.facebook.com/v22.0/${phoneId}`, {
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

  // Nota rev. 109: testEnvia eliminado. Aveonline tiene test endpoint en
  // /integrations/aveonline (panel dedicado).

  async function saveWhatsApp(formData: FormData) {
    'use server'
    const sb = await createClient()
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

    // ADR-0023 Phase 6: merge no-destructivo de credentials.
    // Preserva campos Model B Direct Provider per-tenant (app_id, app_secret_secret_id,
    // verify_token, integration_role, integration_type, webhook_url_path_segment,
    // business_id, notes) que el form actual NO captura pero existen en DB.
    // Sin esto, owner editando WABA + Phone + Token desde panel principal
    // SOBRESCRIBÍA toda credentials, destruyendo el shape Model B.
    const existingCredentials = (existing?.credentials as Record<string, unknown>) ?? {}
    const mergedCredentials = {
      ...existingCredentials,
      access_token_secret_id: secretId,
      phone_number_id: phoneId,
      waba_id: wabaId,
    }
    await sb.from('tenant_integrations').upsert({
      tenant_id:   m.tenant_id,
      provider:    'whatsapp',
      status:      'connected',
      credentials: mergedCredentials,
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
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    const privateKey  = (formData.get('private_key') as string)?.trim()
    const eventsKey   = (formData.get('events_key') as string)?.trim()
    const environment = (formData.get('environment') as string) === 'production' ? 'production' : 'sandbox'

    if (!privateKey || !eventsKey) {
      redirect(`/dashboard/integrations?error=${encodeURIComponent('Ingresa la Llave Privada y la Llave de Eventos de Wompi.')}`)
    }

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

    if (!privateSid || !eventsSid) {
      // Vault failure — no persistir estado incompleto. Log accionable para
      // distinguir en producción "no guardó por Vault" de otros fallos.
      console.error('[saveWompi] Vault upsert falló', {
        tenant: m.tenant_id, privateSid: !!privateSid, eventsSid: !!eventsSid,
      })
      redirect(`/dashboard/integrations?error=${encodeURIComponent('No se pudieron guardar las llaves de Wompi de forma segura (Vault). Intenta de nuevo.')}`)
    }

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
    const sb = await createClient()
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
    const sb = await createClient()
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

  // ── Aveonline (rev. 107 — hub paridad con resto de cards) ─────────────────
  // Lógica core en lib/aveonline-actions.ts. Estos wrappers solo agregan
  // verificación de permisos + redirect con flags ave_test/ave_msg.

  async function saveAveonline(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const result = await connectAveonlineCore(sb, m.tenant_id, u?.email, {
      usuario: (formData.get('usuario') as string) || '',
      password: (formData.get('password') as string) || '',
      authVersion: (formData.get('auth_version') as string) || 'v1.0',
      tiempoToken: 100000,
    })
    revalidatePath('/dashboard/integrations')
    if (!result.ok) {
      redirect(
        `/dashboard/integrations?ave_test=error&ave_msg=${encodeURIComponent(result.error ?? 'Error desconocido')}`,
      )
    }
  }

  async function disconnectAveonline() {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await disconnectAveonlineCore(sb, m.tenant_id)
    revalidatePath('/dashboard/integrations')
  }

  async function testAveonline() {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const result = await testAveonlineCore(sb, m.tenant_id)
    if (!result.ok) {
      redirect(
        `/dashboard/integrations?ave_test=error&ave_msg=${encodeURIComponent(result.error ?? 'Error desconocido')}`,
      )
    }
    redirect('/dashboard/integrations?ave_test=success')
  }

  return (
    <IntegrationsManager
      waInt={waInt}
      templatesApproved={templatesApproved}
      templatesTotal={templatesTotal}
      waConnected={waConnected}
      aveonlineInt={aveonlineInt}
      aveonlineConnected={aveonlineConnected}
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
      meliSameUser={searchParams.meli_same_user}
      tgTest={searchParams.tg_test}
      tgMsg={searchParams.tg_msg}
      waTest={searchParams.wa_test}
      waMsg={searchParams.wa_msg}
      aveTest={searchParams.ave_test}
      aveMsg={searchParams.ave_msg}
      saveAveonline={saveAveonline}
      disconnectAveonline={disconnectAveonline}
      testAveonline={testAveonline}
      disconnectMeli={disconnectMeli}
      saveWompi={saveWompi}
      disconnectWompi={disconnectWompi}
      saveTelegram={saveTelegram}
      disconnectTelegram={disconnectTelegram}
      testTelegram={testTelegram}
      testWhatsApp={testWhatsApp}
      saveWhatsApp={saveWhatsApp}
      disconnectWhatsApp={disconnectWhatsApp}
    />
  )
}
