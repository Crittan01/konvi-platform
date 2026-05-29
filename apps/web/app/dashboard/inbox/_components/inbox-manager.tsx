'use client'

import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'
import {
  MessageSquare, User, Bot, Phone, Clock, AlertCircle, Send,
  Search, X, ChevronLeft, ChevronRight, Filter, CheckCheck, Check,
  Circle, Wifi, WifiOff, Package, ShoppingBag, MapPin, Plus,
  BadgeCheck, BadgeX, Loader2, Info, ChevronsRight,
  ShoppingCart, Mail, FileText, Truck,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { createIdempotencyKey } from '@/lib/idempotency'
import { renderWhatsAppFormat, stripWhatsAppFormat } from '@/lib/whatsapp-format'

// Refactor 2026-05-29 paso 1/10 — types, constantes y helpers extraídos a `_lib/`.
// Single source of truth, server+client safe, testable sin DOM.
import type {
  AgenticState,
  Conversation,
  Message,
  ProductVariation,
  Product,
  OrderRow,
  ContactRow,
  CartItem,
  ActiveCart,
  OpenClaim,
  ConvContext,
  SelectedVariation,
  FilterStatus,
} from '../_lib/types'
import {
  ORDER_STATUS_LABEL,
  ORDER_STATUS_COLOR,
  STATUS_CONFIG,
  FILTER_OPTIONS,
  SLA_BREACH_HOURS,
} from '../_lib/constants'
import {
  formatPhone,
  agenticStateLabel,
  getAgenticStateBadgeColor,
  timeAgo,
  formatDate,
  formatDateTime,
  formatMoney,
  variationLabel,
  isSlaBreach,
  groupConvsByPhone,
} from '../_lib/format'
import { wrapSelection, prefixLine, prefixLineNumbered } from '../_lib/editor'
import { ChatEditorToolbar } from './chat-editor-toolbar'
import { OrderMiniForm } from './order-mini-form'
import { useConversationContext } from '../_hooks/use-conversation-context'
import { useConversations } from '../_hooks/use-conversations'
import { ContextPanel } from './context-panel'
import { ConversationList } from './conversation-list'

// ─── Componente Principal ─────────────────────────────────────────────────────
// Refactor 2026-05-29 paso 2/10 — extraído de page.tsx como Client Component.
// Server page.tsx ahora es thin (auth + tenant + render). InboxManager
// orquesta state local + Realtime + UI 3-paneles.
export default function InboxManager() {
  const supabase = useMemo(() => createClient(), [])
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // --- Estado base ---
  // Refactor paso 7/10 2026-05-29 — conversations + selectedId + loading +
  // showArchived + URL sync + Realtime convs + polling fallback via hook.
  const {
    conversations,
    setConversations,
    selectedId,
    setSelectedId,
    loading,
    error: conversationsLoadError,
    showArchived,
    setShowArchived,
    reload: loadConversations,
    syncUrlParam,
  } = useConversations({ supabase })
  const [messages, setMessages] = useState<Message[]>([])
  const [messagesLoadError, setMessagesLoadError] = useState<string | null>(null)
  const [takingOver, setTakingOver] = useState(false)
  const [replyText, setReplyText] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('active')
  // Rev. 109 founder 2026-05-28 — expand-collapse de grupos por phone.
  // Modelo: 1 cliente = 1 fila visible (la conv primary del grupo). Si el
  // cliente tiene >1 sesión histórica, expand para verlas indentadas.
  const [expandedPhones, setExpandedPhones] = useState<Set<string>>(new Set())
  // F2: scroll histórico cursor-based.
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMoreMessages, setHasMoreMessages] = useState(true)
  const messagesContainerRef = useRef<HTMLDivElement | null>(null)
  const [mobileView, setMobileView] = useState<'list' | 'chat' | 'context'>('list')
  const [waConnected, setWaConnected] = useState<boolean | null>(null)

  // --- Panel contextual ---
  const [contextPanelOpen, setContextPanelOpen] = useState(true)
  // Refactor paso 5/10 2026-05-29 — context vive en hook dedicado.
  // Beneficios: AbortController + interval cleanup automáticos, refresh()
  // expuesto al padre como callback puro, sin state local extra.
  const [productSearchCatalog, setProductSearchCatalog] = useState('')  // búsqueda en catálogo informativo
  const [showAllOrders, setShowAllOrders] = useState(false)  // B2: paginación pedidos
  // Refactor paso 4/10 2026-05-29 — state local del mini-form (productSearchForm,
  // showOrderForm, selectedVariations, orderQtys, orderShipping, orderNotes,
  // creatingOrder, orderError, orderSuccess) + handlers (toggleVariation,
  // createOrder) ahora viven encapsulados en <OrderMiniForm/>.

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const replyInputRef = useRef<HTMLTextAreaElement>(null)

  const selectedConv = conversations.find(c => c.id === selectedId) ?? null

  // Refactor paso 7/10 2026-05-29 — syncUrlParam + restore desde URL +
  // loadConversations + Realtime convs viven en useConversations.

  // ── Filtros ────────────────────────────────────────────────────────────────
  const filteredConvs = conversations.filter(c => {
    const matchesSearch = search === '' || c.customer_phone.includes(search.replace('+', ''))
    // 'active' = bot_active + human_takeover (accionables día-a-día).
    // 'sla_breach' = human_takeover sin respuesta humana ≥SLA_BREACH_HOURS.
    // 'all' = literalmente todas. Otros valores = match exacto al status.
    const matchesFilter =
      filterStatus === 'all'
        ? true
        : filterStatus === 'active'
          ? c.status === 'bot_active' || c.status === 'human_takeover'
          : filterStatus === 'sla_breach'
            ? isSlaBreach(c)
            : c.status === filterStatus
    return matchesSearch && matchesFilter
  })

  // WhatsApp integration status (independiente del hook de conversations).
  useEffect(() => {
    supabase
      .from('tenant_integrations')
      .select('status')
      .eq('provider', 'whatsapp')
      .single()
      .then(({ data }) => {
        setWaConnected(data?.status === 'connected')
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Refactor paso 5/10 2026-05-29 — Contexto del panel derecho via hook.
  // Rev. 103 patrón intacto: real-time mirror del bot (refresh silent 5s)
  // + abort + 404 handling. Lógica extraída a _hooks/use-conversation-context.ts.
  const {
    context: convContext,
    loading: contextLoading,
    refreshing: contextRefreshing,
    refresh: refreshConvContext,
  } = useConversationContext(selectedId, {
    onDeleted: () => setSelectedId(null),
  })

  // ── Cargar mensajes ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!selectedId) return
    setHasMoreMessages(true)
    supabase
      .from('messages')
      .select('id, direction, content, content_type, media_url, created_at, processed, processing_status, skip_reason')
      .eq('conversation_id', selectedId)
      // Excluir snapshots de contexto interno (R-13) — no se renderizan al cliente.
      .neq('content_type', 'context_snapshot')
      // DESC para traer los 100 MÁS RECIENTES (no los 100 más antiguos)
      // Se revierten en el then() para mostrar en orden cronológico (asc visual)
      .order('created_at', { ascending: false })
      .limit(100)
      .then(({ data, error }) => {
        if (error) {
          setMessages([])
          setMessagesLoadError('No se pudieron cargar los mensajes de esta conversación.')
          return
        }
        setMessagesLoadError(null)
        const fetched = (data || []).reverse()
        setMessages(fetched)
        // Si vinieron menos de 100, no hay más historial.
        setHasMoreMessages(fetched.length === 100)
        setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  // ── Realtime — mensajes ────────────────────────────────────────────────────
  const lastRealtimeAt = useRef<number>(0)
  useEffect(() => {
    if (!selectedId) return
    const channel = supabase
      .channel(`messages:${selectedId}`)
      .on('postgres_changes', {
        event: '*', schema: 'public', table: 'messages',
        filter: `conversation_id=eq.${selectedId}`,
      }, (payload) => {
        lastRealtimeAt.current = Date.now()
        if (payload.eventType === 'INSERT') {
          const newMsg = payload.new as Message & { content_type?: string }
          // R-13: snapshots de contexto interno NO se renderizan al cliente.
          if (newMsg.content_type === 'context_snapshot') return
          // A6: dedupe por id para evitar duplicado entre realtime y polling fallback.
          setMessages(prev =>
            prev.some(m => m.id === newMsg.id)
              ? prev
              : [...prev, newMsg as Message]
          )
          setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
          // A1: optimistic update del timestamp lateral — el trigger DB
          // actualizará conversations.last_interaction_at, pero sin esperar al
          // round-trip refrescamos local para que el lateral y el chat
          // queden alineados de inmediato.
          const ts = (payload.new as Message).created_at || new Date().toISOString()
          setConversations(prev =>
            prev.map(c => c.id === selectedId
              ? { ...c, last_interaction_at: ts }
              : c
            ).sort((a, b) => {
              const at = new Date(a.last_interaction_at ?? a.created_at ?? 0).getTime()
              const bt = new Date(b.last_interaction_at ?? b.created_at ?? 0).getTime()
              return bt - at
            })
          )
        } else if (payload.eventType === 'UPDATE') {
          setMessages(prev => prev.map(m => m.id === payload.new.id ? payload.new as Message : m))
        }
      })
      .subscribe((status) => {
        if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') {
          console.warn('[Realtime] messages channel error, fallback polling activado')
        }
      })

    // Fallback: si Realtime falla, recargar mensajes cada 5s
    const fallbackInterval = setInterval(() => {
      const sinceLastEvent = Date.now() - lastRealtimeAt.current
      if (sinceLastEvent > 8000) {
        supabase
          .from('messages')
          .select('id, direction, content, content_type, media_url, created_at, processed, processing_status, skip_reason')
          .eq('conversation_id', selectedId)
          .neq('content_type', 'context_snapshot')
          .order('created_at', { ascending: false })
          .limit(100)
          .then(({ data, error }) => {
            if (error) return
            setMessages((data || []).reverse())
          })
      }
    }, 5000)

    return () => {
      clearInterval(fallbackInterval)
      supabase.removeChannel(channel)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  // Refactor paso 7/10 2026-05-29 — Realtime conversations + polling fallback
  // viven en useConversations. El hook expone setConversations como escape
  // hatch para optimistic updates desde otros effects (realtime messages,
  // mark-as-read) que aún viven en este componente (pendiente paso 9).

  // F2: cargar más mensajes históricos cuando el operador hace scroll arriba.
  const loadMoreMessages = async () => {
    if (!selectedId || loadingMore || !hasMoreMessages || messages.length === 0) return
    const oldest = messages[0]
    if (!oldest?.created_at) return
    const container = messagesContainerRef.current
    const prevScrollHeight = container?.scrollHeight ?? 0
    setLoadingMore(true)
    try {
      const { data, error } = await supabase
        .from('messages')
        .select('id, direction, content, content_type, media_url, created_at, processed, processing_status, skip_reason')
        .eq('conversation_id', selectedId)
        .neq('content_type', 'context_snapshot')
        .lt('created_at', oldest.created_at)
        .order('created_at', { ascending: false })
        .limit(50)
      if (error || !data) {
        setHasMoreMessages(false)
        return
      }
      const older = data.reverse()
      if (older.length === 0) {
        setHasMoreMessages(false)
        return
      }
      setMessages(prev => [...older, ...prev])
      // Restaurar scroll position para que el operador no pierda contexto.
      requestAnimationFrame(() => {
        const c = messagesContainerRef.current
        if (c) c.scrollTop = c.scrollHeight - prevScrollHeight
      })
      if (older.length < 50) setHasMoreMessages(false)
    } finally {
      setLoadingMore(false)
    }
  }

  // ── Seleccionar conversación ───────────────────────────────────────────────
  const handleSelectConv = async (id: string) => {
    setSelectedId(id)
    syncUrlParam(id)
    setMobileView('chat')
    setReplyText('')
    setSendError(null)
    setStatusError(null)
    // A2: marcar como leída — upsert en conversation_reads.
    const now = new Date().toISOString()
    setConversations(prev => prev.map(c => c.id === id ? { ...c, last_read_at: now } : c))
    try {
      const { data: { user } } = await supabase.auth.getUser()
      const tenantId = user?.app_metadata?.tenant_id
      if (user?.id && tenantId) {
        await supabase.from('conversation_reads').upsert(
          { tenant_id: tenantId, user_id: user.id, conversation_id: id, last_read_at: now },
          { onConflict: 'tenant_id,user_id,conversation_id' },
        )
      }
    } catch {
      // El badge optimistic ya está aplicado; el upsert es best-effort.
    }
  }

  // ── Acciones — cambio de estado ────────────────────────────────────────────
  const updateStatus = async (status: Conversation['status']) => {
    if (!selectedId) return
    setTakingOver(true)
    setStatusError(null)

    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token
    if (!token) { setStatusError('Sesión expirada.'); setTakingOver(false); return }

    // A5: Idempotency-Key con scope canónico (igual que send/orders/shipping).
    // Misma key durante reintentos (503) → backend dedup a un solo cambio.
    const idempotencyKey = createIdempotencyKey('conversations.status')
    try {
      const doRequest = async () => {
        const ctrl = new AbortController()
        const timeout = setTimeout(() => ctrl.abort(), 45000)
        try {
          return await fetch(`/api/conversations/${selectedId}/status`, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${token}`,
              'Idempotency-Key': idempotencyKey,
            },
            body: JSON.stringify({ status }),
            signal: ctrl.signal,
          })
        } finally { clearTimeout(timeout) }
      }

      let res = await doRequest()
      if (!res.ok && res.status === 503) {
        await new Promise(r => setTimeout(r, 1500))
        res = await doRequest()
      }

      if (res.ok) {
        setConversations(prev => prev.map(c => c.id === selectedId ? { ...c, status } : c))
      } else {
        const err = await res.json().catch(() => ({ detail: 'Error al actualizar estado' }))
        setStatusError(err.detail || 'Error al actualizar estado')
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') {
        setStatusError('El servicio tardó demasiado. Intenta de nuevo.')
      } else {
        setStatusError('No se pudo actualizar el estado de la conversación.')
      }
    }
    setTakingOver(false)
  }

  // ── Enviar mensaje ─────────────────────────────────────────────────────────
  const handleSendMessage = async () => {
    if (!selectedId || !replyText.trim() || sending) return
    setSending(true)
    setSendError(null)
    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token
    if (!token) { setSendError('Sesión expirada.'); setSending(false); return }
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 90000)
      const idempotencyKey = createIdempotencyKey('conversations.send')
      const res = await fetch(`/api/conversations/${selectedId}/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify({ text: replyText.trim() }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Error desconocido' }))
        setSendError(err.detail || 'No se pudo enviar')
      } else {
        setReplyText('')
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') {
        setSendError('Timeout. Intenta de nuevo.')
      } else {
        setSendError('Error de red.')
      }
    } finally {
      setSending(false)
      replyInputRef.current?.focus()
    }
  }

  // Refactor paso 4/10 2026-05-29 — la lógica de crear pedido y selección
  // de variantes vive ahora en <OrderMiniForm/>. El padre solo provee:
  // products, conversationId, contactId y un callback opcional para
  // refrescar el contexto tras crear pedido (mostrar el nuevo en
  // "Pedidos recientes").
  // Refactor paso 5/10 — refresh delegado al hook (encapsula auth + endpoint).
  const refreshContextAfterOrder = refreshConvContext

  // ── Productos filtrados — catálogo informativo (búsqueda independiente) ────
  const filteredProducts = (convContext?.products ?? []).filter(p =>
    productSearchCatalog === '' ||
    p.title.toLowerCase().includes(productSearchCatalog.toLowerCase()) ||
    (p.product_variations ?? []).some(v => v.sku?.toLowerCase().includes(productSearchCatalog.toLowerCase()))
  )

  // ── WA desconectado ────────────────────────────────────────────────────────
  if (waConnected === false) {
    return (
      <div className="flex items-center justify-center h-[calc(100dvh-7rem)] sm:h-[calc(100vh-4rem)]">
        <div className="flex flex-col items-center gap-4 text-center max-w-sm px-4">
          <WifiOff className="h-10 w-10 text-muted-foreground" />
          <p className="text-muted-foreground text-sm leading-relaxed">
            WhatsApp no está conectado — no llegarán mensajes nuevos ni podrás responder.
            Ve a <strong className="text-foreground">Configuración → Integraciones</strong> para conectarlo.
          </p>
          <a
            href="/dashboard/integrations"
            className="inline-flex items-center gap-1.5 text-xs font-medium px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
          >
            Configurar WhatsApp
          </a>
        </div>
      </div>
    )
  }

  // ─── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-[calc(100vh-8rem)] min-h-[500px] overflow-hidden rounded-[1.25rem] border border-border shadow-sm">

      {/* ── Panel Lista — Refactor paso 8/10 — ConversationList ─────────────── */}
      <ConversationList
        conversations={conversations}
        filteredConvs={filteredConvs}
        selectedId={selectedId}
        onSelect={handleSelectConv}
        loading={loading}
        error={conversationsLoadError}
        search={search}
        setSearch={setSearch}
        filterStatus={filterStatus}
        setFilterStatus={setFilterStatus}
        showArchived={showArchived}
        setShowArchived={setShowArchived}
        mobileView={mobileView}
      />

      {/* ── Panel Chat ──────────────────────────────────────────────────────── */}
      <div className={`
        flex-1 flex flex-col bg-[#F3F6F4] min-w-0
        ${mobileView === 'list' || mobileView === 'context' ? 'hidden sm:flex' : 'flex'}
      `}>
        {!selectedConv ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <div className="text-center">
              <MessageSquare className="h-12 w-12 mx-auto mb-3 opacity-20" />
              <p className="text-sm">Selecciona una conversación</p>
            </div>
          </div>
        ) : (
          <>
            {/* Header chat */}
            <div className="px-4 py-3 border-b border-border flex items-center gap-3 bg-card/80 backdrop-blur-md">
              <button
                onClick={() => setMobileView('list')}
                className="sm:hidden p-1.5 rounded-lg hover:bg-accent text-muted-foreground"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <div className="h-8 w-8 rounded-full bg-primary/15 flex items-center justify-center shrink-0">
                    <Phone className="h-3.5 w-3.5 text-primary" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-sm truncate">
                      {convContext?.contact?.name || formatPhone(selectedConv.customer_phone)}
                    </p>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border cursor-help ${STATUS_CONFIG[selectedConv.status].color}`}
                        title={STATUS_CONFIG[selectedConv.status].description}
                      >
                        {STATUS_CONFIG[selectedConv.status].label}
                      </span>
                      {/* Rev. 103 — SLA timer: muestra hace cuánto fue el último
                          mensaje INBOUND del cliente. Naranja si >5min, rojo si >15min. */}
                      {(() => {
                        const lastInbound = [...messages].reverse().find(m => m.direction === 'inbound')
                        if (!lastInbound) return null
                        const ageMs = Date.now() - new Date(lastInbound.created_at).getTime()
                        const ageMin = Math.floor(ageMs / 60000)
                        let cls = 'text-muted-foreground'
                        if (ageMin >= 15) cls = 'text-red-600 font-medium'
                        else if (ageMin >= 5) cls = 'text-amber-600 font-medium'
                        return (
                          <span className={`inline-flex items-center gap-0.5 text-[10px] ${cls}`} title={`Último mensaje del cliente: ${formatDateTime(lastInbound.created_at)}`}>
                            <Clock className="h-2.5 w-2.5" />
                            {timeAgo(lastInbound.created_at)}
                          </span>
                        )
                      })()}
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex gap-2 shrink-0">
                {selectedConv.status === 'bot_active' && (
                  <Button size="sm" variant="outline" onClick={() => updateStatus('human_takeover')} disabled={takingOver}
                    className="text-amber-600 border-amber-500/30 hover:bg-amber-500/10 text-xs h-8">
                    <AlertCircle className="h-3.5 w-3.5 mr-1" /> Tomar control
                  </Button>
                )}
                {selectedConv.status === 'human_takeover' && (
                  <Button size="sm" variant="outline" onClick={() => updateStatus('bot_active')} disabled={takingOver}
                    className="text-emerald-600 border-emerald-500/30 hover:bg-emerald-500/10 text-xs h-8">
                    <Bot className="h-3.5 w-3.5 mr-1" /> Volver al bot
                  </Button>
                )}
                {selectedConv.status === 'opted_out' && (
                  <Button size="sm" variant="outline" onClick={() => updateStatus('bot_active')} disabled={takingOver}
                    className="text-emerald-600 border-emerald-500/30 hover:bg-emerald-500/10 text-xs h-8"
                    title="Reactivar bot. consent_revoked_at sigue marcado — para reactivar marketing proactivo, el cliente debe re-otorgar consent explícitamente.">
                    <Bot className="h-3.5 w-3.5 mr-1" /> Reactivar bot
                  </Button>
                )}
                {/* Toggle panel contextual en desktop */}
                <button
                  onClick={() => setContextPanelOpen(p => !p)}
                  className="hidden lg:flex items-center justify-center h-8 w-8 rounded-lg border border-border hover:bg-accent text-muted-foreground"
                  title={contextPanelOpen ? 'Cerrar panel' : 'Abrir panel de cliente'}
                >
                  {contextPanelOpen ? <ChevronsRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4 rotate-180" />}
                </button>
                {/* Abrir panel contextual en mobile */}
                <button
                  onClick={() => setMobileView('context')}
                  className="lg:hidden flex items-center justify-center h-8 w-8 rounded-lg border border-border hover:bg-accent text-muted-foreground"
                  title="Ver panel de cliente"
                >
                  <Info className="h-4 w-4" />
                </button>
              </div>
            </div>
            {statusError && (
              <div className="px-4 py-2 text-[11px] text-red-400 bg-red-500/5 border-b border-red-500/20">
                {statusError}
              </div>
            )}
            {/* A3: Banner ventana 24h Meta — solo visible en human_takeover.
                Calcula horas desde el último mensaje inbound real para dar
                visibilidad al operador antes de que intente enviar fuera de
                ventana (Meta rechazaría sin template aprobado). */}
            {selectedConv.status === 'human_takeover' && (() => {
              const lastInbound = [...messages]
                .reverse()
                .find(m => m.direction === 'inbound')
              if (!lastInbound) {
                return (
                  <div className="px-4 py-2 text-[12px] text-red-700 bg-red-50 border-b border-red-200 flex items-center gap-2">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                    <span>
                      Aún no hay mensaje del cliente. Meta solo permite responder libre cuando el cliente abrió la conversación —
                      espera a que escriba o usa una plantilla aprobada.
                    </span>
                  </div>
                )
              }
              const hoursSince =
                (Date.now() - new Date(lastInbound.created_at).getTime()) / 3_600_000
              const hoursRemaining = 24 - hoursSince
              if (hoursRemaining <= 0) {
                return (
                  <div className="px-4 py-2 text-[12px] text-red-700 bg-red-50 border-b border-red-200 flex items-center gap-2">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                    <span>
                      <strong>Ventana 24h expirada</strong> (último mensaje del cliente hace {hoursSince.toFixed(1)}h).
                      Los mensajes libres serán rechazados por Meta — usa una plantilla aprobada.
                    </span>
                  </div>
                )
              }
              if (hoursRemaining < 4) {
                return (
                  <div className="px-4 py-2 text-[12px] text-amber-700 bg-amber-50 border-b border-amber-200 flex items-center gap-2">
                    <Clock className="h-3.5 w-3.5 shrink-0" />
                    <span>
                      Ventana 24h: quedan <strong>{hoursRemaining.toFixed(1)}h</strong> para responder libremente.
                      Después necesitarás una plantilla aprobada por Meta.
                    </span>
                  </div>
                )
              }
              return null
            })()}
            {/* Refactor paso 4/10 — el banner orderSuccess vive ahora dentro
                de <OrderMiniForm/> (state encapsulado). Si en el futuro se
                requiere mostrar el éxito en el panel central también, exponerlo
                via callback onOrderCreated del mini-form. */}

            {/* Mensajes */}
            <div
              ref={messagesContainerRef}
              onScroll={(e) => {
                const t = e.currentTarget
                if (t.scrollTop < 80 && hasMoreMessages && !loadingMore) {
                  void loadMoreMessages()
                }
              }}
              className="flex-1 overflow-y-auto p-4 space-y-3"
            >
              {loadingMore && (
                <div className="text-center text-[11px] text-muted-foreground py-2">
                  Cargando mensajes anteriores...
                </div>
              )}
              {!hasMoreMessages && messages.length >= 100 && (
                <div className="text-center text-[10px] text-muted-foreground py-1">
                  Inicio de la conversación
                </div>
              )}
              {messagesLoadError ? (
                <div className="text-center text-red-400 text-sm pt-12">
                  <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-70" />
                  {messagesLoadError}
                </div>
              ) : messages.length === 0 ? (
                <div className="text-center text-muted-foreground text-sm pt-12">
                  <Circle className="h-8 w-8 mx-auto mb-2 opacity-20" />
                  Sin mensajes aún.
                </div>
              ) : messages.map(msg => {
                const isInbound = msg.direction === 'inbound'
                return (
                  <div key={msg.id} className={`flex gap-2 ${isInbound ? 'justify-start' : 'justify-end'}`}>
                    {isInbound && (
                      <div className="h-7 w-7 rounded-full bg-muted flex items-center justify-center flex-shrink-0 mt-1">
                        <User className="h-3.5 w-3.5 text-muted-foreground" />
                      </div>
                    )}
                    <div className={`max-w-[75%] sm:max-w-[65%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-sm border border-border/50 ${
                      isInbound
                        ? 'bg-card text-foreground rounded-tl-sm'
                        : 'bg-primary text-primary-foreground rounded-tr-sm border-transparent'
                    }`}>
                      {msg.content_type === 'image' && msg.media_url ? (
                        <a href={msg.media_url} target="_blank" rel="noopener noreferrer" className="block mb-1.5">
                          <img
                            src={msg.media_url}
                            alt={msg.content || 'imagen del producto'}
                            className="rounded-lg max-w-full max-h-72 object-contain border border-border/40 bg-background/30"
                            loading="lazy"
                          />
                        </a>
                      ) : null}
                      {msg.content && (
                        <p className="whitespace-pre-wrap break-words">
                          {renderWhatsAppFormat(msg.content)}
                        </p>
                      )}
                      <p className={`text-[11px] mt-1 flex items-center gap-1.5 flex-wrap ${isInbound ? 'text-muted-foreground' : 'text-primary-foreground/70'}`}>
                        {timeAgo(msg.created_at)}
                        {!isInbound && (
                          msg.processed
                            ? <CheckCheck className="h-3 w-3" />
                            : <Check className="h-3 w-3" />
                        )}
                        {/* Estado de procesamiento — visible para asesor, ayuda a diagnosticar */}
                        {!isInbound && msg.processing_status === 'failed' && (
                          <span className="text-[10px] bg-red-500/20 text-red-300 px-1.5 py-0.5 rounded-full"
                            title={msg.skip_reason ?? 'Error al procesar'}>
                            ✕ Error
                          </span>
                        )}
                        {!isInbound && msg.processing_status === 'skipped' && (
                          <span className="text-[10px] bg-muted/40 text-muted-foreground/80 px-1.5 py-0.5 rounded-full"
                            title={msg.skip_reason ?? 'Omitido por el bot'}>
                            — Omitido
                          </span>
                        )}
                      </p>
                    </div>
                    {!isInbound && (
                      <div className="h-7 w-7 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0 mt-1">
                        <Bot className="h-3.5 w-3.5 text-primary" />
                      </div>
                    )}
                  </div>
                )
              })}
              <div ref={messagesEndRef} />
            </div>

            {/* Footer */}
            {selectedConv.status === 'human_takeover' ? (
              <div className="p-3 border-t border-border bg-card space-y-2">
                {sendError && <p className="text-xs text-red-400 text-center">{sendError}</p>}
                {/* Rev. 103 — Toolbar completa de formato WhatsApp (estilo
                    Teams/Slack). Cubre TODAS las opciones de la doc oficial
                    de Meta:
                      Inline: *negrita* _cursiva_ ~tachado~ `código` ```mono```
                      Bloque: > cita · viñetas · numerada
                    Atajos: Ctrl+B negrita · Ctrl+I cursiva · Ctrl+E código.
                */}
                <ChatEditorToolbar
                  textareaRef={replyInputRef}
                  setReplyText={setReplyText}
                />
                <div className="flex gap-2 items-end">
                  <textarea
                    ref={replyInputRef}
                    value={replyText}
                    onChange={e => { setReplyText(e.target.value); setSendError(null) }}
                    onKeyDown={e => {
                      // Rev. 103 — atajos de formato (antes del handler de Enter)
                      // Ctrl+B negrita · Ctrl+I cursiva · Ctrl+E código inline
                      if ((e.ctrlKey || e.metaKey) && !e.shiftKey) {
                        const k = e.key.toLowerCase()
                        if (k === 'b') { e.preventDefault(); wrapSelection(replyInputRef, setReplyText, '*'); return }
                        if (k === 'i') { e.preventDefault(); wrapSelection(replyInputRef, setReplyText, '_'); return }
                        if (k === 'e') { e.preventDefault(); wrapSelection(replyInputRef, setReplyText, '`'); return }
                      }
                      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage() }
                    }}
                    placeholder="Escribe tu respuesta...  (Enter envía · Shift+Enter salto de línea · Ctrl+B negrita · Ctrl+I cursiva · Ctrl+E código)"
                    disabled={sending}
                    rows={2}
                    className="flex-1 resize-none rounded-xl border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                  />
                  <Button
                    size="sm"
                    onClick={handleSendMessage}
                    disabled={sending || !replyText.trim()}
                    className="h-10 px-3 bg-primary hover:bg-primary/90 shrink-0"
                  >
                    {sending ? <span className="text-xs animate-pulse">…</span> : <Send className="h-4 w-4" />}
                  </Button>
                </div>
                {/* Preview formateado del mensaje a enviar */}
                {replyText.trim() && (
                  <div className="rounded-lg bg-background/50 border border-border/40 px-3 py-2 text-xs">
                    <p className="text-[10px] text-muted-foreground mb-1">Vista previa:</p>
                    <div className="whitespace-pre-wrap break-words">
                      {renderWhatsAppFormat(replyText)}
                    </div>
                  </div>
                )}
                <p className="text-[11px] text-amber-600 font-medium text-center flex items-center justify-center gap-1">
                  <User className="h-3 w-3" /> Modo agente humano (bot silenciado)
                </p>
              </div>
            ) : (
              <div className="p-3 border-t border-border bg-card">
                <p className="text-xs text-muted-foreground text-center flex items-center justify-center gap-1">
                  {selectedConv.status === 'bot_active'
                    ? <><Bot className="h-3.5 w-3.5" /> El bot está respondiendo automáticamente</>
                    : <><span className="h-3.5 w-3.5 inline-block" /> Conversación cerrada</>}
                </p>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Panel Contextual Derecho ─────────────────────────────────────────── */}
      {selectedConv && (
        <ContextPanel
          conversation={selectedConv}
          context={convContext}
          loading={contextLoading}
          refreshing={contextRefreshing}
          onCloseMobile={() => setMobileView('chat')}
          onOrderCreated={refreshContextAfterOrder}
          isOpen={contextPanelOpen}
          isMobileActive={mobileView === 'context'}
        />
      )}
    </div>
  )
}
