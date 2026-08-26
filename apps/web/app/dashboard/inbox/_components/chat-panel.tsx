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
 *     T7.2: entrada animada (BubbleIn/AnimatePresence del DS) SOLO para
 *     burbujas nuevas — la carga inicial, el prepend histórico (loadMore) y
 *     los dedupes de polling/realtime NO re-animan (useAnimatableMessageIds).
 *   - Footer: editor WhatsApp + toolbar formato + preview formateado.
 *
 * Props: data del hook useMessages + selectedConv + context (para nombre).
 * Callbacks: onSendMessage, onUpdateStatus, onToggleContextPanel,
 * onOpenMobileContext, onBackToList.
 */
import { useRef as _useRef } from 'react'  // unused; explicit just for clarity
import type React from 'react'
import {
  AlertCircle, Bot, Check, CheckCheck, CheckCircle2, ChevronLeft, ChevronsRight,
  Clock, FileText, Info, MessageSquare, Paperclip, Phone, Send, User,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { AnimatePresence, BubbleIn } from '@/components/ui/motion'
import { useConfirm } from '@/components/ui/confirm-dialog'
import { createClient } from '@/utils/supabase/client'
import { renderWhatsAppFormat } from '@/lib/whatsapp-format'
import { RotateCw } from 'lucide-react'
import { useState } from 'react'
import type { ConvContext, Conversation, Message } from '../_lib/types'
import { STATUS_CONFIG } from '../_lib/constants'
import { formatDateTime, formatPhone, timeAgo } from '../_lib/format'
import { wrapSelection } from '../_lib/editor'
import { useAnimatableMessageIds } from '../_hooks/use-animatable-messages'
import { ChatEditorToolbar } from './chat-editor-toolbar'
import { InboxImage } from './inbox-image'
import { isInboxMediaPath } from '../_lib/media'

void _useRef  // suppress unused

// Etiqueta es-CO por content_type de media (para el placeholder cuando falta media_url).
const MEDIA_TYPE_LABELS: Partial<Record<Message['content_type'], string>> = {
  image: 'imagen',
  audio: 'audio',
  video: 'video',
  document: 'documento',
  sticker: 'sticker',
  location: 'ubicación',
}

// 2026-07-04 (F5) — parse del content de un mensaje 'template' (HSM).
// El worker persiste content como `[TEMPLATE <nombre>] <texto legible>`
// (worker.py:1602). Extraemos el nombre para mostrarlo como etiqueta y dejamos
// el resto como cuerpo. Antes el operador veía el `[TEMPLATE ...]` crudo.
function parseTemplateContent(content: string): { name: string | null; body: string } {
  const m = content.match(/^\s*\[TEMPLATE\s+([^\]]+)\]\s*([\s\S]*)$/)
  if (m) return { name: m[1].trim(), body: m[2].trim() }
  return { name: null, body: content }
}

type Status = Conversation['status']

interface Props {
  selectedConv: Conversation | null
  context: ConvContext | null
  messages: Message[]
  /** Conversación dueña de la data en `messages` (stale paint guard, T7.2). */
  loadedConvId: string | null
  error: string | null
  hasMore: boolean
  loadingMore: boolean
  loadMore: () => void
  messagesContainerRef: React.MutableRefObject<HTMLDivElement | null>
  messagesEndRef: React.RefObject<HTMLDivElement | null>

  /** State del editor + acción enviar (vive en el padre). */
  replyText: string
  setReplyText: (v: string) => void
  replyInputRef: React.RefObject<HTMLTextAreaElement | null>
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
  loadedConvId,
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
  const confirm = useConfirm()

  // T7.2 — ids de mensajes que entran con animación (solo los NUEVOS tras la
  // carga inicial; nunca el historial, el prepend de loadMore ni los dedupes).
  const animatableIds = useAnimatableMessageIds(
    selectedConv?.id ?? null,
    loadedConvId,
    messages,
  )

  // 2026-07-04 (F2) — Cerrar conversación manual. El estado 'closed' ya existe
  // en el contrato (CONVERSATION_STATUSES) y STATUS_CONFIG.closed promete
  // "resolución manual"; faltaba la transición en UI. Confirmamos porque es un
  // cambio de estado visible (aunque reversible: si el cliente vuelve a escribir
  // el connector reabre como bot_active).
  const handleClose = async () => {
    if (!selectedConv) return
    const ok = await confirm({
      title: '¿Cerrar esta conversación?',
      description:
        'Quedará marcada como Cerrada (resuelta). El bot dejará de responder. Si el cliente vuelve a escribir, se reabrirá automáticamente como Bot activo.',
      confirmLabel: 'Cerrar conversación',
      cancelLabel: 'Cancelar',
    })
    if (ok) onUpdateStatus('closed')
  }

  // Rev. 109 founder 2026-05-29 — Rerun IA (P0-3 backlog).
  const [rerunning, setRerunning] = useState(false)
  const [rerunNotice, setRerunNotice] = useState<string | null>(null)
  // Cooldown 5s post-clic: el backend delega el throttle a la UI
  // (conversations.py:1146). Evita que N clicks rápidos disparen N corridas Gemini.
  const [rerunCooldown, setRerunCooldown] = useState(false)

  const handleRerun = async () => {
    if (!selectedConv || selectedConv.status !== 'bot_active') return
    if (rerunning || rerunCooldown) return
    setRerunning(true)
    setRerunNotice(null)
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      const token = session?.access_token
      if (!token) { setRerunNotice('Sesión expirada'); return }
      const res = await fetch(
        `/api/conversations/${selectedConv.id}/rerun`,
        {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` },
        },
      )
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setRerunNotice(data.detail || 'No se pudo re-ejecutar')
      } else {
        setRerunNotice('Rerun encolado — el bot responderá en segundos.')
        // Auto-clear notice tras 6s.
        setTimeout(() => setRerunNotice(null), 6000)
      }
    } catch {
      setRerunNotice('Error de red al re-ejecutar')
    } finally {
      setRerunning(false)
      // Cooldown 5s tras el clic para no amplificar costo LLM por spam.
      setRerunCooldown(true)
      setTimeout(() => setRerunCooldown(false), 5000)
    }
  }

  return (
    <div className={`
      flex-1 flex flex-col chat-canvas min-w-0
      ${mobileView === 'list' || mobileView === 'context' ? 'hidden sm:flex' : 'flex'}
    `}>
      {!selectedConv ? (
        <div className="flex-1 flex items-center justify-center">
          <EmptyState variant="plain" icon={MessageSquare} title="Selecciona una conversación" />
        </div>
      ) : (
        <>
          {/* Header chat */}
          <div className="px-4 py-3 border-b border-border flex items-center gap-3 bg-card/80 backdrop-blur-md">
            <button
              onClick={() => setMobileView('list')}
              aria-label="Volver a la lista de conversaciones"
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
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleRerun}
                    disabled={rerunning || rerunCooldown || messages.length === 0}
                    title={rerunCooldown
                      ? 'Espera unos segundos antes de re-ejecutar de nuevo'
                      : 'Re-procesar último mensaje del cliente — útil si el bot dio respuesta mala o si actualizaste catálogo/cupones'}
                    className="text-violet-600 border-violet-700/30 hover:bg-violet-500/10 text-xs h-8"
                  >
                    <RotateCw className={`h-3.5 w-3.5 mr-1 ${rerunning ? 'animate-spin' : ''}`} /> Rerun IA
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => onUpdateStatus('human_takeover')} disabled={takingOver}
                    className="text-amber-600 border-amber-700/30 hover:bg-amber-500/10 text-xs h-8">
                    <AlertCircle className="h-3.5 w-3.5 mr-1" /> Tomar control
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleClose} disabled={takingOver}
                    title="Marcar la conversación como resuelta y cerrarla. Se reabre si el cliente vuelve a escribir."
                    className="text-slate-700 border-slate-700/30 hover:bg-slate-500/10 text-xs h-8">
                    <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> Cerrar
                  </Button>
                </>
              )}
              {selectedConv.status === 'human_takeover' && (
                <>
                  <Button size="sm" variant="outline" onClick={() => onUpdateStatus('bot_active')} disabled={takingOver}
                    className="text-emerald-600 border-emerald-700/30 hover:bg-emerald-500/10 text-xs h-8">
                    <Bot className="h-3.5 w-3.5 mr-1" /> Volver al bot
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleClose} disabled={takingOver}
                    title="Marcar la conversación como resuelta y cerrarla. Se reabre si el cliente vuelve a escribir."
                    className="text-slate-700 border-slate-700/30 hover:bg-slate-500/10 text-xs h-8">
                    <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> Cerrar
                  </Button>
                </>
              )}
              {selectedConv.status === 'closed' && (
                <Button size="sm" variant="outline" onClick={() => onUpdateStatus('bot_active')} disabled={takingOver}
                  title="Reabrir la conversación y reactivar el bot."
                  className="text-emerald-600 border-emerald-700/30 hover:bg-emerald-500/10 text-xs h-8">
                  <Bot className="h-3.5 w-3.5 mr-1" /> Reabrir
                </Button>
              )}
              {selectedConv.status === 'opted_out' && (
                <Button size="sm" variant="outline" onClick={() => onUpdateStatus('bot_active')} disabled={takingOver}
                  className="text-emerald-600 border-emerald-700/30 hover:bg-emerald-500/10 text-xs h-8"
                  title="Reactivar bot. consent_revoked_at sigue marcado — para reactivar marketing proactivo, el cliente debe re-otorgar consent explícitamente.">
                  <Bot className="h-3.5 w-3.5 mr-1" /> Reactivar bot
                </Button>
              )}
              {/* Toggle panel contextual en desktop */}
              <button
                onClick={onToggleContextPanel}
                aria-label={contextPanelOpen ? 'Cerrar panel de cliente' : 'Abrir panel de cliente'}
                aria-pressed={contextPanelOpen}
                className="hidden lg:flex items-center justify-center h-8 w-8 rounded-lg border border-border hover:bg-accent text-muted-foreground"
                title={contextPanelOpen ? 'Cerrar panel' : 'Abrir panel de cliente'}
              >
                {contextPanelOpen ? <ChevronsRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4 rotate-180" />}
              </button>
              {/* Abrir panel contextual en mobile */}
              <button
                onClick={() => setMobileView('context')}
                aria-label="Ver panel de cliente"
                className="lg:hidden flex items-center justify-center h-8 w-8 rounded-lg border border-border hover:bg-accent text-muted-foreground"
                title="Ver panel de cliente"
              >
                <Info className="h-4 w-4" />
              </button>
            </div>
          </div>
          {statusError && (
            <div className="px-4 py-2 text-[11px] text-red-700 bg-red-500/5 border-b border-red-700/20">
              {statusError}
            </div>
          )}
          {rerunNotice && (
            <div className="px-4 py-2 text-[11px] text-violet-700 bg-violet-500/10 border-b border-violet-700/30 flex items-center gap-1">
              <RotateCw className="h-3 w-3" /> {rerunNotice}
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
              <div className="text-center text-red-700 text-sm pt-12">
                <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-70" />
                {error}
              </div>
            ) : messages.length === 0 ? (
              <EmptyState variant="plain" icon={MessageSquare} className="pt-12" title="Sin mensajes aún." />
            ) : (
              // T7.2 — AnimatePresence con initial={false}: la primera pintura
              // del árbol no anima; cada burbuja decide su entrada con `enter`
              // (solo mensajes NUEVOS). Sin `exit`: la UI no borra mensajes y
              // el cambio de conversación reemplaza la lista entera.
              <AnimatePresence initial={false}>
              {messages.map(msg => {
              const isInbound = msg.direction === 'inbound'
              return (
                <BubbleIn
                  key={msg.id}
                  enter={animatableIds.has(msg.id)}
                  className={`flex gap-2 ${isInbound ? 'justify-start' : 'justify-end'}`}
                >
                  {isInbound && (
                    <div className="h-7 w-7 rounded-full bg-muted flex items-center justify-center shrink-0 mt-1">
                      <User className="h-3.5 w-3.5 text-muted-foreground" />
                    </div>
                  )}
                  <div className={`max-w-[75%] sm:max-w-[65%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-xs border border-border/50 ${
                    isInbound
                      ? 'bg-card text-foreground rounded-tl-sm'
                      : 'bg-primary text-primary-foreground rounded-tr-sm border-transparent'
                  }`}>
                    {msg.content_type === 'template' ? (
                      // F5: mensaje de plantilla HSM (recordatorio/reengagement).
                      // Antes se veía el crudo `[TEMPLATE ...]`; ahora etiqueta + cuerpo.
                      (() => {
                        const tpl = parseTemplateContent(msg.content || '')
                        return (
                          <>
                            <div className={`mb-1.5 inline-flex items-center gap-1.5 text-[10px] font-medium rounded-md px-2 py-0.5 border ${
                              isInbound
                                ? 'border-border/60 bg-muted/40 text-muted-foreground'
                                : 'border-primary-foreground/25 bg-primary-foreground/10 text-primary-foreground/90'
                            }`}
                              title={tpl.name ? `Plantilla aprobada por Meta: ${tpl.name}` : 'Mensaje de plantilla (HSM)'}
                            >
                              <FileText className="h-3 w-3 shrink-0" />
                              Plantilla{tpl.name ? ` · ${tpl.name}` : ''}
                            </div>
                            {tpl.body && (
                              <div className="whitespace-pre-wrap wrap-break-word">
                                {renderWhatsAppFormat(tpl.body)}
                              </div>
                            )}
                          </>
                        )
                      })()
                    ) : MEDIA_TYPE_LABELS[msg.content_type] ? (
                      (() => {
                        // INBOUND (cliente): Meta da un media_id permanente → se sirve vía el proxy
                        // /api/conversations/media/{id} (el media_url de Meta es temporal + con Bearer).
                        // OUTBOUND (operador): media_url es la URL pública del bucket. `location` no
                        // tiene binario descargable → cae al placeholder.
                        const ct = msg.content_type
                        const mediaSrc = msg.media_id
                          ? `/api/conversations/media/${encodeURIComponent(msg.media_id)}`
                          : (msg.media_url || null)
                        if (mediaSrc && ct === 'image') {
                          // G8b: adjuntos privados (esquema inbox-media://) se
                          // firman al render; http(s) = legacy/catálogo directo.
                          if (isInboxMediaPath(mediaSrc)) {
                            return (
                              <InboxImage
                                mediaUrl={mediaSrc}
                                alt={msg.content || 'imagen'}
                              />
                            )
                          }
                          return (
                            <a href={mediaSrc} target="_blank" rel="noopener noreferrer" className="block mb-1.5">
                              <img
                                src={mediaSrc}
                                alt={msg.content || 'imagen'}
                                className="rounded-lg max-w-full max-h-72 object-contain border border-border/40 bg-background/30"
                                loading="lazy"
                              />
                            </a>
                          )
                        }
                        if (mediaSrc && ct === 'audio') {
                          return <audio controls src={mediaSrc} className="mb-1.5 w-full max-w-xs" />
                        }
                        if (mediaSrc && ct === 'video') {
                          return (
                            <video
                              controls
                              src={mediaSrc}
                              className="rounded-lg max-w-full max-h-72 mb-1.5 border border-border/40"
                            />
                          )
                        }
                        if (mediaSrc && (ct === 'document' || ct === 'sticker')) {
                          return (
                            <a
                              href={mediaSrc}
                              target="_blank"
                              rel="noopener noreferrer"
                              className={`mb-1.5 inline-flex items-center gap-1.5 text-[11px] rounded-md px-2 py-1 border ${
                                isInbound
                                  ? 'border-border/60 bg-muted/40 text-muted-foreground hover:bg-muted/60'
                                  : 'border-primary-foreground/20 bg-primary-foreground/10 text-primary-foreground/80'
                              }`}
                            >
                              <Paperclip className="h-3 w-3 shrink-0" />
                              Descargar {MEDIA_TYPE_LABELS[ct]}
                            </a>
                          )
                        }
                        // Sin fuente descargable (media_id/url ausente, p.ej. location o histórico).
                        return (
                          <div className={`mb-1.5 inline-flex items-center gap-1.5 text-[11px] italic rounded-md px-2 py-1 border ${
                            isInbound ? 'border-border/60 bg-muted/40 text-muted-foreground' : 'border-primary-foreground/20 bg-primary-foreground/10 text-primary-foreground/80'
                          }`}>
                            <Paperclip className="h-3 w-3 shrink-0" />
                            Adjunto de {MEDIA_TYPE_LABELS[ct]} recibido — previsualización no disponible
                          </div>
                        )
                      })()
                    ) : null}
                    {msg.content && msg.content_type !== 'template' && (
                      // div (no <p>): renderWhatsAppFormat emite bloques <ul>/<ol>,
                      // inválidos dentro de <p> → hydration error en React 19 / Next 15.
                      // 'template' ya renderiza su cuerpo arriba (etiqueta + body).
                      <div className="whitespace-pre-wrap wrap-break-word">
                        {renderWhatsAppFormat(msg.content)}
                      </div>
                    )}
                    <p className={`text-[11px] mt-1 flex items-center gap-1.5 flex-wrap ${isInbound ? 'text-muted-foreground' : 'text-primary-foreground/70'}`}>
                      {timeAgo(msg.created_at)}
                      {!isInbound && (() => {
                        // Estado de ENTREGA real (delivery receipts de Meta), no el
                        // flag interno `processed` del orquestador. Convenciones:
                        // ✓ enviado · ✓✓ entregado · ✓✓ leído · ⚠ no entregado.
                        const ds = msg.delivery_status
                        if (ds === 'failed') {
                          const err = msg.delivery_error?.[0]
                          const detail = [err?.title, err?.message].filter(Boolean).join(' — ')
                          return (
                            <span
                              className="text-[10px] bg-red-500/20 text-red-700 px-1.5 py-0.5 rounded-full inline-flex items-center gap-0.5"
                              title={detail || 'Meta no pudo entregar este mensaje'}
                            >
                              <AlertCircle className="h-3 w-3" /> No entregado
                            </span>
                          )
                        }
                        if (ds === 'read') {
                          return (
                            <span
                              className="inline-flex items-center gap-0.5"
                              title={`Leído${msg.read_at ? ` · ${formatDateTime(msg.read_at)}` : ''}`}
                            >
                              <CheckCheck className="h-3 w-3" />
                              <span className="text-[10px]">Leído</span>
                            </span>
                          )
                        }
                        if (ds === 'delivered') {
                          return (
                            <CheckCheck
                              className="h-3 w-3 opacity-90"
                              aria-label="Entregado"
                            />
                          )
                        }
                        if (ds === 'sent') {
                          return <Check className="h-3 w-3" aria-label="Enviado" />
                        }
                        // Sin receipt (histórico / mensaje sin tracking Meta):
                        // heurístico previo basado en `processed`, atenuado para
                        // distinguirlo de un estado de entrega confirmado.
                        return msg.processed
                          ? <CheckCheck className="h-3 w-3 opacity-50" aria-label="Procesado" />
                          : <Check className="h-3 w-3 opacity-50" aria-label="Pendiente" />
                      })()}
                      {!isInbound && msg.processing_status === 'failed' && (
                        <span className="text-[10px] bg-red-500/20 text-red-700 px-1.5 py-0.5 rounded-full"
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
                    <div className="h-7 w-7 rounded-full bg-primary/20 flex items-center justify-center shrink-0 mt-1">
                      <Bot className="h-3.5 w-3.5 text-primary" />
                    </div>
                  )}
                </BubbleIn>
              )
            })}
              </AnimatePresence>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Footer */}
          {selectedConv.status === 'human_takeover' ? (
            <div className="p-3 border-t border-border bg-card space-y-2">
              {sendError && <p className="text-xs text-red-700 text-center">{sendError}</p>}
              <ChatEditorToolbar
                textareaRef={replyInputRef}
                setReplyText={setReplyText}
                conversationId={selectedConv.id}
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
                  className="flex-1 resize-none rounded-xl border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-hidden focus:ring-1 focus:ring-primary disabled:opacity-50"
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
                  <div className="whitespace-pre-wrap wrap-break-word">
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
                  : selectedConv.status === 'opted_out'
                    ? <><AlertCircle className="h-3.5 w-3.5" /> Cliente pidió no ser contactado — reactiva el bot para responder</>
                    : <><span className="h-3.5 w-3.5 inline-block" /> Conversación cerrada</>}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
