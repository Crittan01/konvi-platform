export default function Loading() {
  return (
    <div className="space-y-5 max-w-7xl animate-pulse">
      <div className="space-y-1">
        <div className="h-7 w-48 bg-muted rounded" />
        <div className="h-4 w-72 bg-muted rounded" />
      </div>
      <div className="flex gap-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-8 w-24 bg-muted rounded-full" />
        ))}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-40 bg-muted rounded-xl" />
        ))}
      </div>
    </div>
  )
}
