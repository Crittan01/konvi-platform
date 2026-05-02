import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { ShieldCheck, Users } from 'lucide-react'
import AiInsightPanel from '@/components/ai-insight-panel'
import ContactsManager from './_components/contacts-manager'
import { CORE_API_URL } from '@/lib/runtime-env'

// Rev. 102 — module-level scope.
// Bug previo: estaban definidas DENTRO de ContactsPage; los server actions
// inline (addContact/editContact) capturaban CONSENT_SOURCES y
// normalizeDaneCode en su closure. Cuando Next serializaba el action para
// pasarlo como prop al ContactsManager (Client Component), intentaba
// serializar Set.has → "Functions cannot be passed directly to Client
// Components" digest 3617361344. Mover a module scope resuelve: las
// server actions referencian el binding del módulo (resoluble en runtime),
// no un closure capturado en el render.
const CONSENT_SOURCES = new Set([
  'manual_console', 'whatsapp', 'web_form', 'phone_call',
  'in_person', 'import', 'other',
])

const normalizeDaneCode = (raw?: string | null) => {
  const digits = String(raw ?? '').replace(/\D/g, '')
  if (digits.length === 8 && digits.endsWith('000')) return digits.slice(0, 5)
  return digits.slice(0, 5)
}

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
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const canWrite = role === 'owner' || role === 'manager'

  const consentFilter = searchParams?.consent ?? 'all'

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

    // Rev. 102 (Opción A Habeas Data) — Ley 1581 Art. 9: sin
    // consentimiento previo, expreso e informado, NO se pueden tratar
    // datos personales. El sistema permite registrar SOLO el teléfono
    // (mínimo necesario del canal de comunicación). Cualquier otro
    // campo PII rechazado en server.
    const consentGivenCheck = formData.get('consent_given') === 'on'
    if (!consentGivenCheck) {
      const piiAttempted = [
        'name', 'email', 'document_number', 'addr_street', 'notes',
      ].some(k => ((formData.get(k) as string) || '').trim().length > 0)
      if (piiAttempted) {
        throw new Error(
          'No se pueden registrar datos personales sin consentimiento del titular ' +
          '(Ley 1581/2012 Art. 9). Marca el check "El titular autorizó el tratamiento" ' +
          'o no llenes los campos personales.'
        )
      }
    }
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
    // Rev. 102 — Opción B Habeas Data: campos exclusivos del flujo de
    // re-edición post-anonimización.
    const renewedConsentChecked = formData.get('renewed_consent') === 'on'
    const renewedConsentEvidence = ((formData.get('renewed_consent_evidence') as string) || '').trim()

    // Rev. 102 (Opción A Habeas Data) — guard general edit: si NO hay
    // consent activo (ni renewed) y se intenta enviar PII → rechazar.
    // Esto cubre el caso "operador editó un contacto, desmarcó el check
    // y dejó los inputs llenos" — el sistema bloquea el guardado.
    const editingPiiAttempted = [
      'name', 'email', 'document_number', 'addr_street', 'notes',
    ].some(k => ((formData.get(k) as string) || '').trim().length > 0)
    if (!consentGiven && !renewedConsentChecked && editingPiiAttempted) {
      throw new Error(
        'No se pueden persistir datos personales sin consentimiento del titular ' +
        '(Ley 1581/2012 Art. 9). Marca el check de consentimiento o vacía los campos personales.'
      )
    }
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

    // Rev. 102 — Guard de re-edición post-anonimización (Opción B).
    // Si el contact estaba anonimizado (revoked_at no null) Y el operador
    // intenta enviar PII (cualquier campo no vacío) Y no marcó el checkbox
    // de consent renovado o no proporcionó evidencia → rechazar.
    const wasAnonymized = !!prev?.consent_revoked_at && prev?.consent_given === false
    const incomingPii = [
      'name', 'email', 'document_number', 'addr_street', 'notes',
    ].some(k => ((formData.get(k) as string) || '').trim().length > 0)
    if (wasAnonymized && incomingPii) {
      if (!renewedConsentChecked) {
        throw new Error(
          'Este contacto fue anonimizado. Marca "Confirmo consentimiento renovado" antes de editar PII.'
        )
      }
      if (renewedConsentEvidence.length < 10) {
        throw new Error(
          'La evidencia del consentimiento renovado debe tener al menos 10 caracteres.'
        )
      }
    }
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
    // Rev. 69 — documento de identidad en edit. Rev. 102: TI removido.
    const editDocTypeRaw = ((formData.get('document_type') as string) || '').trim().toUpperCase()
    const editDocType = ['CC', 'CE', 'NIT', 'PP', 'OTHER'].includes(editDocTypeRaw) ? editDocTypeRaw : null
    const editDocNumber = ((formData.get('document_number') as string) || '').replace(/[\s.]/g, '').trim() || null
    const mergedEvidence: Record<string, unknown> = {
      ...((prev?.consent_evidence ?? {}) as Record<string, unknown>),
      last_update: {
        source: consentSource || prev?.consent_source || null,
        notice_version: consentNoticeVersion || prev?.consent_notice_version || null,
        note: consentEvidenceNote || null,
        actor_email: u?.email ?? null,
        at: nowIso,
      },
    }
    // Rev. 102 — Opción B Habeas Data: registrar inmutablemente el
    // consent renovado tras anonimización (append a array para que
    // si el ciclo se repite, queden todos los renewals históricos).
    if (wasAnonymized && renewedConsentChecked && renewedConsentEvidence) {
      const prevRenewals = Array.isArray(mergedEvidence.renewals_after_revocation)
        ? mergedEvidence.renewals_after_revocation as unknown[]
        : []
      mergedEvidence.renewals_after_revocation = [
        ...prevRenewals,
        {
          at: nowIso,
          actor_email: u?.email ?? null,
          previous_revoked_at: prev?.consent_revoked_at ?? null,
          evidence_text: renewedConsentEvidence,
        },
      ]
    }
    // Rev. 102 — si el operador confirmó renewed_consent + evidencia,
    // implícitamente el contact está siendo re-activado: forzar
    // consent_given=true para evitar estado contradictorio (PII registrada
    // sin consent activo).
    const effectiveConsentGiven = (wasAnonymized && renewedConsentChecked && renewedConsentEvidence)
      ? true
      : consentGiven
    const shouldMarkRevoked = !effectiveConsentGiven && !!prev?.consent_given
    const effectiveConsentDate = effectiveConsentGiven
      ? (wasAnonymized ? nowIso : (prev?.consent_date ?? nowIso))
      : (prev?.consent_date ?? null)
    await sb.from('contacts').update({
      name:          (formData.get('name') as string) || null,
      email:         (((formData.get('email') as string) || '').trim().toLowerCase()) || null,
      notes:         (formData.get('notes') as string) || null,
      // Rev. 69 — documento (ambos juntos o ambos null).
      document_type:   editDocType && editDocNumber ? editDocType : null,
      document_number: editDocType && editDocNumber ? editDocNumber : null,
      address,
      consent_given: effectiveConsentGiven,
      consent_date: effectiveConsentDate,
      consent_source: consentSource || prev?.consent_source || null,
      // Igual que en addContact: persistimos consent_channel para Ley 1581.
      consent_channel: effectiveConsentGiven ? 'dashboard_console' : null,
      consent_notice_version: consentNoticeVersion || prev?.consent_notice_version || null,
      consent_evidence: mergedEvidence,
      consent_actor_email: u?.email ?? null,
      consent_revoked_at: effectiveConsentGiven ? null : (shouldMarkRevoked ? nowIso : (prev?.consent_revoked_at ?? null)),
      consent_revoked_reason: effectiveConsentGiven ? null : (revocationReason || null),
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

  // Rev. 101 (F1) — HTML imprimible del SAR. Endpoint GET (no POST).
  async function sarPrintableAction(formData: FormData): Promise<{
    ok: boolean
    status: number
    html?: string
    error?: string
  }> {
    'use server'
    const sb = createClient()
    const { data: { session } } = await sb.auth.getSession()
    const m = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, status: 403, error: 'No tienes permisos.' }
    }
    const contactId = String(formData.get('contact_id') || '')
    if (!contactId) return { ok: false, status: 400, error: 'contact_id requerido.' }
    const token = session?.access_token
    if (!token) return { ok: false, status: 401, error: 'Sesión expirada.' }
    try {
      const res = await fetch(
        `${CORE_API_URL}/api/v1/contacts/${encodeURIComponent(contactId)}/data-subject-request/printable`,
        {
          method: 'GET',
          headers: { Authorization: `Bearer ${token}` },
          cache: 'no-store',
        },
      )
      const text = await res.text()
      return { ok: res.ok, status: res.status, html: res.ok ? text : undefined, error: res.ok ? undefined : text.slice(0, 200) }
    } catch (e) {
      return { ok: false, status: 502, error: e instanceof Error ? e.message : 'Network error' }
    }
  }

  // Rev. 100 — SAR (Subject Access Request) Habeas Data Art. 14.
  // Server action proxy al endpoint /api/v1/contacts/{id}/data-subject-request.
  // Devuelve { ok, payload } para que el cliente serialice y descargue.
  async function sarAction(formData: FormData): Promise<{
    ok: boolean
    status: number
    type: string
    payload?: unknown
    error?: string
  }> {
    'use server'
    const sb = createClient()
    const { data: { session } } = await sb.auth.getSession()
    const m = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    const sarType = String(formData.get('sar_type') || 'export')
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, status: 403, type: sarType, error: 'No tienes permisos (owner/manager).' }
    }
    const contactId = String(formData.get('contact_id') || '')
    if (!contactId) {
      return { ok: false, status: 400, type: sarType, error: 'contact_id requerido.' }
    }
    const reason = (formData.get('reason') as string) || undefined
    const token = session?.access_token
    if (!token) {
      return { ok: false, status: 401, type: sarType, error: 'Sesión expirada — recarga la página.' }
    }
    try {
      const res = await fetch(
        `${CORE_API_URL}/api/v1/contacts/${encodeURIComponent(contactId)}/data-subject-request`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ type: sarType, reason }),
          cache: 'no-store',
        },
      )
      const text = await res.text()
      let payload: unknown
      try { payload = JSON.parse(text) } catch { payload = text }
      // Si fue erase, refrescamos la lista (PII anonimizada).
      if (res.ok && (sarType === 'erase' || sarType === 'rectify')) {
        revalidatePath('/dashboard/contacts')
      }
      return { ok: res.ok, status: res.status, type: sarType, payload }
    } catch (e) {
      return { ok: false, status: 502, type: sarType, error: e instanceof Error ? e.message : 'Network error' }
    }
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
      <div className="rounded-xl border border-blue-700/40 bg-blue-700/5 px-4 py-3 text-sm text-blue-700 flex items-start gap-2">
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
        sarAction={sarAction}
        sarPrintableAction={sarPrintableAction}
      />
    </div>
  )
}
