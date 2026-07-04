export default function Loading() {
  return (
    <div className="space-y-5 max-w-7xl animate-pulse">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-7 w-28 bg-muted rounded" />
          <div className="h-4 w-40 bg-muted rounded" />
        </div>
        <div className="h-4 w-48 bg-muted rounded" />
      </div>
      <div className="h-28 bg-muted rounded-xl" />
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="aspect-square bg-muted rounded-xl" />
        ))}
      </div>
    </div>
  )
}
