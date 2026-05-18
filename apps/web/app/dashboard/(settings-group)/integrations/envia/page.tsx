/**
 * Panel Envia — restructura Integraciones Sem 7 F2 cierre.
 *
 * Tabs:
 *   - Setup: API key, ambiente, DANE origen
 *   - Carriers: matrix de preferencias per-tenant (H.2.7) — movido del manager legacy
 *   - Capacidades: toggles Fase 2 (H.2.6) — movido del manager legacy
 *   - COD: contraentrega Ecart Pay (H.2.4 — pausado V.1/V.4)
 *   - Tracking: polling + webhook status (Sem 8)
 */
import { createClient } from '@/utils/supabase/server'
import {
  getCachedUser, getCachedTenantMeta,
} from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import {
  Truck, Settings, Boxes, ShieldCheck, Banknote, Radar,
} from 'lucide-react'
import PanelHeader from '../_components/panel-header'
import PanelTabs, { TabDef } from '../_components/panel-tabs'
import ComingSoon from '../_components/coming-soon'
import EnviaSetup from './_components/envia-setup'
import EnviaCarriersSection, {
  EnviaCarrierPref,
} from './_components/envia-carriers-section'
import EnviaCapabilitiesSection from './_components/envia-capabilities-section'

export const metadata = {
  title: 'Envia — Integraciones',
  description: 'Gestión de logística Envia: setup, carriers, capacidades, COD, tracking.',
}

const TABS: TabDef[] = [
  { id: 'setup',         label: 'Setup',        Icon: Settings },
  { id: 'carriers',      label: 'Carriers',     Icon: Boxes },
  { id: 'capacidades',   label: 'Capacidades',  Icon: ShieldCheck },
  { id: 'cod',           label: 'COD',          Icon: Banknote, comingSoon: true },
  { id: 'tracking',      label: 'Tracking',     Icon: Radar,    comingSoon: true },
]
const VALID_TABS = new Set(TABS.map(t => t.id))

export default async function EnviaPanelPage({
  searchParams,
}: {
  searchParams: { tab?: string }
}) {
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  if (role === 'operator') redirect('/dashboard')

  const requestedTab = (searchParams.tab || 'setup').toLowerCase()
  const tab = VALID_TABS.has(requestedTab) ? requestedTab : 'setup'

  const supabase = createClient()

  // ─── Server Actions (movidas desde /integrations/page.tsx Sem 7 F2) ───────

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
    revalidatePath('/dashboard/integrations/envia')
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
    revalidatePath('/dashboard/integrations/envia')
    return { ok: true }
  }

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
    revalidatePath('/dashboard/integrations/envia')
    return { ok: true }
  }

  // ─── Lookup data ──────────────────────────────────────────────────────────

  let integration: {
    status: string
    credentials: Record<string, unknown>
    meta_data: Record<string, unknown>
  } | null = null
  let carriersEnabled = 0
  let carrierPrefs: EnviaCarrierPref[] = []
  const capabilities: Record<string, boolean> = {}

  if (tenantId) {
    const [integRes, carrCountRes, carrAllRes, capsRes] = await Promise.all([
      supabase
        .from('tenant_integrations')
        .select('status, credentials, meta')
        .eq('tenant_id', tenantId)
        .eq('provider', 'envia')
        .maybeSingle(),
      supabase
        .from('tenant_carriers')
        .select('carrier_code', { count: 'exact', head: true })
        .eq('tenant_id', tenantId)
        .eq('provider', 'envia')
        .eq('enabled', true),
      supabase
        .from('tenant_carriers')
        .select('carrier_code, enabled, display_label, priority, notes')
        .eq('tenant_id', tenantId)
        .eq('provider', 'envia')
        .order('priority', { ascending: true })
        .order('carrier_code', { ascending: true }),
      supabase
        .from('tenant_provider_capabilities')
        .select('capability, enabled')
        .eq('tenant_id', tenantId)
        .eq('provider', 'envia'),
    ])
    if (integRes.data) {
      integration = {
        status: integRes.data.status ?? 'disconnected',
        credentials: (integRes.data.credentials ?? {}) as Record<string, unknown>,
        meta_data: (integRes.data.meta ?? {}) as Record<string, unknown>,
      }
    }
    carriersEnabled = carrCountRes.count ?? 0
    carrierPrefs = (carrAllRes.data as EnviaCarrierPref[] | null) ?? []
    for (const r of (capsRes.data as Array<{ capability: string; enabled: boolean }>) || []) {
      capabilities[r.capability] = r.enabled
    }
  }

  const connected = integration?.status === 'connected'
  const sandbox = !!(integration?.meta_data?.sandbox)
  const danePostal = (integration?.meta_data?.dane_postal as string) ?? null
  const ambienteLabel = sandbox ? 'Sandbox' : 'Producción'

  const metaLine = connected
    ? `Ambiente: ${ambienteLabel} · ${carriersEnabled} carriers habilitados`
    : null

  return (
    <div className="space-y-6">
      <PanelHeader
        Icon={Truck}
        title="Envia"
        connected={connected}
        metaLine={metaLine}
      />

      <PanelTabs
        basePath="/dashboard/integrations/envia"
        tabs={TABS}
        activeTab={tab}
      />

      {tab === 'setup' && (
        <EnviaSetup
          connected={connected}
          credentials={integration?.credentials ?? {}}
          sandbox={sandbox}
          danePostal={danePostal}
        />
      )}

      {tab === 'carriers' && (
        connected ? (
          <EnviaCarriersSection
            prefs={carrierPrefs}
            upsertAction={upsertEnviaCarrier}
            resetAction={resetEnviaCarrierPref}
          />
        ) : (
          <ComingSoon
            title="Conectá Envia primero"
            description="Configurá tu API token en la tab Setup para empezar a gestionar carriers."
          />
        )
      )}

      {tab === 'capacidades' && (
        connected ? (
          <EnviaCapabilitiesSection
            capabilities={capabilities}
            toggleAction={toggleEnviaCapability}
          />
        ) : (
          <ComingSoon
            title="Conectá Envia primero"
            description="Configurá tu API token en la tab Setup para habilitar capabilities Fase 2."
          />
        )
      )}

      {tab === 'cod' && (
        <ComingSoon
          title="Contraentrega (Ecart Pay)"
          description="Configurar carriers con soporte de pago contra entrega + ledger de cobros."
          eta="Sem 9+ (H.2.4 — pendiente validaciones V.1/V.4)"
        />
      )}

      {tab === 'tracking' && (
        <ComingSoon
          title="Tracking + polling de respaldo"
          description="Estado de webhooks Envia + métrica polling_diff_rate. Alertas cuando webhooks fallan."
          eta="Sem 8 (H.2.3 dashboard)"
        />
      )}
    </div>
  )
}
