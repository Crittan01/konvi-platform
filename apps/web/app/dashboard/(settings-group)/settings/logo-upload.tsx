'use client'

import { useState, useRef } from 'react'
import { Loader2, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { createClient } from '@/utils/supabase/client'

interface Props {
  tenantId: string
  currentLogoUrl: string | null
  onSaved?: (url: string | null) => void
}

export default function LogoUpload({ tenantId, currentLogoUrl, onSaved = () => {} }: Props) {
  const [preview, setPreview] = useState<string | null>(currentLogoUrl)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Extensión derivada SOLO del MIME type validado — nunca de file.name
  // Previene path traversal y extensión spoofing (ej: exploit.php.jpg → logo.php)
  const MIME_TO_EXT: Record<string, string> = {
    'image/png':  'png',
    'image/jpeg': 'jpg',
    'image/webp': 'webp',
  }

  const handleFile = async (file: File) => {
    const ext = MIME_TO_EXT[file.type]
    if (!ext) {
      setError('Formato no soportado. Usa PNG, JPG o WebP.')
      return
    }
    if (file.size > 2 * 1024 * 1024) {
      setError('El archivo no debe superar 2 MB')
      return
    }

    setUploading(true)
    setError(null)

    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setError('Sesión expirada'); setUploading(false); return }

    const path = `${tenantId}/logo/logo.${ext}`

    const { error: uploadErr } = await supabase.storage
      .from('tenant-media')
      .upload(path, file, { upsert: true, contentType: file.type })

    if (uploadErr) { setError(uploadErr.message); setUploading(false); return }

    const { data: { publicUrl } } = supabase.storage
      .from('tenant-media')
      .getPublicUrl(path)

    const { error: dbErr } = await supabase
      .from('tenants')
      .update({ logo_url: publicUrl })
      .eq('id', tenantId)

    if (dbErr) { setError(dbErr.message); setUploading(false); return }

    setPreview(publicUrl)
    onSaved(publicUrl)
    setUploading(false)
  }

  const handleRemove = async () => {
    setUploading(true)
    setError(null)
    const supabase = createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) { setError('Sesión expirada'); setUploading(false); return }

    const { error: dbErr } = await supabase
      .from('tenants')
      .update({ logo_url: null })
      .eq('id', tenantId)

    if (dbErr) { setError(dbErr.message); setUploading(false); return }

    setPreview(null)
    onSaved(null)
    setUploading(false)
  }

  return (
    <div className="flex items-center gap-4">
      {/* Preview */}
      <div className="h-16 w-16 rounded-xl border border-border bg-muted flex items-center justify-center overflow-hidden shrink-0">
        {preview ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview} alt="Logo" className="h-full w-full object-cover" />
        ) : (
          <span className="text-2xl font-bold text-muted-foreground">CO</span>
        )}
      </div>

      {/* Controls */}
      <div className="space-y-2">
        <input
          ref={inputRef}
          type="file"
          accept=".jpg,.jpeg,.png,.webp"
          className="hidden"
          onChange={e => { if (e.target.files?.[0]) handleFile(e.target.files[0]) }}
        />
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
          >
            {uploading
              ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Subiendo...</>
              : <><Upload className="h-3.5 w-3.5 mr-1.5" /> Subir logo</>
            }
          </Button>
          {preview && !uploading && (
            <Button type="button" size="sm" variant="ghost" onClick={handleRemove} className="text-destructive hover:text-destructive">
              <X className="h-3.5 w-3.5 mr-1" /> Quitar
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">PNG, JPG o WebP · máx 2 MB</p>
        {error && <p className="text-xs text-danger-fg">{error}</p>}
      </div>
    </div>
  )
}
