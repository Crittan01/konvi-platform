'use client'

/**
 * GalleryPickerModal — selector de imágenes ya subidas al bucket
 * `tenant-media/{tenant_id}/` para reasignar como `cover_image_url`.
 *
 * Caso founder rev. 107 2026-05-24: 16 productos KAIU tenían imágenes
 * reales en Storage, pero un script anterior sobrescribió cover_image_url
 * con placeholders sintéticos → mapping `product_id → file` perdido.
 * Las imágenes seguían existiendo en Storage pero sin tabla de mapping.
 *
 * Este picker permite asociar manualmente desde UI: click en cualquier
 * imagen del grid → setea cover_image_url al public URL del archivo.
 */
import { useEffect, useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import { X, Loader2, Image as ImageIcon } from 'lucide-react'

type FileEntry = {
  name: string
  size: number
  url: string
}

interface Props {
  open: boolean
  onClose: () => void
  tenantId: string
  onSelect: (publicUrl: string) => void
}

export function GalleryPickerModal({ open, onClose, tenantId, onSelect }: Props) {
  const [files, setFiles] = useState<FileEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false

    const fetchGallery = async () => {
      setLoading(true)
      setError(null)
      try {
        const supabase = createClient()
        const { data, error: listErr } = await supabase
          .storage
          .from('tenant-media')
          .list(tenantId, { limit: 200, sortBy: { column: 'created_at', order: 'desc' } })
        if (listErr) throw new Error(listErr.message)

        const entries: FileEntry[] = (data || [])
          .filter(f => {
            // Solo archivos imagen, excluir "logo" reservado del tenant.
            const name = f.name || ''
            if (!name || name === 'logo') return false
            const mime = (f as { metadata?: { mimetype?: string } })?.metadata?.mimetype || ''
            return mime.startsWith('image/')
          })
          .map(f => {
            const { data: publicUrlData } = supabase
              .storage
              .from('tenant-media')
              .getPublicUrl(`${tenantId}/${f.name}`)
            return {
              name: f.name,
              size: (f as { metadata?: { size?: number } })?.metadata?.size ?? 0,
              url: publicUrlData.publicUrl,
            }
          })
        if (!cancelled) setFiles(entries)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'No se pudo cargar la galería')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchGallery()
    return () => { cancelled = true }
  }, [open, tenantId])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="bg-card border border-border rounded-xl shadow-2xl max-w-4xl w-full max-h-[80vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
          <div className="flex items-center gap-2">
            <ImageIcon className="h-5 w-5 text-primary" />
            <h3 className="text-sm font-semibold">Galería del tenant</h3>
            <span className="text-xs text-muted-foreground">
              · imágenes ya subidas a Storage
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Cerrar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto p-4">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}
          {error && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          {!loading && !error && files.length === 0 && (
            <div className="text-center py-12 text-sm text-muted-foreground">
              No hay imágenes en la galería todavía. Sube alguna desde el
              botón &quot;Subir&quot; del producto.
            </div>
          )}
          {!loading && files.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
              {files.map(f => (
                <button
                  key={f.name}
                  type="button"
                  onClick={() => {
                    onSelect(f.url)
                    onClose()
                  }}
                  className="group relative aspect-square rounded-lg overflow-hidden border-2 border-border hover:border-primary transition-colors bg-muted/20"
                  title={`${f.name} · ${Math.round(f.size / 1024)} KB`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={f.url}
                    alt={f.name}
                    className="absolute inset-0 w-full h-full object-cover"
                    loading="lazy"
                  />
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <p className="text-[10px] text-white truncate">
                      {Math.round(f.size / 1024)} KB
                    </p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border text-[11px] text-muted-foreground">
          {files.length > 0 && (
            <span>{files.length} imágenes · click para asignar al producto</span>
          )}
        </div>
      </div>
    </div>
  )
}
