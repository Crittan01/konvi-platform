import { Skeleton } from '@/components/ui/skeleton'

// Skeleton de la ruta Categorías: la page es server-component con 3 queries en
// paralelo (categorías + conteo de productos + contratos de atributos). Paridad
// con catalog/loading.tsx para evitar el flash de contenido vacío al navegar.
export default function Loading() {
  return (
    <div className="space-y-5 max-w-3xl">
      <div className="space-y-2">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="h-4 w-full max-w-lg" />
      </div>
      <Skeleton className="h-28 rounded-xl" />
      <div className="rounded-xl border border-border bg-card divide-y divide-border">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="h-4 flex-1 max-w-xs" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-7 w-24 rounded-md" />
          </div>
        ))}
      </div>
    </div>
  )
}
