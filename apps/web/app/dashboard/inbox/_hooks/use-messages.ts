'use client'

/**
 * Hook: mensajes de la conversación seleccionada.
 *
 * Refactor 2026-05-29 paso 9/10 — extraído de inbox-manager.tsx (HIGH risk crítico).
 *
 * Responsabilidades:
 *   - Carga inicial: 100 mensajes más recientes (DESC) revertidos a ASC visual.
 *   - Realtime postgres_changes filtrado por conversation_id (INSERT/UPDATE)
 *     con dedupe por id (A6) — evita duplicados entre realtime y polling.
 *   - Polling fallback cada 5s si Realtime parece inactivo (sinceLastEvent > 8s).
 *   - Cursor-based pagination (loadMore) cuando el operador scrollea arriba —
 *     restaura scrollTop para no perder contexto.
 *   - Filtro R-13 + F7: snapshots de contexto interno (`context_snapshot`) y
 *     filas de auditoría (`escalation_audit`, `sla_breach_audit`) NO se
 *     renderizan (ver NON_RENDERABLE_CONTENT_TYPES). Antes se pintaban como
 *     burbujas vacías.
 *   - Optimistic patch a `conversations.last_interaction_at` via callback
 *     `onMessageInserted` — mantiene lateral + chat sincronizados sin esperar
 *     trigger DB.
 *
 * Devuelve:
 *   - messages, loading, error
 *   - hasMore, loadingMore, loadMore()
 *   - messagesContainerRef, messagesEndRef (DOM refs para scroll)
 *
 * Pitfalls evitados:
 *   - Closure stale de selectedId: el efecto depende explícitamente del id
 *     (cleanup al cambiar).
 *   - Dedupe en INSERT: setMessages(prev.some(m => m.id) ? prev : [...prev, m])
 *     — idempotente bajo StrictMode dev y race realtime/polling.
 *   - Scroll restoration: capturamos scrollHeight ANTES del fetch + restauramos
 *     con requestAnimationFrame tras setMessages.
 *   - Cleanup MISMA referencia del channel: removeChannel(channel) — sin esto
 *     React 18 StrictMode dev duplica subscriptions silenciosamente.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { SupabaseClient } from '@supabase/supabase-js'
import type { Message } from '../_lib/types'
import {
  NON_RENDERABLE_CONTENT_TYPES,
  NON_RENDERABLE_CONTENT_TYPES_PG,
} from '../_lib/constants'

interface Options {
  supabase: SupabaseClient
  /** Callback opcional para optimistic update de la conv asociada (timestamp).
   *  Si se omite, el padre no recibe notificación (el trigger DB hará el
   *  update igualmente, pero con ~200ms de latencia). */
  onMessageInserted?: (conversationId: string, isoTs: string) => void
}

interface Result {
  messages: Message[]
  error: string | null
  hasMore: boolean
  loadingMore: boolean
  loadMore: () => Promise<void>
  messagesContainerRef: React.MutableRefObject<HTMLDivElement | null>
  messagesEndRef: React.RefObject<HTMLDivElement | null>
  /** Optimistic insert de un mensaje recién enviado por el operador — evita
   *  la espera de ~8-13s del fallback polling cuando Realtime tarda. Dedup por
   *  id: cuando Realtime emita el mismo row, no se duplica. */
  applyOptimistic: (msg: Message) => void
}

const MESSAGE_COLUMNS =
  'id, direction, content, content_type, media_url, media_id, media_mime, created_at, processed, processing_status, skip_reason, delivery_status, delivered_at, read_at, failed_at, delivery_error'
const PAGE_INITIAL = 100
const PAGE_MORE = 50
const POLLING_FALLBACK_THRESHOLD_MS = 8000
const POLLING_INTERVAL_MS = 5000

export function useMessages(
  conversationId: string | null,
  { supabase, onMessageInserted }: Options,
): Result {
  const [messages, setMessages] = useState<Message[]>([])
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)

  const messagesContainerRef = useRef<HTMLDivElement | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const lastRealtimeAt = useRef<number>(0)
  // Callback ref estable — no re-suscribir el efecto si el padre cambia
  // la referencia del callback en cada render.
  const onMessageInsertedRef = useRef(onMessageInserted)
  useEffect(() => { onMessageInsertedRef.current = onMessageInserted }, [onMessageInserted])

  // Carga inicial (100 más recientes ASC visual).
  useEffect(() => {
    if (!conversationId) {
      setMessages([])
      return
    }
    setHasMore(true)
    supabase
      .from('messages')
      .select(MESSAGE_COLUMNS)
      .eq('conversation_id', conversationId)
      .not('content_type', 'in', NON_RENDERABLE_CONTENT_TYPES_PG)
      .order('created_at', { ascending: false })
      .limit(PAGE_INITIAL)
      .then(({ data, error: qErr }) => {
        if (qErr) {
          setMessages([])
          setError('No se pudieron cargar los mensajes de esta conversación.')
          return
        }
        setError(null)
        const fetched = ((data || []) as Message[]).reverse()
        setMessages(fetched)
        setHasMore(fetched.length === PAGE_INITIAL)
        setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
      })
  }, [conversationId, supabase])

  // Realtime + polling fallback.
  useEffect(() => {
    if (!conversationId) return
    const channel = supabase
      .channel(`messages:${conversationId}`)
      .on('postgres_changes', {
        event: '*', schema: 'public', table: 'messages',
        filter: `conversation_id=eq.${conversationId}`,
        // Track 6 (2026-08-22, doc oficial postgres-changes §selecting-columns):
        // select explícito — la fila completa arrastra columnas de auditoría y
        // Realtime TRUNCA silencioso >1.024 KB (campos >64 B se omiten del
        // payload). La PK viaja siempre; lo omitido se re-fetchea por id abajo.
        select: MESSAGE_COLUMNS.split(',').map(c => c.trim()),
      }, (payload) => {
        lastRealtimeAt.current = Date.now()
        if (payload.eventType === 'INSERT') {
          const newMsg = payload.new as Message & { content_type?: string }
          // Anti-truncamiento: si `content` no viajó (payload >1KB), la fila
          // llega incompleta — re-fetch por id con las columnas completas.
          if ((newMsg as unknown as Record<string, unknown>).content === undefined) {
            supabase
              .from('messages')
              .select(MESSAGE_COLUMNS)
              .eq('id', newMsg.id)
              .single()
              .then(({ data }) => {
                if (!data) return
                if (data.content_type &&
                    (NON_RENDERABLE_CONTENT_TYPES as readonly string[]).includes(data.content_type)) return
                setMessages(prev =>
                  prev.some(m => m.id === data.id) ? prev : [...prev, data as Message],
                )
              })
            return
          }
          // R-13 + F7: snapshots internos y filas de auditoría (escalation_audit,
          // sla_breach_audit) NO se renderizan como burbuja.
          if (
            newMsg.content_type &&
            (NON_RENDERABLE_CONTENT_TYPES as readonly string[]).includes(newMsg.content_type)
          ) return
          // A6: dedupe por id (realtime + polling fallback).
          setMessages(prev =>
            prev.some(m => m.id === newMsg.id) ? prev : [...prev, newMsg as Message],
          )
          setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
          // A1: optimistic update del timestamp lateral en el padre.
          const ts = newMsg.created_at || new Date().toISOString()
          onMessageInsertedRef.current?.(conversationId, ts)
        } else if (payload.eventType === 'UPDATE') {
          // Merge (no reemplazo): si el payload vino truncado, los campos
          // omitidos (undefined) no deben pisar los valores ya renderizados.
          const upd = payload.new as Partial<Message> & { id: string }
          setMessages(prev => prev.map(m => m.id === upd.id ? { ...m, ...upd } as Message : m))
        }
      })
      .subscribe((status) => {
        if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') {
          console.warn('[useMessages] channel error, fallback polling activado')
        }
      })

    // Fallback: si Realtime no emite hace > umbral, re-fetch cada 5s.
    const fallbackInterval = setInterval(() => {
      const sinceLastEvent = Date.now() - lastRealtimeAt.current
      if (sinceLastEvent > POLLING_FALLBACK_THRESHOLD_MS) {
        supabase
          .from('messages')
          .select(MESSAGE_COLUMNS)
          .eq('conversation_id', conversationId)
          .not('content_type', 'in', NON_RENDERABLE_CONTENT_TYPES_PG)
          .order('created_at', { ascending: false })
          .limit(PAGE_INITIAL)
          .then(({ data, error: qErr }) => {
            if (qErr) return
            setMessages(((data || []) as Message[]).reverse())
          })
      }
    }, POLLING_INTERVAL_MS)

    return () => {
      clearInterval(fallbackInterval)
      supabase.removeChannel(channel)
    }
  }, [conversationId, supabase])

  // F2: cargar más mensajes históricos (scroll arriba).
  const loadMore = useCallback(async () => {
    if (!conversationId || loadingMore || !hasMore || messages.length === 0) return
    const oldest = messages[0]
    if (!oldest?.created_at) return
    const container = messagesContainerRef.current
    const prevScrollHeight = container?.scrollHeight ?? 0
    setLoadingMore(true)
    try {
      const { data, error: qErr } = await supabase
        .from('messages')
        .select(MESSAGE_COLUMNS)
        .eq('conversation_id', conversationId)
        .not('content_type', 'in', NON_RENDERABLE_CONTENT_TYPES_PG)
        .lt('created_at', oldest.created_at)
        .order('created_at', { ascending: false })
        .limit(PAGE_MORE)
      if (qErr || !data) {
        setHasMore(false)
        return
      }
      const older = (data as Message[]).reverse()
      if (older.length === 0) {
        setHasMore(false)
        return
      }
      setMessages(prev => [...older, ...prev])
      // Restaurar scrollTop para que el operador no pierda contexto visual.
      requestAnimationFrame(() => {
        const c = messagesContainerRef.current
        if (c) c.scrollTop = c.scrollHeight - prevScrollHeight
      })
      if (older.length < PAGE_MORE) setHasMore(false)
    } finally {
      setLoadingMore(false)
    }
  }, [conversationId, supabase, loadingMore, hasMore, messages])

  // Optimistic insert (dedupe por id) + scroll al final.
  const applyOptimistic = useCallback((msg: Message) => {
    if (!msg?.id) return
    setMessages(prev => (prev.some(m => m.id === msg.id) ? prev : [...prev, msg]))
    setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }, [])

  return {
    messages,
    error,
    hasMore,
    loadingMore,
    loadMore,
    messagesContainerRef,
    messagesEndRef,
    applyOptimistic,
  }
}

/**
 * Helper export — el padre lo puede importar para hacer optimistic insert
 * de un mensaje saliente recién enviado (sin esperar Realtime).
 */
export function patchMessages(
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>,
  msg: Message,
) {
  setMessages(prev =>
    prev.some(m => m.id === msg.id) ? prev : [...prev, msg],
  )
}
