'use client'

import { useSyncExternalStore } from 'react'

/**
 * useMediaQuery — suscripción a matchMedia con valor SSR-seguro.
 *
 * Implementada con useSyncExternalStore (el canal oficial para suscribirse a
 * stores externos como matchMedia — sin setState en effects). Server snapshot
 * = false → la presentación inicial es la "móvil" (mobile-first del repo).
 */

// Cache por query: getSnapshot se llama en cada render; sin cache se crearía
// un MediaQueryList nuevo por render (solo se lee .matches, pero es desperdicio).
const mqlCache = new Map<string, MediaQueryList>()

function getMql(query: string): MediaQueryList {
  let mql = mqlCache.get(query)
  if (!mql) {
    mql = window.matchMedia(query)
    mqlCache.set(query, mql)
  }
  return mql
}

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onStoreChange) => {
      const mql = getMql(query)
      mql.addEventListener('change', onStoreChange)
      return () => mql.removeEventListener('change', onStoreChange)
    },
    () => getMql(query).matches,
    () => false,
  )
}
