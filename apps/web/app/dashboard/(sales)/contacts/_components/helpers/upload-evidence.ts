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
 * RLS server-side cubre el caso defensivo: si por alguna razón el caller
 * intenta escribir fuera de su tenant, la policy lo rechaza.
 */
export async function uploadConsentEvidence(
  formData: FormData,
  contactId: string,
  tenantId: string,
): Promise<UploadEvidenceResult> {
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

  const sb = createClient()
  const safeName = file.name.replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 100)
  const path = `${tenantId}/${contactId}/${Date.now()}-${safeName}`

  const { error } = await sb.storage.from(CONSENT_EVIDENCE_BUCKET).upload(path, file, {
    contentType: effectiveMime,
    upsert: false,
  })
  if (error) {
    return { status: 'error', message: error.message }
  }

  const { data } = sb.storage.from(CONSENT_EVIDENCE_BUCKET).getPublicUrl(path)
  return {
    status: 'uploaded',
    url: data.publicUrl,
    path,
    mime: effectiveMime,
    size: file.size,
  }
}
