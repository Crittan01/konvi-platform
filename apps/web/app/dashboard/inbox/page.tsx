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

// ─── Types ────────────────────────────────────────────────────────────────────
interface Conversation {
  id: string
  customer_phone: string
  status: 'bot_active' | 'human_takeover' | 'closed'
  created_at: string
  last_interaction_at?: string
  archived_at?: string | null
  last_message?: { content: string; direction: string; created_at: string } | null
  last_read_at?: string | null  // A2: marca de lectura del operador actual
}

// Rev. 72 — content_type tipado (cierra drift M2). Antes era `string` libre,
// el render condicional podía silenciosamente romperse con valores nuevos.
// 'context_snapshot' es interno (snapshots del orchestrator); el filtro `.neq` lo excluye.
type MessageContentType =
  | 'text'
  | 'image'
  | 'audio'
  | 'video'
  | 'document'
  | 'sticker'
  | 'location'
  | 'context_snapshot'

interface Message {
  id: string
  direction: 'inbound' | 'outbound'
  content: string
  content_type: MessageContentType
  media_url?: string | null
  created_at: string
  processed: boolean
  processing_status?: 'pending' | 'processed' | 'skipped' | 'failed'
  skip_reason?: string | null
}

interface ProductVariation {
  id: string
  sku: string
  price: number
  stock_quantity: number
  attributes: Record<string, string>
  weight_kg?: number
  image_url?: string
}

interface Product {
  id: string
  title: string
  description?: string
  cover_image_url?: string
  stock_total: number
  product_variations: ProductVariation[]
}

interface OrderRow {
  id: string
  status: string
  total_amount: number
  shipping_cost: number
  created_at: string
  items_count: number
}

interface ContactRow {
  id: string
  name?: string
  phone: string
  // Rev. 103 — campos PII completos (espejo del system prompt del bot).
  shipping_phone?: string | null
  email?: string | null
  document_type?: string | null
  document_number?: string | null
  address?: Record<string, unknown>
  consent_given?: boolean
  consent_revoked_at?: string | null
}

// Rev. 103 — Cart-as-SoT en vivo. El operador humano ve el mismo carrito
// que el bot está construyendo turn-by-turn.
interface CartItem {
  product_id: string
  variation_id: string
  quantity: number
  unit_price_cents: number
  title: string
  variant_label: string
  sku: string
}

interface ActiveCart {
  id: string
  items: CartItem[]
  subtotal_cents: number
  shipping_cents: number
  total_cents: number
  carrier_name: string
  requires_requote: boolean
}

// Rev. 103 — Reclamos abiertos espejo del system prompt.
interface OpenClaim {
  id: string
  ticket_number: string
  status: string
  type?: string | null
  created_at: string
}

interface ConvContext {
  contact: ContactRow | null
  recent_orders: OrderRow[]
  active_cart: ActiveCart | null
  open_claims: OpenClaim[]
  products: Product[]
  product_count: number
  low_stock_count: number
}

interface SelectedVariation {
  productId: string
  productTitle: string
  variationId: string
  sku: string
  price: number
  stock: number
  label: string
}

type FilterStatus = 'all' | 'bot_active' | 'human_takeover' | 'closed'

const ORDER_STATUS_LABEL: Record<string, string> = {
  pending:    'Pendiente',
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

const ORDER_STATUS_COLOR: Record<string, string> = {
  pending:    'bg-yellow-500/10 text-yellow-700 border-yellow-500/20',
  confirmed:  'bg-blue-500/10 text-blue-700 border-blue-500/20',
  processing: 'bg-purple-500/10 text-purple-700 border-purple-500/20',
  shipped:    'bg-sky-500/10 text-sky-700 border-sky-500/20',
  delivered:  'bg-emerald-500/10 text-emerald-700 border-emerald-500/20',
  cancelled:  'bg-red-500/10 text-red-600 border-red-500/20',
}

// ─── Config ───────────────────────────────────────────────────────────────────
// A4: cada estado lleva un description que se muestra como tooltip HTML nativo
// en los badges. Permite que un operador no técnico entienda el significado y
// las transiciones permitidas sin abrir documentación externa.
const STATUS_CONFIG = {
  bot_active: {
    label: 'Bot activo',
    color: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20',
    dot: 'bg-emerald-500',
    description: 'Bot activo: el asistente IA responde automáticamente con catálogo, KB y FSM de venta. Toma el control con "Tomar control" si necesitas intervenir.',
  },
  human_takeover: {
    label: 'Agente humano',
    color: 'bg-amber-500/10 text-amber-700 border-amber-500/20',
    dot: 'bg-amber-500',
    description: 'Agente humano: un operador tomó el control y el bot está pausado. Para devolver al bot, usa "Volver al bot" aquí o desde Telegram envía /resolver {id}.',
  },
  closed: {
    label: 'Cerrada',
    color: 'bg-slate-500/10 text-slate-700 border-slate-500/20',
    dot: 'bg-slate-500',
    description: 'Cerrada: la conversación quedó archivada por inactividad o resolución manual. Si el cliente vuelve a escribir, se reabre automáticamente como Bot activo.',
  },
}

const FILTER_OPTIONS: { value: FilterStatus; label: string }[] = [
  { value: 'all',            label: 'Todas' },
  { value: 'bot_active',     label: 'Bot' },
  { value: 'human_takeover', label: 'Agente' },
  { value: 'closed',         label: 'Cerradas' },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────
// Normaliza y formatea teléfono sin importar si el raw ya trae '+' o espacios
const formatPhone = (raw: string): string => {
  const digits = (raw || '').replace(/\D/g, '')
  if (digits.startsWith('57') && digits.length === 12)
    return `+57 ${digits.slice(2, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`
  return digits ? `+${digits}` : (raw || '')
}
const timeAgo = (dateStr: string) => {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'ahora'
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}
const TZ_CO = 'America/Bogota'
const formatDate = (d: string) => {
  try {
    return new Date(d).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric', timeZone: TZ_CO })
  } catch { return d }
}
const formatDateTime = (d: string) => {
  try {
    return new Date(d).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: TZ_CO })
  } catch { return d }
}
const formatMoney = (v: number) =>
  new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', minimumFractionDigits: 0 }).format(v)

// Rev. 103 — Toolbar helpers para editor con formato WhatsApp.
// `wrapSelection` envuelve la selección actual con el marker (ej. *).
// Si no hay selección, inserta `marker marker` y deja el cursor entre.
function wrapSelection(
  ref: React.RefObject<HTMLTextAreaElement | null>,
  setText: (v: string) => void,
  marker: string,
): void {
  const ta = ref.current
  if (!ta) return
  const start = ta.selectionStart ?? 0
  const end = ta.selectionEnd ?? start
  const before = ta.value.slice(0, start)
  const sel = ta.value.slice(start, end)
  const after = ta.value.slice(end)
  const wrapped = `${marker}${sel || 'texto'}${marker}`
  const newVal = `${before}${wrapped}${after}`
  setText(newVal)
  // Re-focus + select el texto envuelto para edición fluida.
  setTimeout(() => {
    ta.focus()
    const newStart = before.length + marker.length
    const newEnd = newStart + (sel.length || 'texto'.length)
    ta.setSelectionRange(newStart, newEnd)
  }, 0)
}

// `prefixLine` agrega el prefix al inicio de cada línea seleccionada
// (o de la línea donde está el cursor si no hay selección).
function prefixLine(
  ref: React.RefObject<HTMLTextAreaElement | null>,
  setText: (v: string) => void,
  prefix: string,
): void {
  const ta = ref.current
  if (!ta) return
  const start = ta.selectionStart ?? 0
  const end = ta.selectionEnd ?? start
  const value = ta.value
  // Localizar inicio y fin de las líneas tocadas
  const lineStart = value.lastIndexOf('\n', start - 1) + 1
  const lineEndRaw = value.indexOf('\n', end)
  const lineEnd = lineEndRaw === -1 ? value.length : lineEndRaw
  const block = value.slice(lineStart, lineEnd)
  const prefixed = block.split('\n').map(l => `${prefix}${l}`).join('\n')
  const newVal = `${value.slice(0, lineStart)}${prefixed}${value.slice(lineEnd)}`
  setText(newVal)
  setTimeout(() => {
    ta.focus()
    ta.setSelectionRange(lineStart + prefix.length, lineStart + prefixed.length)
  }, 0)
}

function variationLabel(v: ProductVariation): string {
  if (v.attributes && Object.keys(v.attributes).length > 0) {
    return Object.entries(v.attributes).map(([k, val]) => `${k}: ${val}`).join(', ')
  }
  return v.sku || 'Estándar'
}

// ─── Componente Principal ─────────────────────────────────────────────────────
export default function InboxPage() {
  const supabase = useMemo(() => createClient(), [])
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // --- Estado base ---
  const [conversations, setConversations] = useState<Conversation[]>([])
  // selectedId no se inicializa desde useSearchParams (puede estar vacío en SSR).
  // Se restaura en useEffect desde window.location.search (siempre disponible cliente).
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const pendingConvRestore = useRef<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(true)
  const [conversationsLoadError, setConversationsLoadError] = useState<string | null>(null)
  const [messagesLoadError, setMessagesLoadError] = useState<string | null>(null)
  const [takingOver, setTakingOver] = useState(false)
  const [replyText, setReplyText] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all')
  // F1: toggle para mostrar conversaciones archivadas (>90 días sin actividad).
  const [showArchived, setShowArchived] = useState(false)
  const showArchivedRef = useRef(false)
  // F2: scroll histórico cursor-based.
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMoreMessages, setHasMoreMessages] = useState(true)
  const messagesContainerRef = useRef<HTMLDivElement | null>(null)
  const [mobileView, setMobileView] = useState<'list' | 'chat' | 'context'>('list')
  const [waConnected, setWaConnected] = useState<boolean | null>(null)

  // --- Panel contextual ---
  const [contextPanelOpen, setContextPanelOpen] = useState(true)
  const [convContext, setConvContext] = useState<ConvContext | null>(null)
  const [contextLoading, setContextLoading] = useState(false)
  // Rev. 103 — indicador silencioso de auto-refresh (visible en header panel
  // como pequeño spinner cuando el polling silent dispara).
  const [contextRefreshing, setContextRefreshing] = useState(false)
  const [productSearchForm, setProductSearchForm]       = useState('')  // búsqueda en mini-form de pedido
  const [productSearchCatalog, setProductSearchCatalog] = useState('')  // búsqueda en catálogo informativo
  const [showAllOrders, setShowAllOrders] = useState(false)  // B2: paginación pedidos

  // --- Mini-form crear pedido ---
  const [showOrderForm, setShowOrderForm] = useState(false)
  const [selectedVariations, setSelectedVariations] = useState<SelectedVariation[]>([])
  const [orderQtys, setOrderQtys] = useState<Record<string, number>>({})
  const [orderShipping, setOrderShipping] = useState<string>('')
  const [orderNotes, setOrderNotes] = useState('')
  const [creatingOrder, setCreatingOrder] = useState(false)
  const [orderError, setOrderError] = useState<string | null>(null)
  const [orderSuccess, setOrderSuccess] = useState<string | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const replyInputRef = useRef<HTMLTextAreaElement>(null)

  const selectedConv = conversations.find(c => c.id === selectedId) ?? null

  // ── Persistir conversación en URL ──────────────────────────────────────────
  const syncUrlParam = useCallback((id: string | null) => {
    const params = new URLSearchParams(window.location.search)
    if (id) {
      params.set('conv', id)
    } else {
      params.delete('conv')
    }
    router.replace(`${pathname}?${params.toString()}`, { scroll: false })
  }, [router, pathname])

  // ── Leer conv de la URL en cliente (antes de cargar conversaciones) ─────────
  useEffect(() => {
    const convId = new URLSearchParams(window.location.search).get('conv')
    if (convId) {
      pendingConvRestore.current = convId
      // Si ya hay conversaciones cargadas (re-mount), restaurar directamente
      setSelectedId(prev => prev ?? convId)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Filtros ────────────────────────────────────────────────────────────────
  const filteredConvs = conversations.filter(c => {
    const matchesSearch = search === '' || c.customer_phone.includes(search.replace('+', ''))
    const matchesFilter = filterStatus === 'all' || c.status === filterStatus
    return matchesSearch && matchesFilter
  })

  // ── Cargar conversaciones ──────────────────────────────────────────────────
  const loadConversations = useCallback(async () => {
    // F1: por default solo conversaciones activas (archived_at IS NULL).
    // Toggle "Ver archivadas" expone las archivadas en el filtro lateral.
    let query = supabase
      .from('conversations')
      .select('id, customer_phone, status, created_at, last_interaction_at, archived_at, messages(content, direction, created_at)')
      .order('last_interaction_at', { ascending: false })
      .limit(50)
    if (!showArchivedRef.current) {
      query = query.is('archived_at', null)
    }
    const { data, error } = await query

    if (error) {
      setConversations([])
      setConversationsLoadError('No se pudieron cargar las conversaciones.')
      setLoading(false)
      return
    }

    setConversationsLoadError(null)
    type RawRow = Omit<Conversation, 'last_message'> & {
      messages?: Array<{ content: string; direction: string; created_at: string }>
    }
    const rows = ((data ?? []) as RawRow[]).map(r => {
      const msgs = r.messages
      return {
        ...r,
        messages: undefined,
        last_message: msgs && msgs.length > 0
          ? msgs.sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
          : null,
      } as Conversation
    })

    // A2: traer marcas de lectura del operador actual para badge unread.
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

    // Restaurar conversación desde URL (pendingConvRestore) o seleccionar la primera
    const urlConvId = pendingConvRestore.current
      ?? new URLSearchParams(window.location.search).get('conv')
    if (urlConvId && rows.some(r => r.id === urlConvId)) {
      setSelectedId(urlConvId)
      pendingConvRestore.current = null
    } else {
      // Solo auto-seleccionar si no hay ninguna conversación activa
      setSelectedId(prev => {
        if (prev && rows.some(r => r.id === prev)) return prev
        if (rows.length === 0) return null
        const preferred = rows.find(r => r.last_message) ?? rows[0]
        syncUrlParam(preferred.id)
        return preferred.id
      })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    loadConversations()
    supabase
      .from('tenant_integrations')
      .select('status')
      .eq('provider', 'whatsapp')
      .single()
      .then(({ data }) => {
        setWaConnected(data?.status === 'connected')
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadConversations])

  // F1: refrescar lista cuando cambia el toggle de archivadas.
  useEffect(() => {
    showArchivedRef.current = showArchived
    loadConversations()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showArchived])

  // ── Cargar contexto del panel al cambiar conversación + auto-refresh ───────
  // Rev. 103 — Real-time mirror del Inbox: refresh cada 5s mientras la
  // conversación está seleccionada para reflejar cambios en cart, address,
  // contact (caso real: bot agrega item al cart en el siguiente turno → el
  // operador humano lo ve sin recargar la página).
  useEffect(() => {
    if (!selectedId) {
      setConvContext(null)
      return
    }
    setContextLoading(true)
    setConvContext(null)
    setShowOrderForm(false)
    setSelectedVariations([])
    setOrderSuccess(null)
    setOrderError(null)

    const controller = new AbortController()
    let refreshTimer: ReturnType<typeof setInterval> | null = null
    let cancelled = false

    const fetchContext = async (opts?: { silent?: boolean }) => {
      if (opts?.silent) setContextRefreshing(true)
      try {
        const { data } = await supabase.auth.getSession()
        const token = data.session?.access_token
        if (!token) {
          if (!opts?.silent) setContextLoading(false)
          return
        }
        const res = await fetch(`/api/conversations/${selectedId}/context`, {
          headers: { 'Authorization': `Bearer ${token}` },
          signal: controller.signal,
        })
        if (!res.ok) return
        const json = await res.json()
        if (!cancelled && !controller.signal.aborted) setConvContext(json)
      } catch (e) {
        if (!controller.signal.aborted && !opts?.silent) console.warn('context error', e)
      } finally {
        if (!cancelled && !controller.signal.aborted) {
          if (opts?.silent) setContextRefreshing(false)
          else setContextLoading(false)
        }
      }
    }

    fetchContext().then(() => {
      // Real-time refresh cada 5s (silent — sin loading flicker).
      refreshTimer = setInterval(() => fetchContext({ silent: true }), 5000)
    })

    return () => {
      cancelled = true
      controller.abort()
      if (refreshTimer) clearInterval(refreshTimer)
    }
  }, [selectedId])  // eslint-disable-line react-hooks/exhaustive-deps

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

  // ── Realtime — conversaciones ──────────────────────────────────────────────
  useEffect(() => {
    const channel = supabase
      .channel('conversations:all')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'conversations' }, (payload) => {
        // A1: optimistic update con el payload, sin re-fetch completo.
        // El trigger DB actualiza last_interaction_at en cada INSERT a messages;
        // ese UPDATE llega aquí con REPLICA IDENTITY FULL.
        if (payload.eventType === 'INSERT') {
          // Conversación nueva — inyectar al state inmediatamente con los datos
          // del payload para evitar race contra el re-fetch (el connector hace
          // INSERT conversations + INSERT messages en pasos separados; sin
          // optimistic update la fila no aparece hasta que el operador
          // refresca con F5).
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
              })
          )
          return
        }
        if (payload.eventType === 'DELETE') {
          const old = payload.old as { id: string }
          setConversations(prev => prev.filter(c => c.id !== old.id))
        }
      })
      .subscribe()

    // Polling de seguridad cada 20s. Si Realtime falla por RLS,
    // race u otros motivos, el polling recoge la conversación nueva sin
    // requerir F5 manual. La query es liviana (50 conversaciones max).
    const pollInterval = setInterval(() => {
      loadConversations()
    }, 20000)

    return () => {
      supabase.removeChannel(channel)
      clearInterval(pollInterval)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadConversations])

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

  // ── Crear pedido desde Inbox ───────────────────────────────────────────────
  const handleToggleVariation = (v: SelectedVariation) => {
    setSelectedVariations(prev => {
      const exists = prev.find(x => x.variationId === v.variationId)
      if (exists) return prev.filter(x => x.variationId !== v.variationId)
      return [...prev, v]
    })
    setOrderQtys(prev => ({ ...prev, [v.variationId]: prev[v.variationId] ?? 1 }))
    setOrderError(null)
    setOrderSuccess(null)
  }

  const handleCreateOrder = async () => {
    if (!selectedId || selectedVariations.length === 0) return
    setCreatingOrder(true)
    setOrderError(null)
    setOrderSuccess(null)

    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token
    if (!token) { setOrderError('Sesión expirada.'); setCreatingOrder(false); return }

    const shippingCost = parseFloat(orderShipping || '0')
    const items = selectedVariations.map(v => ({
      product_id: v.productId,
      variation_id: v.variationId,
      title: `${v.productTitle} — ${v.label}`,
      unit_price: v.price,
      quantity: orderQtys[v.variationId] ?? 1,
    }))

    const idempotencyKey = createIdempotencyKey('orders.create')
    try {
      const res = await fetch('/api/orders', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify({
          conversation_id: selectedId,
          contact_id: convContext?.contact?.id ?? null,
          notes: orderNotes.trim() || null,
          shipping_cost: isNaN(shippingCost) ? 0 : shippingCost,
          items,
          // Crear directo en confirmed para que descuente stock
          auto_confirm: true,
        }),
      })
      const json = await res.json().catch(() => ({ detail: 'Error desconocido' }))
      if (!res.ok) {
        setOrderError(json.detail || 'Error al crear el pedido')
      } else {
        setOrderSuccess(`Pedido #${json.id?.slice(0, 8)} creado y confirmado.`)
        setSelectedVariations([])
        setOrderQtys({})
        setOrderShipping('')
        setOrderNotes('')
        setShowOrderForm(false)
        // Recargar contexto para mostrar el nuevo pedido
        setTimeout(() => {
          supabase.auth.getSession().then(({ data }) => {
            const t = data.session?.access_token
            if (!t) return
            fetch(`/api/conversations/${selectedId}/context`, {
              headers: { 'Authorization': `Bearer ${t}` },
            })
              .then(r => r.json())
              .then(j => setConvContext(j))
              .catch(() => {})
          })
        }, 800)
      }
    } catch {
      setOrderError('Error de red al crear el pedido.')
    } finally {
      setCreatingOrder(false)
    }
  }

  // ── Productos filtrados — dos listas independientes por búsqueda separada ──
  const filteredProductsForm = (convContext?.products ?? []).filter(p =>
    productSearchForm === '' ||
    p.title.toLowerCase().includes(productSearchForm.toLowerCase()) ||
    (p.product_variations ?? []).some(v => v.sku?.toLowerCase().includes(productSearchForm.toLowerCase()))
  )
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

      {/* ── Panel Lista ──────────────────────────────────────────────────────── */}
      <div className={`
        flex flex-col bg-card border-r border-border
        w-full sm:w-80 lg:w-72 xl:w-80 shrink-0
        ${mobileView === 'chat' || mobileView === 'context' ? 'hidden sm:flex' : 'flex'}
      `}>
        {/* Header lista */}
        <div className="p-4 border-b border-border space-y-3">
          <div className="flex items-center justify-between">
            <h1 className="font-semibold text-base flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-primary" />
              Inbox AI
            </h1>
            <div className="flex items-center gap-1 text-xs text-emerald-400">
              <Wifi className="h-3 w-3" />
              <span>Live</span>
            </div>
          </div>

          {/* Búsqueda */}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Buscar por teléfono..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-border bg-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            {search && (
              <button onClick={() => setSearch('')} className="absolute right-2.5 top-1/2 -translate-y-1/2">
                <X className="h-3 w-3 text-muted-foreground" />
              </button>
            )}
          </div>

          {/* Filtros */}
          <div className="flex gap-1 flex-wrap">
            {FILTER_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setFilterStatus(opt.value)}
                className={`text-[11px] px-2 py-0.5 rounded-full border transition-colors ${
                  filterStatus === opt.value
                    ? 'bg-primary/10 text-primary border-primary/30 font-medium'
                    : 'border-border text-muted-foreground hover:text-foreground'
                }`}
              >
                {opt.label}
              </button>
            ))}
            {/* F1: toggle archivadas */}
            <button
              onClick={() => setShowArchived(v => !v)}
              className={`text-[11px] px-2 py-0.5 rounded-full border transition-colors ${
                showArchived
                  ? 'bg-slate-200 text-slate-700 border-slate-400 font-medium'
                  : 'border-border text-muted-foreground hover:text-foreground'
              }`}
              title="Mostrar conversaciones archivadas (cerradas con >90 días sin actividad)"
            >
              {showArchived ? 'Ocultar archivadas' : 'Ver archivadas'}
            </button>
          </div>

          <p className="text-xs text-muted-foreground">
            {filteredConvs.length} conversacion{filteredConvs.length !== 1 ? 'es' : ''}
            {showArchived && ' (incl. archivadas)'}
          </p>
        </div>

        {/* Lista conversaciones */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="space-y-1 p-2">
              {[1,2,3,4].map(i => (
                <div key={i} className="h-16 rounded-lg bg-border/40 animate-pulse" />
              ))}
            </div>
          ) : conversationsLoadError ? (
            <div className="p-8 text-center text-red-400 text-sm">
              <AlertCircle className="h-10 w-10 mx-auto mb-3 opacity-70" />
              <p>{conversationsLoadError}</p>
            </div>
          ) : filteredConvs.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground text-sm">
              <MessageSquare className="h-10 w-10 mx-auto mb-3 opacity-20" />
              <p>{search ? 'Sin resultados' : 'No hay conversaciones'}</p>
            </div>
          ) : (
            filteredConvs.map(conv => {
              const st = STATUS_CONFIG[conv.status]
              const isSelected = conv.id === selectedId
              // A2: marca de unread = último mensaje inbound posterior a last_read_at del operador.
              const hasUnread = !!(
                conv.last_message &&
                conv.last_message.direction === 'inbound' &&
                (!conv.last_read_at || conv.last_message.created_at > conv.last_read_at) &&
                !isSelected
              )
              return (
                <button
                  key={conv.id}
                  onClick={() => handleSelectConv(conv.id)}
                  className={`w-full text-left p-3.5 border-b border-border transition-colors hover:bg-secondary/50 ${
                    isSelected ? 'bg-secondary border-l-2 border-l-primary' : ''
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <div className={`h-2 w-2 rounded-full flex-shrink-0 ${st.dot}`} />
                      <span className={`text-sm ${hasUnread ? 'font-bold text-foreground' : 'font-medium'}`}>
                        {formatPhone(conv.customer_phone)}
                      </span>
                      {hasUnread && (
                        <span
                          className="h-2 w-2 rounded-full bg-emerald-500 flex-shrink-0"
                          title="Mensaje sin leer"
                        />
                      )}
                    </div>
                    <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                      <Clock className="h-2.5 w-2.5" />
                      {timeAgo(conv.last_interaction_at ?? conv.created_at)}
                    </span>
                  </div>
                  {conv.last_message && (
                    <p className="text-[11px] text-muted-foreground ml-4 truncate">
                      {conv.last_message.direction === 'outbound' ? '→ ' : ''}
                      {stripWhatsAppFormat(conv.last_message.content)}
                    </p>
                  )}
                  <div className="ml-4 mt-1">
                    <span
                      className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border cursor-help ${st.color}`}
                      title={st.description}
                    >
                      {st.label}
                    </span>
                  </div>
                </button>
              )
            })
          )}
        </div>
      </div>

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
            {orderSuccess && (
              <div className="px-4 py-2 text-[11px] text-emerald-600 bg-emerald-500/5 border-b border-emerald-500/20 flex items-center gap-1">
                <BadgeCheck className="h-3.5 w-3.5" /> {orderSuccess}
              </div>
            )}

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
                {/* Rev. 103 — Toolbar de formato WhatsApp (estilo Teams/Slack).
                    Inserta los markers alrededor de la selección o donde
                    está el cursor. Atajos Ctrl+B / Ctrl+I dentro del textarea. */}
                <div className="flex items-center gap-1 px-1">
                  <button
                    type="button"
                    onClick={() => wrapSelection(replyInputRef, setReplyText, '*')}
                    title="Negrita (Ctrl+B)"
                    className="h-7 w-7 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-sm font-bold"
                  >B</button>
                  <button
                    type="button"
                    onClick={() => wrapSelection(replyInputRef, setReplyText, '_')}
                    title="Cursiva (Ctrl+I)"
                    className="h-7 w-7 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-sm italic"
                  >I</button>
                  <button
                    type="button"
                    onClick={() => wrapSelection(replyInputRef, setReplyText, '~')}
                    title="Tachado"
                    className="h-7 w-7 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-sm line-through"
                  >S</button>
                  <button
                    type="button"
                    onClick={() => wrapSelection(replyInputRef, setReplyText, '```')}
                    title="Monoespaciado"
                    className="h-7 w-7 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-xs font-mono"
                  >{'</>'}</button>
                  <button
                    type="button"
                    onClick={() => prefixLine(replyInputRef, setReplyText, '> ')}
                    title="Cita"
                    className="h-7 w-7 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-sm"
                  >&ldquo;&rdquo;</button>
                  <span className="text-[10px] text-muted-foreground ml-2">
                    *negrita* _cursiva_ ~tachado~ ```mono```
                  </span>
                </div>
                <div className="flex gap-2 items-end">
                  <textarea
                    ref={replyInputRef}
                    value={replyText}
                    onChange={e => { setReplyText(e.target.value); setSendError(null) }}
                    onKeyDown={e => {
                      // Atajos de formato (Ctrl+B / Ctrl+I) — antes de Enter handler
                      if ((e.ctrlKey || e.metaKey) && !e.shiftKey) {
                        const k = e.key.toLowerCase()
                        if (k === 'b') { e.preventDefault(); wrapSelection(replyInputRef, setReplyText, '*'); return }
                        if (k === 'i') { e.preventDefault(); wrapSelection(replyInputRef, setReplyText, '_'); return }
                      }
                      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage() }
                    }}
                    placeholder="Escribe tu respuesta... (Enter para enviar · Shift+Enter nueva línea · Ctrl+B negrita)"
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
        <div className={`
          flex flex-col bg-muted/30 border-l border-border
          w-full lg:w-80 xl:w-96 shrink-0 overflow-hidden
          ${mobileView === 'context' ? 'flex' : 'hidden lg:flex'}
          ${contextPanelOpen ? 'lg:flex' : 'lg:hidden'}
        `}>
          {/* Header panel — Rev. 103: indicador silencioso de auto-refresh */}
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <span className="text-sm font-semibold flex items-center gap-2">
              <User className="h-4 w-4 text-primary" /> Contexto del cliente
              {contextRefreshing && (
                <Loader2 className="h-3 w-3 text-muted-foreground animate-spin" aria-label="Sincronizando" />
              )}
            </span>
            <button
              onClick={() => setMobileView('chat')}
              className="lg:hidden p-1.5 rounded-lg hover:bg-accent text-muted-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-0">

            {/* Contacto */}
            <section className="p-4 border-b border-border">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Contacto</p>
                {convContext?.contact?.id && (
                  <a
                    href={`/dashboard/contacts?id=${convContext.contact.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Abrir perfil completo del cliente en nueva pestaña"
                    className="text-[10px] text-primary hover:underline inline-flex items-center gap-0.5"
                  >
                    Ver perfil <ChevronsRight className="h-3 w-3" />
                  </a>
                )}
              </div>
              {contextLoading ? (
                <div className="h-12 rounded-lg bg-border/30 animate-pulse" />
              ) : convContext?.contact ? (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <div className="h-9 w-9 rounded-full bg-primary/10 flex items-center justify-center">
                      <User className="h-4 w-4 text-primary" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold">{convContext.contact.name || 'Sin nombre'}</p>
                      <p className="text-xs text-muted-foreground">{formatPhone(convContext.contact.phone)}</p>
                    </div>
                  </div>
                  {/* Rev. 103 — PII completa para que el operador humano
                      vea todo lo que el bot ya tiene (espejo system prompt).
                      Tipografía text-xs (12px) para mejor legibilidad. */}
                  {convContext.contact.email && (
                    <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                      <Mail className="h-3 w-3 shrink-0" />
                      <span className="truncate">{convContext.contact.email}</span>
                    </p>
                  )}
                  {convContext.contact.document_type && convContext.contact.document_number && (
                    <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                      <FileText className="h-3 w-3 shrink-0" />
                      {convContext.contact.document_type} {convContext.contact.document_number}
                    </p>
                  )}
                  {convContext.contact.shipping_phone &&
                   convContext.contact.shipping_phone !== convContext.contact.phone &&
                   convContext.contact.shipping_phone.replace(/\+/g, '') !==
                   convContext.contact.phone.replace(/\+/g, '') && (
                    <p
                      className="text-xs text-amber-700 flex items-center gap-1.5"
                      title="Celular alternativo de envío. La transportadora contactará a este número (no el WhatsApp)."
                    >
                      <Truck className="h-3 w-3 shrink-0" />
                      Envío: {formatPhone(convContext.contact.shipping_phone)}
                    </p>
                  )}
                  {/* Rev. 103 — Address multilinea con jerarquía visual */}
                  {convContext.contact.address && typeof convContext.contact.address === 'object' && (() => {
                    const addr = convContext.contact.address as Record<string, string>
                    const street = addr.street || ''
                    const complex = addr.complex_name || ''
                    const towerApto = [
                      addr.tower ? `Torre ${addr.tower}` : '',
                      addr.apartment ? `Apto ${addr.apartment}` : '',
                    ].filter(Boolean).join(' · ')
                    const city = addr.city || ''
                    const hasAny = street || complex || towerApto || city
                    return hasAny ? (
                      <div className="text-xs text-muted-foreground flex items-start gap-1.5 mt-0.5">
                        <MapPin className="h-3 w-3 shrink-0 mt-0.5" />
                        <div className="flex-1 min-w-0">
                          {street && <p className="font-medium text-foreground">{street}</p>}
                          {complex && <p className="italic">{complex}</p>}
                          {towerApto && <p>{towerApto}</p>}
                          {city && <p className="text-[11px]">{city}</p>}
                        </div>
                      </div>
                    ) : null
                  })()}
                  {convContext.contact.address && typeof convContext.contact.address !== 'object' && (
                    <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                      <MapPin className="h-3 w-3 shrink-0" />
                      {convContext.contact.address as string}
                    </p>
                  )}
                  <div className="flex items-center gap-1 mt-1">
                    {convContext.contact.consent_given ? (
                      <span className="inline-flex items-center gap-0.5 text-[10px] text-emerald-700 bg-emerald-700/10 px-1.5 py-0.5 rounded-full border border-emerald-700/30">
                        <BadgeCheck className="h-3 w-3" /> Habeas data
                      </span>
                    ) : convContext.contact.consent_revoked_at ? (
                      <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-700 bg-amber-700/10 px-1.5 py-0.5 rounded-full border border-amber-700/30">
                        <BadgeX className="h-3 w-3" /> Revocado
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground bg-border/30 px-1.5 py-0.5 rounded-full border border-border">
                        <BadgeX className="h-3 w-3" /> Sin consentimiento
                      </span>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {contextLoading ? '' : 'Cliente no registrado en Contactos.'}
                </p>
              )}
            </section>

            {/* Rev. 103 — Carrito ACTIVO (cart-as-SoT) — espejo de lo que
                el bot está construyendo turn-by-turn. Solo visible si hay
                items. Real-time refresh cada 5s. */}
            {convContext?.active_cart && convContext.active_cart.items.length > 0 && (
              <section className={`p-4 border-b border-border ${
                convContext.active_cart.requires_requote
                  ? 'bg-amber-50/30 dark:bg-amber-950/10'
                  : 'bg-emerald-50/20 dark:bg-emerald-950/5'
              }`}>
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <ShoppingCart className="h-3.5 w-3.5" /> Carrito en construcción
                </p>
                <div className="space-y-1.5">
                  {convContext.active_cart.items.map((it, idx) => (
                    <div key={idx} className="flex justify-between items-start gap-2 p-2 rounded-lg bg-background border border-border">
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium truncate">
                          {it.quantity}× {it.title}
                        </p>
                        {it.variant_label && (
                          <p className="text-[11px] text-muted-foreground">
                            {it.variant_label}
                          </p>
                        )}
                      </div>
                      <p className="text-xs font-medium whitespace-nowrap">
                        {formatMoney(((it.unit_price_cents || 0) * (it.quantity || 1)) / 100)}
                      </p>
                    </div>
                  ))}
                  <div className="pt-1.5 border-t border-border space-y-0.5">
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>Subtotal</span>
                      <span>{formatMoney((convContext.active_cart.subtotal_cents || 0) / 100)}</span>
                    </div>
                    {convContext.active_cart.shipping_cents > 0 && (
                      <div className="flex justify-between text-xs text-muted-foreground">
                        <span>
                          Envío{convContext.active_cart.carrier_name && ` · ${convContext.active_cart.carrier_name}`}
                        </span>
                        <span>{formatMoney(convContext.active_cart.shipping_cents / 100)}</span>
                      </div>
                    )}
                    {convContext.active_cart.requires_requote && (
                      <p
                        className="text-[10px] text-amber-700 italic"
                        title="El carrito cambió después de la última cotización. El bot va a re-cotizar automáticamente la próxima vez que el cliente pregunte por envío."
                      >
                        ⚠ Cart cambió — envío necesita re-cotización
                      </p>
                    )}
                    {convContext.active_cart.total_cents > 0 && (
                      <div className="flex justify-between text-sm font-semibold pt-0.5">
                        <span>Total</span>
                        <span>{formatMoney(convContext.active_cart.total_cents / 100)}</span>
                      </div>
                    )}
                  </div>
                </div>
              </section>
            )}

            {/* Rev. 103 — Reclamos abiertos. Visible al operador humano
                (antes solo el bot los veía en system prompt). Si hay alguno
                el operador puede continuar la atención sin duplicar trabajo. */}
            {convContext?.open_claims && convContext.open_claims.length > 0 && (
              <section className="p-4 border-b border-border">
                <p className="text-xs font-semibold text-red-700 uppercase tracking-wider mb-2 flex items-center gap-1">
                  <AlertCircle className="h-3 w-3" /> Reclamos abiertos ({convContext.open_claims.length})
                </p>
                <div className="space-y-1.5">
                  {convContext.open_claims.map(claim => (
                    <div key={claim.id} className="p-2 rounded-lg bg-red-50/40 border border-red-200/50">
                      <p className="text-xs font-medium">#{claim.ticket_number}</p>
                      {claim.type && (
                        <p className="text-[10px] text-muted-foreground">{claim.type}</p>
                      )}
                      <p className="text-[10px] text-muted-foreground">
                        Abierto · {timeAgo(claim.created_at)}
                      </p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Pedidos recientes */}
            <section className="p-4 border-b border-border">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Pedidos recientes</p>
              {contextLoading ? (
                <div className="space-y-2">
                  {[1,2].map(i => <div key={i} className="h-10 rounded-lg bg-border/30 animate-pulse" />)}
                </div>
              ) : convContext && (convContext.recent_orders ?? []).length > 0 ? (
                <div className="space-y-2">
                  {(showAllOrders
                    ? (convContext.recent_orders ?? [])
                    : (convContext.recent_orders ?? []).slice(0, 3)
                  ).map(order => (
                    <div key={order.id} className="flex items-center justify-between p-2 rounded-lg bg-background border border-border">
                      <div>
                        <p className="text-xs font-medium">#{order.id.slice(0, 8)}</p>
                        <p className="text-[11px] text-muted-foreground">{formatDate(order.created_at)} · {order.items_count} art.</p>
                      </div>
                      <div className="text-right">
                        <span className={`inline-flex text-[10px] px-1.5 py-0.5 rounded-full border ${ORDER_STATUS_COLOR[order.status] ?? 'bg-border/30 text-muted-foreground border-border'}`}>
                          {ORDER_STATUS_LABEL[order.status] ?? order.status}
                        </span>
                        <p className="text-[11px] font-medium mt-0.5">{formatMoney(order.total_amount)}</p>
                      </div>
                    </div>
                  ))}
                  {(convContext.recent_orders ?? []).length > 3 && (
                    <button
                      onClick={() => setShowAllOrders(v => !v)}
                      className="w-full text-[11px] text-muted-foreground hover:text-primary py-1 transition-colors"
                    >
                      {showAllOrders
                        ? '▴ Ver menos'
                        : `▾ Ver ${(convContext.recent_orders ?? []).length - 3} más`}
                    </button>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No hay pedidos vinculados.</p>
              )}

              {/* CTA Crear pedido — solo en human_takeover */}
              {selectedConv.status === 'human_takeover' && !showOrderForm && (
                <button
                  onClick={() => { setShowOrderForm(true); setOrderError(null); setOrderSuccess(null) }}
                  className="mt-3 w-full flex items-center justify-center gap-2 py-1.5 px-3 rounded-lg border border-dashed border-primary/40 text-primary text-xs hover:bg-primary/5 transition-colors"
                >
                  <Plus className="h-3.5 w-3.5" /> Crear Pedido desde Inbox
                </button>
              )}
            </section>

            {/* Mini-form Crear Pedido */}
            {showOrderForm && selectedConv.status === 'human_takeover' && (
              <section className="p-4 border-b border-border bg-background/50">
                <div className="flex items-center justify-between mb-3">
                  <p className="text-xs font-semibold flex items-center gap-1.5">
                    <ShoppingBag className="h-3.5 w-3.5 text-primary" /> Nuevo Pedido
                  </p>
                  <button onClick={() => { setShowOrderForm(false); setSelectedVariations([]); setOrderError(null) }}
                    className="text-muted-foreground hover:text-foreground">
                    <X className="h-4 w-4" />
                  </button>
                </div>

                {/* Selector de variantes */}
                <div className="mb-3">
                  <div className="relative mb-2">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                    <input
                      type="text"
                      placeholder="Buscar producto..."
                      value={productSearchForm}
                      onChange={e => setProductSearchForm(e.target.value)}
                      className="w-full pl-7 pr-2 py-1 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div className="max-h-40 overflow-y-auto space-y-1">
                    {filteredProductsForm.map(product =>
                      (product.product_variations ?? []).map(v => {
                        const label = variationLabel(v)
                        const sel = selectedVariations.find(x => x.variationId === v.id)
                        return (
                          <button
                            key={v.id}
                            onClick={() => handleToggleVariation({
                              productId: product.id,
                              productTitle: product.title,
                              variationId: v.id,
                              sku: v.sku,
                              price: v.price,
                              stock: v.stock_quantity,
                              label,
                            })}
                            className={`w-full text-left px-2 py-1.5 rounded-lg text-xs border transition-colors ${
                              sel
                                ? 'bg-primary/10 border-primary/30 text-primary'
                                : 'bg-background border-border hover:bg-secondary/50'
                            }`}
                          >
                            <span className="font-medium">{product.title}</span>
                            {label !== 'Estándar' && <span className="text-muted-foreground"> — {label}</span>}
                            <span className="float-right font-semibold">{formatMoney(v.price)}</span>
                            <br />
                            <span className={`text-[10px] ${v.stock_quantity <= 0 ? 'text-red-500' : 'text-muted-foreground'}`}>
                              Stock: {v.stock_quantity}
                            </span>
                          </button>
                        )
                      })
                    )}
                  </div>
                </div>

                {/* Ítems seleccionados con cantidades */}
                {selectedVariations.length > 0 && (
                  <div className="space-y-1.5 mb-3">
                    <p className="text-[11px] text-muted-foreground font-medium">Seleccionados:</p>
                    {selectedVariations.map(v => (
                      <div key={v.variationId} className="flex items-center gap-2">
                        <span className="text-xs flex-1 truncate">{v.productTitle} — {v.label}</span>
                        <input
                          type="number"
                          min={1}
                          max={v.stock}
                          value={orderQtys[v.variationId] ?? 1}
                          onChange={e => setOrderQtys(prev => ({ ...prev, [v.variationId]: Math.max(1, parseInt(e.target.value) || 1) }))}
                          className="w-14 px-1 py-0.5 text-xs rounded border border-border bg-background text-center focus:outline-none focus:ring-1 focus:ring-primary"
                        />
                        <button onClick={() => handleToggleVariation(v)} className="text-muted-foreground hover:text-red-400">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                    {/* Total estimado */}
                    <p className="text-xs font-semibold text-right border-t border-border pt-1.5">
                      Subtotal: {formatMoney(
                        selectedVariations.reduce((sum, v) => sum + v.price * (orderQtys[v.variationId] ?? 1), 0)
                      )}
                    </p>
                  </div>
                )}

                {/* Envío */}
                <div className="mb-2">
                  <label className="text-[11px] text-muted-foreground">Costo de envío (COP)</label>
                  <input
                    type="number"
                    min={0}
                    value={orderShipping}
                    onChange={e => setOrderShipping(e.target.value)}
                    placeholder="0"
                    className="mt-0.5 w-full px-2 py-1 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>

                {/* Notas */}
                <div className="mb-3">
                  <label className="text-[11px] text-muted-foreground">Notas (opcional)</label>
                  <textarea
                    value={orderNotes}
                    onChange={e => setOrderNotes(e.target.value)}
                    rows={2}
                    placeholder="Instrucciones de entrega, referencia, etc."
                    className="mt-0.5 w-full resize-none px-2 py-1 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>

                {orderError && (
                  <p className="text-[11px] text-red-400 mb-2 flex items-center gap-1">
                    <AlertCircle className="h-3.5 w-3.5" /> {orderError}
                  </p>
                )}

                <Button
                  size="sm"
                  onClick={handleCreateOrder}
                  disabled={creatingOrder || selectedVariations.length === 0}
                  className="w-full text-xs h-8 bg-primary hover:bg-primary/90"
                >
                  {creatingOrder
                    ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Creando…</>
                    : <><Package className="h-3.5 w-3.5 mr-1.5" /> Crear Pedido Confirmado</>}
                </Button>
                <p className="text-[10px] text-muted-foreground text-center mt-1">
                  El pedido se crea confirmado y descuenta stock inmediatamente.
                </p>
              </section>
            )}

            {/* Catálogo / Inventario */}
            <section className="p-4">
              <div className="flex items-center justify-between mb-2">
                <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                  Catálogo ({convContext?.product_count ?? '—'})
                </p>
                {convContext && (convContext.low_stock_count ?? 0) > 0 && (
                  <span className="text-[10px] text-amber-600 bg-amber-500/10 px-1.5 py-0.5 rounded-full border border-amber-500/20">
                    {convContext.low_stock_count} bajo stock
                  </span>
                )}
              </div>

              {/* Buscador de producto */}
              {!showOrderForm && (
                <div className="relative mb-2">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder="Buscar producto o SKU..."
                    value={productSearchCatalog}
                    onChange={e => setProductSearchCatalog(e.target.value)}
                    className="w-full pl-7 pr-2 py-1 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  {productSearchCatalog && (
                    <button onClick={() => setProductSearchCatalog('')} className="absolute right-2.5 top-1/2 -translate-y-1/2">
                      <X className="h-3 w-3 text-muted-foreground" />
                    </button>
                  )}
                </div>
              )}

              {contextLoading ? (
                <div className="space-y-2">
                  {[1,2,3].map(i => <div key={i} className="h-14 rounded-lg bg-border/30 animate-pulse" />)}
                </div>
              ) : filteredProducts.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  {productSearchCatalog ? 'Sin coincidencias' : 'No hay productos activos'}
                </p>
              ) : (
                <div className="space-y-2">
                  {filteredProducts.map(product => {
                    const _variations = product.product_variations ?? []
                    const prices = _variations.map(v => v.price)
                    const minPrice = prices.length > 0 ? Math.min(...prices) : 0
                    const maxPrice = prices.length > 0 ? Math.max(...prices) : 0
                    return (
                      <div key={product.id} className="rounded-lg border border-border bg-background p-2.5 space-y-1.5">
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-xs font-medium leading-tight">{product.title}</p>
                          <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded-full border ${
                            product.stock_total === 0
                              ? 'bg-red-500/10 text-red-500 border-red-500/20'
                              : product.stock_total <= 3
                              ? 'bg-amber-500/10 text-amber-600 border-amber-500/20'
                              : 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20'
                          }`}>
                            {product.stock_total === 0 ? 'Sin stock' : `${product.stock_total} uds`}
                          </span>
                        </div>
                        <p className="text-[11px] text-primary font-semibold">
                          {minPrice === maxPrice ? formatMoney(minPrice) : `${formatMoney(minPrice)} – ${formatMoney(maxPrice)}`}
                        </p>
                        {/* Variantes compactas */}
                        {_variations.length > 1 && (
                          <div className="flex flex-wrap gap-1">
                            {_variations.slice(0, 5).map(v => (
                              <span
                                key={v.id}
                                className={`text-[10px] px-1.5 py-0.5 rounded border ${
                                  v.stock_quantity <= 0
                                    ? 'border-red-500/20 text-red-400 bg-red-500/5'
                                    : 'border-border text-muted-foreground'
                                }`}
                              >
                                {variationLabel(v)} ({v.stock_quantity})
                              </span>
                            ))}
                            {_variations.length > 5 && (
                              <span className="text-[10px] text-muted-foreground">
                                +{_variations.length - 5} más
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </section>

          </div>
        </div>
      )}
    </div>
  )
}
