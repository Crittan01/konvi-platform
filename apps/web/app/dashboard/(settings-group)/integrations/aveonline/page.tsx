/**
 * Panel Aveonline — rev. 107 O.2 + O.3.
 *
 * Provider alternativo a Envia (decisión ADR-0019: 1 activo per-tenant,
 * sin fallback automático). UI clona estructura de envia/page.tsx con
 * diferencia clave: si NO connected, la tab Setup expone form inline
 * (usuario + password + versión auth) para conectarse. Cuando connect
 * OK → server action persiste credenciales en Vault + tenant_integrations
 * + extrae empresa_id/asesor desde respuesta de Aveonline.
 *
 * Tabs:
 *   - Setup: form de auth o status connected con datos del asesor.
 *   - Carriers: matrix per-tenant (próximo).
 *   - Capacidades: toggles COD/insurance (próximo).
 *   - Tracking: webhook + polling (próximo).
 */
import { createClient } from '@/utils/supabase/server'
import {
  getCachedUser, getCachedTenantMeta,
} from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { Package, Settings, Boxes, ShieldCheck, Radar, BookOpen } from 'lucide-react'
import PanelHeader from '../_components/panel-header'
import PanelTabs, { TabDef } from '../_components/panel-tabs'
import ComingSoon from '../_components/coming-soon'
import AveonlineSetup from './_components/aveonline-setup'
import AveonlineCarriersSection from './_components/aveonline-carriers'
import AveonlineHowItWorks from './_components/aveonline-how-it-works'
import {
  connectAveonline as connectAveonlineCore,
  disconnectAveonline as disconnectAveonlineCore,
} from '@/lib/aveonline-actions'

export const metadata = {
  title: 'Aveonline — Integraciones',
  description: 'Gestión de logística Aveonline: auth, carriers, capacidades, tracking.',
}

const TABS: TabDef[] = [
  { id: 'setup',        label: 'Setup',         Icon: Settings },
  { id: 'carriers',     label: 'Carriers',      Icon: Boxes },
  { id: 'como-funciona',label: 'Cómo funciona', Icon: BookOpen },
  { id: 'capacidades',  label: 'Capacidades',   Icon: ShieldCheck, comingSoon: true },
  { id: 'tracking',     label: 'Tracking',      Icon: Radar,       comingSoon: true },
]
const VALID_TABS = new Set(TABS.map(t => t.id))

export default async function AveonlinePanelPage(
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

  // ─── Server Action: connectAveonline ─────────────────────────────────────
  // O.3 — POST de prueba a autenticarusuario.php con credenciales del tenant.
  // Lógica core extraída a `lib/aveonline-actions.ts` para compartir con
  // el hub `/dashboard/integrations`.

  async function connectAveonline(
    formData: FormData,
  ): Promise<{ ok: boolean; error?: string }> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos para conectar integraciones.' }
    }

    const tiempoTokenRaw =
      ((formData.get('tiempo_token') as string) || '100000').trim()
    const result = await connectAveonlineCore(sb, m.tenant_id, u?.email, {
      usuario: (formData.get('usuario') as string) || '',
      password: (formData.get('password') as string) || '',
      authVersion: (formData.get('auth_version') as string) || 'v1.0',
      tiempoToken: parseInt(tiempoTokenRaw, 10) || 100000,
    })
    if (result.ok) revalidatePath('/dashboard/integrations/aveonline')
    return result
  }

  // ─── Server Action: disconnectAveonline ──────────────────────────────────

  async function disconnectAveonline(): Promise<{
    ok: boolean
    error?: string
  }> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos.' }
    }
    const result = await disconnectAveonlineCore(sb, m.tenant_id)
    if (result.ok) revalidatePath('/dashboard/integrations/aveonline')
    return result
  }

  // ─── Server Action: saveAveonlineIdagente ────────────────────────────────
  //
  // `idagente` (ID del punto de despacho / agencia de envío) es REQUERIDO
  // por el endpoint `generarGuia2` de AveCRM — sin él Aveonline rechaza
  // la generación con error 999 "El nombre del remitente no existe.
  // Valide el Idagente" (dossier §3.5).
  //
  // Hoy `aveonline_client.py` lo lee de `credentials.idagente`. Esta acción
  // permite al owner configurarlo desde la UI sin necesidad de SQL manual.

  async function saveAveonlineIdagente(
    formData: FormData,
  ): Promise<{ ok: boolean; error?: string }> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos.' }
    }

    const idagenteRaw = ((formData.get('idagente') as string) || '').trim()
    // Validación: numérico (Aveonline usa IDs enteros), 1-10 dígitos.
    if (idagenteRaw && !/^\d{1,10}$/.test(idagenteRaw)) {
      return {
        ok: false,
        error: 'ID Agente debe ser numérico (1-10 dígitos).',
      }
    }

    const { data: existing, error: readErr } = await sb
      .from('tenant_integrations')
      .select('credentials, meta')
      .eq('tenant_id', m.tenant_id)
      .eq('provider', 'aveonline')
      .maybeSingle()
    if (readErr) return { ok: false, error: `Error DB: ${readErr.message}` }
    if (!existing) {
      return {
        ok: false,
        error: 'Aveonline no está conectado. Conecta primero la cuenta.',
      }
    }

    const creds = (existing.credentials ?? {}) as Record<string, unknown>
    const meta = (existing.meta ?? {}) as Record<string, unknown>

    const { error: updErr } = await sb
      .from('tenant_integrations')
      .update({
        credentials: { ...creds, idagente: idagenteRaw || null },
        meta: { ...meta, idagente: idagenteRaw || null },
      })
      .eq('tenant_id', m.tenant_id)
      .eq('provider', 'aveonline')

    if (updErr) return { ok: false, error: `Error: ${updErr.message}` }
    revalidatePath('/dashboard/integrations/aveonline')
    return { ok: true }
  }

  // ─── Lookup data ──────────────────────────────────────────────────────────

  let integration: {
    status: string
    credentials: Record<string, unknown>
    meta_data: Record<string, unknown>
  } | null = null

  if (tenantId) {
    const integRes = await supabase
      .from('tenant_integrations')
      .select('status, credentials, meta')
      .eq('tenant_id', tenantId)
      .eq('provider', 'aveonline')
      .maybeSingle()

    if (integRes.data) {
      integration = {
        status: integRes.data.status ?? 'disconnected',
        credentials: (integRes.data.credentials ?? {}) as Record<string, unknown>,
        meta_data: (integRes.data.meta ?? {}) as Record<string, unknown>,
      }
    }
  }

  const connected = integration?.status === 'connected'
  const empresaId = integration?.credentials.empresa_id as number | undefined
  const nombreAsesor =
    integration?.credentials.nombre_asesor as string | undefined
  const authVersion =
    (integration?.credentials.auth_version as string) ?? 'v1.0'

  const metaLine = connected
    ? `Empresa: ${empresaId ?? '—'} · Asesor: ${nombreAsesor ?? '—'} · Auth: ${authVersion}`
    : null

  return (
    <div className="space-y-6">
      <PanelHeader
        Icon={Package}
        title="Aveonline"
        connected={connected}
        metaLine={metaLine}
      />

      <PanelTabs
        basePath="/dashboard/integrations/aveonline"
        tabs={TABS}
        activeTab={tab}
      />

      {tab === 'setup' && (
        <AveonlineSetup
          connected={connected}
          credentials={integration?.credentials ?? {}}
          connectAction={connectAveonline}
          disconnectAction={disconnectAveonline}
          saveIdagenteAction={saveAveonlineIdagente}
        />
      )}

      {tab === 'carriers' && <AveonlineCarriersSection />}

      {tab === 'como-funciona' && <AveonlineHowItWorks />}

      {tab === 'capacidades' && (
        <ComingSoon
          title="Capacidades — COD + Insurance"
          description="Toggle contraentrega (Ecart Pay) + estrategia de valor declarado."
          eta="Rev. 107 M.6"
        />
      )}

      {tab === 'tracking' && (
        <ComingSoon
          title="Tracking — webhook + polling"
          description="Webhook AveCRM + polling backup cada 6h cuando webhooks fallan."
          eta="Rev. 107 M.8"
        />
      )}
    </div>
  )
}
