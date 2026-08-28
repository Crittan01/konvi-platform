import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { Image as ImageIcon, HardDrive, ShieldAlert } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'
import MediaClient from './media-client'

function formatBytesServer(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default async function MediaPage() {
  // Sem 5 perf: cached.
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = await createClient()

  if (!tenantId) {
    return (
      <EmptyState
        variant="plain"
        icon={ShieldAlert}
        className="p-8"
        title="Sin acceso"
        description="Tenant no configurado."
      />
    )
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

      {/* Header — cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={ImageIcon}
        title="Media"
        description={`${mediaFiles.length} archivos · ${formatBytesServer(totalSize)} usado`}
        actions={totalSize > 0 ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <HardDrive className="h-3.5 w-3.5" />
            <span>Almacenamiento de imágenes</span>
          </div>
        ) : undefined}
      />

      <MediaClient
        tenantId={tenantId}
        initialFiles={mediaFiles}
        canWrite={canWrite}
      />
    </div>
  )
}
