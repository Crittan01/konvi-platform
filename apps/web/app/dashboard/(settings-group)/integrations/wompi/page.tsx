/**
 * Panel Wompi — restructura Integraciones Sem 7 F2 cierre.
 *
 * Tabs:
 *   - Setup: 4 keys (public/private/events/integrity) + modo + webhook URL
 *   - Métodos de pago: filter por tenant (H.3.4 Sem 8)
 *   - Transacciones: lista recientes (futuro)
 *   - Refunds: solicitudes de devolución (H.3.5 P2)
 */
import { createClient } from '@/utils/supabase/server'
import {
  getCachedUser, getCachedTenantMeta,
} from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import {
  CreditCard, Settings, Wallet, ReceiptText, RotateCcw,
} from 'lucide-react'
import PanelHeader from '../_components/panel-header'
import PanelTabs, { TabDef } from '../_components/panel-tabs'
import ComingSoon from '../_components/coming-soon'
import WompiSetup from './_components/wompi-setup'

export const metadata = {
  title: 'Wompi — Integraciones',
  description: 'Gestión de pagos Wompi: setup, métodos, transacciones, refunds.',
}

const TABS: TabDef[] = [
  { id: 'setup',         label: 'Setup',          Icon: Settings },
  { id: 'metodos',       label: 'Métodos pago',   Icon: Wallet,       comingSoon: true },
  { id: 'transacciones', label: 'Transacciones',  Icon: ReceiptText,  comingSoon: true },
  { id: 'refunds',       label: 'Refunds',        Icon: RotateCcw,    comingSoon: true },
]
const VALID_TABS = new Set(TABS.map(t => t.id))

export default async function WompiPanelPage(
  props: {
    searchParams: Promise<{ tab?: string }>
  }
) {
  const searchParams = await props.searchParams;
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  if (role === 'operator') redirect('/dashboard')

  const requestedTab = (searchParams.tab || 'setup').toLowerCase()
  const tab = VALID_TABS.has(requestedTab) ? requestedTab : 'setup'

  const supabase = await createClient()

  let integration: {
    status: string
    credentials: Record<string, unknown>
    meta_data: Record<string, unknown>
  } | null = null

  if (tenantId) {
    const { data } = await supabase
      .from('tenant_integrations')
      .select('status, credentials, meta')
      .eq('tenant_id', tenantId)
      .eq('provider', 'wompi')
      .maybeSingle()
    if (data) {
      integration = {
        status: data.status ?? 'disconnected',
        credentials: (data.credentials ?? {}) as Record<string, unknown>,
        meta_data: (data.meta ?? {}) as Record<string, unknown>,
      }
    }
  }

  const connected = integration?.status === 'connected'
  const mode = (integration?.meta_data?.mode as string) ?? (connected ? 'producción' : null)
  const merchantId = (integration?.meta_data?.merchant_id as string)
    ?? (integration?.credentials?.merchant_id as string)
    ?? null

  const metaLine = connected
    ? [merchantId ? `Merchant ${merchantId}` : null, mode ? `Modo ${mode}` : null]
      .filter(Boolean)
      .join(' · ')
    : null

  return (
    <div className="space-y-6">
      <PanelHeader
        Icon={CreditCard}
        title="Wompi"
        connected={connected}
        metaLine={metaLine}
      />

      <PanelTabs
        basePath="/dashboard/integrations/wompi"
        tabs={TABS}
        activeTab={tab}
      />

      {tab === 'setup' && (
        <WompiSetup
          connected={connected}
          credentials={integration?.credentials ?? {}}
          mode={mode}
        />
      )}

      {tab === 'metodos' && (
        <ComingSoon
          title="Métodos de pago habilitados"
          description="Elegí qué métodos ofrecer en checkout (Tarjeta, PSE, Nequi, Daviplata, etc.). Filter per-tenant."
          eta="Sem 8 (H.3.4)"
        />
      )}

      {tab === 'transacciones' && (
        <ComingSoon
          title="Transacciones recientes"
          description="Listado de pagos últimos 30 días con status (APPROVED, DECLINED, PENDING), montos y enlaces a la orden."
          eta="Próximo"
        />
      )}

      {tab === 'refunds' && (
        <ComingSoon
          title="Devoluciones y disputas"
          description="Solicitar refund vía API Wompi + tracking del estado. Compliance con dispute SLA."
          eta="Sem 11 (H.3.5)"
        />
      )}
    </div>
  )
}
