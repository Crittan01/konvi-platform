'use client'

// Bento — grid asimétrico de cards con entrada en cascada (PASO 4, dashboard).
// REGLA del DS: el bento es JERARQUÍA, no decoración.
//   - `span`/`row` existen para marcar la card de mayor peso (ej. revenue),
//     no para adornar; solo aplican en ≥lg (en sm el grid es 2 col uniforme).
//   - El hover con elevación (`card-hover`) SOLO en cards `interactive`
//     (las que navegan al click) — las cards estáticas no flotan (F1).
//   - La cascada de entrada la dan StaggerList/StaggerItem del DS (§4.1):
//     reduced-motion heredado (snap instantáneo, sin stagger).
// Las clases de span van en el StaggerItem (es el hijo DIRECTO del grid);
// el chrome de card va en el Card interior (h-full para rellenar la celda).

import * as React from 'react'
import { cn } from '@/lib/utils'
import { Card } from '@/components/ui/card'
import { StaggerItem, StaggerList } from '@/components/ui/motion'

export function BentoGrid({
  stagger = 0.06,
  className,
  children,
}: {
  /** Delay entre cards en la cascada de entrada (s). */
  stagger?: number
  className?: string
  children: React.ReactNode
}) {
  return (
    <StaggerList
      stagger={stagger}
      className={cn('grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4', className)}
    >
      {children}
    </StaggerList>
  )
}

export function BentoCard({
  span = 1,
  row = 1,
  interactive = false,
  className,
  children,
}: {
  /** Columnas que ocupa en ≥lg (jerarquía visual; default 1). */
  span?: 1 | 2
  /** Filas que ocupa en ≥lg (default 1). */
  row?: 1 | 2
  /** true solo si la card navega al click → card-hover + cursor-pointer (F1). */
  interactive?: boolean
  className?: string
  children: React.ReactNode
}) {
  return (
    <StaggerItem
      className={cn(
        'h-full',
        span === 2 && 'lg:col-span-2',
        row === 2 && 'lg:row-span-2',
      )}
    >
      <Card
        className={cn(
          'h-full',
          interactive && 'card-hover cursor-pointer',
          className,
        )}
      >
        {children}
      </Card>
    </StaggerItem>
  )
}
