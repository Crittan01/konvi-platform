import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { ShieldCheck, Users } from 'lucide-react'
import AiInsightPanel from '@/components/ai-insight-panel'
import ContactsManager from './_components/contacts-manager'

type Contact = {
  id: string
  phone: string
  name: string | null
  email: string | null
  notes: string | null
  consent_given: boolean
  consent_date: string | null
  consent_source: string | null
  consent_notice_version: string | null
  consent_evidence: Record<string, unknown> | null
  consent_actor_email: string | null
  consent_revoked_at: string | null
  consent_revoked_reason: string | null
  created_at: string
  address: Record<string, string> | null
}

export default async function ContactsPage({
  searchParams,
}: {
  searchParams?: { q?: string; consent?: string }
}) {
  const normalizeDaneCode = (raw?: string | null) => {
    const digits = String(raw ?? '').replace(/\D/g, '')
    if (digits.length === 8 && digits.endsWith('000')) return digits.slice(0, 5)
    return digits.slice(0, 5)
  }

  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const canWrite = role === 'owner' || role === 'manager'

  const consentFilter = searchParams?.consent ?? 'all'
  const CONSENT_SOURCES = new Set(['manual_console', 'whatsapp', 'web_form', 'phone_call', 'in_person', 'import', 'other'])

  let contacts: Contact[] = []

  if (tenantId) {
    let query = supabase
      .from('contacts')
      .select(
        'id, phone, name, email, notes, document_type, document_number, ' +
        'consent_given, consent_date, consent_source, consent_notice_version, ' +
        'consent_evidence, consent_actor_email, consent_revoked_at, consent_revoked_reason, created_at, address'
      )
      .eq('tenant_id', tenantId)
      .order('name', { ascending: true, nullsFirst: false })

    if (consentFilter === 'yes') query = query.eq('consent_given', true)
    if (consentFilter === 'no')  query = query.eq('consent_given', false)

    const { data } = await query
    contacts = Array.isArray(data) ? (data as unknown as Contact[]) : []
  }

  // Filtros iniciales ya no se hacen de forma ruda en query,
  // traemos los primeros 500 contactos para que paginen local.
  // Solo la búsqueda full server haría falta si la DB crece mucho, pero por ahora en memoria es Nivel Pro.

  const consentCount = contacts.filter(c => c.consent_given).length
  const revokedCount = contacts.filter(c => !c.consent_given && !!c.consent_revoked_at).length

  // ── Server Actions ─────────────────────────────────────────────────────────

  async function addContact(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const nowIso = new Date().toISOString()
    const consentGiven = formData.get('consent_given') === 'on'
    const sourceRaw = ((formData.get('consent_source') as string) || '').trim()
    const consentSource = sourceRaw && CONSENT_SOURCES.has(sourceRaw) ? sourceRaw : (consentGiven ? 'manual_console' : '')
    const consentNoticeVersion = ((formData.get('consent_notice_version') as string) || '').trim()
    const consentEvidenceNote = ((formData.get('consent_evidence_note') as string) || '').trim()
    const revocationReason = ((formData.get('consent_revoked_reason') as string) || '').trim()
    const street   = (formData.get('addr_street') as string) || null
    const addrCity = (formData.get('addr_city')   as string) || null
    const daneCode = normalizeDaneCode(formData.get('addr_dane_code') as string)
    // Rev. 69 — campos estructurados de address.
    const buildingTypeRaw = (formData.get('addr_building_type') as string) || ''
    const buildingType = ['casa', 'edificio', 'conjunto'].includes(buildingTypeRaw) ? buildingTypeRaw : undefined
    const address  = street ? {
      street,
      number:        (formData.get('addr_number')        as string) || undefined,
      city:          addrCity,
      state:         (formData.get('addr_state')         as string) || undefined,
      country:       'CO',
      dane_code:     daneCode || undefined,
      neighborhood:  (formData.get('addr_neighborhood')  as string) || undefined,
      building_type: buildingType,
      tower:         (formData.get('addr_tower')         as string) || undefined,
      apartment:     (formData.get('addr_apartment')     as string) || undefined,
      complex_name:  (formData.get('addr_complex_name')  as string) || undefined,
      reference:     (formData.get('addr_reference')     as string) || undefined,
    } : null
    // Rev. 69 — documento de identidad.
    const docTypeRaw = ((formData.get('document_type') as string) || '').trim().toUpperCase()
    const docType = ['CC', 'CE', 'NIT', 'PP', 'TI', 'OTHER'].includes(docTypeRaw) ? docTypeRaw : null
    const docNumber = ((formData.get('document_number') as string) || '').replace(/[\s.]/g, '').trim() || null
    const digits = ((formData.get('phone') as string) ?? '').replace(/\D/g, '').slice(0, 10)
    if (digits.length !== 10) {
      // Antes: `return` silencioso. Ahora levantamos error visible para que
      // el operador entienda por qué no se persistió. El cliente del form
      // ya valida con HTML5 + zod-mirror; este es el último guardrail.
      throw new Error('Teléfono inválido. Debe tener 10 dígitos en Colombia.')
    }
    await sb.from('contacts').insert({
      tenant_id:     m.tenant_id,
      phone:         `+57${digits}`,
      name:          (formData.get('name') as string) || null,
      email:         (((formData.get('email') as string) || '').trim().toLowerCase()) || null,
      notes:         (formData.get('notes') as string) || null,
      // rev. 69 — solo persiste si tipo+número están AMBOS poblados (regla Wompi).
      document_type:   docType && docNumber ? docType : null,
      document_number: docType && docNumber ? docNumber : null,
      consent_given: consentGiven,
      consent_date:  consentGiven ? nowIso : null,
      consent_source: consentGiven ? consentSource : null,
      // `consent_channel` (Ley 1581 + migración 20260423000000_contacts_consent_v2):
      // canal por el que el titular dio el consentimiento. En el form web
      // siempre es 'dashboard_console'. Antes quedaba en su default 'manual'
      // generando inconsistencia con `consent_source` (que sí se llenaba).
      consent_channel: consentGiven ? 'dashboard_console' : null,
      consent_notice_version: consentGiven ? (consentNoticeVersion || null) : null,
      consent_evidence: {
        created_via: 'dashboard_contacts',
        note: consentEvidenceNote || null,
        actor_email: u?.email ?? null,
        captured_at: nowIso,
      },
      consent_actor_email: u?.email ?? null,
      consent_revoked_at: !consentGiven && revocationReason ? nowIso : null,
      consent_revoked_reason: !consentGiven ? (revocationReason || null) : null,
      address,
    })
    revalidatePath('/dashboard/contacts')
  }

  async function editContact(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const nowIso = new Date().toISOString()
    const consentGiven = formData.get('consent_given') === 'on'
    const sourceRaw = ((formData.get('consent_source') as string) || '').trim()
    const consentSource = sourceRaw && CONSENT_SOURCES.has(sourceRaw) ? sourceRaw : ''
    const consentNoticeVersion = ((formData.get('consent_notice_version') as string) || '').trim()
    const consentEvidenceNote = ((formData.get('consent_evidence_note') as string) || '').trim()
    const revocationReason = ((formData.get('consent_revoked_reason') as string) || '').trim()
    const { data: existing } = await sb.from('contacts')
      .select('consent_given, consent_date, consent_source, consent_notice_version, consent_evidence, consent_revoked_at')
      .eq('id', formData.get('contact_id') as string)
      .eq('tenant_id', m.tenant_id)
      .single()
    const prev = (existing as {
      consent_given?: boolean
      consent_date?: string | null
      consent_source?: string | null
      consent_notice_version?: string | null
      consent_evidence?: Record<string, unknown> | null
      consent_revoked_at?: string | null
    } | null)
    const street   = (formData.get('addr_street') as string) || null
    const addrCity = (formData.get('addr_city')   as string) || null
    const daneCode = normalizeDaneCode(formData.get('addr_dane_code') as string)
    // Rev. 69 — campos estructurados de address (igual que addAction).
    const editBuildingTypeRaw = (formData.get('addr_building_type') as string) || ''
    const editBuildingType = ['casa', 'edificio', 'conjunto'].includes(editBuildingTypeRaw) ? editBuildingTypeRaw : undefined
    const address  = street ? {
      street,
      number:        (formData.get('addr_number')        as string) || undefined,
      city:          addrCity,
      state:         (formData.get('addr_state')         as string) || undefined,
      country:       'CO',
      dane_code:     daneCode || undefined,
      neighborhood:  (formData.get('addr_neighborhood')  as string) || undefined,
      building_type: editBuildingType,
      tower:         (formData.get('addr_tower')         as string) || undefined,
      apartment:     (formData.get('addr_apartment')     as string) || undefined,
      complex_name:  (formData.get('addr_complex_name')  as string) || undefined,
      reference:     (formData.get('addr_reference')     as string) || undefined,
    } : null
    // Rev. 69 — documento de identidad en edit.
    const editDocTypeRaw = ((formData.get('document_type') as string) || '').trim().toUpperCase()
    const editDocType = ['CC', 'CE', 'NIT', 'PP', 'TI', 'OTHER'].includes(editDocTypeRaw) ? editDocTypeRaw : null
    const editDocNumber = ((formData.get('document_number') as string) || '').replace(/[\s.]/g, '').trim() || null
    const mergedEvidence = {
      ...((prev?.consent_evidence ?? {}) as Record<string, unknown>),
      last_update: {
        source: consentSource || prev?.consent_source || null,
        notice_version: consentNoticeVersion || prev?.consent_notice_version || null,
        note: consentEvidenceNote || null,
        actor_email: u?.email ?? null,
        at: nowIso,
      },
    }
    const shouldMarkRevoked = !consentGiven && !!prev?.consent_given
    const effectiveConsentDate = consentGiven
      ? (prev?.consent_date ?? nowIso)
      : (prev?.consent_date ?? null)
    await sb.from('contacts').update({
      name:          (formData.get('name') as string) || null,
      email:         (((formData.get('email') as string) || '').trim().toLowerCase()) || null,
      notes:         (formData.get('notes') as string) || null,
      // Rev. 69 — documento (ambos juntos o ambos null).
      document_type:   editDocType && editDocNumber ? editDocType : null,
      document_number: editDocType && editDocNumber ? editDocNumber : null,
      address,
      consent_given: consentGiven,
      consent_date: effectiveConsentDate,
      consent_source: consentSource || prev?.consent_source || null,
      // Igual que en addContact: persistimos consent_channel para Ley 1581.
      consent_channel: consentGiven ? 'dashboard_console' : null,
      consent_notice_version: consentNoticeVersion || prev?.consent_notice_version || null,
      consent_evidence: mergedEvidence,
      consent_actor_email: u?.email ?? null,
      consent_revoked_at: consentGiven ? null : (shouldMarkRevoked ? nowIso : (prev?.consent_revoked_at ?? null)),
      consent_revoked_reason: consentGiven ? null : (revocationReason || null),
    })
      .eq('id', formData.get('contact_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/contacts')
  }

  async function deleteContact(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('contacts')
      .delete()
      .eq('id', formData.get('contact_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/contacts')
  }

  // ── UI ─────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Users className="h-5 w-5 text-primary" /> Contactos
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {contacts.length} contactos · {consentCount} con consentimiento Habeas Data · {revokedCount} revocados
          </p>
        </div>
      </div>

      {/* AI Insight — a demanda */}
      {(meta.role === 'owner' || meta.role === 'manager') && (
        <AiInsightPanel module="contacts" label="Contactos" />
      )}

      {/* Habeas Data notice */}
      <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 px-4 py-3 text-sm text-blue-400 flex items-start gap-2">
        <ShieldCheck className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          <span className="font-semibold">Habeas Data — Ley 1581/2012 Colombia.</span>{' '}
          El campo <em>consentimiento</em> registra si el titular autorizó el tratamiento. El tenant es el Responsable ante la SIC.
        </span>
      </div>

      <ContactsManager 
        initialContacts={contacts}
        canWrite={canWrite}
        addAction={addContact}
        editAction={editContact}
        deleteAction={deleteContact}
      />
    </div>
  )
}
