'use client'

/**
 * Hook: contexto del cliente seleccionado (panel derecho del Inbox).
 *
 * Refactor 2026-05-29 paso 5/10 — extraído de inbox-manager.tsx.
 *
 * Responsabilidad única:
 *   - Cargar /api/conversations/{id}/context con Bearer auth.
 *   - Auto-refresh silent cada 5s (real-time mirror del bot que muta cart).
 *   - Si la conv ya no existe (404), retorna deseleccionar al padre.
 *   - Cleanup limpio en unmount + cambio de conversationId.
 *
 * Devuelve:
 *   - context: el contexto cargado (contact + orders + cart + claims + products).
 *   - loading: true durante carga inicial (con flicker — usar para spinner).
 *   - refreshing: true durante auto-refresh silent (sin flicker — usar para
 *     indicador pequeño en header del panel).
 *   - refresh(): trigger manual de fetch (ej. tras crear pedido).
 *
 * Pitfalls que este hook evita:
 *   - AbortController por unmount + Promise pendiente → ignoramos resolución
 *     post-abort para evitar set state on unmounted component.
 *   - Doble interval por StrictMode dev → cleanup desuscribe correctamente.
 *   - Race condition entre fetch inicial y silent refresh → silent solo
 *     arranca DESPUÉS del primer fetch (vía .then).
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { createClient } from '@/utils/supabase/client'
import type { ConvContext } from '../_lib/types'

interface Result {
  context: ConvContext | null
  loading: boolean
  refreshing: boolean
  refresh: () => void
}

interface Options {
  /** Si la conv retorna 404, el padre debe deseleccionar. */
  onDeleted?: () => void
  /** Frecuencia de auto-refresh silent (default 5000ms). */
  refreshIntervalMs?: number
}

export function useConversationContext(
  conversationId: string | null,
  options: Options = {},
): Result {
  const { onDeleted, refreshIntervalMs = 5000 } = options
  const [context, setContext] = useState<ConvContext | null>(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const supabaseRef = useRef(createClient())
  // Refs para callbacks estables sin re-suscribir el efecto.
  const onDeletedRef = useRef(onDeleted)
  useEffect(() => { onDeletedRef.current = onDeleted }, [onDeleted])

  // Trigger manual de refresh — útil tras crear pedido.
  const refresh = useCallback(() => {
    if (!conversationId) return
    const supabase = supabaseRef.current
    supabase.auth.getSession().then(({ data }) => {
      const t = data.session?.access_token
      if (!t) return
      fetch(`/api/conversations/${conversationId}/context`, {
        headers: { 'Authorization': `Bearer ${t}` },
      })
        .then(r => r.json())
        .then(j => setContext(j))
        .catch(() => {})
    })
  }, [conversationId])

  useEffect(() => {
    if (!conversationId) {
      setContext(null)
      return
    }
    setLoading(true)
    setContext(null)

    const supabase = supabaseRef.current
    const controller = new AbortController()
    let refreshTimer: ReturnType<typeof setInterval> | null = null
    let cancelled = false

    const fetchContext = async (opts?: { silent?: boolean }) => {
      if (opts?.silent) setRefreshing(true)
      try {
        const { data } = await supabase.auth.getSession()
        const token = data.session?.access_token
        if (!token) {
          if (!opts?.silent) setLoading(false)
          return
        }
        const res = await fetch(`/api/conversations/${conversationId}/context`, {
          headers: { 'Authorization': `Bearer ${token}` },
          signal: controller.signal,
        })
        if (!res.ok) {
          // Sem 7 F2 cierre 2026-05-19 — si la conv ya no existe (purge contact)
          // deseleccionar para evitar loop infinito de fetches cada 5s.
          if (res.status === 404 && !cancelled && !controller.signal.aborted) {
            onDeletedRef.current?.()
          }
          return
        }
        const json = await res.json()
        if (!cancelled && !controller.signal.aborted) setContext(json)
      } catch (e) {
        if (!controller.signal.aborted && !opts?.silent) {
          // Log silent — el padre no necesita conocer cada error de red.
          console.warn('[useConversationContext] error', e)
        }
      } finally {
        if (!cancelled && !controller.signal.aborted) {
          if (opts?.silent) setRefreshing(false)
          else setLoading(false)
        }
      }
    }

    fetchContext().then(() => {
      // Real-time refresh silent (sin flicker).
      refreshTimer = setInterval(() => fetchContext({ silent: true }), refreshIntervalMs)
    })

    return () => {
      cancelled = true
      controller.abort()
      if (refreshTimer) clearInterval(refreshTimer)
    }
  }, [conversationId, refreshIntervalMs])

  return { context, loading, refreshing, refresh }
}
