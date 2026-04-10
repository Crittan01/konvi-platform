import { createClient } from '@/utils/supabase/server'
import { Badge } from '@/components/ui/badge'
import MediaClient from './media-client'

export default async function MediaPage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  // Listar archivos del tenant desde el servidor
  const { data: files } = await supabase.storage
    .from('tenant-media')
    .list(tenantId, { sortBy: { column: 'created_at', order: 'desc' }, limit: 100 })

  const mediaFiles = (files ?? []).filter(f => f.name !== '.emptyFolderPlaceholder')

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-primary">Media</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {mediaFiles.length} archivos · JPG, PNG, WebP, GIF · máx. 5MB por archivo
          </p>
        </div>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      <MediaClient
        tenantId={tenantId}
        initialFiles={mediaFiles}
        canWrite={canWrite}
      />
    </div>
  )
}
