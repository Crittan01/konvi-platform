'use client'

/**
 * Panel lista de conversaciones del Inbox (sidebar izquierdo).
 *
 * Refactor 2026-05-29 paso 8/10 — extraído de inbox-manager.tsx.
 *
 * Sub-componente JSX-heavy (~240 LOC). Recibe data + setters por props,
 * NO posee state principal (vive en useConversations del padre).
 *
 * Renderiza:
 *   - Header: title + Live indicator.
 *   - Search input por teléfono.
 *   - Chips de filtros (Activas/SLA/Todas/Bot/Agente/Cerradas/Opt-out)
 *     + toggle "Ver archivadas".
 *   - Contador: "X clientes · ⏰ N en SLA breach" (clickable).
 *   - Lista agrupada por phone con expand-collapse de sesiones históricas.
 *   - Badges per row: status, agentic_state, SLA, unread dot.
 *
 * State LOCAL del componente:
 *   - expandedPhones (Set): qué clientes tienen sesiones históricas expandidas.
 */
import { useState } from 'react'
import {
  AlertCircle, Clock, MessageSquare, Search, Wifi, X,
} from 'lucide-react'
import type { Conversation, FilterStatus } from '../_lib/types'
import {
  agenticStateLabel,
  formatPhone,
  getAgenticStateBadgeColor,
  groupConvsByPhone,
  isSlaBreach,
  timeAgo,
} from '../_lib/format'
import { FILTER_OPTIONS, SLA_BREACH_HOURS, STATUS_CONFIG } from '../_lib/constants'
import { stripWhatsAppFormat } from '@/lib/whatsapp-format'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { StaggerList, StaggerItem } from '@/components/ui/motion'

interface Props {
  conversations: Conversation[]
  filteredConvs: Conversation[]
  selectedId: string | null
  onSelect: (id: string) => void
  loading: boolean
  error: string | null
  search: string
  setSearch: (v: string) => void
  filterStatus: FilterStatus
  setFilterStatus: (v: FilterStatus) => void
  showArchived: boolean
  setShowArchived: (v: boolean | ((prev: boolean) => boolean)) => void
  /** En móvil, ocultar este panel cuando se selecciona chat o contexto. */
  mobileView: 'list' | 'chat' | 'context'
  /** Paginación incremental: hay conversaciones más antiguas sin cargar. */
  hasMore: boolean
  loadingMore: boolean
  onLoadMore: () => void
}

export function ConversationList({
  conversations,
  filteredConvs,
  selectedId,
  onSelect,
  loading,
  error,
  search,
  setSearch,
  filterStatus,
  setFilterStatus,
  showArchived,
  setShowArchived,
  mobileView,
  hasMore,
  loadingMore,
  onLoadMore,
}: Props) {
  // State local: expansión de grupos por phone.
  const [expandedPhones, setExpandedPhones] = useState<Set<string>>(new Set())

  const renderConvRow = (
    conv: Conversation,
    opts: { isHistorical?: boolean } = {},
  ) => {
    const st = STATUS_CONFIG[conv.status]
    const isSelected = conv.id === selectedId
    const hasUnread = !!(
      conv.last_message &&
      conv.last_message.direction === 'inbound' &&
      (!conv.last_read_at || conv.last_message.created_at > conv.last_read_at) &&
      !isSelected
    )
    return (
      <button
        onClick={() => onSelect(conv.id)}
        className={`w-full text-left p-3.5 border-b border-border transition-colors hover:bg-secondary/50 ${
          isSelected ? 'bg-secondary border-l-2 border-l-primary' : ''
        } ${opts.isHistorical ? 'pl-8 bg-secondary/20' : ''}`}
      >
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full shrink-0 ${st.dot}`} />
            <span
              className={`text-sm ${hasUnread ? 'font-bold text-foreground' : 'font-medium'} ${opts.isHistorical ? 'text-muted-foreground' : ''} truncate max-w-44`}
              title={conv.contact_name ? `${conv.contact_name} · ${formatPhone(conv.customer_phone)}` : formatPhone(conv.customer_phone)}
            >
              {opts.isHistorical
                ? `Sesión ${timeAgo(conv.last_interaction_at ?? conv.created_at)} atrás`
                // F2: nombre denormalizado (Meta profile.name) como etiqueta
                // principal; degrada al teléfono si aún no se capturó.
                : (conv.contact_name?.trim() || formatPhone(conv.customer_phone))}
            </span>
            {hasUnread && (
              <span
                className="h-2 w-2 rounded-full bg-emerald-500 shrink-0"
                role="status"
                aria-label="Mensaje sin leer"
                title="Mensaje sin leer"
              />
            )}
          </div>
          {!opts.isHistorical && (
            <span className="text-[11px] text-muted-foreground flex items-center gap-1">
              <Clock className="h-2.5 w-2.5" />
              {timeAgo(conv.last_interaction_at ?? conv.created_at)}
            </span>
          )}
        </div>
        {conv.last_message && (
          <p className="text-[11px] text-muted-foreground ml-4 truncate">
            {conv.last_message.direction === 'outbound' ? '→ ' : ''}
            {stripWhatsAppFormat(conv.last_message.content)}
          </p>
        )}
        <div className="ml-4 mt-1 flex items-center gap-1.5 flex-wrap">
          <span
            className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border cursor-help ${st.color}`}
            title={st.description}
          >
            {st.label}
          </span>
          {conv.agentic_state && (
            <span
              className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border ${getAgenticStateBadgeColor(conv.agentic_state)}`}
              title={`Estado del bot: ${conv.agentic_state}`}
            >
              {agenticStateLabel(conv.agentic_state)}
            </span>
          )}
          {isSlaBreach(conv) && (
            <span
              className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border border-red-700 bg-red-700/10 text-red-700 font-semibold"
              title={`Sin respuesta humana hace ≥${SLA_BREACH_HOURS}h — atender ya`}
            >
              ⏰ SLA
            </span>
          )}
        </div>
      </button>
    )
  }

  const toggleExpand = (phone: string) => {
    setExpandedPhones(prev => {
      const next = new Set(prev)
      if (next.has(phone)) next.delete(phone)
      else next.add(phone)
      return next
    })
  }

  return (
    <div className={`
      flex flex-col bg-card border-r border-border
      w-full sm:w-80 lg:w-72 xl:w-80 shrink-0
      ${mobileView === 'chat' || mobileView === 'context' ? 'hidden sm:flex' : 'flex'}
    `}>
      {/* Header lista */}
      <div className="p-4 border-b border-border space-y-3">
        <div className="flex items-center justify-between">
          <h1 className="font-semibold text-base flex items-center gap-2">
            {/* Mini-tile de marca (firma Kaiu a escala inbox, T7.12): el h1 vive
                en el panel angosto (w-80) y el PageHeader completo no cabe —
                excepción documentada en UX-UI §5. Mismo degradado del tile DS. */}
            <span
              aria-hidden
              className="h-7 w-7 shrink-0 rounded-lg bg-gradient-to-br from-primary to-[hsl(var(--amber))] flex items-center justify-center shadow-sm glow-primary ring-1 ring-white/15"
            >
              <MessageSquare className="h-3.5 w-3.5 text-white" />
            </span>
            Inbox AI
          </h1>
          <div className="flex items-center gap-1 text-xs text-emerald-700">
            <Wifi className="h-3 w-3" />
            <span>Live</span>
          </div>
        </div>

        {/* Búsqueda */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Buscar por nombre o teléfono..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-border bg-background placeholder:text-muted-foreground focus:outline-hidden focus:ring-1 focus:ring-primary"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              aria-label="Limpiar búsqueda"
              className="absolute right-2.5 top-1/2 -translate-y-1/2"
            >
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
          {/* BLOQUE G-1 (review fix): chip limpiable para filtros de deep-link
              (OpsCards del dashboard: bot_active / human_takeover) que NO están en
              FILTER_OPTIONS. Sin esto la lista se filtra pero ningún chip se resalta
              → parece rota, sin forma de ver/limpiar el filtro. Reset → 'active'. */}
          {!FILTER_OPTIONS.some(o => o.value === filterStatus) &&
           STATUS_CONFIG[filterStatus as keyof typeof STATUS_CONFIG] && (
            <button
              onClick={() => setFilterStatus('active')}
              title="Quitar filtro"
              className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border border-amber-700/30 bg-amber-500/10 text-amber-700 font-medium hover:bg-amber-500/15 transition-colors"
            >
              {STATUS_CONFIG[filterStatus as keyof typeof STATUS_CONFIG].label}
              <X className="h-2.5 w-2.5" />
            </button>
          )}
          <button
            onClick={() => setShowArchived(v => !v)}
            className={`text-[11px] px-2 py-0.5 rounded-full border transition-colors ${
              showArchived
                ? 'bg-slate-200 text-slate-700 border-slate-700 font-medium'
                : 'border-border text-muted-foreground hover:text-foreground'
            }`}
            title="Mostrar conversaciones archivadas (cerradas con >90 días sin actividad)"
          >
            {showArchived ? 'Ocultar archivadas' : 'Ver archivadas'}
          </button>
        </div>

        {(() => {
          const groupCount = groupConvsByPhone(filteredConvs).length
          const breachCount = conversations.filter(isSlaBreach).length
          return (
            <p className="text-xs text-muted-foreground">
              {groupCount} cliente{groupCount !== 1 ? 's' : ''}
              {filteredConvs.length !== groupCount && (
                <span className="ml-1 opacity-70">
                  ({filteredConvs.length} conv{filteredConvs.length !== 1 ? 's' : ''})
                </span>
              )}
              {showArchived && ' · incl. archivadas'}
              {breachCount > 0 && filterStatus !== 'sla_breach' && (
                <button
                  type="button"
                  onClick={() => setFilterStatus('sla_breach')}
                  className="ml-2 inline-flex items-center text-[10px] font-semibold text-red-700 hover:underline"
                  title="Ver convs sin respuesta humana en SLA"
                >
                  · ⏰ {breachCount} en SLA breach
                </button>
              )}
            </p>
          )
        })()}
      </div>

      {/* Lista conversaciones */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="space-y-1 p-2">
            {[1, 2, 3, 4].map(i => (
              <Skeleton key={i} className="h-16 rounded-lg bg-border/40" />
            ))}
          </div>
        ) : error ? (
          <div className="p-8 text-center text-red-700 text-sm">
            <AlertCircle className="h-10 w-10 mx-auto mb-3 opacity-70" />
            <p>{error}</p>
          </div>
        ) : filteredConvs.length === 0 ? (
          <EmptyState
            variant="plain"
            icon={MessageSquare}
            className="p-8 text-sm"
            title={search ? undefined : 'Aún no hay conversaciones'}
            description={
              search ? (
                <>Sin resultados para &ldquo;{search}&rdquo;.</>
              ) : (
                <span className="text-xs leading-relaxed">
                  Cuando un cliente le escriba a tu WhatsApp aparecerá aquí automáticamente.
                  Verifica que tu número esté conectado en{' '}
                  <a href="/dashboard/integrations" className="text-primary hover:underline">
                    Configuración → Integraciones
                  </a>.
                </span>
              )
            }
          />
        ) : (
          (() => {
            const groups = groupConvsByPhone(filteredConvs)
            const listRows = groups.flatMap(group => {
              const isExpanded = expandedPhones.has(group.phone)
              const rows: React.ReactElement[] = []

              rows.push(
                <div key={`${group.phone}-primary`} className="relative">
                  {renderConvRow(group.primary)}
                  {group.others.length > 0 && (
                    <button
                      onClick={(e) => { e.stopPropagation(); toggleExpand(group.phone) }}
                      className="absolute top-3 right-12 inline-flex items-center gap-1 h-5 px-2 text-[10px] font-semibold rounded-full border border-border bg-background hover:bg-muted/40 transition-colors"
                      title={isExpanded ? 'Ocultar sesiones históricas' : 'Ver sesiones históricas del cliente'}
                    >
                      {isExpanded ? '▾' : '▸'} +{group.others.length}
                    </button>
                  )}
                </div>,
              )

              if (isExpanded && group.others.length > 0) {
                for (const other of group.others) {
                  rows.push(
                    <div key={other.id}>
                      {renderConvRow(other, { isHistorical: true })}
                    </div>,
                  )
                }
              }

              return rows
            })
            // "Ver más" — carga incremental de conversaciones más antiguas
            // (la búsqueda filtra solo lo cargado; cargar más amplía el alcance).
            if (hasMore && !search) {
              listRows.push(
                <div key="__load_more" className="p-3">
                  <button
                    type="button"
                    onClick={onLoadMore}
                    disabled={loadingMore}
                    className="w-full text-[11px] font-medium py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors disabled:opacity-60"
                  >
                    {loadingMore ? 'Cargando…' : 'Ver conversaciones más antiguas'}
                  </button>
                </div>,
              )
            }
            // Spec WOW §4.2: entrada escalonada sutil (stagger 25ms) SOLO en los
            // primeros 6 ítems (sin cascada infinita). Las keys estables
            // (phone / conv.id) hacen que los refetches de realtime/polling NO
            // re-animen; una conversación nueva entra con la animación una vez.
            return (
              <StaggerList stagger={0.025}>
                {listRows.slice(0, 6).map((row, i) => (
                  <StaggerItem key={row.key ?? i}>{row}</StaggerItem>
                ))}
                {listRows.slice(6)}
              </StaggerList>
            )
          })()
        )}
      </div>
    </div>
  )
}
