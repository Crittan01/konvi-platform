'use client'

/**
 * G8b fase 2 — imagen de adjunto PRIVADO del inbox (bucket tenant-inbox-media).
 *
 * Si media_url es del esquema `inbox-media://` → pide signed URL al server
 * (getInboxMediaSignedUrl: verifica sesión + tenant del path) y la usa con
 * refresh antes de expirar. Si es http(s) → legacy pública o catálogo → directo.
 */
import { useEffect, useState } from 'react'
import { ImageIcon } from 'lucide-react'
import { getInboxMediaSignedUrl } from '../actions'
import {
  INBOX_MEDIA_SIGNED_TTL_SECONDS,
  isInboxMediaPath,
} from '../_lib/media'

export function InboxImage({
  mediaUrl,
  alt,
}: {
  mediaUrl: string
  alt: string
}) {
  const isPrivate = isInboxMediaPath(mediaUrl)
  const [src, setSrc] = useState<string | null>(isPrivate ? null : mediaUrl)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!isPrivate) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | null = null

    const resolve = async () => {
      const r = await getInboxMediaSignedUrl(mediaUrl)
      if (!alive) return
      if ('url' in r) {
        setSrc(r.url)
        // Refresh antes de expirar (90% del TTL).
        timer = setTimeout(resolve, INBOX_MEDIA_SIGNED_TTL_SECONDS * 900)
      } else {
        setFailed(true)
      }
    }
    resolve()
    return () => {
      alive = false
      if (timer) clearTimeout(timer)
    }
  }, [mediaUrl, isPrivate])

  if (failed) {
    return (
      <span className="mb-1.5 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <ImageIcon className="h-3.5 w-4" /> No se pudo cargar la imagen
      </span>
    )
  }
  if (!src) {
    return (
      <span className="mb-1.5 block h-24 w-40 animate-pulse rounded-lg bg-muted/40" />
    )
  }
  return (
    <a href={src} target="_blank" rel="noopener noreferrer" className="block mb-1.5">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt || 'imagen'}
        className="rounded-lg max-w-full max-h-72 object-contain border border-border/40 bg-background/30"
        loading="lazy"
      />
    </a>
  )
}
