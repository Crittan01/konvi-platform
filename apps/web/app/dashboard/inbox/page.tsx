'use client'

import { useEffect, useRef, useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import { MessageSquare, User, Bot, Phone, Clock, AlertCircle, Send } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

// ─── Types ────────────────────────────────────────────────────────────────────
interface Conversation {
  id: string
  customer_phone: string
  status: 'bot_active' | 'human_takeover' | 'closed'
  created_at: string
  messages?: Message[]
}

interface Message {
  id: string
  direction: 'inbound' | 'outbound'
  content: string
  content_type: string
  created_at: string
  processed: boolean
}

const STATUS_CONFIG = {
  bot_active: { label: 'Bot activo', color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
  human_takeover: { label: 'Agente humano', color: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  closed: { label: 'Cerrada', color: 'bg-slate-500/15 text-slate-400 border-slate-500/30' },
}

function formatPhone(phone: string) {
  return `+${phone}`
}

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'ahora'
  if (mins < 60) return `hace ${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `hace ${hrs}h`
  return `hace ${Math.floor(hrs / 24)}d`
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
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const replyInputRef = useRef<HTMLTextAreaElement>(null)

  const selectedConv = conversations.find(c => c.id === selectedId)

  // ── Cargar conversaciones del tenant (via RLS — solo ve las suyas) ──────────
  useEffect(() => {
    const load = async () => {
      const { data } = await supabase
        .from('conversations')
        .select('id, customer_phone, status, created_at')
        .order('created_at', { ascending: false })
        .limit(50)

      setConversations(data || [])
      setLoading(false)

      // Seleccionar la primera por defecto
      if (data && data.length > 0 && !selectedId) {
        setSelectedId(data[0].id)
      }
    }
    load()
  }, [])

  // ── Cargar mensajes de la conversación seleccionada ────────────────────────
  useEffect(() => {
    if (!selectedId) return

    const loadMessages = async () => {
      const { data } = await supabase
        .from('messages')
        .select('id, direction, content, content_type, created_at, processed')
        .eq('conversation_id', selectedId)
        .order('created_at', { ascending: true })
        .limit(100)

      setMessages(data || [])
      setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
    }
    loadMessages()
  }, [selectedId])

  // ── Realtime — nuevos mensajes en la conversación activa ───────────────────
  useEffect(() => {
    if (!selectedId) return

    const channel = supabase
      .channel(`messages:${selectedId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'messages',
          filter: `conversation_id=eq.${selectedId}`,
        },
        (payload) => {
          setMessages(prev => [...prev, payload.new as Message])
          setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
        }
      )
      .subscribe()

    return () => { supabase.removeChannel(channel) }
  }, [selectedId])

  // ── Realtime — cambios en conversaciones (nuevo estado, nuevo chat) ─────────
  useEffect(() => {
    const channel = supabase
      .channel('conversations:all')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'conversations' },
        () => {
          // Recargar lista de conversaciones
          supabase
            .from('conversations')
            .select('id, customer_phone, status, created_at')
            .order('created_at', { ascending: false })
            .limit(50)
            .then(({ data }) => setConversations(data || []))
        }
      )
      .subscribe()

    return () => { supabase.removeChannel(channel) }
  }, [])

  // ── Tomar control humano ────────────────────────────────────────────────────
  const handleTakeover = async () => {
    if (!selectedId) return
    setTakingOver(true)
    await supabase
      .from('conversations')
      .update({ status: 'human_takeover' })
      .eq('id', selectedId)

    setConversations(prev =>
      prev.map(c => c.id === selectedId ? { ...c, status: 'human_takeover' } : c)
    )
    setTakingOver(false)
  }

  // ── Devolver al bot ─────────────────────────────────────────────────────────
  const handleReturnToBot = async () => {
    if (!selectedId) return
    setTakingOver(true)
    await supabase
      .from('conversations')
      .update({ status: 'bot_active' })
      .eq('id', selectedId)

    setConversations(prev =>
      prev.map(c => c.id === selectedId ? { ...c, status: 'bot_active' } : c)
    )
    setTakingOver(false)
  }

  // ── Enviar mensaje como agente humano ──────────────────────────────────────
  const handleSendMessage = async () => {
    if (!selectedId || !replyText.trim() || sending) return
    setSending(true)
    setSendError(null)

    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token

    if (!token) {
      setSendError('Sesión expirada. Recarga la página.')
      setSending(false)
      return
    }

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

    try {
      const res = await fetch(`${apiUrl}/api/v1/conversations/${selectedId}/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ text: replyText.trim() }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Error desconocido' }))
        setSendError(err.detail || 'No se pudo enviar el mensaje')
      } else {
        setReplyText('')
        // El nuevo mensaje llegará vía Realtime — no necesitamos añadirlo manualmente
      }
    } catch {
      setSendError('Error de red. Verifica la conexión.')
    } finally {
      setSending(false)
      replyInputRef.current?.focus()
    }
  }

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-[calc(100vh-4rem)] gap-0 overflow-hidden rounded-lg border border-border">

      {/* Panel izquierdo — Lista de conversaciones */}
      <div className="w-80 flex-shrink-0 border-r border-border bg-card flex flex-col">
        <div className="p-4 border-b border-border">
          <h1 className="font-semibold text-lg flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-primary" />
            Inbox AI
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            {conversations.length} conversaciones
          </p>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-4 text-center text-muted-foreground text-sm">Cargando...</div>
          ) : conversations.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground text-sm">
              <MessageSquare className="h-10 w-10 mx-auto mb-3 opacity-30" />
              <p>No hay conversaciones aún.</p>
              <p className="text-xs mt-1">Los mensajes de WhatsApp aparecerán aquí.</p>
            </div>
          ) : (
            conversations.map(conv => {
              const st = STATUS_CONFIG[conv.status]
              const isSelected = conv.id === selectedId
              return (
                <button
                  key={conv.id}
                  onClick={() => setSelectedId(conv.id)}
                  className={`w-full text-left p-4 border-b border-border transition-colors hover:bg-accent/50 ${
                    isSelected ? 'bg-accent' : ''
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <Phone className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="text-sm font-medium">{formatPhone(conv.customer_phone)}</span>
                    </div>
                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {timeAgo(conv.created_at)}
                    </span>
                  </div>
                  <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded-full border ${st.color}`}>
                    {st.label}
                  </span>
                </button>
              )
            })
          )}
        </div>
      </div>

      {/* Panel derecho — Hilo de mensajes */}
      <div className="flex-1 flex flex-col bg-background">
        {!selectedConv ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <div className="text-center">
              <MessageSquare className="h-12 w-12 mx-auto mb-3 opacity-20" />
              <p>Selecciona una conversación</p>
            </div>
          </div>
        ) : (
          <>
            {/* Header de la conversación */}
            <div className="p-4 border-b border-border flex items-center justify-between bg-card">
              <div>
                <p className="font-semibold">{formatPhone(selectedConv.customer_phone)}</p>
                <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded-full border ${STATUS_CONFIG[selectedConv.status].color}`}>
                  {STATUS_CONFIG[selectedConv.status].label}
                </span>
              </div>
              <div className="flex gap-2">
                {selectedConv.status === 'bot_active' && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleTakeover}
                    disabled={takingOver}
                    className="text-amber-500 border-amber-500/30 hover:bg-amber-500/10"
                  >
                    <AlertCircle className="h-4 w-4 mr-1" />
                    Tomar control
                  </Button>
                )}
                {selectedConv.status === 'human_takeover' && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleReturnToBot}
                    disabled={takingOver}
                    className="text-emerald-500 border-emerald-500/30 hover:bg-emerald-500/10"
                  >
                    <Bot className="h-4 w-4 mr-1" />
                    Volver al bot
                  </Button>
                )}
              </div>
            </div>

            {/* Mensajes */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {messages.length === 0 ? (
                <div className="text-center text-muted-foreground text-sm pt-8">
                  Sin mensajes en esta conversación.
                </div>
              ) : (
                messages.map(msg => {
                  const isInbound = msg.direction === 'inbound'
                  return (
                    <div
                      key={msg.id}
                      className={`flex gap-2 ${isInbound ? 'justify-start' : 'justify-end'}`}
                    >
                      {isInbound && (
                        <div className="h-7 w-7 rounded-full bg-muted flex items-center justify-center flex-shrink-0 mt-1">
                          <User className="h-3.5 w-3.5 text-muted-foreground" />
                        </div>
                      )}
                      <div
                        className={`max-w-[70%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                          isInbound
                            ? 'bg-muted text-foreground rounded-tl-sm'
                            : 'bg-primary text-primary-foreground rounded-tr-sm'
                        }`}
                      >
                        <p>{msg.content}</p>
                        <p className={`text-xs mt-1 ${isInbound ? 'text-muted-foreground' : 'text-primary-foreground/70'}`}>
                          {timeAgo(msg.created_at)}
                          {!isInbound && (
                            <span className="ml-1">
                              {msg.processed ? '✓✓' : '✓'}
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
                })
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Footer — input de respuesta (takeover) o info (bot/cerrada) */}
            {selectedConv.status === 'human_takeover' ? (
              <div className="p-3 border-t border-border bg-card/50 space-y-2">
                {sendError && (
                  <p className="text-xs text-red-400 text-center">{sendError}</p>
                )}
                <div className="flex gap-2 items-end">
                  <textarea
                    ref={replyInputRef}
                    value={replyText}
                    onChange={e => {
                      setReplyText(e.target.value)
                      setSendError(null)
                    }}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        handleSendMessage()
                      }
                    }}
                    placeholder="Escribe tu respuesta... (Enter para enviar, Shift+Enter para salto de línea)"
                    disabled={sending}
                    rows={2}
                    className="flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                  />
                  <Button
                    size="sm"
                    onClick={handleSendMessage}
                    disabled={sending || !replyText.trim()}
                    className="h-10 px-3 bg-primary hover:bg-primary/90 text-primary-foreground"
                  >
                    {sending ? (
                      <span className="text-xs">Enviando...</span>
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                  </Button>
                </div>
                <p className="text-xs text-amber-400/70 text-center">
                  👤 Modo agente — el bot no responderá mientras tengas el control
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
