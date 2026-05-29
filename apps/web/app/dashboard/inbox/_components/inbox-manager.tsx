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
import { useMessages } from '../_hooks/use-messages'
import { ContextPanel } from './context-panel'
import { ConversationList } from './conversation-list'
import { ChatPanel } from './chat-panel'

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
  // Refactor paso 9/10 2026-05-29 — messages state vive en useMessages hook.
  // Optimistic patch a conversations.last_interaction_at via callback.
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
  // F2 scroll histórico cursor-based — vive en useMessages.
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
  // Refactor paso 9/10 2026-05-29 — carga inicial + Realtime + polling
  // fallback de mensajes viven en useMessages. Optimistic patch a
  // last_interaction_at via callback onMessageInserted.
  const {
    messages,
    error: messagesLoadError,
    hasMore: hasMoreMessages,
    loadingMore,
    loadMore: loadMoreMessages,
    messagesContainerRef,
    messagesEndRef,
  } = useMessages(selectedId, {
    supabase,
    onMessageInserted: (convId, ts) => {
      setConversations(prev =>
        prev.map(c => c.id === convId
          ? { ...c, last_interaction_at: ts }
          : c,
        ).sort((a, b) => {
          const at = new Date(a.last_interaction_at ?? a.created_at ?? 0).getTime()
          const bt = new Date(b.last_interaction_at ?? b.created_at ?? 0).getTime()
          return bt - at
        }),
      )
    },
  })

  // Refactor paso 7/10 2026-05-29 — Realtime conversations + polling fallback
  // viven en useConversations. El hook expone setConversations como escape
  // hatch para optimistic updates desde otros effects (realtime messages,
  // mark-as-read) que aún viven en este componente (pendiente paso 9).

  // Refactor paso 9/10 — loadMoreMessages, hasMoreMessages, loadingMore
  // viven en useMessages. F2 cursor-based pagination encapsulada.

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

      {/* ── Panel Chat — Refactor paso 10/10 — ChatPanel ────────────────────── */}
      <ChatPanel
        selectedConv={selectedConv}
        context={convContext}
        messages={messages}
        error={messagesLoadError}
        hasMore={hasMoreMessages}
        loadingMore={loadingMore}
        loadMore={() => { void loadMoreMessages() }}
        messagesContainerRef={messagesContainerRef}
        messagesEndRef={messagesEndRef}
        replyText={replyText}
        setReplyText={setReplyText}
        replyInputRef={replyInputRef}
        sending={sending}
        sendError={sendError}
        onSendMessage={handleSendMessage}
        takingOver={takingOver}
        statusError={statusError}
        onUpdateStatus={updateStatus}
        mobileView={mobileView}
        setMobileView={setMobileView}
        contextPanelOpen={contextPanelOpen}
        onToggleContextPanel={() => setContextPanelOpen(p => !p)}
      />


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
