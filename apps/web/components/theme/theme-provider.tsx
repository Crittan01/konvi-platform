'use client'

/**
 * ThemeProvider ligero (sin next-themes) — Web UX Fase 0.
 *
 * - Resuelve el tema inicial: preferencia guardada (localStorage) > preferencia
 *   del sistema (prefers-color-scheme).
 * - Aplica la clase `.dark` en <html> (los tokens del canvas viven en globals.css).
 * - Persiste la elección. Escucha cambios del sistema SOLO si el usuario no eligió
 *   manualmente (respeta la intención explícita).
 *
 * El flash inicial (FOUC) lo evita el script inline en app/layout.tsx, que corre
 * antes del primer paint; este provider sincroniza el estado de React con lo que
 * ese script ya dejó aplicado.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'konvi-theme'

type ThemeContextValue = {
  theme: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function systemPrefersDark(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  )
}

function readStored(): Theme | null {
  if (typeof window === 'undefined') return null
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null
  }
}

function applyTheme(theme: Theme) {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Estado inicial coherente con SSR (light); el efecto lo corrige en el cliente
  // según lo que el script anti-FOUC ya aplicó — sin segundo flash.
  const [theme, setThemeState] = useState<Theme>('light')

  useEffect(() => {
    const initial = readStored() ?? (systemPrefersDark() ? 'dark' : 'light')
    setThemeState(initial)
    applyTheme(initial)
  }, [])

  // Cambios del sistema: solo si el usuario NO fijó una preferencia explícita.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      if (readStored() !== null) return
      const next: Theme = mq.matches ? 'dark' : 'light'
      setThemeState(next)
      applyTheme(next)
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t)
    applyTheme(t)
    try {
      localStorage.setItem(STORAGE_KEY, t)
    } catch {
      /* almacenamiento no disponible — el tema aplica igual en memoria */
    }
  }, [])

  const toggle = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark')
  }, [theme, setTheme])

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggle }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme debe usarse dentro de <ThemeProvider>')
  return ctx
}
