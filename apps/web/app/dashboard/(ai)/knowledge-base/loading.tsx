export default function Loading() {
  return (
    <div className="space-y-5 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="h-7 w-44 bg-muted rounded" />
        <div className="h-9 w-36 bg-muted rounded" />
      </div>
      <div className="h-10 bg-muted rounded-xl" />
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-20 bg-muted rounded-xl" />
        ))}
      </div>
    </div>
  )
}
