/**
 * Settings → Salud de mis integraciones (Tenant Console).
 *
 * Rev. 109 J.2.11 — PER-TENANT view de health metrics de las 5 integraciones.
 * Decisión arquitectónica founder 2026-05-29: vista cross-tenant founder
 * va a Platform Console (diferido). Aquí el TENANT ve la salud de SUS
 * integraciones.
 *
 * Métricas refrescadas cada 5min por cron del orchestrator (worker.py).
 * Si una métrica sana pasa a warning/critical y el tenant tiene Telegram
 * conectado, el operador recibe una alerta (notify_escalation_async).
 */
import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import { HealthGrid } from './_components/health-grid'
import { RefreshButton } from './_components/refresh-button'
import { Activity } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import type { HealthRow } from './_components/types'

export const dynamic = 'force-dynamic'

async function getOwnerOrManagerTenant(): Promise<string> {
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !meta.role || !['owner', 'manager'].includes(meta.role)) {
    redirect('/dashboard')
  }
  return meta.tenant_id
}

async function getHealthMetrics(
  tenantId: string,
): Promise<{ rows: HealthRow[]; error: boolean }> {
  // RLS filtra por tenant automáticamente. Service-role NO necesario
  // porque la policy de SELECT permite authenticated del tenant correcto.
  const sb = await createClient()
  const { data, error } = await sb
    .from('tenant_provider_health')
    .select('*')
    .eq('tenant_id', tenantId)
    .order('provider', { ascending: true })
    .order('metric', { ascending: true })
  if (error) {
    // No lo enmascaramos como empty state: la UI muestra un error dedicado.
    console.error('[health] fetch error', error)
    return { rows: [], error: true }
  }
  return { rows: (data || []) as HealthRow[], error: false }
}

export default async function HealthPage() {
  const tenantId = await getOwnerOrManagerTenant()
  const { rows, error } = await getHealthMetrics(tenantId)

  // Agrupar por provider.
  const byProvider = rows.reduce<Record<string, HealthRow[]>>((acc, m) => {
    acc[m.provider] = acc[m.provider] || []
    acc[m.provider].push(m)
    return acc
  }, {})

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={Activity}
        title="Salud de mis integraciones"
        description="Estado de WhatsApp, Wompi, Aveonline, MercadoLibre y Telegram. Se recolecta cada 5 minutos; usa «Actualizar» para ver la última lectura. Si una integración con Telegram conectado empieza a fallar, te avisamos por ese canal."
        actions={<RefreshButton />}
      />

      <HealthGrid byProvider={byProvider} fetchError={error} />

      <footer className="text-xs text-muted-foreground border-t border-border pt-4">
        <p>
          ¿Una integración aparece como crítica? Abre su página en Integraciones
          con «Ver integración», revisa el panel del proveedor o escribe a
          soporte@konvi.co.
        </p>
      </footer>
    </div>
  )
}
