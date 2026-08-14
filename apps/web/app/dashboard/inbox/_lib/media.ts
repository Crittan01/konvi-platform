/**
 * G8b fase 2 — esquema de media privada del inbox.
 *
 * Los adjuntos que el operador envía a clientes viven en el bucket PRIVADO
 * `tenant-inbox-media` (antes: tenant-media público → legibles por cualquiera
 * con la URL). En `messages.media_url` se persiste el PATH con el esquema
 * distintivo `inbox-media://{path}` en vez de la URL pública completa.
 *
 * Consumidores:
 *  - Chat: si media_url empieza con el esquema → firmar (server action) antes
 *    de renderizar. Si es http(s) → legacy pública o catálogo, render directo.
 *  - Worker (envío a Meta): firma con TTL holgado al procesar la cola.
 */

export const INBOX_MEDIA_SCHEME = 'inbox-media://'
export const INBOX_MEDIA_BUCKET = 'tenant-inbox-media'
/** TTL de la URL firmada para render en el chat (minutos). */
export const INBOX_MEDIA_SIGNED_TTL_SECONDS = 60 * 60 // 1h
/** TTL holgado para el envío a Meta (descarga en el momento del envío). */
export const INBOX_MEDIA_META_TTL_SECONDS = 24 * 60 * 60 // 24h

export function isInboxMediaPath(url: string | null | undefined): boolean {
  return typeof url === 'string' && url.startsWith(INBOX_MEDIA_SCHEME)
}

export function inboxMediaPathFromUrl(url: string): string {
  return url.slice(INBOX_MEDIA_SCHEME.length)
}

export function toInboxMediaUrl(path: string): string {
  return `${INBOX_MEDIA_SCHEME}${path}`
}
