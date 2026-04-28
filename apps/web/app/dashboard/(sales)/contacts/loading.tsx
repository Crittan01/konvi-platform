export default function Loading() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="h-7 w-24 bg-muted rounded" />
        <div className="h-9 w-10 bg-muted rounded" />
      </div>
      <div className="h-10 bg-muted rounded" />
      <div className="space-y-2">
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="h-14 bg-muted rounded-xl" />
        ))}
      </div>
    </div>
  )
}
