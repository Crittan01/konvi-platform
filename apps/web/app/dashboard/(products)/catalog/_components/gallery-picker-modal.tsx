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
import { useEffect, useRef, useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import { X, Loader2, Image as ImageIcon, Trash2, Info } from 'lucide-react'
import { useConfirm } from '@/components/ui/confirm-dialog'

const GALLERY_LIMIT = 200

type FileEntry = {
  name: string
  size: number
  url: string
  createdAt: string | null
  usedByProduct: string | null  // título del producto que tiene cover_image_url=url, si alguno
}

interface Props {
  open: boolean
  onClose: () => void
  tenantId: string
  onSelect: (publicUrl: string) => void
}

export function GalleryPickerModal({ open, onClose, tenantId, onSelect }: Props) {
  const confirmar = useConfirm()
  const [files, setFiles] = useState<FileEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletingName, setDeletingName] = useState<string | null>(null)
  const [truncated, setTruncated] = useState(false)
  const dialogRef = useRef<HTMLDivElement>(null)

  const fetchGallery = async () => {
    setLoading(true)
    setError(null)
    try {
      const supabase = createClient()
      // 1) Listar archivos en Storage.
      const { data, error: listErr } = await supabase
        .storage
        .from('tenant-media')
        .list(tenantId, { limit: GALLERY_LIMIT, sortBy: { column: 'created_at', order: 'desc' } })
      if (listErr) throw new Error(listErr.message)
      setTruncated((data?.length ?? 0) >= GALLERY_LIMIT)

      // 2) Reverse lookup: ¿qué producto, si alguno, usa cada archivo? Se consideran TANTO la portada
      //    del producto (products.cover_image_url) COMO la foto de cada variante (product_variations.image_url)
      //    — antes solo miraba la portada y marcaba como "sin asignar" fotos que sí usaban las variantes.
      const [{ data: prodData, error: prodErr }, { data: varData, error: varErr }] = await Promise.all([
        supabase
          .from('products')
          .select('title, cover_image_url')
          .eq('tenant_id', tenantId)
          .not('cover_image_url', 'is', null),
        supabase
          .from('product_variations')
          .select('image_url, products(title)')
          .eq('tenant_id', tenantId)
          .not('image_url', 'is', null),
      ])
      if (prodErr) throw new Error(prodErr.message)
      if (varErr) throw new Error(varErr.message)
      const urlToProduct = new Map<string, string>()
      for (const p of (prodData || [])) {
        if (p.cover_image_url && p.title) urlToProduct.set(p.cover_image_url, p.title)
      }
      for (const v of (varData || []) as { image_url: string | null; products: { title?: string } | { title?: string }[] | null }[]) {
        if (!v.image_url) continue
        const prod = Array.isArray(v.products) ? v.products[0] : v.products
        const title = prod?.title
        if (title && !urlToProduct.has(v.image_url)) urlToProduct.set(v.image_url, title)
      }

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
            createdAt: (f as { created_at?: string | null })?.created_at ?? null,
            usedByProduct: urlToProduct.get(publicUrlData.publicUrl) ?? null,
          }
        })
        // Ordenamiento: huérfanas primero (más útil para el founder
        // reasignándolas), luego en uso. Dentro de cada grupo, más
        // recientes primero (created_at desc).
        .sort((a, b) => {
          const aOrphan = a.usedByProduct ? 1 : 0
          const bOrphan = b.usedByProduct ? 1 : 0
          if (aOrphan !== bOrphan) return aOrphan - bOrphan
          const aTs = a.createdAt ? Date.parse(a.createdAt) : 0
          const bTs = b.createdAt ? Date.parse(b.createdAt) : 0
          return bTs - aTs
        })
      setFiles(entries)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo cargar la galería')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    void fetchGallery()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tenantId])

  // A11y: cerrar con Escape + enfocar el diálogo al abrir (semántica de diálogo modal).
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    dialogRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  /**
   * Borra el archivo de Storage. Operación destructiva — confirm antes.
   * Si el cover_image_url de algún producto apunta a este archivo, el
   * thumbnail aparecerá broken hasta que reasignes uno nuevo (no cascada
   * automática). El componente catalog ya tiene fallback <ImageOff>.
   */
  const handleDelete = async (fileName: string) => {
    const sizeKb = Math.round((files.find(f => f.name === fileName)?.size ?? 0) / 1024)
    if (!(await confirmar({
      title: `¿Borrar definitivamente "${fileName}"?`,
      description: `${sizeKb} KB. Si algún producto usa esta imagen, dejará de mostrarse hasta que le asignes otra. Esta acción no se puede deshacer.`,
      confirmLabel: 'Borrar', destructive: true,
    }))) return

    setDeletingName(fileName)
    setError(null)
    try {
      const supabase = createClient()
      const { error: delErr } = await supabase
        .storage
        .from('tenant-media')
        .remove([`${tenantId}/${fileName}`])
      if (delErr) throw new Error(delErr.message)
      // Refresh listing.
      await fetchGallery()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo borrar')
    } finally {
      setDeletingName(null)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="gallery-picker-title"
        tabIndex={-1}
        className="bg-card border border-border rounded-xl shadow-2xl max-w-4xl w-full max-h-[80vh] flex flex-col focus:outline-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
          <div className="flex items-center gap-2">
            <ImageIcon className="h-5 w-5 text-primary" />
            <h3 id="gallery-picker-title" className="text-sm font-semibold">Galería de imágenes</h3>
            <span className="text-xs text-muted-foreground">
              · fotos que ya subiste
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
          {!loading && !error && truncated && (
            <div className="mb-3 flex items-start gap-2 rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-xs text-warning-fg">
              <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>Mostrando las {GALLERY_LIMIT} imágenes más recientes. Si buscas una más antigua, súbela de nuevo desde el producto.</span>
            </div>
          )}
          {!loading && files.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
              {files.map(f => {
                const isDeleting = deletingName === f.name
                const sizeKB = Math.round(f.size / 1024)
                const dateStr = f.createdAt
                  ? new Date(f.createdAt).toLocaleDateString('es-CO', { timeZone: 'America/Bogota',
                      day: '2-digit', month: 'short', year: 'numeric',
                    })
                  : ''
                return (
                  <div
                    key={f.name}
                    className={`group relative rounded-lg overflow-hidden border-2 transition-colors bg-card flex flex-col ${
                      f.usedByProduct
                        ? 'border-success-border hover:border-success-fg'
                        : 'border-border hover:border-primary'
                    }`}
                  >
                    {/* Thumbnail con click para seleccionar */}
                    <div className="relative aspect-square bg-muted/20">
                      <button
                        type="button"
                        onClick={() => {
                          if (isDeleting) return
                          onSelect(f.url)
                          onClose()
                        }}
                        disabled={isDeleting}
                        className="absolute inset-0 w-full h-full"
                        title={`Seleccionar — ${f.name}`}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={f.url}
                          alt={f.name}
                          className="absolute inset-0 w-full h-full object-cover"
                          loading="lazy"
                        />
                        {isDeleting && (
                          <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
                            <Loader2 className="h-6 w-6 text-white animate-spin" />
                          </div>
                        )}
                      </button>

                      {/* Botón borrar — esquina superior derecha */}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDelete(f.name)
                        }}
                        disabled={isDeleting}
                        className="absolute top-1.5 right-1.5 z-10 h-7 w-7 rounded-md bg-black/60 hover:bg-destructive border border-white/20 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-50"
                        title="Borrar de Storage"
                        aria-label="Borrar"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>

                      {/* Badge "en uso por" — siempre visible (esquina sup izq) */}
                      {f.usedByProduct && (
                        <div
                          className="absolute top-1.5 left-1.5 z-10 inline-flex items-center gap-1 max-w-[calc(100%-50px)] px-1.5 py-0.5 rounded-md bg-emerald-500/95 text-white text-[10px] font-medium shadow-xs"
                          title={`En uso por: ${f.usedByProduct}`}
                        >
                          <span className="truncate">{f.usedByProduct}</span>
                        </div>
                      )}
                    </div>

                    {/* Metadata visible siempre debajo del thumbnail */}
                    <div className="px-2 py-1.5 border-t border-border/50 bg-muted/10">
                      <p className="text-[10px] font-mono text-foreground truncate" title={f.name}>
                        {f.name}
                      </p>
                      <p className="text-[10px] text-muted-foreground flex items-center justify-between mt-0.5">
                        <span>{sizeKB} KB</span>
                        {dateStr && <span className="text-muted-foreground/70">{dateStr}</span>}
                      </p>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border text-[11px] text-muted-foreground flex items-center justify-between gap-3">
          {files.length > 0 ? (
            <>
              <span>
                <span className="font-medium text-foreground">{files.length}</span> imágenes ·
                {' '}<span className="text-warning-fg">{files.filter(f => !f.usedByProduct).length} sin asignar</span> ·
                {' '}<span className="text-success-fg">{files.filter(f => f.usedByProduct).length} en uso</span>
              </span>
              <span>Click para asignar · hover → 🗑 para borrar</span>
            </>
          ) : (
            <span>&nbsp;</span>
          )}
        </div>
      </div>
    </div>
  )
}
