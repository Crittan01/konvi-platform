'use client'

import { useState, useRef } from 'react'
import { createClient } from '@/utils/supabase/client'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

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
  const [files, setFiles] = useState<StorageFile[]>(initialFiles)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const supabase = createClient()
  const BUCKET = 'tenant-media'

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

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

    const { error: uploadError } = await supabase.storage
      .from(BUCKET)
      .upload(path, file, { cacheControl: '3600', upsert: false })

    if (uploadError) {
      setError(`Error al subir: ${uploadError.message}`)
      setUploading(false)
      return
    }

    // Refrescar lista
    const { data: updated } = await supabase.storage
      .from(BUCKET)
      .list(tenantId, { sortBy: { column: 'created_at', order: 'desc' }, limit: 100 })

    setFiles((updated ?? []).filter(f => f.name !== '.emptyFolderPlaceholder') as StorageFile[])
    setUploading(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleDelete(filename: string) {
    const path = `${tenantId}/${filename}`
    const { error: deleteError } = await supabase.storage.from(BUCKET).remove([path])
    if (deleteError) {
      setError(`Error al eliminar: ${deleteError.message}`)
      return
    }
    setFiles(prev => prev.filter(f => f.name !== filename))
  }

  function getPublicUrl(filename: string): string {
    const { data } = supabase.storage
      .from(BUCKET)
      .getPublicUrl(`${tenantId}/${filename}`)
    return data.publicUrl
  }

  async function copyUrl(filename: string) {
    const url = getPublicUrl(filename)
    await navigator.clipboard.writeText(url)
    setCopied(filename)
    setTimeout(() => setCopied(null), 2000)
  }

  return (
    <div className="space-y-4">
      {/* Upload */}
      {canWrite && (
        <div className="flex items-center gap-3">
          <label
            htmlFor="media-upload"
            className={`inline-flex items-center px-4 py-2 rounded-md text-sm font-medium border cursor-pointer transition-colors
              ${uploading ? 'opacity-50 cursor-not-allowed bg-muted' : 'bg-primary text-primary-foreground hover:bg-primary/90'}`}
          >
            {uploading ? 'Subiendo...' : '+ Subir imagen'}
          </label>
          <input
            id="media-upload"
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            className="hidden"
            disabled={uploading}
            onChange={handleUpload}
          />
          <span className="text-xs text-muted-foreground">JPG, PNG, WebP, GIF · máx. 5MB</span>
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          {error}
        </div>
      )}

      {/* Grid de imágenes */}
      {files.length === 0 ? (
        <div className="p-12 border border-dashed rounded-lg text-center text-muted-foreground">
          <p className="font-medium">Sin archivos aún.</p>
          <p className="text-sm mt-1">Sube imágenes para asociarlas a tus productos.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {files.map(file => {
            const url = getPublicUrl(file.name)
            const size = file.metadata?.size ?? 0
            return (
              <Card key={file.name} className="overflow-hidden">
                <div className="aspect-square bg-muted relative group">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={url}
                    alt={file.name}
                    className="w-full h-full object-cover"
                  />
                  {canWrite && (
                    <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        className="text-xs h-7"
                        onClick={() => copyUrl(file.name)}
                      >
                        {copied === file.name ? '¡Copiado!' : 'Copiar URL'}
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        className="text-xs h-7"
                        onClick={() => handleDelete(file.name)}
                      >
                        Eliminar
                      </Button>
                    </div>
                  )}
                </div>
                <CardContent className="p-2">
                  <p className="text-xs text-muted-foreground truncate" title={file.name}>
                    {file.name}
                  </p>
                  {size > 0 && (
                    <p className="text-xs text-muted-foreground">{formatBytes(size)}</p>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
