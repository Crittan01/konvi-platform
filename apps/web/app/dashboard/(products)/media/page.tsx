import { createClient } from '@/utils/supabase/server'
import { Image as ImageIcon, HardDrive } from 'lucide-react'
import MediaClient from './media-client'

function formatBytesServer(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default async function MediaPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const canWrite = role === 'owner' || role === 'manager'

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const { data: files } = await supabase.storage
    .from('tenant-media')
    .list(tenantId, { sortBy: { column: 'created_at', order: 'desc' }, limit: 100 })

  const mediaFiles = (files ?? []).filter(f => f.name !== '.emptyFolderPlaceholder') as {
    name: string; id: string | null
    metadata?: { size?: number | null; mimetype?: string | null } | null
    created_at?: string | null
  }[]

  const totalSize = mediaFiles.reduce((acc, f) => acc + (f.metadata?.size ?? 0), 0)

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <ImageIcon className="h-5 w-5 text-primary" /> Media
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {mediaFiles.length} archivos · {formatBytesServer(totalSize)} usado
          </p>
        </div>
        {totalSize > 0 && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <HardDrive className="h-3.5 w-3.5" />
            <span>Supabase Storage — bucket tenant-media</span>
          </div>
        )}
      </div>

      <MediaClient
        tenantId={tenantId}
        initialFiles={mediaFiles}
        canWrite={canWrite}
      />
    </div>
  )
}
