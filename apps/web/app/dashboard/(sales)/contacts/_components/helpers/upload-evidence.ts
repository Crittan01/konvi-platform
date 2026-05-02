'use server'

import { createClient } from '@/utils/supabase/server'

const CONSENT_EVIDENCE_BUCKET = 'consent-evidence'
const CONSENT_EVIDENCE_MAX_SIZE_BYTES = 5 * 1024 * 1024 // 5 MB
const CONSENT_EVIDENCE_ALLOWED_MIMES: ReadonlySet<string> = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/webp',
])

export type UploadEvidenceResult =
  | { status: 'skipped'; reason: 'no_file' | 'empty_file' }
  | { status: 'rejected'; reason: 'too_large' | 'mime_not_allowed' }
  | { status: 'uploaded'; url: string; path: string; mime: string; size: number }
  | { status: 'error'; message: string }

/**
 * Rev. 103 (F10) — Sube evidencia física al bucket privado consent-evidence.
 *
 * Path convention: {tenant_id}/{contact_id}/{timestamp}-{filename}
 * Validaciones: size ≤ 5MB · MIME en allowlist (PDF/JPG/PNG/WEBP).
 *
 * RLS server-side cubre el caso defensivo: si por alguna razón el caller
 * intenta escribir fuera de su tenant, la policy lo rechaza. Aquí
 * validamos también para devolver un error humano antes del round-trip.
 *
 * Retorna URL pública usando getPublicUrl. Como el bucket es privado, la
 * URL solo funciona para usuarios autenticados con acceso RLS al objeto.
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
    return { status: 'rejected', reason: 'too_large' }
  }
  if (!CONSENT_EVIDENCE_ALLOWED_MIMES.has(file.type)) {
    return { status: 'rejected', reason: 'mime_not_allowed' }
  }

  const sb = createClient()
  const safeName = file.name.replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 100)
  const path = `${tenantId}/${contactId}/${Date.now()}-${safeName}`

  const { error } = await sb.storage.from(CONSENT_EVIDENCE_BUCKET).upload(path, file, {
    contentType: file.type,
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
    mime: file.type,
    size: file.size,
  }
}
