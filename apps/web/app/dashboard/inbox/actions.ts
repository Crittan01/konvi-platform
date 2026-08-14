'use server'

/**
 * G8b fase 2 — firma de URLs de adjuntos privados del inbox.
 *
 * Patrón de `getConsentEvidenceSignedUrl` (contacts): verifica sesión +
 * que el path pertenece al tenant del usuario (el path empieza por
 * `{tenant_id}/`), y firma con TTL corto. El bucket es PRIVADO
 * (`tenant-inbox-media`) — sin la firma el objeto no es legible.
 */
import { createClient } from '@/utils/supabase/server'
import {
  INBOX_MEDIA_BUCKET,
  INBOX_MEDIA_SIGNED_TTL_SECONDS,
  inboxMediaPathFromUrl,
  isInboxMediaPath,
} from './_lib/media'

export async function getInboxMediaSignedUrl(
  mediaUrl: string,
): Promise<{ url: string } | { error: string }> {
  if (!isInboxMediaPath(mediaUrl)) {
    return { error: 'media_url no es del esquema inbox-media://' }
  }
  const sb = await createClient()
  const { data: { user: u } } = await sb.auth.getUser()
  const tenantId = (u?.app_metadata ?? {}) as { tenant_id?: string }
  if (!u || !tenantId.tenant_id) return { error: 'No autenticado' }

  const path = inboxMediaPathFromUrl(mediaUrl)
  // El path debe pertenecer al tenant del usuario (convención {tenant_id}/…).
  if (!path.startsWith(`${tenantId.tenant_id}/`)) {
    return { error: 'El adjunto no pertenece a tu tenant' }
  }

  const { data, error } = await sb.storage
    .from(INBOX_MEDIA_BUCKET)
    .createSignedUrl(path, INBOX_MEDIA_SIGNED_TTL_SECONDS)

  if (error || !data?.signedUrl) {
    return { error: error?.message || 'No se pudo generar URL temporal' }
  }
  return { url: data.signedUrl }
}
