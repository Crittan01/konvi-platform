/**
 * Settings → Cerrar cuenta (Tenant offboarding).
 *
 * Rev. 109 J.2.4.4 Fase 2 — UI tenant-level del lifecycle de cierre.
 * Compliance Habeas Data Ley 1581 Art. 16 (derecho de eliminación) +
 * Art. 22 (custodia post-cierre).
 *
 * Owner-only. Manager/operator NO ven esta página (redirect Dashboard).
 *
 * Estados visuales:
 *   - active: 3 acciones (Exportar datos · Solicitar eliminación · Volver)
 *   - soft_deleted_grace_period: banner amber + "Cancelar eliminación"
 *   - hard_deleted: no debería ocurrir (JWT inválido tras hard-delete)
 */
import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import { TriangleAlert } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import { ClosureForm } from './_components/closure-form'

export const dynamic = 'force-dynamic'

interface OffboardingStatus {
  tenant_id: string
  state: 'active' | 'soft_deleted_grace_period' | 'hard_deleted'
  deletion_requested_at: string | null
  deletion_scheduled_for: string | null
  deletion_reason: string | null
  deleted_at: string | null
  is_recoverable: boolean
}

async function getOwnerTenant(): Promise<{ tenantId: string; tenantName: string }> {
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!meta.tenant_id || meta.role !== 'owner') {
    redirect('/dashboard')
  }
  const { data: tenant } = await sb
    .from('tenants')
    .select('name')
    .eq('id', meta.tenant_id)
    .single()
  return {
    tenantId: meta.tenant_id,
    tenantName: tenant?.name || meta.tenant_id,
  }
}

async function getOffboardingStatus(tenantId: string): Promise<OffboardingStatus | null> {
  // El status lo expone backend via /api/v1/tenant/offboarding/status, pero
  // como hay session cookie + RLS owner-only en tenant_offboarding_log, podemos
  // leer directo de la tabla tenants con campos públicos.
  const sb = await createClient()
  const { data } = await sb
    .from('tenants')
    .select('id, deletion_requested_at, deletion_scheduled_for, deletion_reason, deleted_at')
    .eq('id', tenantId)
    .single()
  if (!data) return null

  let state: OffboardingStatus['state'] = 'active'
  if (data.deleted_at) state = 'hard_deleted'
  else if (data.deletion_requested_at) state = 'soft_deleted_grace_period'

  return {
    tenant_id: data.id,
    state,
    deletion_requested_at: data.deletion_requested_at,
    deletion_scheduled_for: data.deletion_scheduled_for,
    deletion_reason: data.deletion_reason,
    deleted_at: data.deleted_at,
    is_recoverable: state === 'soft_deleted_grace_period',
  }
}

export default async function AccountClosurePage() {
  const { tenantId, tenantName } = await getOwnerTenant()
  const status = await getOffboardingStatus(tenantId)

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={TriangleAlert}
        title="Cerrar cuenta"
        description="Gestiona la eliminación de tu cuenta y la portabilidad de tus datos conforme a la Ley 1581 (Habeas Data)."
      />

      <ClosureForm
        tenantId={tenantId}
        tenantName={tenantName}
        status={status}
      />

      <footer className="text-xs text-muted-foreground border-t border-border pt-4 space-y-1">
        <p>
          <strong>Compliance:</strong> tu derecho a eliminación está cubierto por
          Ley 1581 Art. 16. Tu trazabilidad de consent + audit log se preserva
          5 años post-cierre (Art. 22).
        </p>
        <p>
          ¿Dudas? Escríbenos a soporte@konvi.co e indica en el asunto tu número
          de documento (el NIT o la cédula con la que registraste el negocio).
        </p>
      </footer>
    </div>
  )
}
