import { Skeleton } from '@/components/ui/skeleton'

export default function Loading() {
  return (
    <div className="space-y-5 max-w-3xl">
      <Skeleton className="h-7 w-40 bg-muted rounded" />
      <Skeleton className="h-24 bg-muted rounded-xl" />
      <div className="space-y-3 p-5 border border-border/40 rounded-xl">
        <Skeleton className="h-5 w-32 bg-muted rounded" />
        <Skeleton className="h-10 bg-muted rounded" />
        <Skeleton className="h-28 bg-muted rounded" />
        <Skeleton className="h-9 w-28 bg-muted rounded ml-auto" />
      </div>
    </div>
  )
}
