import { Skeleton } from '@/components/ui/skeleton'

export default function Loading() {
  return (
    <div className="space-y-5 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-7 w-56 bg-muted rounded" />
          <Skeleton className="h-4 w-64 bg-muted rounded" />
        </div>
      </div>
      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-20 bg-muted rounded-xl" />
        ))}
      </div>
      {/* Historial */}
      <div className="space-y-3">
        <Skeleton className="h-4 w-40 bg-muted rounded" />
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-24 bg-muted rounded-xl" />
        ))}
      </div>
    </div>
  )
}
