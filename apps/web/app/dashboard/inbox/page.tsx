'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { createClient } from '@/utils/supabase/client'
import {
  MessageSquare, User, Bot, Phone, Clock, AlertCircle, Send,
  Search, X, ChevronLeft, Filter, Info, CheckCheck, Check,
  Circle, Wifi,
} from 'lucide-react'
import { Button } from '@/components/ui/button'

// ─── Types ────────────────────────────────────────────────────────────────────
interface Conversation {
  id: string
  customer_phone: string
  status: 'bot_active' | 'human_takeover' | 'closed'
  created_at: string
}

interface Message {
  id: string
  direction: 'inbound' | 'outbound'
  content: string
  content_type: string
  created_at: string
  processed: boolean
}

type FilterStatus = 'all' | 'bot_active' | 'human_takeover' | 'closed'

// ─── Config ───────────────────────────────────────────────────────────────────
const STATUS_CONFIG = {
  bot_active:     { label: 'Bot activo',    color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', dot: 'bg-emerald-400' },
  human_takeover: { label: 'Agente humano', color: 'bg-amber-500/15 text-amber-400 border-amber-500/30',       dot: 'bg-amber-400' },
  closed:         { label: 'Cerrada',       color: 'bg-slate-500/15 text-slate-400 border-slate-500/30',       dot: 'bg-slate-400' },
}

const FILTER_OPTIONS: { value: FilterStatus; label: string }[] = [
  { value: 'all',            label: 'Todas' },
  { value: 'bot_active',     label: 'Bot activo' },
  { value: 'human_takeover', label: 'Agente humano' },
  { value: 'closed',         label: 'Cerradas' },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────
const formatPhone = (phone: string) => `+${phone}`
const timeAgo = (dateStr: string) => {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'ahora'
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

// ─── Componente Principal ─────────────────────────────────────────────────────
export default function InboxPage() {
  const supabase = createClient()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(true)
  const [takingOver, setTakingOver] = useState(false)
  const [replyText, setReplyText] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all')
  // mobile: 'list' | 'chat'
  const [mobileView, setMobileView] = useState<'list' | 'chat'>('list')

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const replyInputRef = useRef<HTMLTextAreaElement>(null)

  const selectedConv = conversations.find(c => c.id === selectedId) ?? null

  // ── Filtros ────────────────────────────────────────────────────────────────
  const filteredConvs = conversations.filter(c => {
    const matchesSearch = search === '' || c.customer_phone.includes(search.replace('+', ''))
    const matchesFilter = filterStatus === 'all' || c.status === filterStatus
    return matchesSearch && matchesFilter
  })

  // ── Cargar conversaciones ──────────────────────────────────────────────────
  const loadConversations = useCallback(async () => {
    const { data } = await supabase
      .from('conversations')
      .select('id, customer_phone, status, created_at')
      .order('created_at', { ascending: false })
      .limit(50)
    setConversations(data || [])
    setLoading(false)
    if (data && data.length > 0 && !selectedId) {
      setSelectedId(data[0].id)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { loadConversations() }, [loadConversations])

  // ── Cargar mensajes ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!selectedId) return
    supabase
      .from('messages')
      .select('id, direction, content, content_type, created_at, processed')
      .eq('conversation_id', selectedId)
      .order('created_at', { ascending: true })
      .limit(100)
      .then(({ data }) => {
        setMessages(data || [])
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

  // ── Acciones ───────────────────────────────────────────────────────────────
  const updateStatus = async (status: Conversation['status']) => {
    if (!selectedId) return
    setTakingOver(true)
    await supabase.from('conversations').update({ status }).eq('id', selectedId)
    setConversations(prev => prev.map(c => c.id === selectedId ? { ...c, status } : c))
    setTakingOver(false)
  }

  const handleSendMessage = async () => {
    if (!selectedId || !replyText.trim() || sending) return
    setSending(true)
    setSendError(null)
    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token
    if (!token) { setSendError('Sesión expirada.'); setSending(false); return }
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${apiUrl}/api/v1/conversations/${selectedId}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
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
    } catch {
      setSendError('Error de red.')
    } finally {
      setSending(false)
      replyInputRef.current?.focus()
    }
  }

  const handleSelectConv = (id: string) => {
    setSelectedId(id)
    setMobileView('chat')
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-[calc(100dvh-7rem)] sm:h-[calc(100vh-4rem)] overflow-hidden rounded-xl border border-border shadow-sm">

      {/* ── Panel Lista — oculto en mobile cuando hay chat seleccionado ──── */}
      <div className={`
        flex flex-col bg-card border-r border-border
        w-full sm:w-80 lg:w-72 xl:w-80
        ${mobileView === 'chat' ? 'hidden sm:flex' : 'flex'}
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
                    ? 'bg-primary/15 text-primary border-primary/40'
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

        {/* Lista */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="space-y-1 p-2">
              {[1,2,3,4].map(i => (
                <div key={i} className="h-16 rounded-lg bg-border/40 animate-pulse" />
              ))}
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
                  className={`w-full text-left p-3.5 border-b border-border/60 transition-colors hover:bg-accent/40 ${
                    isSelected ? 'bg-accent border-l-2 border-l-primary' : ''
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <div className={`h-2 w-2 rounded-full flex-shrink-0 ${st.dot}`} />
                      <span className="text-sm font-medium">{formatPhone(conv.customer_phone)}</span>
                    </div>
                    <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                      <Clock className="h-2.5 w-2.5" />
                      {timeAgo(conv.created_at)}
                    </span>
                  </div>
                  <div className="ml-4">
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
        flex-1 flex flex-col bg-background min-w-0
        ${mobileView === 'list' ? 'hidden sm:flex' : 'flex'}
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
            <div className="px-4 py-3 border-b border-border flex items-center gap-3 bg-card">
              {/* Botón volver en mobile */}
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
                    className="text-amber-500 border-amber-500/30 hover:bg-amber-500/10 text-xs h-8">
                    <AlertCircle className="h-3.5 w-3.5 mr-1" /> Tomar control
                  </Button>
                )}
                {selectedConv.status === 'human_takeover' && (
                  <Button size="sm" variant="outline" onClick={() => updateStatus('bot_active')} disabled={takingOver}
                    className="text-emerald-500 border-emerald-500/30 hover:bg-emerald-500/10 text-xs h-8">
                    <Bot className="h-3.5 w-3.5 mr-1" /> Volver al bot
                  </Button>
                )}
              </div>
            </div>

            {/* Mensajes */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {messages.length === 0 ? (
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
                    <div className={`max-w-[75%] sm:max-w-[65%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                      isInbound
                        ? 'bg-muted text-foreground rounded-tl-sm'
                        : 'bg-primary text-primary-foreground rounded-tr-sm'
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
              <div className="p-3 border-t border-border bg-card/50 space-y-2">
                {sendError && (
                  <p className="text-xs text-red-400 text-center">{sendError}</p>
                )}
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
                <p className="text-[11px] text-amber-400/70 text-center">
                  👤 Modo agente — el bot no responderá
                </p>
              </div>
            ) : (
              <div className="p-3 border-t border-border bg-card/50">
                <p className="text-xs text-muted-foreground text-center">
                  {selectedConv.status === 'bot_active'
                    ? '🤖 El bot está respondiendo automáticamente'
                    : '🔒 Conversación cerrada'}
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
