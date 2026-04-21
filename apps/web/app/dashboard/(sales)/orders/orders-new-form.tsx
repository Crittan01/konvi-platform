'use client'

import { useState } from 'react'
import { Plus, Trash2, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { createIdempotencyKey } from '@/lib/idempotency'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface Variation {
  id: string
  price: number | null
  attributes: Record<string, string> | null
}

interface Product {
  id: string
  title: string
  product_variations: Variation[]
}

interface Contact {
  id: string
  phone: string
  name: string | null
}

interface LineItem {
  productId: string
  productTitle: string
  variationId: string
  price: number
  quantity: number
}

interface Props {
  products: Product[]
  contacts: Contact[]
  onCreated?: () => void
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function variationLabel(v: Variation): string {
  if (!v.attributes || Object.keys(v.attributes).length === 0) return 'Estándar'
  return Object.entries(v.attributes).map(([k, val]) => `${k}: ${val}`).join(', ')
}

// ─── Componente ───────────────────────────────────────────────────────────────

export default function OrdersNewForm({ products, contacts, onCreated = () => {} }: Props) {
  const [contactId, setContactId] = useState('')
  const [notes, setNotes] = useState('')
  const [shippingCost, setShippingCost] = useState(0)
  const [items, setItems] = useState<LineItem[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const subtotal = items.reduce((acc, i) => acc + i.price * i.quantity, 0)
  const grandTotal = subtotal + shippingCost

  // ── Añadir línea vacía ──────────────────────────────────────────────────────
  const addLine = () => {
    if (products.length === 0) return
    const p = products[0]
    const v = p.product_variations?.[0]
    if (!v) return
    setItems(prev => [...prev, {
      productId: p.id,
      productTitle: p.title,
      variationId: v.id,
      price: v.price ?? 0,
      quantity: 1,
    }])
  }

  // ── Cambiar producto en una línea ───────────────────────────────────────────
  const changeProduct = (idx: number, productId: string) => {
    const p = products.find(pr => pr.id === productId)
    if (!p) return
    const v = p.product_variations?.[0]
    if (!v) return
    setItems(prev => prev.map((item, i) =>
      i === idx ? { ...item, productId: p.id, productTitle: p.title, variationId: v.id, price: v.price ?? 0 } : item
    ))
  }

  // ── Cambiar variante en una línea ───────────────────────────────────────────
  const changeVariation = (idx: number, variationId: string) => {
    const item = items[idx]
    const p = products.find(pr => pr.id === item.productId)
    const v = p?.product_variations.find(vr => vr.id === variationId)
    if (!v) return
    setItems(prev => prev.map((it, i) =>
      i === idx ? { ...it, variationId: v.id, price: v.price ?? 0 } : it
    ))
  }

  // ── Cambiar cantidad ────────────────────────────────────────────────────────
  const changeQty = (idx: number, qty: number) => {
    if (qty < 1) return
    setItems(prev => prev.map((it, i) => i === idx ? { ...it, quantity: qty } : it))
  }

  // ── Cambiar precio manual ───────────────────────────────────────────────────
  const changePrice = (idx: number, price: number) => {
    if (price < 0) return
    setItems(prev => prev.map((it, i) => i === idx ? { ...it, price } : it))
  }

  // ── Eliminar línea ──────────────────────────────────────────────────────────
  const removeLine = (idx: number) => {
    setItems(prev => prev.filter((_, i) => i !== idx))
  }

  // ── Submit ──────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (items.length === 0) { setError('Agrega al menos un producto'); return }
    setSubmitting(true)
    setError(null)

    const payload = {
      contact_id: contactId || null,
      notes: notes || null,
      shipping_cost: shippingCost,
      items: items.map(it => ({
        product_id: it.productId,
        variation_id: it.variationId,
        title: it.productTitle,
        unit_price: it.price,
        quantity: it.quantity,
      })),
    }

    try {
      const idempotencyKey = createIdempotencyKey('orders.create')
      const res = await fetch('/api/orders', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(15000),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Error desconocido' }))
        setError(err.detail || 'No se pudo crear el pedido')
      } else {
        setItems([])
        setContactId('')
        setNotes('')
        setShippingCost(0)
        onCreated()
      }
    } catch {
      setError('Error de red. Verifica la conexión.')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Nuevo Pedido</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* Contacto */}
        <div className="space-y-1">
          <Label>Contacto</Label>
          <select
            value={contactId}
            onChange={e => setContactId(e.target.value)}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          >
            <option value="">Sin contacto</option>
            {contacts.map(c => (
              <option key={c.id} value={c.id}>
                {c.name ? `${c.name} (${c.phone})` : c.phone}
              </option>
            ))}
          </select>
        </div>

        {/* Líneas de ítem */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>Productos</Label>
            <Button type="button" size="sm" variant="outline" onClick={addLine} className="h-7 text-xs gap-1">
              <Plus className="h-3 w-3" />
              Añadir
            </Button>
          </div>

          {items.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-3 border border-dashed rounded-lg">
              Presiona &quot;Añadir&quot; para agregar productos
            </p>
          )}

          {items.map((item, idx) => {
            const currentProduct = products.find(p => p.id === item.productId)
            return (
              <div key={idx} className="rounded-lg border border-border bg-muted/30 p-3 space-y-2">
                <div className="flex gap-2 items-start">
                  {/* Producto */}
                  <div className="flex-1 space-y-1">
                    <select
                      value={item.productId}
                      onChange={e => changeProduct(idx, e.target.value)}
                      className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                    >
                      {products.map(p => (
                        <option key={p.id} value={p.id}>{p.title}</option>
                      ))}
                    </select>
                    {/* Variante */}
                    {currentProduct && currentProduct.product_variations.length > 1 && (
                      <select
                        value={item.variationId}
                        onChange={e => changeVariation(idx, e.target.value)}
                        className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                      >
                        {currentProduct.product_variations.map(v => (
                          <option key={v.id} value={v.id}>
                            {variationLabel(v)} — ${v.price ?? '?'}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                  {/* Eliminar */}
                  <button
                    type="button"
                    onClick={() => removeLine(idx)}
                    className="mt-1 text-muted-foreground hover:text-destructive transition-colors"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                {/* Precio y cantidad */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-0.5">
                    <label className="text-xs text-muted-foreground">Precio ($)</label>
                    <Input
                      type="number"
                      step="0.01"
                      min="0.01"
                      value={item.price}
                      onChange={e => changePrice(idx, parseFloat(e.target.value) || 0)}
                      className="h-7 text-xs"
                    />
                  </div>
                  <div className="space-y-0.5">
                    <label className="text-xs text-muted-foreground">Cantidad</label>
                    <Input
                      type="number"
                      min="1"
                      value={item.quantity}
                      onChange={e => changeQty(idx, parseInt(e.target.value) || 1)}
                      className="h-7 text-xs"
                    />
                  </div>
                </div>

                {/* Subtotal línea */}
                <p className="text-xs text-right text-muted-foreground">
                  Subtotal: <span className="text-primary font-medium">${(item.price * item.quantity).toFixed(2)}</span>
                </p>
              </div>
            )
          })}

          {/* Total */}
          {items.length > 0 && (
            <div className="space-y-3 pt-3 border-t border-border">
              <div className="flex justify-between items-center text-sm">
                <span className="text-muted-foreground">Subtotal ítems</span>
                <span>${subtotal.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center text-sm">
                <span className="text-muted-foreground flex items-center">
                  Costo de Envío ($)
                </span>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={shippingCost === 0 ? '' : shippingCost}
                  placeholder="0.00"
                  onChange={e => setShippingCost(parseFloat(e.target.value) || 0)}
                  className="h-8 w-28 text-right text-xs"
                />
              </div>
              <div className="flex justify-between items-center pt-2 border-t border-border">
                <span className="text-sm font-medium">Total</span>
                <span className="text-xl font-bold text-primary">${grandTotal.toFixed(2)}</span>
              </div>
            </div>
          )}
        </div>

        {/* Notas */}
        <div className="space-y-1">
          <Label>Notas</Label>
          <Input
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="Instrucciones especiales..."
          />
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}

        <Button
          type="button"
          onClick={handleSubmit}
          disabled={submitting || items.length === 0}
          className="w-full"
        >
          {submitting ? (
            <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Creando...</>
          ) : (
            'Crear pedido'
          )}
        </Button>
      </CardContent>
    </Card>
  )
}
