/**
 * Panel Telegram — restructura Integraciones Sem 7 F2 cierre.
 *
 * Canal interno de notificaciones a operadores del tenant (NO clientes
 * finales). El operador recibe en SU Telegram:
 *   - Human takeover requests
 *   - Pagos pendientes > 25min (F1 cron)
 *   - Calidad WhatsApp baja
 *
 * Tabs:
 *   - Bot: bot_token + webhook + bot_username
 *   - Operadores: lista de chat_ids que reciben notificaciones
 *   - Comandos: /resolver, /estado (futuro multi-bot)
 */
import { createClient } from '@/utils/supabase/server'
import {
  getCachedUser, getCachedTenantMeta,
} from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import {
  Send, Bot, Users, Terminal,
} from 'lucide-react'
import PanelHeader from '../_components/panel-header'
import PanelTabs, { TabDef } from '../_components/panel-tabs'
import ComingSoon from '../_components/coming-soon'
import TelegramSetup from './_components/telegram-setup'

export const metadata = {
  title: 'Telegram — Integraciones',
  description: 'Canal interno de notificaciones a operadores del tenant.',
}

const TABS: TabDef[] = [
  { id: 'bot',          label: 'Bot',         Icon: Bot },
  { id: 'operadores',   label: 'Operadores',  Icon: Users,    comingSoon: true },
  { id: 'comandos',     label: 'Comandos',    Icon: Terminal, comingSoon: true },
]
const VALID_TABS = new Set(TABS.map(t => t.id))

export default async function TelegramPanelPage(
  props: {
    searchParams: Promise<{ tab?: string }>
  }
) {
  const searchParams = await props.searchParams;
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  if (role === 'operator') redirect('/dashboard')

  const requestedTab = (searchParams.tab || 'bot').toLowerCase()
  const tab = VALID_TABS.has(requestedTab) ? requestedTab : 'bot'

  const supabase = await createClient()

  let notif: {
    enabled: boolean
    config: Record<string, string>
  } | null = null

  if (tenantId) {
    const { data } = await supabase
      .from('notification_settings')
      .select('enabled, config')
      .eq('tenant_id', tenantId)
      .eq('channel', 'telegram')
      .maybeSingle()
    if (data) {
      notif = {
        enabled: !!data.enabled,
        config: (data.config ?? {}) as Record<string, string>,
      }
    }
  }

  const tokenConfigured = !!(notif?.config?.bot_token_secret_id ?? notif?.config?.bot_token)
  const chatIdConfigured = !!notif?.config?.chat_id
  const connected = !!(notif?.enabled && tokenConfigured && chatIdConfigured)

  const botUsername = notif?.config?.bot_username ?? null
  const metaLine = connected
    ? botUsername
      ? `Bot @${botUsername}`
      : 'Bot configurado'
    : null

  return (
    <div className="space-y-6">
      <PanelHeader
        Icon={Send}
        title="Telegram (operadores)"
        connected={connected}
        metaLine={metaLine}
      />

      <PanelTabs
        basePath="/dashboard/integrations/telegram"
        tabs={TABS}
        activeTab={tab}
      />

      {tab === 'bot' && (
        <TelegramSetup
          connected={connected}
          config={notif?.config ?? {}}
        />
      )}

      {tab === 'operadores' && (
        <ComingSoon
          title="Operadores que reciben notificaciones"
          description="Listado de chat_ids con su nombre + qué tipos de notificación reciben (takeovers, pagos pendientes, calidad)."
          eta="Próximo (multi-operador)"
        />
      )}

      {tab === 'comandos' && (
        <ComingSoon
          title="Comandos del bot"
          description="Configurar /resolver, /estado y otros comandos disponibles para operadores. Multi-bot per-tenant futuro."
          eta="Sem 11 (H.6.2)"
        />
      )}
    </div>
  )
}
