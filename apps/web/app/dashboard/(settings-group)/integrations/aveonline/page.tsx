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
import { Package, Settings, Boxes, ShieldCheck, Radar } from 'lucide-react'
import PanelHeader from '../_components/panel-header'
import PanelTabs, { TabDef } from '../_components/panel-tabs'
import ComingSoon from '../_components/coming-soon'
import AveonlineSetup from './_components/aveonline-setup'

export const metadata = {
  title: 'Aveonline — Integraciones',
  description: 'Gestión de logística Aveonline: auth, carriers, capacidades, tracking.',
}

const TABS: TabDef[] = [
  { id: 'setup',        label: 'Setup',       Icon: Settings },
  { id: 'carriers',     label: 'Carriers',    Icon: Boxes,       comingSoon: true },
  { id: 'capacidades',  label: 'Capacidades', Icon: ShieldCheck, comingSoon: true },
  { id: 'tracking',     label: 'Tracking',    Icon: Radar,       comingSoon: true },
]
const VALID_TABS = new Set(TABS.map(t => t.id))

// Endpoint oficial v1.0 documentado en dossier §2.1.
const AVEONLINE_AUTH_URL =
  'https://app.aveonline.co/api/comunes/v1.0/autenticarusuario.php'

export default async function AveonlinePanelPage({
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

  // ─── Server Action: connectAveonline ─────────────────────────────────────
  // O.3 — POST de prueba a autenticarusuario.php con credenciales del tenant.
  // Si status=ok extrae empresa_id + token + asesor y persiste:
  //   • tenant_integrations row con status='connected', credentials
  //     enriquecidas + JWT cacheado.
  //   • password → Vault via pgsec_create_secret (RPC en migración
  //     20260426020000_vault_setup_*).

  async function connectAveonline(
    formData: FormData,
  ): Promise<{ ok: boolean; error?: string }> {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos para conectar integraciones.' }
    }

    const usuario = ((formData.get('usuario') as string) || '').trim()
    const password = ((formData.get('password') as string) || '').trim()
    const authVersion =
      ((formData.get('auth_version') as string) || 'v1.0').trim()
    const tiempoTokenRaw =
      ((formData.get('tiempo_token') as string) || '100000').trim()

    if (!usuario || usuario.length < 3) {
      return { ok: false, error: 'Usuario requerido (mínimo 3 caracteres).' }
    }
    if (!password || password.length < 4) {
      return { ok: false, error: 'Password requerida (mínimo 4 caracteres).' }
    }
    if (!['v1.0', 'v2.0'].includes(authVersion)) {
      return { ok: false, error: 'Versión de auth inválida (use v1.0 o v2.0).' }
    }
    const tiempoToken = Math.max(
      3600, Math.min(31536000, parseInt(tiempoTokenRaw, 10) || 100000),
    )

    // POST de prueba a Aveonline para validar credenciales reales antes
    // de persistir nada. Dossier §2.1 v1.0 — el body canónico.
    let aveResp: {
      status?: string
      message?: string
      token?: string
      cuentas?: Array<{
        usuarios?: Array<{
          id?: number
          documento?: string
          nombre?: string
          razon?: string
          asesorlogistico?: string
          nombreasesor?: string
        }>
      }>
    } = {}
    try {
      const resp = await fetch(AVEONLINE_AUTH_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tipo: 'auth',
          usuario,
          clave: password,
          acceso: 'ecommerce',
          tiempoToken,
        }),
      })
      if (!resp.ok) {
        return {
          ok: false,
          error: `Aveonline retornó HTTP ${resp.status}. Revisa tu cuenta.`,
        }
      }
      aveResp = await resp.json()
    } catch (e) {
      return {
        ok: false,
        error: `No pudimos conectar con Aveonline: ${
          e instanceof Error ? e.message : 'error de red'
        }`,
      }
    }

    if (aveResp.status !== 'ok' || !aveResp.token) {
      return {
        ok: false,
        error: `Aveonline rechazó las credenciales: ${
          aveResp.message || 'usuario o clave incorrectos'
        }`,
      }
    }

    // Extraer empresa_id + datos asesor desde la respuesta.
    const usuarioData = aveResp.cuentas?.[0]?.usuarios?.[0] ?? {}
    const empresaId = usuarioData.id ?? null
    const asesorLogistico = usuarioData.asesorlogistico ?? null
    const nombreAsesor = usuarioData.nombreasesor ?? null
    const razonSocial = usuarioData.razon ?? null

    if (!empresaId) {
      return {
        ok: false,
        error: 'Aveonline no retornó empresa_id válido. Contacta soporte.',
      }
    }

    // Persistir password en Vault — IDEMPOTENT.
    //
    // Rev. 107 fix bug "duplicate key value violates unique constraint
    // secrets_name_idx": al reconectar un tenant que YA tenía credenciales,
    // el secret name en vault.secrets ya existe (UNIQUE). Solución: leer la
    // row actual de tenant_integrations; si existe `password_secret_id`,
    // hacer UPDATE del secret. Si no, CREATE.
    const vaultName = `${m.tenant_id}/aveonline/password`
    let secretId: string | null = null

    const { data: existingRow } = await sb
      .from('tenant_integrations')
      .select('credentials')
      .eq('tenant_id', m.tenant_id)
      .eq('provider', 'aveonline')
      .maybeSingle()

    const existingSecretId =
      (existingRow?.credentials as { password_secret_id?: string } | null)
        ?.password_secret_id ?? null

    if (existingSecretId) {
      // Reconexión — actualizar secret existente (mismo UUID, mismo name).
      const { error: updErr } = await sb.rpc('pgsec_update_secret', {
        p_id: existingSecretId,
        p_secret: password,
      })
      if (updErr) {
        return {
          ok: false,
          error: `Vault update error: ${updErr.message}`,
        }
      }
      secretId = existingSecretId
    } else {
      // Primera conexión — crear secret nuevo.
      const { data: newSecretId, error: createErr } = await sb.rpc(
        'pgsec_create_secret',
        {
          p_secret: password,
          p_name: vaultName,
          p_description: 'Aveonline password v1.0 auth',
        },
      )
      if (createErr || !newSecretId) {
        return {
          ok: false,
          error: `Vault create error: ${createErr?.message || 'no secret_id retornado'}`,
        }
      }
      secretId = newSecretId
    }

    // Calcular jwt_expires_at desde tiempoToken (segundos).
    const expiresAt = new Date(Date.now() + tiempoToken * 1000).toISOString()

    // Upsert tenant_integrations.
    const { error: upsertErr } = await sb
      .from('tenant_integrations')
      .upsert(
        {
          tenant_id: m.tenant_id,
          provider: 'aveonline',
          status: 'connected',
          credentials: {
            usuario,
            password_secret_id: secretId,
            empresa_id: empresaId,
            asesor_logistico: asesorLogistico,
            nombre_asesor: nombreAsesor,
            razon_social: razonSocial,
            jwt_token: aveResp.token,
            jwt_expires_at: expiresAt,
            tiempo_token: tiempoToken,
            auth_version: authVersion,
          },
          meta: {
            // Campos NO-sensibles, safe para mostrar en hub UI sin
            // exponer jwt_token / password_secret_id.
            connected_at: new Date().toISOString(),
            connected_by: u?.email,
            empresa_id: String(empresaId),
            auth_version: authVersion,
            razon_social: razonSocial ?? '',
            nombre_asesor: nombreAsesor ?? '',
          },
        },
        { onConflict: 'tenant_id,provider' },
      )
    if (upsertErr) {
      return {
        ok: false,
        error: `Error guardando integración: ${upsertErr.message}`,
      }
    }

    revalidatePath('/dashboard/integrations/aveonline')
    return { ok: true }
  }

  // ─── Server Action: disconnectAveonline ──────────────────────────────────

  async function disconnectAveonline(): Promise<{
    ok: boolean
    error?: string
  }> {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos.' }
    }

    // Marcar status=disconnected (no borrar row para preservar audit).
    // El password sigue en Vault — limpieza manual si tenant lo solicita
    // (Habeas Data SAR endpoint cubre eso).
    const { error } = await sb
      .from('tenant_integrations')
      .update({ status: 'disconnected' })
      .eq('tenant_id', m.tenant_id)
      .eq('provider', 'aveonline')

    if (error) return { ok: false, error: `Error: ${error.message}` }
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
  const asesorLogistico =
    integration?.credentials.asesor_logistico as string | undefined
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
        />
      )}

      {tab === 'carriers' && (
        <ComingSoon
          title="Carriers — preferencias per-tenant"
          description="Matrix de transportadoras Aveonline (Coordinadora, Servientrega, TCC, etc.) con preferencias de cotización."
          eta="Rev. 107 M.7"
        />
      )}

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
