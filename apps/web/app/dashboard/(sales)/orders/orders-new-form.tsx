'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Plus, Trash2, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { createIdempotencyKey } from '@/lib/idempotency'

// Rev. 108 Fase B — método de pago del pedido manual.
//   • credit → link Wompi (default). Con auto_confirm=false arranca en 'pending'.
//   • cod    → contraentrega: el backend crea el pedido 'confirmed' y descuenta
//              inventario de una vez (el courier recauda al entregar).
type PaymentMethod = 'credit' | 'cod'

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
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('credit')
  const [autoConfirm, setAutoConfirm] = useState(false)

  const subtotal = items.reduce((acc, i) => acc + i.price * i.quantity, 0)
  const grandTotal = subtotal + shippingCost

  // Solo productos con al menos una variante son pedibles. Antes addLine hacía
  // no-op silencioso si el catálogo estaba vacío o el producto no tenía variante;
  // ahora se filtran y el botón "Añadir" se deshabilita con guía contextual.
  const addableProducts = products.filter(p => (p.product_variations?.length ?? 0) > 0)
  const canAdd = addableProducts.length > 0

  // ── Añadir línea vacía ──────────────────────────────────────────────────────
  const addLine = () => {
    const p = addableProducts[0]
    if (!p) return
    const v = p.product_variations[0]
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
    const p = addableProducts.find(pr => pr.id === productId)
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
      payment_method: paymentMethod,
      // COD ya arranca 'confirmed' en backend → auto_confirm sólo aplica a credit.
      auto_confirm: paymentMethod === 'credit' ? autoConfirm : false,
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
        setPaymentMethod('credit')
        setAutoConfirm(false)
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
            <Button type="button" size="sm" variant="outline" onClick={addLine} disabled={!canAdd} className="h-7 text-xs gap-1">
              <Plus className="h-3 w-3" />
              Añadir
            </Button>
          </div>

          {!canAdd ? (
            <p className="text-xs text-muted-foreground text-center py-3 px-3 border border-dashed rounded-lg">
              No tienes productos con variantes disponibles.{' '}
              <Link href="/dashboard/catalog" className="text-primary hover:underline">
                Créalos en Catálogo
              </Link>{' '}
              antes de armar un pedido.
            </p>
          ) : items.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-3 border border-dashed rounded-lg">
              Presiona &quot;Añadir&quot; para agregar productos
            </p>
          )}

          {items.map((item, idx) => {
            const currentProduct = addableProducts.find(p => p.id === item.productId)
            return (
              <div key={idx} className="rounded-lg border border-border bg-muted/30 p-3 space-y-2">
                <div className="flex gap-2 items-start">
                  {/* Producto */}
                  <div className="flex-1 space-y-1">
                    <select
                      value={item.productId}
                      onChange={e => changeProduct(idx, e.target.value)}
                      aria-label="Producto"
                      className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                    >
                      {addableProducts.map(p => (
                        <option key={p.id} value={p.id}>{p.title}</option>
                      ))}
                    </select>
                    {/* Variante */}
                    {currentProduct && currentProduct.product_variations.length > 1 && (
                      <select
                        value={item.variationId}
                        onChange={e => changeVariation(idx, e.target.value)}
                        aria-label="Variante"
                        className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                      >
                        {currentProduct.product_variations.map(v => (
                          <option key={v.id} value={v.id}>
                            {variationLabel(v)} — {v.price != null ? `$${v.price.toLocaleString('es-CO')}` : 'sin precio'}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                  {/* Eliminar */}
                  <button
                    type="button"
                    onClick={() => removeLine(idx)}
                    aria-label={`Eliminar ${item.productTitle}`}
                    className="mt-1 text-muted-foreground hover:text-destructive transition-colors"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                {/* Precio y cantidad — COP sin centavos */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-0.5">
                    <label className="text-xs text-muted-foreground">Precio (COP)</label>
                    <Input
                      type="number"
                      step="50"
                      min="1"
                      value={item.price}
                      onChange={e => changePrice(idx, parseInt(e.target.value, 10) || 0)}
                      className="h-7 text-xs"
                    />
                  </div>
                  <div className="space-y-0.5">
                    <label className="text-xs text-muted-foreground">Cantidad</label>
                    <Input
                      type="number"
                      min="1"
                      value={item.quantity}
                      onChange={e => changeQty(idx, parseInt(e.target.value, 10) || 1)}
                      className="h-7 text-xs"
                    />
                  </div>
                </div>

                {/* Subtotal línea */}
                <p className="text-xs text-right text-muted-foreground">
                  Subtotal: <span className="text-primary font-medium">${(item.price * item.quantity).toLocaleString('es-CO')}</span>
                </p>
              </div>
            )
          })}

          {/* Total */}
          {items.length > 0 && (
            <div className="space-y-3 pt-3 border-t border-border">
              <div className="flex justify-between items-center text-sm">
                <span className="text-muted-foreground">Subtotal ítems</span>
                <span>${subtotal.toLocaleString('es-CO')}</span>
              </div>
              <div className="flex justify-between items-center text-sm">
                <span className="text-muted-foreground flex items-center">
                  Costo de envío (COP)
                </span>
                <Input
                  type="number"
                  step="50"
                  min="0"
                  value={shippingCost === 0 ? '' : shippingCost}
                  placeholder="0"
                  aria-label="Costo de envío en pesos"
                  onChange={e => setShippingCost(parseInt(e.target.value, 10) || 0)}
                  className="h-8 w-28 text-right text-xs"
                />
              </div>
              <div className="flex justify-between items-center pt-2 border-t border-border">
                <span className="text-sm font-medium">Total</span>
                <span className="text-xl font-bold text-primary">${grandTotal.toLocaleString('es-CO')}</span>
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

        {/* Método de pago (Rev. 108 Fase B) */}
        <div className="space-y-2">
          <Label>Método de pago</Label>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Método de pago">
            <button
              type="button"
              role="radio"
              aria-checked={paymentMethod === 'credit'}
              onClick={() => setPaymentMethod('credit')}
              className={`rounded-lg border px-3 py-2 text-xs text-left transition-colors ${
                paymentMethod === 'credit'
                  ? 'border-primary/50 bg-primary/10 text-foreground'
                  : 'border-border text-muted-foreground hover:bg-accent'
              }`}
            >
              <span className="block font-medium">Pago en línea</span>
              <span className="block text-[11px] text-muted-foreground">Link de pago Wompi</span>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={paymentMethod === 'cod'}
              onClick={() => setPaymentMethod('cod')}
              className={`rounded-lg border px-3 py-2 text-xs text-left transition-colors ${
                paymentMethod === 'cod'
                  ? 'border-emerald-700/50 bg-emerald-500/10 text-foreground'
                  : 'border-border text-muted-foreground hover:bg-accent'
              }`}
            >
              <span className="block font-medium">Contraentrega (COD)</span>
              <span className="block text-[11px] text-muted-foreground">El courier recauda</span>
            </button>
          </div>

          {paymentMethod === 'cod' ? (
            <p className="text-[11px] text-muted-foreground leading-snug px-1">
              El pedido se crea <span className="font-medium text-foreground">confirmado</span> y
              descuenta inventario de inmediato. La guía contraentrega se genera desde el listado.
            </p>
          ) : (
            <div className="flex items-start justify-between gap-3 rounded-lg border border-border bg-muted/30 px-3 py-2">
              <div className="min-w-0">
                <p className="text-xs font-medium">Confirmar de inmediato</p>
                <p className="text-[11px] text-muted-foreground leading-snug">
                  Descuenta inventario ahora. Déjalo apagado para cobrar primero con link Wompi.
                </p>
              </div>
              <Switch
                checked={autoConfirm}
                onCheckedChange={setAutoConfirm}
                aria-label="Confirmar el pedido de inmediato"
                className="mt-0.5 shrink-0"
              />
            </div>
          )}
        </div>

        {error && <p className="text-xs text-red-700">{error}</p>}

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
