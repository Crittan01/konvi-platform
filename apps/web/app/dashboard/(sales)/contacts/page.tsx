import { createClient } from '@/utils/supabase/server'
import { createAdminClient } from '@/utils/supabase/admin'
import { revalidatePath } from 'next/cache'
import { ShieldCheck, Users } from 'lucide-react'
import AiInsightPanel from '@/components/ai-insight-panel'
import ContactsManager from './_components/contacts-manager'
import { CORE_API_URL } from '@/lib/runtime-env'
import { hashPhone } from '@/lib/crypto/phone-hash'
import { uploadConsentEvidence } from './_components/helpers/upload-evidence'

// Rev. 102 — module-level scope.
// Bug previo: estaban definidas DENTRO de ContactsPage; los server actions
// inline (addContact/editContact) capturaban CONSENT_SOURCES y
// normalizeDaneCode en su closure. Cuando Next serializaba el action para
// pasarlo como prop al ContactsManager (Client Component), intentaba
// serializar Set.has → "Functions cannot be passed directly to Client
// Components" digest 3617361344. Mover a module scope resuelve: las
// server actions referencian el binding del módulo (resoluble en runtime),
// no un closure capturado en el render.
// Rev. 103 (SaaS B2B pivot) — canales operacionales completos.
// El tenant es Responsable ante la SIC; la plataforma es Encargado puro
// (modelo Wati/Mailchimp/Respond.io). El operador del tenant decide qué
// canal aplica según su flujo. Help text en UI explica cada uno.
//   - manual_console: operador registra consent dado fuera del sistema
//   - whatsapp: hilo de conversación es la evidencia (mejor caso, nativo)
//   - web_form: form en sistema del tenant
//   - phone_call: llamada con el titular; evidencia = grabación o nota
//   - in_person: documento físico firmado; opcional adjuntar escaneo (F10)
//   - import: sistema origen con due diligence
//   - other: catch-all, exige Evidencia minLength=20 (validado server)
//   - marketplace_meli: solo via webhook MeLi (no en UI dropdown)
const CONSENT_SOURCES = new Set([
  'manual_console', 'whatsapp', 'web_form', 'phone_call',
  'in_person', 'import', 'other', 'marketplace_meli',
])

// Rev. 102 — Versión vigente del aviso/política de privacidad de la
// plataforma. Sincronizado con docs/legal/privacy-policy.md.
// Cuando un titular otorga consent, el server estampa AUTOMÁTICAMENTE
// esta versión en consent_notice_version. El operador NO escribe esto
// (era confuso pedirle un número de versión que no conocía). Si la
// política cambia, bumpear esta constante + el archivo legal.
const CURRENT_PRIVACY_NOTICE_VERSION = 'v2026-05-01'

// Rev. 102 — Country codes soportados para el phone del titular.
// Default Colombia (+57). Otros países disponibles por si llega un
// extranjero (CE/PP). El bot WhatsApp está optimizado para CO; en
// otros países el contact se registra correctamente pero el flujo
// del bot puede ser limitado hasta que se internacionalice.
//
// E.164 spec: total digits including country code is 8-15. Prefijo
// va sin el +. Validamos en server: digits totales (sin prefijo) entre
// 7 y 14 dependiendo del país.
const SUPPORTED_COUNTRY_CODES = new Set([
  '57',  // Colombia (default)
  '58',  // Venezuela
  '593', // Ecuador
  '51',  // Perú
  '52',  // México
  '1',   // USA / Canadá
  '34',  // España
  '54',  // Argentina
  '56',  // Chile
  '55',  // Brasil
])

const normalizeDaneCode = (raw?: string | null) => {
  const digits = String(raw ?? '').replace(/\D/g, '')
  if (digits.length === 8 && digits.endsWith('000')) return digits.slice(0, 5)
  return digits.slice(0, 5)
}

type Contact = {
  id: string
  phone: string
  shipping_phone: string | null
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
  // Sem 5 perf: cached comparte con DashboardLayout.
  const { getCachedUser, getCachedTenantMeta } = await import('@/utils/supabase/cached-user')
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = createClient()

  const consentFilter = searchParams?.consent ?? 'all'

  let contacts: Contact[] = []

  if (tenantId) {
    let query = supabase
      .from('contacts')
      .select(
        'id, phone, shipping_phone, name, email, notes, document_type, document_number, ' +
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

    // Rev. 103 (SaaS B2B) — la plataforma es Encargado puro. El tenant
    // firma DPA y certifica tener base legal apropiada para los datos
    // que registra. Si llena PII sin marcar consent → persistimos con
    // consent_given=false; el bot WhatsApp pedirá consent activamente
    // cuando el cliente conteste.
    const nowIso = new Date().toISOString()
    const consentGiven = formData.get('consent_given') === 'on'
    const sourceRaw = ((formData.get('consent_source') as string) || '').trim()
    // Rev. 102 — Canal ahora vacío + required en UI; backend rechaza si
    // consent_given=true sin canal seleccionado.
    if (consentGiven && (!sourceRaw || !CONSENT_SOURCES.has(sourceRaw))) {
      throw new Error(
        'Falta seleccionar el canal por el que el titular dio consent. ' +
        'Es obligatorio para audit (Ley 1581 Art. 9).'
      )
    }
    const consentSource = sourceRaw
    // Rev. 102 — versión auto-estampada con la constante vigente.
    const consentNoticeVersion = CURRENT_PRIVACY_NOTICE_VERSION
    const consentEvidenceNote = ((formData.get('consent_evidence_note') as string) || '').trim()
    // Rev. 102 — canal "other" exige Evidencia ≥ 20 chars (catch-all
    // legítimo solo si el operador puede describir de dónde vino).
    if (consentGiven && consentSource === 'other' && consentEvidenceNote.length < 20) {
      throw new Error(
        'Cuando el canal es "Otro" la Evidencia debe describir de dónde vino el ' +
        'consentimiento (mínimo 20 caracteres). Si no puedes describirlo, el canal no aplica.'
      )
    }
    const revocationReason = ((formData.get('consent_revoked_reason') as string) || '').trim()
    const street   = (formData.get('addr_street') as string) || null
    const addrCity = (formData.get('addr_city')   as string) || null
    const daneCode = normalizeDaneCode(formData.get('addr_dane_code') as string)
    // Rev. 69 — campos estructurados de address.
    // Sem 7 F2 cierre 2026-05-19 (Opción 1 SIMPLIFY):
    //   building_type ∈ {casa, edificio, conjunto, oficina}
    //   conjunto_type ∈ {torres, casas} si conjunto.
    //   floor + company_name opcionales.
    const buildingTypeRaw = (formData.get('addr_building_type') as string) || ''
    const buildingType = ['casa', 'edificio', 'conjunto', 'oficina'].includes(buildingTypeRaw) ? buildingTypeRaw : undefined
    const conjuntoTypeRaw = (formData.get('addr_conjunto_type') as string) || ''
    const conjuntoType = ['torres', 'casas'].includes(conjuntoTypeRaw) ? conjuntoTypeRaw : undefined
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
      conjunto_type: conjuntoType,
      floor:         (formData.get('addr_floor')         as string) || undefined,
      company_name:  (formData.get('addr_company_name')  as string) || undefined,
    } : null
    // Rev. 69 — documento de identidad.
    const docTypeRaw = ((formData.get('document_type') as string) || '').trim().toUpperCase()
    const docType = ['CC', 'CE', 'NIT', 'PP', 'TI', 'OTHER'].includes(docTypeRaw) ? docTypeRaw : null
    const docNumber = ((formData.get('document_number') as string) || '').replace(/[\s.]/g, '').trim() || null
    // Rev. 102 — phone con country code seleccionable.
    const phoneCountryRaw = ((formData.get('phone_country') as string) || '57').replace(/\D/g, '')
    const phoneCountry = SUPPORTED_COUNTRY_CODES.has(phoneCountryRaw) ? phoneCountryRaw : '57'
    const digits = ((formData.get('phone') as string) ?? '').replace(/\D/g, '').slice(0, 14)
    // E.164: phone total (country + número) entre 8 y 15 dígitos.
    // Validación laxa por país: número (sin country) entre 7 y 14.
    if (digits.length < 7 || digits.length > 14) {
      throw new Error(
        `Teléfono inválido. Debe tener entre 7 y 14 dígitos (sin contar el código de país +${phoneCountry}).`
      )
    }
    const phoneE164 = `+${phoneCountry}${digits}`
    // Rev. 103 — phone alternativo de envío (opcional). Si el usuario lo
    // deja vacío, defaulteamos al phone WhatsApp para que la transportadora
    // siempre tenga un número de contacto.
    const shippingPhoneRaw = ((formData.get('shipping_phone') as string) || '').replace(/\D/g, '')
    const shippingPhoneE164 = (shippingPhoneRaw.length >= 10 && shippingPhoneRaw[shippingPhoneRaw.length - 10] !== '0')
      ? `+57${shippingPhoneRaw.slice(-10)}`
      : phoneE164
    const initialEvidence: Record<string, unknown> = {
      created_via: 'dashboard_contacts',
      note: consentEvidenceNote || null,
      actor_email: u?.email ?? null,
      captured_at: nowIso,
    }
    const { data: inserted } = await sb.from('contacts').insert({
      tenant_id:     m.tenant_id,
      phone:         phoneE164,
      shipping_phone: shippingPhoneE164,
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
      consent_evidence: initialEvidence,
      consent_actor_email: u?.email ?? null,
      consent_revoked_at: !consentGiven && revocationReason ? nowIso : null,
      consent_revoked_reason: !consentGiven ? (revocationReason || null) : null,
      address,
    }).select('id').single()

    // Rev. 103 (F10) — si canal in_person + file adjunto, sube a Storage
    // y persiste URL en consent_evidence.attachment_url (segundo update).
    // Importante: si upload falla (MIME no válido, > 5MB, error storage),
    // NO abortamos. El contact ya está creado; persistimos un marker en
    // evidence para que el operador sepa que el adjunto falló y pueda
    // reintentar editando. Romper con throw aquí causa "Error al cargar
    // el módulo" en Next y oculta el problema real.
    const newId = (inserted as { id?: string } | null)?.id
    if (newId && consentGiven && consentSource === 'in_person') {
      const result = await uploadConsentEvidence(formData, newId, m.tenant_id)
      if (result.status === 'uploaded') {
        // Persistimos `attachment_path` (no `attachment_url`): el bucket
        // es privado, la UI genera signed URL on-demand.
        await sb.from('contacts').update({
          consent_evidence: {
            ...initialEvidence,
            attachment_path: result.path,
            attachment_mime: result.mime,
            attachment_size: result.size,
            attachment_uploaded_at: new Date().toISOString(),
          },
        }).eq('id', newId).eq('tenant_id', m.tenant_id)
      } else if (result.status === 'rejected' || result.status === 'error') {
        const skipReason = result.status === 'rejected' ? result.reason : 'storage_error'
        await sb.from('contacts').update({
          consent_evidence: {
            ...initialEvidence,
            attachment_skip_reason: skipReason,
            attachment_skip_filename: 'filename' in result ? result.filename : null,
            attachment_skip_received_mime: 'receivedMime' in result ? result.receivedMime : null,
            attachment_skip_storage_message: result.status === 'error' ? result.message : null,
            attachment_skip_at: new Date().toISOString(),
          },
        }).eq('id', newId).eq('tenant_id', m.tenant_id)
        console.warn(
          '[F10] Contact creado pero adjunto no se subió',
          { contactId: newId, skipReason, filename: 'filename' in result ? result.filename : null,
            receivedMime: 'receivedMime' in result ? result.receivedMime : null,
            storageMessage: result.status === 'error' ? result.message : null },
        )
      }
    }
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
    // Rev. 102 — Canal ahora required en UI cuando consent_given=true.
    if (consentGiven && (!sourceRaw || !CONSENT_SOURCES.has(sourceRaw))) {
      throw new Error(
        'Falta seleccionar el canal por el que el titular dio consent. ' +
        'Es obligatorio para audit (Ley 1581 Art. 9).'
      )
    }
    const consentSource = sourceRaw
    // Rev. 102 — versión auto-estampada con la constante vigente.
    const consentNoticeVersion = CURRENT_PRIVACY_NOTICE_VERSION
    // Rev. 102 — `consent_evidence_note` puede venir del bloque normal de
    // consent O del bloque renewed_consent (post-anonim). Tomamos el que
    // venga primero no vacío. Esto evita duplicar el mismo campo en el
    // form cuando awaitingRenewal=true.
    const renewedConsentEvidenceRaw = ((formData.get('renewed_consent_evidence') as string) || '').trim()
    const consentEvidenceNoteRaw = ((formData.get('consent_evidence_note') as string) || '').trim()
    const consentEvidenceNote = consentEvidenceNoteRaw || renewedConsentEvidenceRaw
    const revocationReason = ((formData.get('consent_revoked_reason') as string) || '').trim()
    // Rev. 102 — canal "other" exige Evidencia ≥ 20 chars.
    if (consentGiven && consentSource === 'other' && consentEvidenceNote.length < 20) {
      throw new Error(
        'Cuando el canal es "Otro" la Evidencia debe describir de dónde vino el ' +
        'consentimiento (mínimo 20 caracteres).'
      )
    }
    // Rev. 102 — Opción B Habeas Data: campos exclusivos del flujo de
    // re-edición post-anonimización (mantenido en rev. 103: la
    // anonimización formal sí es ritual legal serio).
    const renewedConsentChecked = formData.get('renewed_consent') === 'on'
    const renewedConsentEvidence = ((formData.get('renewed_consent_evidence') as string) || '').trim()

    const { data: existing } = await sb.from('contacts')
      .select('phone, consent_given, consent_date, consent_source, consent_notice_version, consent_evidence, consent_revoked_at')
      .eq('id', formData.get('contact_id') as string)
      .eq('tenant_id', m.tenant_id)
      .single()
    const prev = (existing as {
      phone?: string | null
      consent_given?: boolean
      consent_date?: string | null
      consent_source?: string | null
      consent_notice_version?: string | null
      consent_evidence?: Record<string, unknown> | null
      consent_revoked_at?: string | null
    } | null)

    // Rev. 102 — Guardrail server-side: bloquear desmarcar el check de
    // consent en Edit cuando el contact tenía consent_given=true.
    // La revocación debe ir por el flujo formal (botón Anonimizar) que
    // garantiza nullificación de PII + audit inmutable + notif tenant.
    // Si el operador (o un cliente API) intenta hacer "soft revoke"
    // desmarcando el check + guardar con PII llena → rechazar.
    if (prev?.consent_given === true && !consentGiven && !renewedConsentChecked) {
      throw new Error(
        'No puedes revocar el consentimiento desmarcando este check. ' +
        'Para revocar usa el botón "Anonimizar" en la sección Habeas Data — ' +
        'esa acción borra la PII, deja audit inmutable y notifica al tenant ' +
        'conforme Ley 1581/2012 Art. 15.'
      )
    }

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
    // Sem 7 F2 cierre 2026-05-19 (Opción 1 SIMPLIFY).
    const editBuildingTypeRaw = (formData.get('addr_building_type') as string) || ''
    const editBuildingType = ['casa', 'edificio', 'conjunto', 'oficina'].includes(editBuildingTypeRaw) ? editBuildingTypeRaw : undefined
    const editConjuntoTypeRaw = (formData.get('addr_conjunto_type') as string) || ''
    const editConjuntoType = ['torres', 'casas'].includes(editConjuntoTypeRaw) ? editConjuntoTypeRaw : undefined
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
      conjunto_type: editConjuntoType,
      floor:         (formData.get('addr_floor')         as string) || undefined,
      company_name:  (formData.get('addr_company_name')  as string) || undefined,
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
    // Rev. 103 — Cap renewals_after_revocation a las últimas 50 entries
    // para que JSONB no crezca sin control en contracts enterprise con
    // muchos ciclos de revocación/renovación. Marker de truncamiento
    // queda en evidence (transparencia ante SIC).
    if (Array.isArray(mergedEvidence.renewals_after_revocation)) {
      const arr = mergedEvidence.renewals_after_revocation as unknown[]
      if (arr.length > 50) {
        mergedEvidence.renewals_after_revocation = arr.slice(-50)
        mergedEvidence.renewals_truncated_at = nowIso
        mergedEvidence.renewals_truncated_count = arr.length - 50
      }
    }
    // Rev. 103 (F10) — Si canal in_person + archivo adjunto, sube
    // evidencia física al bucket consent-evidence y persiste URL en
    // mergedEvidence.attachment_url. La SAR export incluye el URL.
    // Si upload falla (MIME no válido, > 5MB, error storage), NO abortamos
    // el edit: persistimos marker en evidence + log; los demás campos del
    // form se aplican normalmente.
    const editContactId = (formData.get('contact_id') as string) || ''
    if (editContactId && consentSource === 'in_person') {
      const upload = await uploadConsentEvidence(formData, editContactId, m.tenant_id)
      if (upload.status === 'uploaded') {
        // Persistimos `attachment_path` (no `attachment_url`): el bucket
        // es privado, la UI genera signed URL on-demand.
        // Si hay un attachment_url legacy, lo limpiamos.
        delete mergedEvidence.attachment_url
        mergedEvidence.attachment_path = upload.path
        mergedEvidence.attachment_mime = upload.mime
        mergedEvidence.attachment_size = upload.size
        mergedEvidence.attachment_uploaded_at = nowIso
      } else if (upload.status === 'rejected' || upload.status === 'error') {
        const skipReason = upload.status === 'rejected' ? upload.reason : 'storage_error'
        mergedEvidence.attachment_skip_reason = skipReason
        mergedEvidence.attachment_skip_filename = 'filename' in upload ? upload.filename : null
        mergedEvidence.attachment_skip_received_mime = 'receivedMime' in upload ? upload.receivedMime : null
        mergedEvidence.attachment_skip_storage_message = upload.status === 'error' ? upload.message : null
        mergedEvidence.attachment_skip_at = nowIso
        console.warn(
          '[F10] Edit contact: adjunto no se subió',
          { contactId: editContactId, skipReason,
            filename: 'filename' in upload ? upload.filename : null,
            receivedMime: 'receivedMime' in upload ? upload.receivedMime : null,
            storageMessage: upload.status === 'error' ? upload.message : null },
        )
      }
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
    // Rev. 103 — shipping_phone (opcional). Si el usuario lo deja vacío,
    // defaulteamos al phone WhatsApp del contact (prev.phone) para que la
    // transportadora siempre tenga un número de contacto.
    const editShippingRaw = ((formData.get('shipping_phone') as string) || '').replace(/\D/g, '')
    const editShippingE164 = (editShippingRaw.length >= 10 && editShippingRaw[editShippingRaw.length - 10] !== '0')
      ? `+57${editShippingRaw.slice(-10)}`
      : (prev?.phone ?? null)
    await sb.from('contacts').update({
      name:          (formData.get('name') as string) || null,
      email:         (((formData.get('email') as string) || '').trim().toLowerCase()) || null,
      notes:         (formData.get('notes') as string) || null,
      shipping_phone: editShippingE164,
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
    const { data: { session } } = await sb.auth.getSession()
    const u = session?.user
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    // Sem 7 F2 cierre 2026-05-19 — purge endpoint requiere role 'owner'
    // (hard cascade es destructivo, no debe ser permitido a 'manager').
    if (!m.tenant_id || m.role !== 'owner') {
      throw new Error('Solo el owner puede eliminar contactos en cascade.')
    }
    const contactId = (formData.get('contact_id') as string) || ''
    if (!contactId) return
    const reason = ((formData.get('delete_reason') as string) || '').trim()
    const token = session?.access_token
    if (!token) {
      throw new Error('Sesión expirada — recarga la página.')
    }

    // Sem 7 F2 cierre 2026-05-19 — Bug founder UAT (conv 056490b8):
    // ANTES esta server action hacía DELETE directo a tabla contacts. Eso
    // dejaba carts/conversations/orders huérfanos en DB que el cart-recovery
    // del bot recuperaba silenciosamente en próximas conversaciones del
    // mismo phone → cart contaminado con items históricos.
    //
    // AHORA delega al endpoint `POST /api/v1/contacts/{id}/purge` que
    // ejecuta cascade completo (audit log + helper `purge_contact_completely`).
    // Misma lógica reusable desde `scripts/wipe_conversation.py --purge-contact`.
    try {
      const res = await fetch(
        `${CORE_API_URL}/api/v1/contacts/${encodeURIComponent(contactId)}/purge`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ reason: reason || null }),
          cache: 'no-store',
        },
      )
      if (!res.ok) {
        const errText = await res.text()
        throw new Error(
          `Purge falló (${res.status}): ${errText.slice(0, 200)}`
        )
      }
    } catch (e) {
      console.error('[deleteContact] purge API call falló', e)
      throw e
    }
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

  // Rev. 105 H.4.1.x — Server action: reactivar consent tras soft opt-out
  // (STOP keyword via WhatsApp). Limpia consent_revoked_at + reason; PII
  // intacta (no se anonimizó). Audit log Habeas Data Art. 9 con actor +
  // reason. Idempotente: si ya está activo, no-op.
  async function reactivateConsentAction(
    formData: FormData,
  ): Promise<{ ok: boolean; status: number; message: string }> {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    // Rev. 105 H.4.1.x — owner-only (Habeas Data ART. 11). Manager NO
    // puede reactivar consent — debe escalar al owner para que firme.
    if (!m.tenant_id || m.role !== 'owner') {
      return {
        ok: false,
        status: 403,
        message: 'Solo el owner puede reactivar consent (gobierno Habeas Data ART. 11). Contactar al owner del tenant para que ejecute la acción.',
      }
    }
    const contactId = ((formData.get('contact_id') as string) || '').trim()
    const reason = ((formData.get('reason') as string) || '').trim()
    if (!contactId) return { ok: false, status: 400, message: 'contact_id requerido' }
    if (reason.length < 10) {
      return { ok: false, status: 400, message: 'Razón requerida (mínimo 10 caracteres)' }
    }

    // Verificar contact + capturar phone para hash audit.
    const { data: contact } = await sb.from('contacts')
      .select('phone, consent_revoked_at, consent_revoked_reason')
      .eq('id', contactId)
      .eq('tenant_id', m.tenant_id)
      .single()
    if (!contact) {
      return { ok: false, status: 404, message: 'Contacto no encontrado' }
    }
    if (!contact.consent_revoked_at) {
      return { ok: true, status: 200, message: 'Consent ya estaba activo (no-op)' }
    }

    // Audit log ANTES de UPDATE (Habeas Data Art. 9 — append-only inmutable).
    const admin = createAdminClient()
    const auditResult = await admin.from('consent_audit_log').insert({
      tenant_id: m.tenant_id,
      contact_id: contactId,
      phone_hash: hashPhone((contact as { phone?: string | null }).phone),
      event: 'granted',
      source: 'tenant_console',
      actor_email: u?.email ?? null,
      actor_user_id: u?.id ?? null,
      evidence: {
        trigger: 'manual_reactivate',
        reason,
        previous_revoked_reason: (contact as { consent_revoked_reason?: string | null }).consent_revoked_reason,
        reactivated_at: new Date().toISOString(),
      },
    })
    if (auditResult.error) {
      console.error('[reactivateConsent] audit log insert falló', auditResult.error)
      return { ok: false, status: 500, message: 'No se pudo registrar audit log. Reactivación abortada.' }
    }

    // UPDATE contacts limpiando revoke flags (PII intacta, NO anonimiza).
    const { error: updateErr } = await sb.from('contacts')
      .update({ consent_revoked_at: null, consent_revoked_reason: null })
      .eq('id', contactId)
      .eq('tenant_id', m.tenant_id)
    if (updateErr) {
      console.error('[reactivateConsent] update contact falló', updateErr)
      return { ok: false, status: 500, message: 'Audit log se registró pero update falló. Estado inconsistente — reportar.' }
    }

    // Rev. 105 H.4.1.x.gov.sync — Sincronía Inbox: también vuelve
    // conversations.status='opted_out' → 'bot_active' para que el operador
    // vea estado consistente en ambas UIs (Contactos + Inbox). Asimetría
    // STOP→opted_out / Reactivar→bot_active es el design simétrico correcto.
    // El customer_phone del contact mapea a conversations.customer_phone (1:N).
    const contactPhone = (contact as { phone?: string | null }).phone
    let conversationsReactivated = 0
    if (contactPhone) {
      const { data: convData, error: convUpdateErr } = await sb.from('conversations')
        .update({ status: 'bot_active' })
        .eq('tenant_id', m.tenant_id)
        .eq('customer_phone', contactPhone)
        .eq('status', 'opted_out')
        .select('id')
      if (convUpdateErr) {
        // No abortamos — el consent ya se reactivó. Solo loguear.
        console.error('[reactivateConsent] conversations sync falló (no crítico)', convUpdateErr)
      } else {
        conversationsReactivated = (convData ?? []).length
      }
    }

    revalidatePath('/dashboard/contacts')
    revalidatePath('/dashboard/inbox')

    const syncMsg = conversationsReactivated > 0
      ? ` Conversaciones reactivadas: ${conversationsReactivated} (Inbox sincronizado).`
      : ''
    return {
      ok: true,
      status: 200,
      message: `Consent reactivado. Marketing puede reanudarse al cliente.${syncMsg}`,
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
      {(role === 'owner' || role === 'manager') && (
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
        userRole={role}
        addAction={addContact}
        editAction={editContact}
        deleteAction={deleteContact}
        sarAction={sarAction}
        sarPrintableAction={sarPrintableAction}
        reactivateConsentAction={reactivateConsentAction}
      />
    </div>
  )
}
