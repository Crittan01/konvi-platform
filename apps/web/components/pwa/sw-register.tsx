'use client'

import { useEffect } from 'react'

/**
 * Registra el service worker (solo en producción). No renderiza nada.
 * El SW es conservador (solo cachea assets inmutables) — ver public/sw.js.
 */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') return
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
    const register = () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {
        /* silencioso — la app funciona igual sin SW */
      })
    }
    if (document.readyState === 'complete') register()
    else {
      window.addEventListener('load', register)
      return () => window.removeEventListener('load', register)
    }
  }, [])
  return null
}
