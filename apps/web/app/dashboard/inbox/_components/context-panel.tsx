'use client'

/**
 * Panel contextual derecho del Inbox.
 *
 * Refactor 2026-05-29 paso 6/10 — extraído de inbox-manager.tsx.
 *
 * Muestra (en orden vertical):
 *   1. Contacto: nombre, phone, email, doc, address, consent badges.
 *   2. Carrito activo (cart-as-SoT, espejo en vivo del bot).
 *   3. Reclamos abiertos (rev. 103, espejo system prompt).
 *   4. Pedidos recientes (B2 paginación 3 + Ver más).
 *   5. Mini-form crear pedido (encapsulado en <OrderMiniForm/>).
 *   6. Catálogo informativo (búsqueda + grid con stock badges + variantes).
 *
 * Auto-refresh + state del contexto vive en <InboxManager/> via
 * useConversationContext. Este componente sólo CONSUME.
 *
 * State local únicamente:
 *   - showAllOrders (B2 paginación)
 *   - productSearch (filtro local del catálogo informativo)
 */
import { useState } from 'react'
import {
  AlertCircle, BadgeCheck, BadgeX, ChevronsRight, FileText,
  Loader2, Mail, MapPin, Search, ShoppingCart, Truck, User, X,
} from 'lucide-react'
import type { ConvContext, Conversation } from '../_lib/types'
import {
  formatDate, formatMoney, formatPhone, timeAgo, variationLabel,
} from '../_lib/format'
import { ORDER_STATUS_COLOR, ORDER_STATUS_LABEL } from '../_lib/constants'
import { OrderMiniForm } from './order-mini-form'

interface Props {
  conversation: Conversation
  context: ConvContext | null
  loading: boolean
  refreshing: boolean
  /** Para móvil — cerrar vuelve al panel central chat. */
  onCloseMobile: () => void
  /** Callback tras crear pedido — refrescar el contexto. */
  onOrderCreated: () => void
  /** Visible en desktop según toggle del padre. */
  isOpen: boolean
  /** En móvil, sólo visible si mobileView==='context'. */
  isMobileActive: boolean
}

export function ContextPanel({
  conversation,
  context,
  loading,
  refreshing,
  onCloseMobile,
  onOrderCreated,
  isOpen,
  isMobileActive,
}: Props) {
  const [showAllOrders, setShowAllOrders] = useState(false)
  const [productSearch, setProductSearch] = useState('')

  const filteredProducts = (context?.products ?? []).filter(p =>
    productSearch === '' ||
    p.title.toLowerCase().includes(productSearch.toLowerCase()) ||
    (p.product_variations ?? []).some(v => v.sku?.toLowerCase().includes(productSearch.toLowerCase())),
  )

  return (
    <div className={`
      flex flex-col bg-muted/30 border-l border-border
      w-full lg:w-80 xl:w-96 shrink-0 overflow-hidden
      ${isMobileActive ? 'flex' : 'hidden lg:flex'}
      ${isOpen ? 'lg:flex' : 'lg:hidden'}
    `}>
      {/* Header panel — Rev. 103: indicador silencioso de auto-refresh */}
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <span className="text-sm font-semibold flex items-center gap-2">
          <User className="h-4 w-4 text-primary" /> Contexto del cliente
          {refreshing && (
            <Loader2 className="h-3 w-3 text-muted-foreground animate-spin" aria-label="Sincronizando" />
          )}
        </span>
        <button
          onClick={onCloseMobile}
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
            {context?.contact?.id && (
              <a
                href={`/dashboard/contacts?id=${context.contact.id}`}
                target="_blank"
                rel="noopener noreferrer"
                title="Abrir perfil completo del cliente en nueva pestaña"
                className="text-[10px] text-primary hover:underline inline-flex items-center gap-0.5"
              >
                Ver perfil <ChevronsRight className="h-3 w-3" />
              </a>
            )}
          </div>
          {loading ? (
            <div className="h-12 rounded-lg bg-border/30 animate-pulse" />
          ) : context?.contact ? (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <div className="h-9 w-9 rounded-full bg-primary/10 flex items-center justify-center">
                  <User className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <p className="text-sm font-semibold">{context.contact.name || 'Sin nombre'}</p>
                  <p className="text-xs text-muted-foreground">{formatPhone(context.contact.phone)}</p>
                </div>
              </div>
              {context.contact.email && (
                <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                  <Mail className="h-3 w-3 shrink-0" />
                  <span className="truncate">{context.contact.email}</span>
                </p>
              )}
              {context.contact.document_type && context.contact.document_number && (
                <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                  <FileText className="h-3 w-3 shrink-0" />
                  {context.contact.document_type} {context.contact.document_number}
                </p>
              )}
              {context.contact.shipping_phone &&
               context.contact.shipping_phone !== context.contact.phone &&
               context.contact.shipping_phone.replace(/\+/g, '') !==
               context.contact.phone.replace(/\+/g, '') && (
                <p
                  className="text-xs text-amber-700 flex items-center gap-1.5"
                  title="Celular alternativo de envío. La transportadora contactará a este número (no el WhatsApp)."
                >
                  <Truck className="h-3 w-3 shrink-0" />
                  Envío: {formatPhone(context.contact.shipping_phone)}
                </p>
              )}
              {/* Rev. 103 — Address multilinea con jerarquía visual */}
              {context.contact.address && typeof context.contact.address === 'object' && (() => {
                const addr = context.contact.address as Record<string, string>
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
              {context.contact.address && typeof context.contact.address !== 'object' && (
                <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                  <MapPin className="h-3 w-3 shrink-0" />
                  {context.contact.address as string}
                </p>
              )}
              <div className="flex items-center gap-1 mt-1">
                {context.contact.consent_given ? (
                  <span className="inline-flex items-center gap-0.5 text-[10px] text-emerald-700 bg-emerald-700/10 px-1.5 py-0.5 rounded-full border border-emerald-700/30">
                    <BadgeCheck className="h-3 w-3" /> Habeas data
                  </span>
                ) : context.contact.consent_revoked_at ? (
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
              {loading ? '' : 'Cliente no registrado en Contactos.'}
            </p>
          )}
        </section>

        {/* Carrito ACTIVO (cart-as-SoT) — espejo bot turn-by-turn */}
        {context?.active_cart && context.active_cart.items.length > 0 && (
          <section className={`p-4 border-b border-border ${
            context.active_cart.requires_requote
              ? 'bg-amber-50/30 dark:bg-amber-950/10'
              : 'bg-emerald-50/20 dark:bg-emerald-950/5'
          }`}>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <ShoppingCart className="h-3.5 w-3.5" /> Carrito en construcción
            </p>
            <div className="space-y-1.5">
              {context.active_cart.items.map((it, idx) => (
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
                  <span>{formatMoney((context.active_cart.subtotal_cents || 0) / 100)}</span>
                </div>
                {(() => {
                  const status = context.active_cart.shipping_status || (
                    context.active_cart.shipping_cents > 0
                      ? (context.active_cart.requires_requote ? 'stale' : 'active')
                      : 'pending'
                  )
                  const cents = context.active_cart.shipping_cents || 0
                  const carrier = context.active_cart.carrier_name || ''
                  const cls =
                    status === 'stale'
                      ? 'text-amber-700'
                      : status === 'pending'
                        ? 'text-muted-foreground italic'
                        : 'text-muted-foreground'
                  return (
                    <div className={`flex justify-between text-xs ${cls}`}>
                      <span className="flex items-center gap-1">
                        Envío{carrier && ` · ${carrier}`}
                        {status === 'stale' && (
                          <span
                            title="El carrito cambió post-cotización. El bot re-cotizará al confirmar."
                            className="text-[9px] uppercase tracking-wider px-1 py-px rounded bg-amber-100 text-amber-800 border border-amber-200"
                          >
                            recotizar
                          </span>
                        )}
                        {status === 'pending' && (
                          <span className="text-[9px] uppercase tracking-wider px-1 py-px rounded bg-border/40 text-muted-foreground">
                            pendiente
                          </span>
                        )}
                      </span>
                      <span>
                        {cents > 0 ? formatMoney(cents / 100) : '—'}
                      </span>
                    </div>
                  )
                })()}
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>
                    Descuento
                    {context.active_cart.coupon_code && (
                      <span className="ml-1 text-[9px] uppercase tracking-wider px-1 py-px rounded bg-emerald-100 text-emerald-800 border border-emerald-200">
                        {context.active_cart.coupon_code}
                      </span>
                    )}
                  </span>
                  <span className={context.active_cart.discount_cents > 0 ? 'text-emerald-700' : ''}>
                    {context.active_cart.discount_cents > 0
                      ? `-${formatMoney(context.active_cart.discount_cents / 100)}`
                      : '—'}
                  </span>
                </div>
                {context.active_cart.total_cents > 0 && (
                  <div className="flex justify-between text-sm font-semibold pt-0.5">
                    <span>Total</span>
                    <span>{formatMoney(context.active_cart.total_cents / 100)}</span>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {/* Reclamos abiertos */}
        {context?.open_claims && context.open_claims.length > 0 && (
          <section className="p-4 border-b border-border">
            <p className="text-xs font-semibold text-red-700 uppercase tracking-wider mb-2 flex items-center gap-1">
              <AlertCircle className="h-3 w-3" /> Reclamos abiertos ({context.open_claims.length})
            </p>
            <div className="space-y-1.5">
              {context.open_claims.map(claim => (
                <div key={claim.id} className="p-2 rounded-lg bg-red-50/40 border border-red-200/50">
                  <p className="text-xs font-medium">#{claim.ticket_number}</p>
                  {claim.reason && (
                    <p className="text-[11px] text-muted-foreground line-clamp-2 italic">
                      {claim.reason}
                    </p>
                  )}
                  <p className="text-[10px] text-muted-foreground mt-0.5">
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
          {loading ? (
            <div className="space-y-2">
              {[1, 2].map(i => <div key={i} className="h-10 rounded-lg bg-border/30 animate-pulse" />)}
            </div>
          ) : context && (context.recent_orders ?? []).length > 0 ? (
            <div className="space-y-2">
              {(showAllOrders
                ? (context.recent_orders ?? [])
                : (context.recent_orders ?? []).slice(0, 3)
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
              {(context.recent_orders ?? []).length > 3 && (
                <button
                  onClick={() => setShowAllOrders(v => !v)}
                  className="w-full text-[11px] text-muted-foreground hover:text-primary py-1 transition-colors"
                >
                  {showAllOrders
                    ? '▴ Ver menos'
                    : `▾ Ver ${(context.recent_orders ?? []).length - 3} más`}
                </button>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No hay pedidos vinculados.</p>
          )}

          {/* Mini-form crear pedido — sólo en human_takeover */}
          {conversation.status === 'human_takeover' && (
            <OrderMiniForm
              products={context?.products ?? []}
              conversationId={conversation.id}
              contactId={context?.contact?.id ?? null}
              onOrderCreated={onOrderCreated}
            />
          )}
        </section>

        {/* Catálogo informativo */}
        <section className="p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
              Catálogo ({context?.product_count ?? '—'})
            </p>
            {context && (context.low_stock_count ?? 0) > 0 && (
              <span className="text-[10px] text-amber-600 bg-amber-500/10 px-1.5 py-0.5 rounded-full border border-amber-500/20">
                {context.low_stock_count} bajo stock
              </span>
            )}
          </div>

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

          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map(i => <div key={i} className="h-14 rounded-lg bg-border/30 animate-pulse" />)}
            </div>
          ) : filteredProducts.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              {productSearch ? 'Sin coincidencias' : 'No hay productos activos'}
            </p>
          ) : (
            <div className="space-y-2">
              {filteredProducts.map(product => {
                const variations = product.product_variations ?? []
                const prices = variations.map(v => v.price)
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
                    {variations.length > 1 && (
                      <div className="flex flex-wrap gap-1">
                        {variations.slice(0, 5).map(v => (
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
                        {variations.length > 5 && (
                          <span className="text-[10px] text-muted-foreground">
                            +{variations.length - 5} más
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
  )
}
