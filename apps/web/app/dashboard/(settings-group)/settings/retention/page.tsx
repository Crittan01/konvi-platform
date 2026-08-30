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
import { PageHeader } from '@/components/ui/page-header'
import { ok, fail, type ActionResult } from '@/lib/action-result'
import RetentionPoliciesForm, {
  IMPLEMENTED_ACTION,
  type Entity,
} from './_components/retention-policies-form'

export const metadata = { title: 'Retención datos' }

type Policy = {
  id: string
  tenant_id: string | null
  entity: Entity
  ttl_days: number
  action: 'archive' | 'soft_delete' | 'hard_delete' | 'anonymize'
  enabled: boolean
}

// Descripciones en lenguaje del comerciante (no jerga de ingeniería). La ACCIÓN
// de cada entidad es fija: el cron (fn_apply_retention) SOLO implementa una acción
// por entidad; ofrecer otras (archive/anonymize) dejaba de purgar en silencio y
// creaba un riesgo de cumplimiento. Por eso la UI no permite cambiar la acción.
const ENTITY_LABELS: Record<Entity, { label: string; description: string }> = {
  messages: {
    label: 'Mensajes de WhatsApp',
    description: 'Se eliminan definitivamente los mensajes con más de N días de antigüedad. Predeterminado: 180 días.',
  },
  conversations: {
    label: 'Conversaciones',
    description: 'Se archivan (dejan de mostrarse, sin borrarse) las conversaciones sin actividad durante N días. Predeterminado: 365 días.',
  },
  contacts_inactive: {
    label: 'Contactos inactivos sin autorización de datos',
    description: 'Se archivan los contactos que nunca dieron autorización de tratamiento de datos y llevan N días sin actividad. Predeterminado: 730 días.',
  },
  pii_access_log: {
    label: 'Registro de accesos a datos personales',
    description: 'Se elimina definitivamente el registro interno de quién consultó datos personales, tras N días. Predeterminado: 365 días.',
  },
}

export default async function RetentionPoliciesPage() {
  const sb = await createClient()
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
  // F6: devuelve ActionResult (antes void con return silencioso). Además, la ACCIÓN
  // se fuerza a la única implementada por fn_apply_retention para esa entidad —
  // así un action no soportado no puede persistir aunque el form fuera manipulado.
  async function saveOverride(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb2 = await createClient()
    const { data: { user: u } } = await sb2.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return fail('No tienes permiso para configurar retención (requiere owner o manager).')
    }
    const entity = String(formData.get('entity') || '') as Entity
    const ttl = parseInt(String(formData.get('ttl_days') || '0'), 10)
    if (!(entity in IMPLEMENTED_ACTION)) return fail('Entidad de retención inválida.')
    if (!ttl || ttl < 1 || ttl > 3650) {
      return fail('El plazo debe ser un número entre 1 y 3650 días.')
    }
    const action = IMPLEMENTED_ACTION[entity]
    // Buscar override existente.
    const { data: existing, error: selErr } = await sb2
      .from('retention_policies')
      .select('id')
      .eq('tenant_id', m.tenant_id)
      .eq('entity', entity)
      .limit(1)
    if (selErr) {
      console.error('[retention.saveOverride] select tenant=%s error=%s', m.tenant_id, selErr.message)
      return fail(`No se pudo guardar: ${selErr.message}`)
    }
    let writeErr
    if (existing && existing.length > 0) {
      ({ error: writeErr } = await sb2
        .from('retention_policies')
        .update({ ttl_days: ttl, action, enabled: true, updated_at: new Date().toISOString() })
        .eq('id', existing[0].id)
        .eq('tenant_id', m.tenant_id))
    } else {
      ({ error: writeErr } = await sb2
        .from('retention_policies')
        .insert({ tenant_id: m.tenant_id, entity, ttl_days: ttl, action, enabled: true }))
    }
    if (writeErr) {
      console.error('[retention.saveOverride] write tenant=%s error=%s', m.tenant_id, writeErr.message)
      return fail(`No se pudo guardar: ${writeErr.message}`)
    }
    revalidatePath('/dashboard/settings/retention')
    return ok('Plazo de retención guardado.')
  }

  async function deleteOverride(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb2 = await createClient()
    const { data: { user: u } } = await sb2.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return fail('No tienes permiso para configurar retención (requiere owner o manager).')
    }
    const id = String(formData.get('id') || '')
    if (!id) return fail('Falta el identificador del override.')
    const { error } = await sb2
      .from('retention_policies')
      .delete()
      .eq('id', id)
      .eq('tenant_id', m.tenant_id)
    if (error) {
      console.error('[retention.deleteOverride] tenant=%s error=%s', m.tenant_id, error.message)
      return fail(`No se pudo restaurar el default: ${error.message}`)
    }
    revalidatePath('/dashboard/settings/retention')
    return ok('Restaurado al plazo predeterminado.')
  }

  return (
    <div className="space-y-5 max-w-4xl">
      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={Database}
        title="Retención de datos"
        description="Habeas Data Ley 1581/2012 Art. 4 — uso limitado y prudente. Configura cuánto tiempo se conservan los datos de tu tenant antes de purgarse automáticamente cada domingo 03:xx UTC."
      />

      <div className="rounded-xl border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-fg">
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
