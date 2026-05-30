'use client'

import { useState, useRef } from 'react'
import { createClient } from '@/utils/supabase/client'
import { ImageIcon, Loader2, X, Camera, FolderOpen } from 'lucide-react'
import { GalleryPickerModal } from './gallery-picker-modal'

interface Props {
  name: string           // nombre del input hidden (para el form action)
  defaultUrl?: string    // imagen existente
  tenantId: string
  size?: 'sm' | 'md' | 'lg'
  label?: string
  onUrlChange?: (url: string) => void  // callback para estado externo (crear producto)
}

export function ImageUploadBox({ name, defaultUrl = '', tenantId, size = 'md', label, onUrlChange }: Props) {
  const [url, setUrl]       = useState(defaultUrl)
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState<string | null>(null)
  const [galleryOpen, setGalleryOpen] = useState(false)
  const inputRef            = useRef<HTMLInputElement>(null)

  const sizeClasses = {
    sm: 'w-16 h-16',
    md: 'w-24 h-24',
    lg: 'w-32 h-32',
  }[size]

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    setLoading(true)
    try {
      const ext = file.name.split('.').pop() || 'jpg'
      const path = `${tenantId}/${Date.now()}-${Math.random().toString(36).slice(2)}.${ext}`
      const supabase = createClient()
      const { error: uploadErr } = await supabase.storage.from('tenant-media').upload(path, file)
      if (uploadErr) throw new Error(uploadErr.message)
      const { data } = supabase.storage.from('tenant-media').getPublicUrl(path)
      setUrl(data.publicUrl)
      onUrlChange?.(data.publicUrl)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al subir')
    } finally {
      setLoading(false)
      // reset input so same file can be re-selected
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className="space-y-1">
      {label && <label className="text-[10px] font-semibold text-muted-foreground uppercase">{label}</label>}
      <input type="hidden" name={name} value={url} />
      <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={handleFile} />

      <div className="flex items-end gap-2">
        {/* Caja clicable */}
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={loading}
          className={`${sizeClasses} relative rounded-lg border-2 border-dashed border-border bg-muted/30 overflow-hidden flex items-center justify-center cursor-pointer hover:border-primary/60 hover:bg-muted/60 transition-all disabled:opacity-60 group`}
        >
          {loading ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          ) : url ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url} alt="" className="w-full h-full object-cover" />
              <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                <Camera className="h-5 w-5 text-white" />
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center gap-1 text-muted-foreground/50">
              <ImageIcon className="h-5 w-5" />
              <span className="text-[9px]">Subir</span>
            </div>
          )}
        </button>

        {/* Acciones secundarias: galería + quitar */}
        <div className="flex flex-col gap-1.5">
          <button
            type="button"
            onClick={() => setGalleryOpen(true)}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-primary/40 bg-primary/5 text-[11px] font-medium text-primary hover:bg-primary/10 hover:border-primary/60 transition-colors whitespace-nowrap"
            title="Seleccionar imagen ya subida al tenant"
          >
            <FolderOpen className="h-3.5 w-3.5" /> Galería
          </button>
          {url && (
            <button
              type="button"
              onClick={() => { setUrl(''); onUrlChange?.('') }}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] text-muted-foreground hover:text-destructive hover:bg-destructive/5 transition-colors whitespace-nowrap"
            >
              <X className="h-3 w-3" /> Quitar
            </button>
          )}
        </div>
      </div>

      {error && <p className="text-[10px] text-destructive">{error}</p>}

      <GalleryPickerModal
        open={galleryOpen}
        onClose={() => setGalleryOpen(false)}
        tenantId={tenantId}
        onSelect={(publicUrl) => {
          setUrl(publicUrl)
          onUrlChange?.(publicUrl)
        }}
      />
    </div>
  )
}
