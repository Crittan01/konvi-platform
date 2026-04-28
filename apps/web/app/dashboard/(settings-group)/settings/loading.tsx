export default function Loading() {
  return (
    <div className="space-y-6 max-w-4xl animate-pulse">
      <div className="h-7 w-40 bg-muted rounded" />
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="space-y-3 p-5 border border-border/40 rounded-xl">
          <div className="h-5 w-36 bg-muted rounded" />
          <div className="h-10 bg-muted rounded" />
          <div className="h-10 bg-muted rounded" />
          <div className="h-9 w-28 bg-muted rounded ml-auto" />
        </div>
      ))}
    </div>
  )
}
