'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'
import {
  MessageSquare, User, Bot, Phone, Clock, AlertCircle, Send,
  Search, X, ChevronLeft, ChevronRight, Filter, CheckCheck, Check,
  Circle, Wifi, WifiOff, Package, ShoppingBag, MapPin, Plus,
  BadgeCheck, BadgeX, Loader2, Info, ChevronsRight,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { createIdempotencyKey } from '@/lib/idempotency'

// ─── Types ────────────────────────────────────────────────────────────────────
interface Conversation {
  id: string
  customer_phone: string
  status: 'bot_active' | 'human_takeover' | 'closed'
  created_at: string
  last_interaction_at?: string
  last_message?: { content: string; direction: string; created_at: string } | null
}

interface Message {
  id: string
  direction: 'inbound' | 'outbound'
  content: string
  content_type: string
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
  address?: Record<string, unknown>
  consent_given?: boolean
  consent_revoked_at?: string | null
}

interface ConvContext {
  contact: ContactRow | null
  recent_orders: OrderRow[]
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
const STATUS_CONFIG = {
  bot_active:     { label: 'Bot activo',    color: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20', dot: 'bg-emerald-500' },
  human_takeover: { label: 'Agente humano', color: 'bg-amber-500/10 text-amber-700 border-amber-500/20',       dot: 'bg-amber-500' },
  closed:         { label: 'Cerrada',       color: 'bg-slate-500/10 text-slate-700 border-slate-500/20',       dot: 'bg-slate-500' },
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

function variationLabel(v: ProductVariation): string {
  if (v.attributes && Object.keys(v.attributes).length > 0) {
    return Object.entries(v.attributes).map(([k, val]) => `${k}: ${val}`).join(', ')
  }
  return v.sku || 'Estándar'
}

// ─── Componente Principal ─────────────────────────────────────────────────────
export default function InboxPage() {
  const supabase = createClient()
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
  const [mobileView, setMobileView] = useState<'list' | 'chat' | 'context'>('list')
  const [waConnected, setWaConnected] = useState<boolean | null>(null)

  // --- Panel contextual ---
  const [contextPanelOpen, setContextPanelOpen] = useState(true)
  const [convContext, setConvContext] = useState<ConvContext | null>(null)
  const [contextLoading, setContextLoading] = useState(false)
  const [productSearch, setProductSearch] = useState('')
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
    const { data, error } = await supabase
      .from('conversations')
      .select('id, customer_phone, status, created_at, last_interaction_at, messages(content, direction, created_at)')
      .order('last_interaction_at', { ascending: false })
      .limit(50)

    if (error) {
      setConversations([])
      setConversationsLoadError('No se pudieron cargar las conversaciones.')
      setLoading(false)
      return
    }

    setConversationsLoadError(null)
    const rows = (data as Conversation[] | null) ?? []
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

  // ── Cargar contexto del panel al cambiar conversación ─────────────────────
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
    supabase.auth.getSession().then(({ data }) => {
      const token = data.session?.access_token
      if (!token) { setContextLoading(false); return }
      fetch(`/api/conversations/${selectedId}/context`, {
        headers: { 'Authorization': `Bearer ${token}` },
        signal: controller.signal,
      })
        .then(r => r.json())
        .then(json => {
          if (!controller.signal.aborted) setConvContext(json)
        })
        .catch(e => { if (!controller.signal.aborted) console.warn('context error', e) })
        .finally(() => { if (!controller.signal.aborted) setContextLoading(false) })
    })
    return () => controller.abort()
  }, [selectedId])  // eslint-disable-line react-hooks/exhaustive-deps

  // ── Cargar mensajes ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!selectedId) return
    supabase
      .from('messages')
      .select('id, direction, content, content_type, created_at, processed, processing_status, skip_reason')
      .eq('conversation_id', selectedId)
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
        setMessages((data || []).reverse())   // revertir DESC → ASC para display cronológico
        setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  // ── Realtime — mensajes ────────────────────────────────────────────────────
  useEffect(() => {
    if (!selectedId) return
    const channel = supabase
      .channel(`messages:${selectedId}`)
      .on('postgres_changes', {
        event: 'INSERT', schema: 'public', table: 'messages',
        filter: `conversation_id=eq.${selectedId}`,
      }, (payload) => {
        setMessages(prev => [...prev, payload.new as Message])
        setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
      })
      .subscribe()
    return () => { supabase.removeChannel(channel) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  // ── Realtime — conversaciones ──────────────────────────────────────────────
  useEffect(() => {
    const channel = supabase
      .channel('conversations:all')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'conversations' }, () => {
        loadConversations()
      })
      .subscribe()
    return () => { supabase.removeChannel(channel) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadConversations])

  // ── Seleccionar conversación ───────────────────────────────────────────────
  const handleSelectConv = (id: string) => {
    setSelectedId(id)
    syncUrlParam(id)
    setMobileView('chat')
    setReplyText('')
    setSendError(null)
    setStatusError(null)
  }

  // ── Acciones — cambio de estado ────────────────────────────────────────────
  const updateStatus = async (status: Conversation['status']) => {
    if (!selectedId) return
    setTakingOver(true)
    setStatusError(null)

    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token
    if (!token) { setStatusError('Sesión expirada.'); setTakingOver(false); return }

    try {
      const doRequest = async () => {
        const ctrl = new AbortController()
        const timeout = setTimeout(() => ctrl.abort(), 45000)
        try {
          return await fetch(`/api/conversations/${selectedId}/status`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
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

  // ── Productos filtrados en contextPanel ────────────────────────────────────
  const filteredProducts = (convContext?.products ?? []).filter(p =>
    productSearch === '' ||
    p.title.toLowerCase().includes(productSearch.toLowerCase()) ||
    (p.product_variations ?? []).some(v => v.sku?.toLowerCase().includes(productSearch.toLowerCase()))
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
          </div>

          <p className="text-xs text-muted-foreground">
            {filteredConvs.length} conversacion{filteredConvs.length !== 1 ? 'es' : ''}
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
                      <span className="text-sm font-medium">{formatPhone(conv.customer_phone)}</span>
                    </div>
                    <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                      <Clock className="h-2.5 w-2.5" />
                      {timeAgo(conv.last_interaction_at ?? conv.created_at)}
                    </span>
                  </div>
                  {conv.last_message && (
                    <p className="text-[11px] text-muted-foreground ml-4 truncate">
                      {conv.last_message.direction === 'outbound' ? '→ ' : ''}
                      {conv.last_message.content}
                    </p>
                  )}
                  <div className="ml-4 mt-1">
                    <span className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border ${st.color}`}>
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
                  <div className="min-w-0">
                    <p className="font-semibold text-sm truncate">{formatPhone(selectedConv.customer_phone)}</p>
                    <span className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border ${STATUS_CONFIG[selectedConv.status].color}`}>
                      {STATUS_CONFIG[selectedConv.status].label}
                    </span>
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
            {orderSuccess && (
              <div className="px-4 py-2 text-[11px] text-emerald-600 bg-emerald-500/5 border-b border-emerald-500/20 flex items-center gap-1">
                <BadgeCheck className="h-3.5 w-3.5" /> {orderSuccess}
              </div>
            )}

            {/* Mensajes */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
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
                      <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                      <p className={`text-[11px] mt-1 flex items-center gap-1 ${isInbound ? 'text-muted-foreground' : 'text-primary-foreground/70'}`}>
                        {timeAgo(msg.created_at)}
                        {!isInbound && (
                          msg.processed
                            ? <CheckCheck className="h-3 w-3" />
                            : <Check className="h-3 w-3" />
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
                <div className="flex gap-2 items-end">
                  <textarea
                    ref={replyInputRef}
                    value={replyText}
                    onChange={e => { setReplyText(e.target.value); setSendError(null) }}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage() }
                    }}
                    placeholder="Escribe tu respuesta... (Enter para enviar)"
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
          {/* Header panel */}
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <span className="text-sm font-semibold flex items-center gap-2">
              <User className="h-4 w-4 text-primary" /> Contexto del cliente
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
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Contacto</p>
              {contextLoading ? (
                <div className="h-12 rounded-lg bg-border/30 animate-pulse" />
              ) : convContext?.contact ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                      <User className="h-4 w-4 text-primary" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">{convContext.contact.name || 'Sin nombre'}</p>
                      <p className="text-xs text-muted-foreground">{formatPhone(convContext.contact.phone)}</p>
                    </div>
                  </div>
                  {convContext.contact.address && (
                    <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                      <MapPin className="h-3 w-3" />
                      {typeof convContext.contact.address === 'object'
                        ? [
                            (convContext.contact.address as Record<string, string>)['street'],
                            (convContext.contact.address as Record<string, string>)['number'],
                            (convContext.contact.address as Record<string, string>)['city']
                          ].filter(Boolean).join(', ') || 'Dirección registrada'
                        : (convContext.contact.address as string)}
                    </p>
                  )}
                  <div className="flex items-center gap-1 mt-1">
                    {convContext.contact.consent_given ? (
                      <span className="inline-flex items-center gap-0.5 text-[10px] text-emerald-600 bg-emerald-500/10 px-1.5 py-0.5 rounded-full border border-emerald-500/20">
                        <BadgeCheck className="h-3 w-3" /> Habeas data
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

            {/* Pedidos recientes */}
            <section className="p-4 border-b border-border">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">Pedidos recientes</p>
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
                      value={productSearch}
                      onChange={e => setProductSearch(e.target.value)}
                      className="w-full pl-7 pr-2 py-1 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div className="max-h-40 overflow-y-auto space-y-1">
                    {filteredProducts.map(product =>
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
                    value={productSearch}
                    onChange={e => setProductSearch(e.target.value)}
                    className="w-full pl-7 pr-2 py-1 text-xs rounded-lg border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  {productSearch && (
                    <button onClick={() => setProductSearch('')} className="absolute right-2.5 top-1/2 -translate-y-1/2">
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
                  {productSearch ? 'Sin coincidencias' : 'No hay productos activos'}
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
