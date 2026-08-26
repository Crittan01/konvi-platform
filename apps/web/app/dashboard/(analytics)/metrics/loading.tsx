import { Skeleton } from '@/components/ui/skeleton'

export default function Loading() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-7 w-28 bg-muted rounded" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-24 bg-muted rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-64 bg-muted rounded-xl" />
    </div>
  )
}
