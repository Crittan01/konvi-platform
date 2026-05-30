/**
 * Settings → Salud de mis integraciones (Tenant Console).
 *
 * Rev. 109 J.2.11 — PER-TENANT view de health metrics de las 5 integraciones.
 * Decisión arquitectónica founder 2026-05-29: vista cross-tenant founder
 * va a Platform Console (diferido). Aquí el TENANT ve la salud de SUS
 * integraciones.
 *
 * Métricas refrescadas cada 5min por cron del orchestrator (worker.py).
 * Si una métrica pasa de healthy → warning/critical, operador del tenant
 * recibe alerta Telegram (notify_escalation_async).
 */
import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import { HealthGrid } from './_components/health-grid'

export const dynamic = 'force-dynamic'

interface HealthRow {
  provider: string
  metric: string
  value: string | null
  threshold: string | null
  status: 'healthy' | 'warning' | 'critical' | 'unknown'
  detail: Record<string, unknown>
  observed_at: string
  updated_at: string
}

async function getOwnerOrManagerTenant(): Promise<string> {
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || !meta.role || !['owner', 'manager'].includes(meta.role)) {
    redirect('/dashboard')
  }
  return meta.tenant_id
}

async function getHealthMetrics(tenantId: string): Promise<HealthRow[]> {
  // RLS filtra por tenant automáticamente. Service-role NO necesario
  // porque la policy de SELECT permite authenticated del tenant correcto.
  const sb = createClient()
  const { data, error } = await sb
    .from('tenant_provider_health')
    .select('*')
    .eq('tenant_id', tenantId)
    .order('provider', { ascending: true })
    .order('metric', { ascending: true })
  if (error) {
    console.error('[health] fetch error', error)
    return []
  }
  return (data || []) as HealthRow[]
}

export default async function HealthPage() {
  const tenantId = await getOwnerOrManagerTenant()
  const metrics = await getHealthMetrics(tenantId)

  // Agrupar por provider.
  const byProvider = metrics.reduce<Record<string, HealthRow[]>>((acc, m) => {
    acc[m.provider] = acc[m.provider] || []
    acc[m.provider].push(m)
    return acc
  }, {})

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Salud de mis integraciones</h1>
        <p className="text-sm text-muted-foreground">
          Estado en tiempo real de WhatsApp, Wompi, Envia, MercadoLibre y Telegram.
          Refrescado cada 5 minutos. Si algo falla, te avisamos por Telegram.
        </p>
      </header>

      <HealthGrid byProvider={byProvider} />

      <footer className="text-xs text-muted-foreground border-t border-border pt-4">
        <p>
          ¿Una integración aparece como crítica? Revisa tu panel del proveedor o
          escribe a soporte@konvi.com.
        </p>
      </footer>
    </div>
  )
}
