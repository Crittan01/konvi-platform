import { Skeleton } from '@/components/ui/skeleton'

export default function Loading() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-7 w-28 bg-muted rounded" />
        <Skeleton className="h-9 w-36 bg-muted rounded" />
      </div>
      <div className="flex gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-20 flex-1 bg-muted rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-10 bg-muted rounded" />
      <div className="space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-14 bg-muted rounded-xl" />
        ))}
      </div>
    </div>
  )
}
