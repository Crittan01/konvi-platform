// PageHeader — cabecera de módulo con identidad (Track 7: piloto T7.11 en
// settings/security, rollout transversal T7.12).
//
// La firma diferencial de la casa a escala de módulo (directiva founder
// 2026-08-25: el lenguaje de auth impregna TODO el front):
//   - Tile degradado primary→amber + `glow-primary` + glifo blanco — hermano
//     del brand tile de auth (`auth-scene.tsx`), como marca de la casa.
//   - Título + contexto (descripción) + slot de acciones a la derecha.
//   - Coreografía de entrada vía wrappers del DS (StaggerList/StaggerItem —
//     prohibido `motion` crudo, §4.1): hidratación-segura y estática bajo
//     prefers-reduced-motion sin trabajo extra.
//
// Sin 'use client': quien la importa decide el grafo (server page o client
// island) — los wrappers de motion son la frontera client. El `icon` se
// recibe como componente Lucide y se renderiza AQUÍ (nunca cruza la frontera
// server→client como prop serializable de un wrapper client).

import * as React from 'react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { StaggerItem, StaggerList } from '@/components/ui/motion'

export interface PageHeaderProps {
  /** Icono del módulo (Lucide). Se pinta blanco sobre el tile degradado. */
  icon: LucideIcon
  /** Nombre del módulo (único h1 de la página). ReactNode: el saludo del
   *  home lleva un span con `text-gradient` (T7.12). */
  title: React.ReactNode
  /** Contexto bajo el título (conteo, descripción corta, email…). */
  description?: React.ReactNode
  /** Acciones a la derecha (exportar, CTA primaria del módulo…). */
  actions?: React.ReactNode
  className?: string
}

export function PageHeader({ icon: Icon, title, description, actions, className }: PageHeaderProps) {
  return (
    <StaggerList
      stagger={0.06}
      className={cn('flex flex-col sm:flex-row sm:items-center justify-between gap-3', className)}
    >
      <StaggerItem className="flex items-center gap-3 min-w-0">
        {/* Tile de marca: degradado primary→amber + glow (firma Kaiu). */}
        <span
          aria-hidden
          className="h-10 w-10 shrink-0 rounded-xl bg-gradient-to-br from-primary to-[hsl(var(--amber))] flex items-center justify-center shadow-sm glow-primary ring-1 ring-white/15"
        >
          <Icon className="h-5 w-5 text-white" />
        </span>
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground">{title}</h1>
          {description && (
            <p className="text-sm text-muted-foreground mt-0.5">{description}</p>
          )}
        </div>
      </StaggerItem>
      {actions && <StaggerItem className="shrink-0">{actions}</StaggerItem>}
    </StaggerList>
  )
}
