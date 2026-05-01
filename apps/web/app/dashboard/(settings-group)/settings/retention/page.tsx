// Rev. 101 (F4) — UI configuración retention policies per-tenant.
//
// Tabla `retention_policies`: defaults globales (tenant_id IS NULL) cubren
// a todos los tenants. Cuando el tenant override una entity, se inserta
// una fila con su tenant_id; pg_cron domingos 03:xx UTC aplica la
// política efectiva (override > default).
//
// Habeas Data Ley 1581/2012 Art. 4 (uso limitado y prudente) + Art. 11
// exigen que el responsable defina plazos razonables. Esta UI permite
// al tenant ajustar default global (180/365/730d).

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Database } from 'lucide-react'
import RetentionPoliciesForm from './_components/retention-policies-form'

type Policy = {
  id: string
  tenant_id: string | null
  entity: 'messages' | 'conversations' | 'contacts_inactive' | 'pii_access_log'
  ttl_days: number
  action: 'archive' | 'soft_delete' | 'hard_delete' | 'anonymize'
  enabled: boolean
}

const ENTITY_LABELS: Record<Policy['entity'], { label: string; description: string }> = {
  messages: {
    label: 'Mensajes WhatsApp',
    description: 'Hard delete tras N días desde created_at. Default 180.',
  },
  conversations: {
    label: 'Conversaciones',
    description: 'Soft delete (archived_at) tras N días sin actividad. Default 365.',
  },
  contacts_inactive: {
    label: 'Contactos inactivos sin consent',
    description: 'Soft delete (deleted_at) si consent_given=false y no hay actividad. Default 730.',
  },
  pii_access_log: {
    label: 'Logs de acceso a PII',
    description: 'Hard delete tras N días desde accessed_at. Default 365.',
  },
}

export default async function RetentionPoliciesPage() {
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const canWrite = ['owner', 'manager'].includes(meta.role ?? '')

  // Cargar defaults globales + overrides del tenant.
  const { data: defaultsData } = await sb
    .from('retention_policies')
    .select('id, tenant_id, entity, ttl_days, action, enabled')
    .is('tenant_id', null)
    .eq('enabled', true)

  let overridesData: Policy[] = []
  if (tenantId) {
    const { data } = await sb
      .from('retention_policies')
      .select('id, tenant_id, entity, ttl_days, action, enabled')
      .eq('tenant_id', tenantId)
    overridesData = (data ?? []) as Policy[]
  }

  const defaults = (defaultsData ?? []) as Policy[]

  // Server action: guarda override per-tenant (upsert).
  async function saveOverride(formData: FormData) {
    'use server'
    const sb2 = createClient()
    const { data: { user: u } } = await sb2.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const entity = String(formData.get('entity') || '') as Policy['entity']
    const ttl = parseInt(String(formData.get('ttl_days') || '0'), 10)
    const action = String(formData.get('action') || '') as Policy['action']
    if (!entity || !ttl || ttl < 1 || ttl > 3650 || !action) return
    // Buscar override existente.
    const { data: existing } = await sb2
      .from('retention_policies')
      .select('id')
      .eq('tenant_id', m.tenant_id)
      .eq('entity', entity)
      .limit(1)
    if (existing && existing.length > 0) {
      await sb2
        .from('retention_policies')
        .update({ ttl_days: ttl, action, enabled: true, updated_at: new Date().toISOString() })
        .eq('id', existing[0].id)
    } else {
      await sb2
        .from('retention_policies')
        .insert({ tenant_id: m.tenant_id, entity, ttl_days: ttl, action, enabled: true })
    }
    revalidatePath('/dashboard/settings/retention')
  }

  async function deleteOverride(formData: FormData) {
    'use server'
    const sb2 = createClient()
    const { data: { user: u } } = await sb2.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const id = String(formData.get('id') || '')
    if (!id) return
    await sb2
      .from('retention_policies')
      .delete()
      .eq('id', id)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/settings/retention')
  }

  return (
    <div className="space-y-5 max-w-4xl">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Database className="h-5 w-5 text-primary" /> Retención de datos
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Habeas Data Ley 1581/2012 Art. 4 — uso limitado y prudente.
          Configura cuánto tiempo se conservan los datos de tu tenant
          antes de purgarse automáticamente cada domingo 03:xx UTC.
        </p>
      </div>

      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-400">
        <strong>Importante:</strong> los cambios aplican el siguiente domingo a las 03:xx UTC.
        Los audit logs ({'consent_audit_log'}) son append-only por ley y NO se purgan automáticamente.
      </div>

      <RetentionPoliciesForm
        defaults={defaults}
        overrides={overridesData}
        canWrite={canWrite}
        entityLabels={ENTITY_LABELS}
        saveAction={saveOverride}
        deleteAction={deleteOverride}
      />
    </div>
  )
}
