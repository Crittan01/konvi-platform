'use client'

/**
 * Hook: qué mensajes del chat deben ENTRAR con animación (Track 7 · T7.2).
 *
 * Regla: SOLO animan los mensajes que llegan DESPUÉS de que la conversación
 * terminó su carga inicial (realtime INSERT, polling fallback que descubre
 * uno nuevo, optimistic insert del operador). NO animan:
 *   - la carga inicial (sería una cascada de hasta 100 burbujas),
 *   - el histórico paginado con loadMore (prepend al scrollear arriba),
 *   - los re-renders por dedupe polling/realtime (mismo id ya visto),
 *   - la pintura stale de la conversación anterior mientras carga la nueva
 *     (use-messages no limpia `messages` al cambiar de id — `loadedConvId`
 *     desambigua: solo prima/anima cuando la data en pantalla ES de esta
 *     conversación).
 *
 * Detección: por id (dedupe) + created_at. Un mensaje "nuevo" se ANEXA al
 * final (created_at >= el mayor visto); el prepend de loadMore trae filas
 * estrictamente más viejas (`.lt('created_at', oldest)` en use-messages) y
 * queda excluido. `>=` (no `>`) cubre dos inserts en el mismo milisegundo.
 * Mensaje nuevo sin fecha parseable: se anima (mejor animar de más que
 * congelar una llegada real).
 *
 * Estado en useState (no ref): el set se lee EN RENDER (react-hooks/refs lo
 * prohíbe para refs) y se actualiza post-commit en useEffect — un render
 * descartado por concurrent mode nunca deja ids fantasma. La burbuja nueva
 * monta con enter=true en el primer pass; el re-render que dispara el efecto
 * la pasa a enter=false, pero `initial` solo aplica al montar: la animación
 * ya arrancó y termina intacta.
 */
import { useEffect, useState } from 'react'
import type { Message } from '../_lib/types'

interface SeenState {
  convId: string | null
  /** true una vez que la data de ESTA conversación ya está en pantalla. */
  primed: boolean
  /** ids ya renderizados — nunca re-animar (dedupe polling/realtime). */
  ids: Set<string>
  /** Mayor created_at (ms) visto; el prepend histórico queda por debajo. */
  maxTs: number
}

const fresh = (convId: string | null): SeenState => ({
  convId,
  primed: false,
  ids: new Set(),
  maxTs: 0,
})

const tsOf = (m: Message): number => Date.parse(m.created_at ?? '')

export function useAnimatableMessageIds(
  convId: string | null,
  loadedConvId: string | null,
  messages: Message[],
): Set<string> {
  const [seen, setSeen] = useState<SeenState>(() => fresh(null))

  const viewReady = convId !== null && loadedConvId === convId
  // El estado vigente para ESTA conversación: si el id cambió y el efecto aún
  // no corre, deriva uno fresco al vuelo (así la pintura stale no anima ni
  // contamina el seen de la conversación nueva).
  const current = seen.convId === convId ? seen : fresh(convId)

  const animatable = new Set<string>()
  if (viewReady && current.primed) {
    for (const m of messages) {
      if (current.ids.has(m.id)) continue
      const ts = tsOf(m)
      if (!Number.isFinite(ts) || ts >= current.maxTs) animatable.add(m.id)
    }
  }

  useEffect(() => {
    if (!viewReady) return
    // setState post-commit (react-hooks/set-state-in-effect: warn aceptado —
    // la alternativa recomendada, setState en render, está como error en este
    // repo; y refs en render están prohibidos. Este es el patrón sancionado).
    // Bail `return prev` cuando nada cambió: el polling dedupe NO dispara
    // re-renders vacíos cada 5s.
    setSeen(prev => {
      const base = prev.convId === convId && prev.primed ? prev : fresh(convId)
      const ids = new Set(base.ids)
      let maxTs = base.maxTs
      let changed = base !== prev
      for (const m of messages) {
        if (!ids.has(m.id)) { ids.add(m.id); changed = true }
        const ts = tsOf(m)
        if (Number.isFinite(ts) && ts > maxTs) { maxTs = ts; changed = true }
      }
      return changed ? { convId, primed: true, ids, maxTs } : prev
    })
  }, [viewReady, convId, messages])

  return animatable
}
