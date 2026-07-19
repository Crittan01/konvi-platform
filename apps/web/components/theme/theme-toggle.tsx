'use client'

/**
 * Toggle de tema claro/oscuro — Web UX Fase 0. Pensado para el topbar oscuro
 * (hereda el color crema). Accesible: aria-label + focus visible.
 */
import { Moon, Sun } from 'lucide-react'

import { useTheme } from './theme-provider'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
      title={isDark ? 'Modo claro' : 'Modo oscuro'}
      className="inline-flex h-8 w-8 items-center justify-center rounded-lg opacity-80 transition-colors hover:bg-white/10 hover:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current"
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      <span className="sr-only">{isDark ? 'Modo claro' : 'Modo oscuro'}</span>
    </button>
  )
}
