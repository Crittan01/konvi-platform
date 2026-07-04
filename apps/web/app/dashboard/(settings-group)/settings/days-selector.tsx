'use client'

import { useState } from 'react'

const DAY_LABELS: Record<number, string> = {
  1: 'Lu', 2: 'Ma', 3: 'Mi', 4: 'Ju', 5: 'Vi', 6: 'Sá', 7: 'Do',
}

interface Props {
  initialDays?: number[]
}

export function DaysSelector({ initialDays }: Props) {
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(initialDays ?? [1, 2, 3, 4, 5])
  )

  const toggle = (d: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(d)) next.delete(d)
      else next.add(d)
      return next
    })
  }

  const DAY_FULL: Record<number, string> = {
    1: 'Lunes', 2: 'Martes', 3: 'Miércoles', 4: 'Jueves', 5: 'Viernes', 6: 'Sábado', 7: 'Domingo',
  }

  return (
    <div className="flex gap-1.5 flex-wrap">
      {[1, 2, 3, 4, 5, 6, 7].map(d => (
        <button
          key={d}
          type="button"
          onClick={() => toggle(d)}
          aria-pressed={selected.has(d)}
          aria-label={DAY_FULL[d]}
          className={[
            'h-8 w-9 rounded-md border text-xs font-medium cursor-pointer select-none transition-colors',
            selected.has(d)
              ? 'bg-primary text-primary-foreground border-primary'
              : 'border-border hover:border-primary/40 text-muted-foreground',
          ].join(' ')}
        >
          {DAY_LABELS[d]}
        </button>
      ))}
      {/* Hidden inputs — envían los días seleccionados al server action */}
      {Array.from(selected).sort().map(d => (
        <input key={d} type="hidden" name="support_days" value={d} />
      ))}
    </div>
  )
}
