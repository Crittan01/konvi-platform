'use client'

/**
 * Mini-form para crear pedidos desde el Inbox (panel derecho contextual).
 *
 * Refactor 2026-05-29 paso 4/10 — extraído de inbox-manager.tsx.
 *
 * Encapsula:
 *   - State local: selectedVariations, orderQtys, shipping, notes, search,
 *     creating, error, success, showForm.
 *   - Handlers: toggleVariation, createOrder.
 *   - JSX completo: botón abrir + form selector variantes + cantidades +
 *     envío + notas + submit.
 *
 * Props mínimas (4):
 *   - products: catálogo del tenant (lo provee el panel derecho).
 *   - conversationId: a qué conversación se asocia el pedido.
 *   - contactId: contacto del cliente (puede ser null).
 *   - onOrderCreated: callback opcional para refrescar contexto del panel padre.
 *
 * Visibilidad: la sección "Crear Pedido desde Inbox" solo se muestra cuando
 * el padre lo permite (status='human_takeover' + canWrite) — el padre
 * decide montar este componente. NO lo hacemos visible si no aplica.
 */
import { useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import {
  AlertCircle, BadgeCheck, Loader2, Package, Plus, Search,
  ShoppingBag, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { createIdempotencyKey } from '@/lib/idempotency'
import type { Product, SelectedVariation } from '../_lib/types'
import { formatMoney, variationLabel } from '../_lib/format'

interface Props {
  products: Product[]
  conversationId: string
  contactId: string | null
  onOrderCreated?: () => void
}

export function OrderMiniForm({
  products,
  conversationId,
  contactId,
  onOrderCreated,
}: Props) {
  const [showForm, setShowForm] = useState(false)
  const [selectedVariations, setSelectedVariations] = useState<SelectedVariation[]>([])
  const [orderQtys, setOrderQtys] = useState<Record<string, number>>({})
  const [orderShipping, setOrderShipping] = useState<string>('')
  const [orderNotes, setOrderNotes] = useState('')
  const [productSearch, setProductSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const handleToggleVariation = (v: SelectedVariation) => {
    setSelectedVariations(prev => {
      const exists = prev.find(x => x.variationId === v.variationId)
      if (exists) return prev.filter(x => x.variationId !== v.variationId)
      return [...prev, v]
    })
    setOrderQtys(prev => ({ ...prev, [v.variationId]: prev[v.variationId] ?? 1 }))
    setError(null)
    setSuccess(null)
  }

  const handleCreateOrder = async () => {
    if (selectedVariations.length === 0) return
    setCreating(true)
    setError(null)
    setSuccess(null)

    const supabase = createClient()
    const { data: { session } } = await supabase.auth.getSession()
    const token = session?.access_token
    if (!token) { setError('Sesión expirada.'); setCreating(false); return }

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
          conversation_id: conversationId,
          contact_id: contactId,
          notes: orderNotes.trim() || null,
          shipping_cost: isNaN(shippingCost) ? 0 : shippingCost,
          items,
          // Crear directo en confirmed para que descuente stock
          auto_confirm: true,
        }),
      })
      const json = await res.json().catch(() => ({ detail: 'Error desconocido' }))
      if (!res.ok) {
        setError(json.detail || 'Error al crear el pedido')
      } else {
        setSuccess(`Pedido #${json.id?.slice(0, 8)} creado y confirmado.`)
        setSelectedVariations([])
        setOrderQtys({})
        setOrderShipping('')
        setOrderNotes('')
        setShowForm(false)
        // Notificar al padre que refresque contexto
        if (onOrderCreated) {
          setTimeout(() => { onOrderCreated() }, 800)
        }
      }
    } catch {
      setError('Error de red al crear el pedido.')
    } finally {
      setCreating(false)
    }
  }

  // Productos filtrados por búsqueda local.
  const filtered = products.filter(p =>
    productSearch === '' ||
    p.title.toLowerCase().includes(productSearch.toLowerCase()) ||
    (p.product_variations ?? []).some(v => v.sku?.toLowerCase().includes(productSearch.toLowerCase())),
  )

  return (
    <>
      {/* Banner success cuando el form se cierra tras crear pedido */}
      {success && (
        <p className="text-[11px] text-emerald-600 mx-4 mb-2 flex items-center gap-1">
          <BadgeCheck className="h-3.5 w-3.5" /> {success}
        </p>
      )}

      {/* Botón abrir form */}
      {!showForm && (
        <button
          onClick={() => setShowForm(true)}
          className="mt-3 w-full flex items-center justify-center gap-2 py-1.5 px-3 rounded-lg border border-dashed border-primary/40 text-primary text-xs hover:bg-primary/5 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" /> Crear Pedido desde Inbox
        </button>
      )}

      {/* Mini-form expandido */}
      {showForm && (
        <section className="p-4 border-b border-border bg-background/50">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold flex items-center gap-1.5">
              <ShoppingBag className="h-3.5 w-3.5 text-primary" /> Nuevo Pedido
            </p>
            <button
              onClick={() => { setShowForm(false); setSelectedVariations([]); setError(null) }}
              className="text-muted-foreground hover:text-foreground"
            >
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
              {filtered.map(product =>
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
                      <span className={`text-[10px] ${v.stock_quantity <= 0 ? 'text-red-700' : 'text-muted-foreground'}`}>
                        Stock: {v.stock_quantity}
                      </span>
                    </button>
                  )
                }),
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
                    onChange={e => setOrderQtys(prev => ({
                      ...prev,
                      [v.variationId]: Math.max(1, parseInt(e.target.value) || 1),
                    }))}
                    className="w-14 px-1 py-0.5 text-xs rounded border border-border bg-background text-center focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <button onClick={() => handleToggleVariation(v)} className="text-muted-foreground hover:text-red-700">
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
              <p className="text-xs font-semibold text-right border-t border-border pt-1.5">
                Subtotal: {formatMoney(
                  selectedVariations.reduce((sum, v) => sum + v.price * (orderQtys[v.variationId] ?? 1), 0),
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

          {error && (
            <p className="text-[11px] text-red-700 mb-2 flex items-center gap-1">
              <AlertCircle className="h-3.5 w-3.5" /> {error}
            </p>
          )}

          <Button
            size="sm"
            onClick={handleCreateOrder}
            disabled={creating || selectedVariations.length === 0}
            className="w-full text-xs h-8 bg-primary hover:bg-primary/90"
          >
            {creating
              ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Creando…</>
              : <><Package className="h-3.5 w-3.5 mr-1.5" /> Crear Pedido Confirmado</>}
          </Button>
          <p className="text-[10px] text-muted-foreground text-center mt-1">
            El pedido se crea confirmado y descuenta stock inmediatamente.
          </p>
        </section>
      )}
    </>
  )
}
