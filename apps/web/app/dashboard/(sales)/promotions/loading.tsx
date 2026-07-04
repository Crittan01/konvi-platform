/**
 * Skeleton de carga de Promociones — paridad con orders/ y contacts/.
 * Refleja el layout real: encabezado + botón "Nuevo cupón" + tabla.
 */
export default function Loading() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="space-y-2">
        <div className="h-7 w-40 bg-muted rounded" />
        <div className="h-4 w-72 bg-muted rounded" />
      </div>
      <div className="h-9 w-36 bg-muted rounded" />
      <div className="rounded-md border border-border bg-card">
        <div className="h-10 bg-muted/40 rounded-t-md" />
        <div className="divide-y divide-border">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-14 bg-muted/10" />
          ))}
        </div>
      </div>
    </div>
  )
}
