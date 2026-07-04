import { Skeleton } from '@/components/ui/skeleton'

/**
 * Skeleton del home operativo (F4 2026-07-04). El home ejecuta ~22 queries
 * server-side (page.tsx + layout.tsx) antes del primer paint; sin este fallback
 * la navegación al inicio quedaba en blanco. Refleja la estructura real:
 * header + tabs + 4 OpsCards + acceso rápido + gráfica.
 */
export default function DashboardLoading() {
  return (
    <div className="space-y-5 max-w-7xl" aria-busy="true" aria-label="Cargando panel">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="space-y-2">
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-40" />
        </div>
        <Skeleton className="h-9 w-32 rounded-xl" />
      </div>

      {/* Tabs */}
      <div className="flex gap-4 border-b border-border pb-2">
        <Skeleton className="h-6 w-28" />
        <Skeleton className="h-6 w-24" />
      </div>

      {/* OpsCards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 rounded-xl" />
        ))}
      </div>

      {/* Acceso rápido */}
      <div className="space-y-3">
        <Skeleton className="h-4 w-32" />
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      </div>

      {/* Gráfica */}
      <Skeleton className="h-32 rounded-xl" />
    </div>
  )
}
