export default function Loading() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="space-y-2">
        <div className="h-7 w-56 bg-muted rounded" />
        <div className="h-4 w-full max-w-3xl bg-muted rounded" />
      </div>
      <div className="flex items-center justify-between gap-4">
        <div className="h-10 w-full max-w-md bg-muted rounded" />
        <div className="h-9 w-36 bg-muted rounded" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-20 bg-muted rounded-xl" />
          ))}
        </div>
        <div className="hidden lg:block lg:col-span-2 h-96 bg-muted rounded-xl" />
      </div>
    </div>
  )
}
