'use server'

import { createClient } from '@/utils/supabase/server'

const CONSENT_EVIDENCE_BUCKET = 'consent-evidence'
const CONSENT_EVIDENCE_MAX_SIZE_BYTES = 5 * 1024 * 1024 // 5 MB

// MIME oficiales aceptados por el bucket de Storage (sincronizado con la
// migración 20260510020000). Algunos browsers envían cadenas alternativas
// como `application/x-pdf` o vacío — para esos casos hacemos fallback por
// extensión antes de rechazar.
const CONSENT_EVIDENCE_ALLOWED_MIMES: ReadonlySet<string> = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/webp',
])

const EXTENSION_TO_MIME: Record<string, string> = {
  pdf: 'application/pdf',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
}

export type UploadEvidenceResult =
  | { status: 'skipped'; reason: 'no_file' | 'empty_file' }
  | { status: 'rejected'; reason: 'too_large' | 'mime_not_allowed'; receivedMime?: string; filename?: string }
  | { status: 'uploaded'; url: string; path: string; mime: string; size: number }
  | { status: 'error'; message: string }

/**
 * Rev. 103 (F10) — Sube evidencia física al bucket privado consent-evidence.
 *
 * Path convention: {tenant_id}/{contact_id}/{timestamp}-{filename}
 * Validaciones: size ≤ 5MB · MIME en allowlist (PDF/JPG/PNG/WEBP) con
 * fallback por extensión si el browser no envió un MIME estándar.
 *
 * YELLOW-13 (auditoría OWASP 2026-08-23): el tenant_id se deriva SIEMPRE de
 * la sesión (app_metadata del JWT) — nunca de un argumento del cliente
 * ('use server' = endpoint invocable con argumentos arbitrarios). Defensa en
 * profundidad: la policy de Storage sigue siendo la barrera última — si por
 * alguna razón se intenta escribir fuera del tenant, la policy lo rechaza.
 */
export async function uploadConsentEvidence(
  formData: FormData,
  contactId: string,
): Promise<UploadEvidenceResult> {
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const m = (user?.app_metadata ?? {}) as { tenant_id?: string }
  if (!user || !m.tenant_id) return { status: 'error', message: 'No autenticado' }
  const tenantId = m.tenant_id

  const file = formData.get('consent_evidence_file')
  if (!file || !(file instanceof File)) {
    return { status: 'skipped', reason: 'no_file' }
  }
  if (file.size === 0) {
    return { status: 'skipped', reason: 'empty_file' }
  }
  if (file.size > CONSENT_EVIDENCE_MAX_SIZE_BYTES) {
    return { status: 'rejected', reason: 'too_large', filename: file.name }
  }

  // Resolver MIME efectivo: prefiere el del browser si está en allowlist;
  // si no, intenta inferir por extensión. Esto cubre browsers que envían
  // 'application/x-pdf', '' (vacío) o sniff incorrecto.
  let effectiveMime = file.type
  if (!CONSENT_EVIDENCE_ALLOWED_MIMES.has(effectiveMime)) {
    const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
    const mimeFromExt = EXTENSION_TO_MIME[ext]
    if (mimeFromExt) {
      effectiveMime = mimeFromExt
    } else {
      return {
        status: 'rejected',
        reason: 'mime_not_allowed',
        receivedMime: file.type || '(empty)',
        filename: file.name,
      }
    }
  }

  const safeName = file.name.replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 100)
  const path = `${tenantId}/${contactId}/${Date.now()}-${safeName}`

  const { error } = await sb.storage.from(CONSENT_EVIDENCE_BUCKET).upload(path, file, {
    contentType: effectiveMime,
    upsert: false,
  })
  if (error) {
    return { status: 'error', message: error.message }
  }

  return {
    status: 'uploaded',
    // Rev. 103 hotfix: el bucket es PRIVADO; getPublicUrl() devuelve un
    // path /object/public/ que retorna 404. La UI debe usar
    // getConsentEvidenceSignedUrl(contactId) para acceder al archivo.
    // url se persiste vacío (compat con código que aún la lee).
    url: '',
    path,
    mime: effectiveMime,
    size: file.size,
  }
}

/**
 * Rev. 103 — Genera signed URL temporal (5 min) para acceder a un
 * adjunto de evidencia. Bucket privado: solo el tenant owner del
 * archivo puede leerlo (RLS lo refuerza). Llamado on-click desde la UI
 * cuando el operador quiere ver/descargar la evidencia.
 *
 * Retorna null si: contact no existe, contact pertenece a otro tenant,
 * no hay attachment_path en evidence, o storage falla.
 */
export async function getConsentEvidenceSignedUrl(
  contactId: string,
): Promise<{ url: string } | { error: string }> {
  if (!contactId) return { error: 'contact_id requerido' }
  const sb = await createClient()
  const { data: { user: u } } = await sb.auth.getUser()
  const m = (u?.app_metadata ?? {}) as { tenant_id?: string }
  if (!m.tenant_id) return { error: 'No autenticado' }

  const { data: contact } = await sb.from('contacts')
    .select('consent_evidence')
    .eq('id', contactId)
    .eq('tenant_id', m.tenant_id)
    .single()
  if (!contact) return { error: 'Contacto no encontrado' }

  const evidence = (contact.consent_evidence ?? {}) as Record<string, unknown>
  const path = typeof evidence.attachment_path === 'string'
    ? evidence.attachment_path
    : null
  if (!path) return { error: 'No hay archivo adjunto para este contacto' }

  const { data, error } = await sb.storage
    .from(CONSENT_EVIDENCE_BUCKET)
    .createSignedUrl(path, 60 * 5) // 5 min TTL

  if (error || !data?.signedUrl) {
    return { error: error?.message || 'No se pudo generar URL temporal' }
  }
  return { url: data.signedUrl }
}
