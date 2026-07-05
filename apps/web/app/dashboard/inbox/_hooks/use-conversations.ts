'use client'

/**
 * Hook: lista de conversaciones del Inbox (carga + Realtime + URL sync).
 *
 * Refactor 2026-05-29 paso 7/10 — extraído de inbox-manager.tsx (HIGH risk).
 *
 * Responsabilidades:
 *   - Carga inicial con last_message + last_read_at (A2 unread badges).
 *   - Realtime postgres_changes en `conversations` (INSERT/UPDATE/DELETE)
 *     con optimistic updates + polling fallback 20s.
 *   - URL sync (?conv=ID) — restaurar selección al mount + sincronizar
 *     cuando el operador navega entre convs.
 *   - F1 toggle archivadas (refresh on change).
 *   - Auto-selección: primera conv con last_message si no hay URL ni
 *     selección previa.
 *
 * Devuelve:
 *   - conversations: array completo del tenant (RLS aplica).
 *   - selectedId / setSelectedId: control de selección.
 *   - loading / error: estado UI.
 *   - showArchived / setShowArchived: toggle F1.
 *   - reload(): trigger manual de re-fetch.
 *
 * Pitfalls evitados:
 *   - Closure stale de showArchived: usamos showArchivedRef.current dentro
 *     del callback async para que las suscripciones Realtime lean el valor
 *     vigente sin re-suscribirse.
 *   - Doble suscripción en StrictMode dev: cleanup desuscribe con la MISMA
 *     referencia del channel.
 *   - URL sync sin Suspense: useSearchParams suspende; usamos
 *     window.location.search directamente (siempre disponible cliente).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { SupabaseClient } from '@supabase/supabase-js'
import { useRouter, usePathname } from 'next/navigation'
import type { Conversation } from '../_lib/types'
import { NON_RENDERABLE_CONTENT_TYPES } from '../_lib/constants'

interface Options {
  /** Cliente Supabase compartido — pasarlo evita crear N clientes. */
  supabase: SupabaseClient
}

interface Result {
  conversations: Conversation[]
  /** Escape hatch para optimistic updates desde el padre (realtime
   *  messages handler, mark-as-read, status change inline). Usar con
   *  cuidado — el hook ya maneja la mayoría de mutaciones via Realtime. */
  setConversations: React.Dispatch<React.SetStateAction<Conversation[]>>
  selectedId: string | null
  setSelectedId: (id: string | null) => void
  loading: boolean
  error: string | null
  showArchived: boolean
  setShowArchived: (v: boolean | ((prev: boolean) => boolean)) => void
  /** Re-fetch manual (útil tras acciones administrativas). */
  reload: () => void
  /** Sincronizar el querystring ?conv= con el ID dado (o limpiarlo). */
  syncUrlParam: (id: string | null) => void
  /** Paginación incremental — hay conversaciones más antiguas sin cargar. */
  hasMore: boolean
  loadingMore: boolean
  /** Cargar el siguiente lote (amplía la ventana en PAGE_STEP y re-fetchea). */
  loadMore: () => void
}

// Ventana inicial + incremento por "Ver más". El re-fetch (realtime/poll) usa
// la ventana vigente, de modo que lo cargado con "Ver más" NO se pierde.
const PAGE_INITIAL = 50
const PAGE_STEP = 50
// Umbral de inactividad de Realtime para que el polling de seguridad refetchee
// (paridad con useMessages: si Realtime está sano, no refetcheamos en vano).
const POLLING_FALLBACK_THRESHOLD_MS = 8000

export function useConversations({ supabase }: Options): Result {
  const router = useRouter()
  const pathname = usePathname()

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedIdState] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showArchived, setShowArchivedState] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  // Ref para que las suscripciones Realtime lean el valor vigente sin re-suscribirse.
  const showArchivedRef = useRef(false)
  const pendingConvRestore = useRef<string | null>(null)
  // Ventana vigente (crece con "Ver más"). Ref para que el re-fetch de
  // realtime/poll respete lo ya cargado sin recrear el callback.
  const pageSizeRef = useRef(PAGE_INITIAL)
  // Timestamp del último evento Realtime — para que el poll solo actúe si
  // Realtime parece inactivo.
  const lastRealtimeAt = useRef(0)
  // F2: `contact_name` es denormalizado y puede no existir aún (migración
  // 20260704150000 sin aplicar). Empezamos incluyéndolo; si PostgREST responde
  // "undefined column" (42703) lo apagamos y re-fetcheamos sin él, para que la
  // lista NUNCA se rompa por una columna pendiente de migrar.
  const contactNameColRef = useRef(true)

  // URL sync — usar replace para NO empujar history (UX de panel selector).
  const syncUrlParam = useCallback((id: string | null) => {
    const params = new URLSearchParams(window.location.search)
    if (id) params.set('conv', id)
    else params.delete('conv')
    router.replace(`${pathname}?${params.toString()}`, { scroll: false })
  }, [router, pathname])

  const setSelectedId = useCallback((id: string | null) => {
    setSelectedIdState(id)
    syncUrlParam(id)
  }, [syncUrlParam])

  const setShowArchived = useCallback(
    (v: boolean | ((prev: boolean) => boolean)) => {
      setShowArchivedState(prev => {
        const next = typeof v === 'function' ? v(prev) : v
        showArchivedRef.current = next
        return next
      })
    },
    [],
  )

  // Carga inicial (+ refresh por showArchived).
  const loadConversations = useCallback(async () => {
    const buildQuery = () => {
      // F7: pedimos content_type + los 3 más recientes (no 1) para elegir en
      // cliente el último mensaje RENDERABLE del preview — un audit row
      // (escalation_audit/sla_breach_audit) o context_snapshot no debe pintarse
      // como "último mensaje". Se filtra en cliente para NO arriesgar el
      // inner-join implícito de PostgREST sobre embedded (podría ocultar convs).
      const msgEmbed = 'messages(content, direction, created_at, content_type)'
      const cols = contactNameColRef.current
        ? `id, customer_phone, contact_name, status, agentic_state, created_at, last_interaction_at, archived_at, ${msgEmbed}`
        : `id, customer_phone, status, agentic_state, created_at, last_interaction_at, archived_at, ${msgEmbed}`
      let q = supabase
        .from('conversations')
        .select(cols)
        .order('last_interaction_at', { ascending: false })
        // Perf: sólo los últimos mensajes por conv para el preview — limitar el
        // recurso embebido evita traer el historial completo de cada conv en
        // cada carga/poll/realtime (payload crecía linealmente).
        .order('created_at', { referencedTable: 'messages', ascending: false })
        .limit(3, { referencedTable: 'messages' })
        .limit(pageSizeRef.current)
      if (!showArchivedRef.current) {
        q = q.is('archived_at', null)
      }
      return q
    }

    let { data, error: qErr } = await buildQuery()

    // F2: degradación segura si `contact_name` aún no está migrado (42703).
    if (qErr && contactNameColRef.current && (qErr as { code?: string }).code === '42703') {
      contactNameColRef.current = false
      ;({ data, error: qErr } = await buildQuery())
    }

    if (qErr) {
      setConversations([])
      setError('No se pudieron cargar las conversaciones.')
      setLoading(false)
      return
    }

    setError(null)
    // Si el backend devolvió la ventana completa, probablemente hay más.
    setHasMore((data?.length ?? 0) >= pageSizeRef.current)
    type RawRow = Omit<Conversation, 'last_message'> & {
      messages?: Array<{ content: string; direction: string; created_at: string; content_type?: string }>
    }
    // Cast vía unknown: el `.select(cols)` con string dinámico (F2 fallback)
    // impide a supabase-js inferir el tipo de fila literal.
    const rows = ((data ?? []) as unknown as RawRow[]).map(r => {
      // F7: último mensaje RENDERABLE (excluye audit rows / snapshots).
      const renderable = (r.messages ?? [])
        .filter(m => !(m.content_type &&
          (NON_RENDERABLE_CONTENT_TYPES as readonly string[]).includes(m.content_type)))
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
      return {
        ...r,
        messages: undefined,
        last_message: renderable.length > 0 ? renderable[0] : null,
      } as Conversation
    })

    // A2: marcas de lectura para badge unread.
    if (rows.length > 0) {
      const ids = rows.map(r => r.id)
      const { data: readsData } = await supabase
        .from('conversation_reads')
        .select('conversation_id, last_read_at')
        .in('conversation_id', ids)
      const readsMap = new Map<string, string>()
      ;(readsData ?? []).forEach((r: { conversation_id: string; last_read_at: string }) => {
        readsMap.set(r.conversation_id, r.last_read_at)
      })
      rows.forEach(r => {
        r.last_read_at = readsMap.get(r.id) ?? null
      })
    }
    setConversations(rows)
    setLoading(false)

    // Restaurar conversación desde URL (pendingConvRestore) o seleccionar la primera.
    const urlConvId = pendingConvRestore.current
      ?? new URLSearchParams(window.location.search).get('conv')
    if (urlConvId && rows.some(r => r.id === urlConvId)) {
      setSelectedIdState(urlConvId)
      pendingConvRestore.current = null
    } else {
      setSelectedIdState(prev => {
        if (prev && rows.some(r => r.id === prev)) return prev
        if (rows.length === 0) return null
        const preferred = rows.find(r => r.last_message) ?? rows[0]
        syncUrlParam(preferred.id)
        return preferred.id
      })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supabase])

  // "Ver más": amplía la ventana y re-fetchea (respetando showArchived + filtros).
  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return
    setLoadingMore(true)
    pageSizeRef.current += PAGE_STEP
    try {
      await loadConversations()
    } finally {
      setLoadingMore(false)
    }
  }, [loadingMore, hasMore, loadConversations])

  // Restaurar conv de la URL en mount.
  useEffect(() => {
    const convId = new URLSearchParams(window.location.search).get('conv')
    if (convId) {
      pendingConvRestore.current = convId
      setSelectedIdState(prev => prev ?? convId)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Carga inicial.
  useEffect(() => {
    loadConversations()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadConversations])

  // Refresh al togglear archivadas.
  useEffect(() => {
    showArchivedRef.current = showArchived
    loadConversations()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showArchived])

  // Realtime conversations + polling fallback.
  useEffect(() => {
    const channel = supabase
      .channel('conversations:all')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'conversations' }, (payload) => {
        lastRealtimeAt.current = Date.now()
        if (payload.eventType === 'INSERT') {
          const newConv = payload.new as Conversation
          if (newConv?.id) {
            setConversations(prev => {
              if (prev.some(c => c.id === newConv.id)) return prev
              if (!showArchivedRef.current && newConv.archived_at) return prev
              const merged: Conversation = {
                ...newConv,
                last_message: null,
                last_read_at: null,
              }
              return [merged, ...prev].sort((a, b) => {
                const at = new Date(a.last_interaction_at ?? a.created_at ?? 0).getTime()
                const bt = new Date(b.last_interaction_at ?? b.created_at ?? 0).getTime()
                return bt - at
              })
            })
          }
          // Re-fetch para llenar last_message cuando el INSERT a messages
          // (que ocurre milisegundos después) ya esté visible.
          loadConversations()
          return
        }
        if (payload.eventType === 'UPDATE') {
          const upd = payload.new as Partial<Conversation> & { id: string }
          setConversations(prev =>
            prev.map(c => c.id === upd.id ? { ...c, ...upd } : c)
              .sort((a, b) => {
                const at = new Date(a.last_interaction_at ?? a.created_at ?? 0).getTime()
                const bt = new Date(b.last_interaction_at ?? b.created_at ?? 0).getTime()
                return bt - at
              }),
          )
          return
        }
        if (payload.eventType === 'DELETE') {
          const old = payload.old as { id: string }
          setConversations(prev => prev.filter(c => c.id !== old.id))
        }
      })
      .subscribe()

    // Polling de seguridad cada 20s — si Realtime falla por RLS/race,
    // el polling recoge la conversación nueva sin requerir F5 manual.
    // Solo refetchea si Realtime lleva > umbral en silencio (evita refetch
    // redundante permanente cuando Realtime está sano).
    const pollInterval = setInterval(() => {
      if (Date.now() - lastRealtimeAt.current > POLLING_FALLBACK_THRESHOLD_MS) {
        loadConversations()
      }
    }, 20000)

    return () => {
      supabase.removeChannel(channel)
      clearInterval(pollInterval)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadConversations])

  return {
    conversations,
    setConversations,
    selectedId,
    setSelectedId,
    loading,
    error,
    showArchived,
    setShowArchived,
    reload: loadConversations,
    syncUrlParam,
    hasMore,
    loadingMore,
    loadMore,
  }
}

/**
 * Patch incremental al state de conversations desde el padre.
 * Útil para optimistic updates de mensajes/lectura sin re-suscribir.
 */
export function patchConversation(
  setConversations: React.Dispatch<React.SetStateAction<Conversation[]>>,
  id: string,
  patch: Partial<Conversation>,
) {
  setConversations(prev =>
    prev.map(c => c.id === id ? { ...c, ...patch } : c),
  )
}
