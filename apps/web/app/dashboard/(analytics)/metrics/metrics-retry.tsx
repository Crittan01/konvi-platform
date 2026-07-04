'use client'

import { useRouter } from 'next/navigation'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

/** Reintento para el estado de error del server component (re-fetch server-side). */
export default function MetricsRetry() {
  const router = useRouter()
  return (
    <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5" onClick={() => router.refresh()}>
      <RefreshCw className="h-3.5 w-3.5" /> Reintentar
    </Button>
  )
}
