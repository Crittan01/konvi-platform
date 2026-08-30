'use client'

/**
 * Attachment uploader — botón 📎 que sube imagen al bucket `tenant-media`
 * y dispara el envío via `/api/conversations/{id}/send-image`.
 *
 * Rev. 109 P0-2 — feedback founder 2026-05-29 "modo humano envía imágenes".
 *
 * Flujo:
 *   1. Operador click 📎 → file picker (accept image/jpeg|png|webp).
 *   2. Validación local: tamaño ≤ 5MB, MIME en allowlist.
 *   3. Modal preview con caption opcional (max 1024 chars per Meta).
 *   4. Click "Enviar" → upload a tenant-media bucket via supabase-js.
 *   5. Obtener publicUrl → POST /api/conversations/{id}/send-image.
 *   6. Optimistic close + reset; el mensaje aparece via Realtime.
 *
 * NO depende del editor de texto — es independiente y se inserta al
 * lado del toolbar. No requiere `conversationId` en URL state porque
 * es client-side (`/api/conversations/[id]/send-image` resuelve por
 * params del proxy Next).
 */
import { useEffect, useRef, useState } from 'react'
import { Paperclip, X, Loader2, ImageIcon } from 'lucide-react'
import { createClient } from '@/utils/supabase/client'
import { errorDetailToString } from '../_lib/errors'
import { toInboxMediaUrl } from '../_lib/media'

interface Props {
  conversationId: string | null
  /** Callback opcional para refrescar mensajes tras envío exitoso. */
  onSent?: () => void
  /** Disable toggle (e.g., conversación NO en human_takeover). */
  disabled?: boolean
}

const MAX_BYTES = 5 * 1024 * 1024 // Meta image limit 5MB
const ACCEPTED_MIMES = ['image/jpeg', 'image/png', 'image/webp']

export function AttachmentUploader({ conversationId, onSent, disabled }: Props) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [caption, setCaption] = useState('')
  const [tenantId, setTenantId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // tenantId on-mount.
  useEffect(() => {
    const sb = createClient()
    sb.auth.getUser().then(({ data: { user } }) => {
      const tid = user?.app_metadata?.tenant_id as string | undefined
      if (tid) setTenantId(tid)
    })
  }, [])

  // Limpiar ObjectURL del preview cuando cambia / cierra.
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  const reset = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(null)
    setPreviewUrl(null)
    setCaption('')
    setError(null)
    setUploading(false)
    if (inputRef.current) inputRef.current.value = ''
  }

  const close = () => {
    reset()
    setOpen(false)
  }

  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setError(null)
    if (!ACCEPTED_MIMES.includes(f.type)) {
      setError(`Tipo no permitido: ${f.type}. Aceptados: JPEG, PNG, WebP.`)
      return
    }
    if (f.size > MAX_BYTES) {
      setError(
        `Archivo demasiado grande (${(f.size / 1024 / 1024).toFixed(1)} MB). ` +
        `Máximo 5 MB por Meta WhatsApp Cloud API.`,
      )
      return
    }
    setFile(f)
    setPreviewUrl(URL.createObjectURL(f))
  }

  const onSend = async () => {
    if (!file || !conversationId || !tenantId) {
      setError('Falta archivo, conversación o tenant — recarga la página.')
      return
    }
    setError(null)
    setUploading(true)
    try {
      const ext = file.name.split('.').pop() || 'jpg'
      const safeExt = ext.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 5)
      // G8b: bucket PRIVADO tenant-inbox-media (antes: tenant-media público —
      // cualquiera con la URL leía el adjunto). El path queda sin prefijo
      // extra: el bucket ya es dedicado. Se persiste el esquema
      // `inbox-media://{path}` (no la URL pública) — el chat lo firma al
      // render y el worker lo firma al enviar a Meta.
      const path = `${tenantId}/${conversationId}/${Date.now()}-${Math.random().toString(36).slice(2)}.${safeExt}`
      const sb = createClient()
      const { error: uploadErr } = await sb.storage
        .from('tenant-inbox-media')
        .upload(path, file, { contentType: file.type, upsert: false })
      if (uploadErr) {
        throw new Error(`Upload falló: ${uploadErr.message}`)
      }
      const imageUrl = toInboxMediaUrl(path)

      const res = await fetch(
        `/api/conversations/${conversationId}/send-image`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            image_url: imageUrl,
            caption: caption.trim() || null,
          }),
        },
      )
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Error desconocido' }))
        // BLOQUE E: `detail` puede ser objeto ({code, message}) — normalizar a string legible
        // (antes `new Error(obj)` producía "[object Object]" en la UI).
        throw new Error(errorDetailToString(data?.detail, `HTTP ${res.status}`))
      }

      // Éxito — close + refresh por Realtime (no necesitamos optimistic push).
      onSent?.()
      close()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error desconocido al enviar')
      setUploading(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled || !conversationId}
        title={disabled ? 'Toma el control para enviar archivos' : 'Adjuntar imagen'}
        aria-label="Adjuntar imagen"
        className="h-7 min-w-[28px] px-1.5 rounded inline-flex items-center justify-center text-foreground hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <Paperclip className="h-4 w-4" />
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Adjuntar imagen al cliente"
        >
          <div className="w-full max-w-md rounded-lg border border-border bg-card shadow-xl">
            <header className="flex items-center justify-between p-3 border-b border-border">
              <h2 className="text-sm font-semibold inline-flex items-center gap-2">
                <ImageIcon className="h-4 w-4" /> Enviar imagen
              </h2>
              <button
                type="button"
                onClick={close}
                disabled={uploading}
                aria-label="Cerrar"
                className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-accent disabled:opacity-40"
              >
                <X className="h-4 w-4" />
              </button>
            </header>

            <div className="p-3 space-y-3">
              {!file ? (
                <button
                  type="button"
                  onClick={() => inputRef.current?.click()}
                  className="w-full h-32 rounded-md border-2 border-dashed border-border hover:border-foreground/30 transition-colors inline-flex flex-col items-center justify-center gap-1 text-muted-foreground"
                >
                  <ImageIcon className="h-8 w-8" />
                  <span className="text-sm">Seleccionar imagen</span>
                  <span className="text-[10px]">JPG · PNG · WebP — máx 5 MB</span>
                </button>
              ) : (
                <div className="space-y-2">
                  <div className="relative rounded-md border border-border overflow-hidden bg-muted">
                    {previewUrl && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={previewUrl}
                        alt="Preview"
                        className="w-full max-h-64 object-contain"
                      />
                    )}
                    <button
                      type="button"
                      onClick={reset}
                      disabled={uploading}
                      className="absolute top-1 right-1 h-7 w-7 rounded-full bg-black/60 text-white inline-flex items-center justify-center hover:bg-black/80 disabled:opacity-40"
                      aria-label="Quitar imagen"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    {file.name} · {(file.size / 1024).toFixed(0)} KB
                  </p>
                  <div>
                    <label className="text-[10px] font-semibold uppercase text-muted-foreground">
                      Texto que acompaña (opcional)
                    </label>
                    <textarea
                      value={caption}
                      onChange={e => setCaption(e.target.value.slice(0, 1024))}
                      disabled={uploading}
                      rows={2}
                      maxLength={1024}
                      placeholder="Descripción breve para el cliente…"
                      className="w-full mt-1 px-2 py-1.5 rounded-md border border-border bg-background text-sm resize-none disabled:opacity-60"
                    />
                    <p className="text-[10px] text-muted-foreground text-right mt-0.5">
                      {caption.length} / 1024
                    </p>
                  </div>
                </div>
              )}

              <input
                ref={inputRef}
                type="file"
                accept={ACCEPTED_MIMES.join(',')}
                className="hidden"
                onChange={onPickFile}
              />

              {error && (
                <p className="text-xs text-danger-fg bg-danger-bg border border-danger-border rounded px-2 py-1">
                  {error}
                </p>
              )}
            </div>

            <footer className="flex items-center justify-end gap-2 p-3 border-t border-border">
              <button
                type="button"
                onClick={close}
                disabled={uploading}
                className="h-8 px-3 rounded-md text-sm border border-border hover:bg-accent disabled:opacity-40"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={onSend}
                disabled={!file || uploading || !conversationId || !tenantId}
                className="h-8 px-3 rounded-md text-sm bg-foreground text-background hover:opacity-90 inline-flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {uploading ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Enviando…
                  </>
                ) : (
                  <>Enviar imagen</>
                )}
              </button>
            </footer>
          </div>
        </div>
      )}
    </>
  )
}
