import { Skeleton } from '@/components/ui/skeleton'

export default function Loading() {
  return (
    <div className="space-y-6 max-w-7xl">
      {/* Encabezado */}
      <div className="space-y-2">
        <Skeleton className="h-7 w-52 bg-muted rounded" />
        <Skeleton className="h-4 w-full max-w-3xl bg-muted rounded" />
      </div>

      {/* Filtros por estado + búsqueda */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
        <div className="flex gap-1 flex-wrap">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-24 bg-muted rounded-md" />
          ))}
        </div>
        <Skeleton className="h-9 w-full max-w-xs bg-muted rounded-md" />
      </div>

      {/* Tabla de publicaciones */}
      <div className="border border-border/50 rounded-xl overflow-hidden">
        <Skeleton className="h-11 bg-muted/60" />
        <div className="divide-y divide-border/40">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-16 bg-muted/30" />
          ))}
        </div>
      </div>
    </div>
  )
}
