'use client'

import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import type { FinanceRange } from '../lib/window'

const RANGES: { value: FinanceRange; label: string }[] = [
  { value: 'last_month', label: 'Mes Pasado' },
  { value: 'month', label: 'Mes Actual' },
  { value: 'all', label: 'Todo el Histórico' },
]

/**
 * FinanceFilters — la ventana ahora vive en el server (searchParam ?range=),
 * no en useState cliente. Así el P&L se acota antes de leer la DB en vez de
 * traer todo y filtrar en JS (que truncaba silenciosamente).
 */
export default function FinanceFilters({ current }: { current: FinanceRange }) {
  const router = useRouter()
  return (
    <div className="flex gap-1.5 flex-wrap" role="group" aria-label="Rango de tiempo del P&L">
      {RANGES.map((r) => (
        <Button
          key={r.value}
          size="sm"
          variant={current === r.value ? 'default' : 'outline'}
          className="h-7 text-xs"
          aria-pressed={current === r.value}
          onClick={() => router.replace(`/dashboard/finance?range=${r.value}`)}
        >
          {r.label}
        </Button>
      ))}
    </div>
  )
}
