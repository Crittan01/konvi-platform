'use client'

import { useState, useRef, useCallback } from 'react'
import { createClient } from '@/utils/supabase/client'
import { Button } from '@/components/ui/button'
import { Upload, Copy, Check, Trash2, Image, X } from 'lucide-react'

type StorageFile = {
  name: string
  id: string | null
  metadata?: { size?: number | null; mimetype?: string | null } | null
  created_at?: string | null
}

type Props = {
  tenantId: string
  initialFiles: StorageFile[]
  canWrite: boolean
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function MediaClient({ tenantId, initialFiles, canWrite }: Props) {
  const [files, setFiles]       = useState<StorageFile[]>(initialFiles)
  const [uploading, setUploading] = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [copied, setCopied]     = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [preview, setPreview]   = useState<{ url: string; name: string } | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const supabase = createClient()
  const BUCKET = 'tenant-media'

  const getPublicUrl = useCallback((filename: string) => {
    const { data } = supabase.storage.from(BUCKET).getPublicUrl(`${tenantId}/${filename}`)
    return data.publicUrl
  }, [supabase, tenantId])

  async function uploadFile(file: File) {
    const allowed = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
    if (!allowed.includes(file.type)) {
      setError('Solo se permiten imágenes JPG, PNG, WebP o GIF.')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      setError('El archivo supera el límite de 5MB.')
      return
    }
    setError(null)
    setUploading(true)
    const ext      = file.name.split('.').pop()
    const filename = `${Date.now()}-${Math.random().toString(36).slice(2)}.${ext}`
    const path     = `${tenantId}/${filename}`
    const { error: uploadError } = await supabase.storage.from(BUCKET).upload(path, file, { cacheControl: '3600', upsert: false })
    if (uploadError) { setError(`Error al subir: ${uploadError.message}`); setUploading(false); return }
    const { data: updated } = await supabase.storage.from(BUCKET).list(tenantId, { sortBy: { column: 'created_at', order: 'desc' }, limit: 100 })
    setFiles((updated ?? []).filter(f => f.name !== '.emptyFolderPlaceholder') as StorageFile[])
    setUploading(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) await uploadFile(file)
  }

  async function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) await uploadFile(file)
  }

  async function handleDelete(filename: string) {
    setDeleting(filename)
    const { error: deleteError } = await supabase.storage.from(BUCKET).remove([`${tenantId}/${filename}`])
    if (deleteError) { setError(`Error al eliminar: ${deleteError.message}`); setDeleting(null); return }
    setFiles(prev => prev.filter(f => f.name !== filename))
    setDeleting(null)
    if (preview?.name === filename) setPreview(null)
  }

  async function copyUrl(filename: string) {
    const url = getPublicUrl(filename)
    await navigator.clipboard.writeText(url)
    setCopied(filename)
    setTimeout(() => setCopied(null), 2000)
  }

  return (
    <>
      <div className="space-y-5">
        {/* Drop zone / Upload */}
        {canWrite && (
          <div
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`relative cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-all ${
              dragging
                ? 'border-primary bg-primary/10 scale-[1.01]'
                : 'border-border hover:border-primary/50 hover:bg-muted/30'
            } ${uploading ? 'pointer-events-none opacity-60' : ''}`}
          >
            <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp,image/gif"
              className="hidden" disabled={uploading} onChange={handleFileChange} />
            <Upload className={`h-8 w-8 mx-auto mb-2 ${dragging ? 'text-primary' : 'text-muted-foreground'}`} />
            <p className="text-sm font-medium text-foreground">
              {uploading ? 'Subiendo...' : dragging ? 'Suelta para subir' : 'Arrastra una imagen o haz clic'}
            </p>
            <p className="text-xs text-muted-foreground mt-1">JPG, PNG, WebP, GIF · máx. 5MB</p>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
            <X className="h-4 w-4 shrink-0" />
            {error}
            <button onClick={() => setError(null)} className="ml-auto"><X className="h-3.5 w-3.5" /></button>
          </div>
        )}

        {/* Stats */}
        {files.length > 0 && (
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">{files.length} imagen{files.length !== 1 ? 'es' : ''}</p>
            <p className="text-xs text-muted-foreground">
              {formatBytes(files.reduce((acc, f) => acc + (f.metadata?.size ?? 0), 0))} total
            </p>
          </div>
        )}

        {/* Grid */}
        {files.length === 0 ? (
          <div className="flex flex-col items-center py-16 rounded-xl border border-dashed border-border text-center">
            <Image className="h-10 w-10 text-muted-foreground/40 mb-3" />
            <p className="text-muted-foreground text-sm font-medium">Sin archivos aún.</p>
            <p className="text-xs text-muted-foreground mt-1">Sube imágenes para asociarlas a tus productos.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
            {files.map(file => {
              const url  = getPublicUrl(file.name)
              const size = file.metadata?.size ?? 0
              const isDeleting = deleting === file.name
              return (
                <div key={file.name} className="group relative rounded-xl overflow-hidden border border-border bg-muted aspect-square">
                  {/* Imagen */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={url} alt={file.name}
                    className="w-full h-full object-cover cursor-pointer transition-transform group-hover:scale-105"
                    onClick={() => setPreview({ url, name: file.name })}
                  />

                  {/* Overlay de acciones */}
                  <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-2 p-2">
                    <button
                      onClick={() => copyUrl(file.name)}
                      className="flex items-center gap-1 px-2 py-1 rounded-lg bg-white/20 hover:bg-white/30 text-white text-[11px] font-medium transition-colors w-full justify-center"
                    >
                      {copied === file.name ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                      {copied === file.name ? 'Copiado' : 'Copiar URL'}
                    </button>
                    {canWrite && (
                      <button
                        onClick={() => handleDelete(file.name)}
                        disabled={isDeleting}
                        className="flex items-center gap-1 px-2 py-1 rounded-lg bg-red-500/70 hover:bg-red-500 text-white text-[11px] font-medium transition-colors w-full justify-center disabled:opacity-50"
                      >
                        <Trash2 className="h-3 w-3" />
                        {isDeleting ? '...' : 'Eliminar'}
                      </button>
                    )}
                  </div>

                  {/* Footer con nombre/ tamaño */}
                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent px-2 py-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <p className="text-[10px] text-white/90 truncate">{file.name.split('-').slice(2).join('-') || file.name}</p>
                    {size > 0 && <p className="text-[10px] text-white/60">{formatBytes(size)}</p>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Lightbox */}
      {preview && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          onClick={() => setPreview(null)}
        >
          <div className="relative max-w-3xl max-h-[80vh] w-full" onClick={e => e.stopPropagation()}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={preview.url} alt={preview.name} className="w-full h-auto max-h-[70vh] object-contain rounded-xl" />
            <div className="flex items-center justify-between mt-3 px-1">
              <p className="text-sm text-white/80 truncate">{preview.name}</p>
              <div className="flex gap-2 shrink-0">
                <Button size="sm" variant="secondary" className="h-8 text-xs gap-1.5" onClick={() => copyUrl(preview.name)}>
                  {copied === preview.name ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                  {copied === preview.name ? 'Copiado' : 'Copiar URL'}
                </Button>
                <Button size="sm" variant="ghost" className="h-8 text-white/80 hover:text-white" onClick={() => setPreview(null)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
