import { Skeleton } from '@/components/ui/skeleton'

export default function Loading() {
  return (
    <div className="space-y-5 max-w-7xl">
      <div className="space-y-1">
        <Skeleton className="h-7 w-48 bg-muted rounded" />
        <Skeleton className="h-4 w-72 bg-muted rounded" />
      </div>
      <div className="flex gap-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-24 bg-muted rounded-full" />
        ))}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-40 bg-muted rounded-xl" />
        ))}
      </div>
    </div>
  )
}
