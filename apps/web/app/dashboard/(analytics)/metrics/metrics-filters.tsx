'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { Button } from '@/components/ui/button'

const PERIODS = [
  { value: '7',  label: '7 días' },
  { value: '30', label: '30 días' },
  { value: '90', label: '90 días' },
  { value: 'all', label: 'Todo' },
]

export default function MetricsFilters({ current }: { current: string }) {
  const router = useRouter()
  const params = useSearchParams()

  const setFilter = (period: string) => {
    const sp = new URLSearchParams(params.toString())
    sp.set('period', period)
    router.replace(`/dashboard/metrics?${sp.toString()}`)
  }

  return (
    <div className="flex gap-1.5 flex-wrap">
      {PERIODS.map(p => (
        <Button
          key={p.value}
          size="sm"
          variant={current === p.value ? 'default' : 'outline'}
          className="h-7 text-xs"
          onClick={() => setFilter(p.value)}
        >
          {p.label}
        </Button>
      ))}
    </div>
  )
}
