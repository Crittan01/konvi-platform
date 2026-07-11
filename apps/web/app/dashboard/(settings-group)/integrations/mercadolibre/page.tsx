/**
 * Panel Mercado Libre — restructura Integraciones Sem 7 F2 cierre.
 *
 * Tabs:
 *   - Setup: estado OAuth, seller_id, token expiration
 *   - Listings: catálogo de publicaciones (Sem 9 H.5)
 *   - Q&A: respuestas automáticas a preguntas (Sem 9 H.5.1)
 *   - Mensajes: post-venta (Sem 9 H.5.2)
 *
 * Hoy: tab Setup read-only. Conectar/desconectar sigue en /integrations
 * (manager legacy) hasta migración completa.
 */
import { createClient } from '@/utils/supabase/server'
import {
  getCachedUser, getCachedTenantMeta,
} from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import { ShoppingBag, Settings, Package, MessageCircle, Inbox } from 'lucide-react'
import PanelHeader from '../_components/panel-header'
import PanelTabs, { TabDef } from '../_components/panel-tabs'
import ComingSoon from '../_components/coming-soon'
import MeLiSetup from './_components/meli-setup'

export const metadata = {
  title: 'Mercado Libre — Integraciones',
  description: 'Gestión del canal Mercado Libre: setup, listings, Q&A, mensajes.',
}

const TABS: TabDef[] = [
  { id: 'setup',     label: 'Setup',     Icon: Settings },
  { id: 'listings',  label: 'Listings',  Icon: Package },
  { id: 'qa',        label: 'Q&A',       Icon: MessageCircle,  comingSoon: true },
  { id: 'messages',  label: 'Mensajes',  Icon: Inbox,          comingSoon: true },
]
const VALID_TABS = new Set(TABS.map(t => t.id))

export default async function MercadoLibrePanelPage(
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
      .eq('provider', 'mercadolibre')
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
  // El callback OAuth guarda el id del vendedor MeLi en meta.user_id (integrations.py) — NO en
  // meta.seller_id ni credentials.seller_id (que nunca se escriben) → antes mostraba '—' en una
  // cuenta conectada. Fallback a los campos legacy por si algún registro antiguo los tuviera.
  const sellerId = (integration?.meta_data?.user_id as string)
    ?? (integration?.meta_data?.seller_id as string)
    ?? (integration?.credentials?.seller_id as string)
    ?? null
  const metaLine = connected
    ? `Seller ID ${sellerId ?? '—'}`
    : null

  return (
    <div className="space-y-6">
      <PanelHeader
        Icon={ShoppingBag}
        title="Mercado Libre"
        connected={connected}
        metaLine={metaLine}
      />

      <PanelTabs
        basePath="/dashboard/integrations/mercadolibre"
        tabs={TABS}
        activeTab={tab}
      />

      {tab === 'setup' && (
        <MeLiSetup
          connected={connected}
          sellerId={sellerId}
        />
      )}

      {tab === 'listings' && (
        <div className="rounded-lg border border-border bg-muted/20 p-6 space-y-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Package className="h-4 w-4" />
            Catálogo de publicaciones
          </div>
          <p className="text-sm text-muted-foreground">
            El gestor de publicaciones Mercado Libre (vincular, sincronizar stock, importar) está
            disponible en el módulo Marketplace.
          </p>
          <a
            href="/dashboard/marketplace"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            Abrir gestor de Marketplace
          </a>
        </div>
      )}

      {tab === 'qa' && (
        <ComingSoon
          title="Preguntas y respuestas"
          description="Bot responde automáticamente preguntas públicas en tus publicaciones MeLi. Reusa el agente AI configurado."
          eta="Sem 9 (H.5.1)"
        />
      )}

      {tab === 'messages' && (
        <ComingSoon
          title="Mensajes post-venta"
          description="Atención automatizada vía mensajes MeLi tras una venta. Cumple políticas CBT Colombia (tiempos respuesta < 8h)."
          eta="Sem 9 (H.5.2)"
        />
      )}
    </div>
  )
}
