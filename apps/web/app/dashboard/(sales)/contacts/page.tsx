import { createClient } from '@/utils/supabase/server'
import { createAdminClient } from '@/utils/supabase/admin'
import { revalidatePath } from 'next/cache'
import { ShieldCheck, Users } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import AiInsightPanel from '@/components/ai-insight-panel'
import ContactsManager from './_components/contacts-manager'
import { CORE_API_URL } from '@/lib/runtime-env'
import { uploadConsentEvidence } from './_components/helpers/upload-evidence'

export const metadata = { title: 'Contactos' }

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

// Cota superior del listado. El bot crea un contact por cada teléfono
// entrante, así que el fetch DEBE estar acotado (data-fetching pattern:
// listados acotados). La paginación real server-side es decisión de
// producto pendiente (umbral definitivo); mientras tanto 500 protege el
// render y la búsqueda/filtros operan sobre esa ventana en memoria.
const CONTACTS_FETCH_CAP = 500

const normalizeDaneCode = (raw?: string | null) => {
  const digits = String(raw ?? '').replace(/\D/g, '')
  if (digits.length === 8 && digits.endsWith('000')) return digits.slice(0, 5)
  return digits.slice(0, 5)
}

// F68: contrato canónico de resultado de server action (mismo shape que
// promotions-manager.tsx). Sustituye a `throw new Error(msg)`, que en producción
// Next.js reemplaza por texto genérico + digest → el operador nunca veía la causa
// (teléfono duplicado 409, guard Wompi, validación de consent Ley 1581).
type ActionResult = { ok: boolean; error?: string }

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

export default async function ContactsPage(
  props: {
    searchParams?: Promise<{ q?: string; consent?: string }>
  }
) {
  const searchParams = await props.searchParams;
  // Sem 5 perf: cached comparte con DashboardLayout.
  const { getCachedUser, getCachedTenantMeta } = await import('@/utils/supabase/cached-user')
  await getCachedUser()
  const { tenantId, role, email: userEmail } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = await createClient()

  const consentFilter = searchParams?.consent ?? 'all'

  let contacts: Contact[] = []
  // Data-fetching pattern: surfacear errores de lectura (NO falso-0). Si la
  // query falla, el operador ve un estado de error con reintento, no una
  // lista vacía que parece "no hay contactos".
  let loadError: string | null = null

  if (tenantId) {
    let query = supabase
      .from('contacts')
      .select(
        'id, phone, shipping_phone, name, email, notes, document_type, document_number, ' +
        'consent_given, consent_date, consent_source, consent_notice_version, ' +
        'consent_evidence, consent_actor_email, consent_revoked_at, consent_revoked_reason, created_at, address'
      )
      .eq('tenant_id', tenantId)
      // No listar contactos soft-eliminados (retención Cód. Comercio): quedan
      // con deleted_at poblado y NO deben aparecer como "Sin nombre".
      .is('deleted_at', null)
      .order('name', { ascending: true, nullsFirst: false })
      // Listado acotado: traemos como máximo CONTACTS_FETCH_CAP filas para
      // que la búsqueda/filtros/paginación operen en memoria sin unbounded fetch.
      .limit(CONTACTS_FETCH_CAP)

    if (consentFilter === 'yes') query = query.eq('consent_given', true)
    if (consentFilter === 'no')  query = query.eq('consent_given', false)

    const { data, error } = await query
    if (error) {
      loadError = error.message || 'No se pudieron cargar los contactos.'
    } else {
      contacts = Array.isArray(data) ? (data as unknown as Contact[]) : []
    }
  }

  // Decisión F2 (Habeas Data Ley 1581 Art. 9): registrar el acceso de consola
  // al LISTADO de PII. Best-effort — un solo row-resumen por carga (no uno por
  // contacto). Degrada en SILENCIO si la columna contact_id aún es NOT NULL
  // (migración 20260704150000 la vuelve nullable): el insert falla y se ignora,
  // sin romper el render. La tabla pii_access_log es service_role-only → admin.
  if (tenantId && !loadError && contacts.length > 0) {
    try {
      const admin = createAdminClient()
      const { error: piiLogErr } = await admin.from('pii_access_log').insert({
        tenant_id: tenantId,
        contact_id: null,
        accessed_by: `user:${userEmail || 'unknown'}`,
        purpose: 'contact_list_view',
        fields_accessed: ['name', 'email', 'phone', 'document_number', 'address'],
      })
      if (piiLogErr) {
        console.warn('[contacts] pii_access_log list-view no registrado (no crítico)', piiLogErr.message)
      }
    } catch (e) {
      console.warn('[contacts] pii_access_log list-view insert lanzó (no crítico)', e)
    }
  }

  // Si alcanzamos la cota, la ventana en memoria puede no contener todos los
  // contactos del tenant — avisamos al operador para que use la búsqueda.
  const capReached = contacts.length >= CONTACTS_FETCH_CAP

  const consentCount = contacts.filter(c => c.consent_given).length
  const revokedCount = contacts.filter(c => !c.consent_given && !!c.consent_revoked_at).length

  // ── Server Actions ─────────────────────────────────────────────────────────

  async function addContact(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos (se requiere owner o manager).' }
    }

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
      return { ok: false, error:
        'Falta seleccionar el canal por el que el titular dio consent. ' +
        'Es obligatorio para audit (Ley 1581 Art. 9).' }
    }
    const consentSource = sourceRaw
    // Rev. 102 — versión auto-estampada con la constante vigente.
    const consentNoticeVersion = CURRENT_PRIVACY_NOTICE_VERSION
    const consentEvidenceNote = ((formData.get('consent_evidence_note') as string) || '').trim()
    // Rev. 102 — canal "other" exige Evidencia ≥ 20 chars (catch-all
    // legítimo solo si el operador puede describir de dónde vino).
    if (consentGiven && consentSource === 'other' && consentEvidenceNote.length < 20) {
      return { ok: false, error:
        'Cuando el canal es "Otro" la Evidencia debe describir de dónde vino el ' +
        'consentimiento (mínimo 20 caracteres). Si no puedes describirlo, el canal no aplica.' }
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
    // Rev. 102 — TI removido (menores, Decreto 1377): la API lo rechaza (422)
    // y el dropdown ya no lo ofrece. La whitelist debe coincidir.
    const docType = ['CC', 'CE', 'NIT', 'PP', 'OTHER'].includes(docTypeRaw) ? docTypeRaw : null
    const docNumber = ((formData.get('document_number') as string) || '').replace(/[\s.]/g, '').trim() || null
    // Rev. 102 — phone con country code seleccionable.
    const phoneCountryRaw = ((formData.get('phone_country') as string) || '57').replace(/\D/g, '')
    const phoneCountry = SUPPORTED_COUNTRY_CODES.has(phoneCountryRaw) ? phoneCountryRaw : '57'
    const digits = ((formData.get('phone') as string) ?? '').replace(/\D/g, '').slice(0, 14)
    // E.164: phone total (country + número) entre 8 y 15 dígitos.
    // Validación laxa por país: número (sin country) entre 7 y 14.
    if (digits.length < 7 || digits.length > 14) {
      return { ok: false, error:
        `Teléfono inválido. Debe tener entre 7 y 14 dígitos (sin contar el código de país +${phoneCountry}).` }
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
    // A9 finiquito — la creación pasa por el API router /api/v1/contacts/
    // (RBAC owner/manager + idempotency + audit_log + pii_access_log Art. 9).
    // Antes era escritura DIRECTA a Supabase sin esas garantías (drift §3).
    // El API computa consent_date / consent_revoked_at / consent_actor_email
    // server-side (actor autoritativo del JWT, no client-supplied).
    const token = (await sb.auth.getSession()).data.session?.access_token
    if (!token) return { ok: false, error: 'Sesión expirada. Vuelve a iniciar sesión.' }
    let res: Response
    try {
      res = await fetch(`${CORE_API_URL}/api/v1/contacts/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({
          phone:           phoneE164,
          shipping_phone:  shippingPhoneE164,
          name:            (formData.get('name') as string) || null,
          email:           (((formData.get('email') as string) || '').trim().toLowerCase()) || null,
          notes:           (formData.get('notes') as string) || null,
          document_type:   docType && docNumber ? docType : null,
          document_number: docType && docNumber ? docNumber : null,
          address,
          consent_given:   consentGiven,
          consent_source:  consentGiven ? consentSource : null,
          consent_channel: consentGiven ? 'dashboard_console' : null,
          consent_notice_version: consentGiven ? (consentNoticeVersion || null) : null,
          consent_evidence: initialEvidence,
          consent_revoked_reason: !consentGiven ? (revocationReason || null) : null,
        }),
      })
    } catch (e) {
      console.error('[addContact] network error', e)
      return { ok: false, error: 'Error de red al crear el contacto. Intenta de nuevo.' }
    }
    if (!res.ok) {
      const detail = await res.text()
      // 409 = teléfono duplicado (UNIQUE tenant+phone). Mensaje claro al operador.
      if (res.status === 409) return { ok: false, error: 'Ya existe un contacto con ese teléfono.' }
      return { ok: false, error: detail || 'Error al crear el contacto.' }
    }
    const inserted = await res.json() as { id?: string }

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
      // Decisión F2 — el 2º write de evidencia (metadata del adjunto) pasa AHORA
      // por PATCH /api/v1/contacts/{id} (RL + idempotency + audit + pii_access_log)
      // en vez de un update DIRECTO a Supabase. El API mergea `consent_attachment`
      // en el consent_evidence existente (ya contiene initialEvidence del create),
      // así que solo enviamos los campos del adjunto.
      let attachmentMeta: Record<string, unknown> | null = null
      if (result.status === 'uploaded') {
        // Persistimos `attachment_path` (no `attachment_url`): el bucket
        // es privado, la UI genera signed URL on-demand.
        attachmentMeta = {
          attachment_path: result.path,
          attachment_mime: result.mime,
          attachment_size: result.size,
          attachment_uploaded_at: new Date().toISOString(),
        }
      } else if (result.status === 'rejected' || result.status === 'error') {
        const skipReason = result.status === 'rejected' ? result.reason : 'storage_error'
        attachmentMeta = {
          attachment_skip_reason: skipReason,
          attachment_skip_filename: 'filename' in result ? result.filename : null,
          attachment_skip_received_mime: 'receivedMime' in result ? result.receivedMime : null,
          attachment_skip_storage_message: result.status === 'error' ? result.message : null,
          attachment_skip_at: new Date().toISOString(),
        }
        console.warn(
          '[F10] Contact creado pero adjunto no se subió',
          { contactId: newId, skipReason, filename: 'filename' in result ? result.filename : null,
            receivedMime: 'receivedMime' in result ? result.receivedMime : null,
            storageMessage: result.status === 'error' ? result.message : null },
        )
      }
      if (attachmentMeta) {
        // No bloqueante: el contact ya está creado. Si el PATCH del adjunto
        // falla, se registra un warning y el operador puede reintentar editando.
        try {
          const patchRes = await fetch(
            `${CORE_API_URL}/api/v1/contacts/${encodeURIComponent(newId)}`,
            {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
              body: JSON.stringify({ consent_attachment: attachmentMeta }),
              cache: 'no-store',
            },
          )
          if (!patchRes.ok) {
            console.warn('[F10] PATCH metadata de adjunto post-create falló', {
              contactId: newId, status: patchRes.status,
            })
          }
        } catch (e) {
          console.warn('[F10] PATCH metadata de adjunto post-create network error', e)
        }
      }
    }
    revalidatePath('/dashboard/contacts')
    return { ok: true }
  }

  async function editContact(formData: FormData): Promise<ActionResult> {
    'use server'
    // A9 finiquito — editContact migró a PATCH /api/v1/contacts/{id} (router con
    // RBAC + idempotency + audit_log + pii_access_log Art. 9). La MÁQUINA DE
    // ESTADOS DE CONSENT (Habeas Data: guards soft-revoke + renovación
    // post-anonimización + mergedEvidence + renewals + effectiveConsentGiven)
    // ahora vive API-side en _compute_consent_update (contacts.py), idéntica al
    // comportamiento previo (verificada con tests). Antes era escritura directa
    // a Supabase con la lógica acá (drift §3, sin audit). El server action solo
    // parsea el form, sube el adjunto client-side y envía los inputs crudos.
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) {
      return { ok: false, error: 'Sin permisos (se requiere owner o manager).' }
    }
    const editContactId = (formData.get('contact_id') as string) || ''
    if (!editContactId) return { ok: false, error: 'contact_id requerido.' }

    const consentGiven = formData.get('consent_given') === 'on'
    const sourceRaw = ((formData.get('consent_source') as string) || '').trim()
    const consentSource = sourceRaw
    const consentNoticeVersion = CURRENT_PRIVACY_NOTICE_VERSION
    const renewedConsentEvidence = ((formData.get('renewed_consent_evidence') as string) || '').trim()
    const consentEvidenceNote = ((formData.get('consent_evidence_note') as string) || '').trim() || renewedConsentEvidence
    const renewedConsentChecked = formData.get('renewed_consent') === 'on'
    const revocationReason = ((formData.get('consent_revoked_reason') as string) || '').trim()

    // Validaciones UX inmediatas (la API también las enforce server-side; estos
    // throws dan feedback rápido al operador sin round-trip).
    if (consentGiven && (!sourceRaw || !CONSENT_SOURCES.has(sourceRaw))) {
      return { ok: false, error:
        'Falta seleccionar el canal por el que el titular dio consent. ' +
        'Es obligatorio para audit (Ley 1581 Art. 9).' }
    }
    if (consentGiven && consentSource === 'other' && consentEvidenceNote.length < 20) {
      return { ok: false, error:
        'Cuando el canal es "Otro" la Evidencia debe describir de dónde vino el ' +
        'consentimiento (mínimo 20 caracteres).' }
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
    // Adjunto de evidencia in_person: se sube client-side a Storage (el archivo
    // NO viaja por JSON); a la API va solo la metadata en consent_attachment.
    // El API la mergea en consent_evidence (limpia attachment_url legacy).
    let consentAttachment: Record<string, unknown> | undefined
    if (consentSource === 'in_person') {
      const upload = await uploadConsentEvidence(formData, editContactId, m.tenant_id)
      const nowIso = new Date().toISOString()
      if (upload.status === 'uploaded') {
        consentAttachment = {
          attachment_path: upload.path,
          attachment_mime: upload.mime,
          attachment_size: upload.size,
          attachment_uploaded_at: nowIso,
        }
      } else if (upload.status === 'rejected' || upload.status === 'error') {
        const skipReason = upload.status === 'rejected' ? upload.reason : 'storage_error'
        consentAttachment = {
          attachment_skip_reason: skipReason,
          attachment_skip_filename: 'filename' in upload ? upload.filename : null,
          attachment_skip_received_mime: 'receivedMime' in upload ? upload.receivedMime : null,
          attachment_skip_storage_message: upload.status === 'error' ? upload.message : null,
          attachment_skip_at: nowIso,
        }
        console.warn('[F10] Edit contact: adjunto no se subió', { contactId: editContactId, skipReason })
      }
    }

    // shipping_phone (opcional): solo se envía si el operador ingresó uno válido;
    // vacío → se omite y la API conserva el valor actual (PATCH semantics).
    const editShippingRaw = ((formData.get('shipping_phone') as string) || '').replace(/\D/g, '')
    const editShippingE164 = (editShippingRaw.length >= 10 && editShippingRaw[editShippingRaw.length - 10] !== '0')
      ? `+57${editShippingRaw.slice(-10)}`
      : undefined

    const token = (await sb.auth.getSession()).data.session?.access_token
    if (!token) return { ok: false, error: 'Sesión expirada. Vuelve a iniciar sesión.' }

    // Decisión F2 (coordinación UI+API de la semántica de presencia): el API ya
    // distingue "campo enviado como null (limpiar)" de "campo ausente (no tocar)".
    // Los inputs de PII se renderizan `disabled` cuando la PII está bloqueada
    // (piiUnlocked=false) y un input disabled NO viaja en FormData. Por eso SOLO
    // incluimos un campo en el PATCH si su input estuvo PRESENTE en el form:
    //   • presente y vacío ('')  → null → el API limpia el campo (bug corregido).
    //   • ausente (disabled/oculto) → OMITIDO → el API conserva el valor actual.
    // Sin esta coordinación, editar el consent con PII bloqueada borraría
    // name/email/notes/documento/dirección al enviarlos como null.
    const patchBody: Record<string, unknown> = {
      // Inputs CRUDOS del flujo de consent — el API computa la máquina de
      // estados (guards soft-revoke/renovación + mergedEvidence + fechas).
      consent_given:   consentGiven,
      consent_source:  consentSource || null,
      consent_channel: 'dashboard_console',
      consent_notice_version: consentNoticeVersion || null,
      consent_evidence_note: consentEvidenceNote || null,
      consent_revoked_reason: revocationReason || null,
      renewed_consent: renewedConsentChecked,
      renewed_consent_evidence: renewedConsentEvidence || null,
    }
    if (formData.has('name')) {
      patchBody.name = (formData.get('name') as string) || null
    }
    if (formData.has('email')) {
      patchBody.email = (((formData.get('email') as string) || '').trim().toLowerCase()) || null
    }
    if (formData.has('notes')) {
      patchBody.notes = (formData.get('notes') as string) || null
    }
    if (editShippingE164) {
      patchBody.shipping_phone = editShippingE164
    }
    // DocumentFields solo se renderiza si piiUnlocked → si sus inputs no están
    // presentes, no tocamos el documento.
    if (formData.has('document_type') || formData.has('document_number')) {
      patchBody.document_type = editDocType && editDocNumber ? editDocType : null
      patchBody.document_number = editDocType && editDocNumber ? editDocNumber : null
    }
    // AddressSelector solo se renderiza si piiUnlocked y hay dirección/se agrega
    // → si addr_street no viaja, conservamos la dirección actual.
    if (formData.has('addr_street')) {
      patchBody.address = address
    }
    if (consentAttachment) {
      patchBody.consent_attachment = consentAttachment
    }

    let res: Response
    try {
      res = await fetch(`${CORE_API_URL}/api/v1/contacts/${encodeURIComponent(editContactId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify(patchBody),
      })
    } catch (e) {
      console.error('[editContact] network error', e)
      return { ok: false, error: 'Error de red al actualizar el contacto. Intenta de nuevo.' }
    }
    if (!res.ok) {
      const detail = await res.text()
      return { ok: false, error: detail || 'Error al actualizar el contacto.' }
    }
    revalidatePath('/dashboard/contacts')
    return { ok: true }
  }

  async function deleteContact(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    // Sem 7 F2 cierre 2026-05-20 — Bug founder UAT (web.log alerta):
    // ANTES usábamos `session.user` directamente — Supabase lo marcaba
    // como `insecure` porque viene de cookies sin verificación de JWT.
    // AHORA: `getUser()` contacta al Auth Server y valida autenticidad
    // (operación segura). `getSession()` solo para el `access_token`
    // que va al endpoint API (que también verifica el JWT server-side).
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    // Sem 7 F2 cierre 2026-05-19 — purge endpoint requiere role 'owner'
    // (hard cascade es destructivo, no debe ser permitido a 'manager').
    if (!m.tenant_id || m.role !== 'owner') {
      return { ok: false, error: 'Solo el owner puede eliminar contactos en cascade.' }
    }
    const contactId = (formData.get('contact_id') as string) || ''
    if (!contactId) return { ok: false, error: 'contact_id requerido.' }
    const reason = ((formData.get('delete_reason') as string) || '').trim()
    const { data: { session } } = await sb.auth.getSession()
    const token = session?.access_token
    if (!token) {
      return { ok: false, error: 'Sesión expirada — recarga la página.' }
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
        // Sem 7 F2 cierre 2026-05-21 — Capa A.3 (Wompi payment link guard):
        // 409 = purge bloqueada por link Wompi activo (<30 min). Wompi NO
        // permite invalidar links existentes, así que propagamos mensaje
        // claro al operador en lugar de error genérico.
        if (res.status === 409) {
          type PurgeBlockedDetail = {
            code?: string
            message?: string
            pending_payments?: unknown[]
          }
          let parsed: PurgeBlockedDetail | null = null
          try {
            const body = (await res.json()) as { detail?: PurgeBlockedDetail }
            parsed = body?.detail ?? null
          } catch {
            parsed = null
          }
          if (parsed?.code === 'purge_blocked_active_payment_link') {
            const count = Array.isArray(parsed.pending_payments)
              ? parsed.pending_payments.length
              : 0
            return { ok: false, error:
              parsed.message ||
                `No se puede eliminar: el contacto tiene ${count} link(s) de pago Wompi activo(s). ` +
                  'Wompi no permite invalidar links existentes — espera ~30 min a que expire(n) ' +
                  'o cancela la(s) orden(es) manualmente antes de reintentar.' }
          }
        }
        const errText = await res.text()
        return { ok: false, error: `Purge falló (${res.status}): ${errText.slice(0, 200)}` }
      }
    } catch (e) {
      // F68: los return {ok:false} internos ya salieron de la función; este catch
      // solo captura rechazos reales de red (fetch reject) — antes re-lanzaba y en
      // prod Next.js enmascaraba el mensaje.
      console.error('[deleteContact] purge API call falló', e)
      return { ok: false, error: 'Error de red al eliminar el contacto. Intenta de nuevo.' }
    }
    revalidatePath('/dashboard/contacts')
    return { ok: true }
  }

  // Rev. 101 (F1) — HTML imprimible del SAR. Endpoint GET (no POST).
  async function sarPrintableAction(formData: FormData): Promise<{
    ok: boolean
    status: number
    html?: string
    error?: string
  }> {
    'use server'
    const sb = await createClient()
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
    const sb = await createClient()
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
      // Decisión F2 (Habeas Data Art. 16): la rectificación se satisface con el
      // formulario de edición (trazable vía PATCH auditado), NO con type='rectify'
      // del SAR — la UI ya no ofrece ese tipo. Se retira el branch residual.
      if (res.ok && sarType === 'erase') {
        revalidatePath('/dashboard/contacts')
      }
      return { ok: res.ok, status: res.status, type: sarType, payload }
    } catch (e) {
      return { ok: false, status: 502, type: sarType, error: e instanceof Error ? e.message : 'Network error' }
    }
  }

  // Rev. 105 / Decisión F2 — Server action: reactivar consent tras soft opt-out
  // (STOP keyword via WhatsApp). Limpia consent_revoked_at + reason; PII intacta
  // (no se anonimizó). Idempotente: si ya está activo, no-op.
  //
  // Decisión F2: ANTES esta acción mutaba la DB con admin client DIRECTO
  // (consent_audit_log + contacts + conversations) sin rate-limit, idempotencia
  // ni atomicidad, rompiendo la simetría de auditoría del módulo. AHORA delega al
  // endpoint POST /api/v1/contacts/{id}/reactivate-consent (RL_WRITE + idempotency
  // + consent_audit_log append-only + sync Inbox), igual que el resto del módulo.
  async function reactivateConsentAction(
    formData: FormData,
  ): Promise<{ ok: boolean; status: number; message: string }> {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    // owner-only (Habeas Data ART. 11). Feedback rápido UX; la API también lo
    // enforce (require_owner_role) → defensa en profundidad.
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

    const token = (await sb.auth.getSession()).data.session?.access_token
    if (!token) return { ok: false, status: 401, message: 'Sesión expirada — recarga la página.' }

    let res: Response
    try {
      res = await fetch(
        `${CORE_API_URL}/api/v1/contacts/${encodeURIComponent(contactId)}/reactivate-consent`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ reason }),
          cache: 'no-store',
        },
      )
    } catch (e) {
      console.error('[reactivateConsent] network error', e)
      return { ok: false, status: 502, message: 'Error de red al reactivar consent. Intenta de nuevo.' }
    }

    type ReactivatePayload = {
      message?: string
      conversations_reactivated?: number
      detail?: string | { message?: string }
    }
    let payload: ReactivatePayload | null = null
    try { payload = (await res.json()) as ReactivatePayload } catch { payload = null }

    if (!res.ok) {
      const rawDetail = payload?.detail
      const detailMsg = typeof rawDetail === 'string'
        ? rawDetail
        : (rawDetail?.message || payload?.message)
      return {
        ok: false,
        status: res.status,
        message: detailMsg || `No se pudo reactivar consent (${res.status}).`,
      }
    }

    revalidatePath('/dashboard/contacts')
    revalidatePath('/dashboard/inbox')

    const n = payload?.conversations_reactivated ?? 0
    const syncMsg = n > 0 ? ` Conversaciones reactivadas: ${n} (Inbox sincronizado).` : ''
    return {
      ok: true,
      status: 200,
      message: (payload?.message || 'Consent reactivado. Marketing puede reanudarse al cliente.') + syncMsg,
    }
  }

  // ── UI ─────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header — cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={Users}
        title="Contactos"
        description={`${contacts.length} contactos · ${consentCount} con consentimiento Habeas Data · ${revokedCount} revocados`}
      />

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
        loadError={loadError}
        capReached={capReached}
        fetchCap={CONTACTS_FETCH_CAP}
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
