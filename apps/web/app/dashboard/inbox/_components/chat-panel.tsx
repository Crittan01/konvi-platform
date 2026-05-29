'use client'

/**
 * Panel central del Inbox: header conversación + historial mensajes + editor.
 *
 * Refactor 2026-05-29 paso 10/10 — última pieza del refactor. Cierra
 * el ciclo: inbox-manager queda como orquestador puro (~250 LOC) que
 * conecta hooks + 3 paneles + handlers.
 *
 * Sub-secciones:
 *   - Empty state si no hay conversación seleccionada.
 *   - Header: nombre/phone + status badge + SLA timer (último inbound).
 *   - Botones de cambio de status (Tomar control / Volver al bot / Reactivar bot).
 *   - Toggle panel contextual (desktop) + open mobile.
 *   - Banner 24h Meta (ventana CSW) cuando status='human_takeover'.
 *   - Mensajes con dedupe + scroll histórico cursor + R-13 filter aplicado.
 *   - Footer: editor WhatsApp + toolbar formato + preview formateado.
 *
 * Props: data del hook useMessages + selectedConv + context (para nombre).
 * Callbacks: onSendMessage, onUpdateStatus, onToggleContextPanel,
 * onOpenMobileContext, onBackToList.
 */
import { useRef as _useRef } from 'react'  // unused; explicit just for clarity
import type React from 'react'
import {
  AlertCircle, Bot, Check, CheckCheck, ChevronLeft, ChevronsRight,
  Circle, Clock, Info, MessageSquare, Phone, Send, User,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { renderWhatsAppFormat } from '@/lib/whatsapp-format'
import type { ConvContext, Conversation, Message } from '../_lib/types'
import { STATUS_CONFIG } from '../_lib/constants'
import { formatDateTime, formatPhone, timeAgo } from '../_lib/format'
import { wrapSelection } from '../_lib/editor'
import { ChatEditorToolbar } from './chat-editor-toolbar'

void _useRef  // suppress unused

type Status = Conversation['status']

interface Props {
  selectedConv: Conversation | null
  context: ConvContext | null
  messages: Message[]
  error: string | null
  hasMore: boolean
  loadingMore: boolean
  loadMore: () => void
  messagesContainerRef: React.MutableRefObject<HTMLDivElement | null>
  messagesEndRef: React.RefObject<HTMLDivElement>

  /** State del editor + acción enviar (vive en el padre). */
  replyText: string
  setReplyText: (v: string) => void
  replyInputRef: React.RefObject<HTMLTextAreaElement>
  sending: boolean
  sendError: string | null
  onSendMessage: () => void

  /** Status flow (Tomar control / Volver al bot). */
  takingOver: boolean
  statusError: string | null
  onUpdateStatus: (newStatus: Status) => void

  /** UI controls. */
  mobileView: 'list' | 'chat' | 'context'
  setMobileView: (v: 'list' | 'chat' | 'context') => void
  contextPanelOpen: boolean
  onToggleContextPanel: () => void
}

export function ChatPanel({
  selectedConv,
  context,
  messages,
  error,
  hasMore,
  loadingMore,
  loadMore,
  messagesContainerRef,
  messagesEndRef,
  replyText,
  setReplyText,
  replyInputRef,
  sending,
  sendError,
  onSendMessage,
  takingOver,
  statusError,
  onUpdateStatus,
  mobileView,
  setMobileView,
  contextPanelOpen,
  onToggleContextPanel,
}: Props) {
  return (
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
                    {context?.contact?.name || formatPhone(selectedConv.customer_phone)}
                  </p>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border cursor-help ${STATUS_CONFIG[selectedConv.status].color}`}
                      title={STATUS_CONFIG[selectedConv.status].description}
                    >
                      {STATUS_CONFIG[selectedConv.status].label}
                    </span>
                    {/* Rev. 103 — SLA timer: hace cuánto fue el último inbound. */}
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
                <Button size="sm" variant="outline" onClick={() => onUpdateStatus('human_takeover')} disabled={takingOver}
                  className="text-amber-600 border-amber-500/30 hover:bg-amber-500/10 text-xs h-8">
                  <AlertCircle className="h-3.5 w-3.5 mr-1" /> Tomar control
                </Button>
              )}
              {selectedConv.status === 'human_takeover' && (
                <Button size="sm" variant="outline" onClick={() => onUpdateStatus('bot_active')} disabled={takingOver}
                  className="text-emerald-600 border-emerald-500/30 hover:bg-emerald-500/10 text-xs h-8">
                  <Bot className="h-3.5 w-3.5 mr-1" /> Volver al bot
                </Button>
              )}
              {selectedConv.status === 'opted_out' && (
                <Button size="sm" variant="outline" onClick={() => onUpdateStatus('bot_active')} disabled={takingOver}
                  className="text-emerald-600 border-emerald-500/30 hover:bg-emerald-500/10 text-xs h-8"
                  title="Reactivar bot. consent_revoked_at sigue marcado — para reactivar marketing proactivo, el cliente debe re-otorgar consent explícitamente.">
                  <Bot className="h-3.5 w-3.5 mr-1" /> Reactivar bot
                </Button>
              )}
              {/* Toggle panel contextual en desktop */}
              <button
                onClick={onToggleContextPanel}
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
          {/* Banner Meta ventana 24h */}
          {selectedConv.status === 'human_takeover' && (() => {
            const lastInbound = [...messages].reverse().find(m => m.direction === 'inbound')
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

          {/* Mensajes */}
          <div
            ref={messagesContainerRef}
            onScroll={(e) => {
              const t = e.currentTarget
              if (t.scrollTop < 80 && hasMore && !loadingMore) {
                loadMore()
              }
            }}
            className="flex-1 overflow-y-auto p-4 space-y-3"
          >
            {loadingMore && (
              <div className="text-center text-[11px] text-muted-foreground py-2">
                Cargando mensajes anteriores...
              </div>
            )}
            {!hasMore && messages.length >= 100 && (
              <div className="text-center text-[10px] text-muted-foreground py-1">
                Inicio de la conversación
              </div>
            )}
            {error ? (
              <div className="text-center text-red-400 text-sm pt-12">
                <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-70" />
                {error}
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
              <ChatEditorToolbar
                textareaRef={replyInputRef}
                setReplyText={setReplyText}
              />
              <div className="flex gap-2 items-end">
                <textarea
                  ref={replyInputRef}
                  value={replyText}
                  onChange={e => setReplyText(e.target.value)}
                  onKeyDown={e => {
                    if ((e.ctrlKey || e.metaKey) && !e.shiftKey) {
                      const k = e.key.toLowerCase()
                      if (k === 'b') { e.preventDefault(); wrapSelection(replyInputRef, setReplyText, '*'); return }
                      if (k === 'i') { e.preventDefault(); wrapSelection(replyInputRef, setReplyText, '_'); return }
                      if (k === 'e') { e.preventDefault(); wrapSelection(replyInputRef, setReplyText, '`'); return }
                    }
                    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSendMessage() }
                  }}
                  placeholder="Escribe tu respuesta...  (Enter envía · Shift+Enter salto de línea · Ctrl+B negrita · Ctrl+I cursiva · Ctrl+E código)"
                  disabled={sending}
                  rows={2}
                  className="flex-1 resize-none rounded-xl border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                />
                <Button
                  size="sm"
                  onClick={onSendMessage}
                  disabled={sending || !replyText.trim()}
                  className="h-10 px-3 bg-primary hover:bg-primary/90 shrink-0"
                >
                  {sending ? <span className="text-xs animate-pulse">…</span> : <Send className="h-4 w-4" />}
                </Button>
              </div>
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
  )
}
