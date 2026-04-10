import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Boxes, AlertTriangle, Package } from 'lucide-react'

const DEFAULT_THRESHOLD = 5

type Variation = {
  id: string
  attributes: Record<string, string> | null
  stock_quantity: number
  price: number
}

type Product = {
  id: string
  title: string
  status: string
  product_variations: Variation[]
}

type Movement = {
  id: string
  delta: number
  new_stock: number
  reason: string | null
  created_at: string
  variation_id: string
}

function formatAttributes(attrs: Record<string, string> | null): string {
  if (!attrs || Object.keys(attrs).length === 0) return 'Estándar'
  return Object.entries(attrs).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

export default async function InventoryPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const [productsRes, movementsRes, tenantRes] = await Promise.all([
    supabase
      .from('products')
      .select('id, title, status, product_variations(id, attributes, stock_quantity, price)')
      .eq('tenant_id', tenantId)
      .eq('status', 'active')
      .order('title'),
    supabase
      .from('stock_movements')
      .select('id, delta, new_stock, reason, created_at, variation_id')
      .eq('tenant_id', tenantId)
      .order('created_at', { ascending: false })
      .limit(30),
    supabase
      .from('tenants')
      .select('low_stock_threshold')
      .eq('id', tenantId)
      .single(),
  ])

  const products  = (productsRes.data as Product[]) ?? []
  const movements = (movementsRes.data as Movement[]) ?? []
  const threshold: number = (tenantRes.data as { low_stock_threshold?: number } | null)?.low_stock_threshold ?? DEFAULT_THRESHOLD

  const allVariations  = products.flatMap(p => p.product_variations)
  const totalUnits     = allVariations.reduce((s, v) => s + v.stock_quantity, 0)
  const lowStockCount  = allVariations.filter(v => v.stock_quantity > 0 && v.stock_quantity <= threshold).length
  const zeroStockCount = allVariations.filter(v => v.stock_quantity === 0).length

  // ── Server Actions ────────────────────────────────────────────────────────

  async function adjustStock(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const variationId = formData.get('variation_id') as string
    const productId   = formData.get('product_id') as string
    const delta       = parseInt(formData.get('delta') as string)
    const reason      = (formData.get('reason') as string) || 'Ajuste manual'
    if (!variationId || isNaN(delta) || delta === 0) return
    const { data: variation } = await sb
      .from('product_variations')
      .select('stock_quantity')
      .eq('id', variationId)
      .eq('tenant_id', m.tenant_id)
      .single()
    if (!variation) return
    const newStock = Math.max(0, (variation as { stock_quantity: number }).stock_quantity + delta)
    const { data: { session: s } } = await sb.auth.getSession()
    await Promise.all([
      sb.from('product_variations').update({ stock_quantity: newStock }).eq('id', variationId).eq('tenant_id', m.tenant_id),
      sb.from('stock_movements').insert({
        tenant_id: m.tenant_id, product_id: productId, variation_id: variationId,
        delta, new_stock: newStock, reason, created_by: s?.user?.id ?? null,
      }),
    ])
    revalidatePath('/dashboard/inventory')
  }

  async function saveThreshold(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const val = parseInt(formData.get('threshold') as string)
    if (isNaN(val) || val < 0) return
    await sb.from('tenants').update({ low_stock_threshold: val }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/inventory')
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Boxes className="h-5 w-5 text-primary" /> Inventario
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {products.length} productos activos · {allVariations.length} variantes
          </p>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-3 gap-3 sm:gap-4">
        <div className="rounded-xl border border-border bg-card p-4 sm:p-5">
          <p className="text-xs text-muted-foreground uppercase tracking-wide">Total stock</p>
          <p className="text-2xl sm:text-3xl font-bold text-primary mt-1">{totalUnits}</p>
          <p className="text-xs text-muted-foreground mt-1">{allVariations.length} variantes</p>
        </div>
        <div className={`rounded-xl border bg-card p-4 sm:p-5 ${lowStockCount > 0 ? 'border-yellow-500/30 bg-yellow-500/5' : 'border-border'}`}>
          <div className="flex items-center gap-1.5 mb-1">
            {lowStockCount > 0 && <AlertTriangle className="h-3.5 w-3.5 text-yellow-400" />}
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Stock bajo</p>
          </div>
          <p className={`text-2xl sm:text-3xl font-bold mt-1 ${lowStockCount > 0 ? 'text-yellow-400' : 'text-primary'}`}>
            {lowStockCount}
          </p>
          <p className="text-xs text-muted-foreground mt-1">≤ {threshold} unidades</p>
        </div>
        <div className={`rounded-xl border bg-card p-4 sm:p-5 ${zeroStockCount > 0 ? 'border-red-500/30 bg-red-500/5' : 'border-border'}`}>
          <p className="text-xs text-muted-foreground uppercase tracking-wide">Sin stock</p>
          <p className={`text-2xl sm:text-3xl font-bold mt-1 ${zeroStockCount > 0 ? 'text-red-400' : 'text-primary'}`}>
            {zeroStockCount}
          </p>
          <p className="text-xs text-muted-foreground mt-1">en cero</p>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">

        {/* Lista de productos */}
        <div className="lg:col-span-2 space-y-4">
          {products.length === 0 ? (
            <div className="flex flex-col items-center py-16 rounded-xl border border-dashed text-center">
              <Package className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground text-sm">No hay productos activos.</p>
            </div>
          ) : (
            products.map(product => (
              <div key={product.id} className="rounded-xl border border-border bg-card overflow-hidden">
                <div className="px-4 py-3 border-b border-border bg-muted/20">
                  <p className="font-semibold text-sm">{product.title}</p>
                </div>
                <div className="p-3 space-y-3">
                  {product.product_variations.map(variation => {
                    const isLow  = variation.stock_quantity > 0 && variation.stock_quantity <= threshold
                    const isZero = variation.stock_quantity === 0
                    return (
                      <div key={variation.id} className={`rounded-lg border p-3 space-y-3 ${isZero ? 'border-red-500/30 bg-red-500/5' : isLow ? 'border-yellow-500/30 bg-yellow-500/5' : 'border-border'}`}>
                        <div className="flex justify-between items-start">
                          <div>
                            <p className="text-sm font-medium">{formatAttributes(variation.attributes)}</p>
                            <p className="text-xs text-muted-foreground">${variation.price} c/u</p>
                          </div>
                          <div className="text-right">
                            <p className={`text-2xl font-bold ${isZero ? 'text-red-400' : isLow ? 'text-yellow-400' : 'text-primary'}`}>
                              {variation.stock_quantity}
                            </p>
                            <p className="text-xs font-medium">
                              {isZero ? <span className="text-red-400">❌ Sin stock</span>
                                : isLow ? <span className="text-yellow-400">⚠️ Stock bajo</span>
                                : <span className="text-emerald-400">✓ OK</span>}
                            </p>
                          </div>
                        </div>

                        {canWrite && (
                          <form action={adjustStock} className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-2 border-t border-border">
                            <input type="hidden" name="variation_id" value={variation.id} />
                            <input type="hidden" name="product_id"   value={product.id} />
                            <div className="space-y-1">
                              <Label className="text-[11px]">Ajuste (±)</Label>
                              <Input name="delta" type="number" placeholder="10 o -3" className="h-7 text-xs" required />
                            </div>
                            <div className="space-y-1">
                              <Label className="text-[11px]">Motivo</Label>
                              <Input name="reason" placeholder="Compra..." className="h-7 text-xs" />
                            </div>
                            <div className="flex items-end">
                              <Button type="submit" size="sm" className="h-7 text-xs w-full sm:w-auto">Aplicar</Button>
                            </div>
                          </form>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Panel lateral */}
        <div className="space-y-4">

          {/* Umbral configurable */}
          {canWrite && (
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="font-semibold text-sm mb-3">⚙️ Umbral de alerta</p>
              <form action={saveThreshold} className="flex gap-2 items-end">
                <div className="flex-1 space-y-1">
                  <Label className="text-xs">Unidades mínimas</Label>
                  <Input name="threshold" type="number" min="0" defaultValue={threshold} className="h-8 text-sm" required />
                </div>
                <Button type="submit" size="sm" className="h-8">Guardar</Button>
              </form>
              <p className="text-xs text-muted-foreground mt-2">
                Variantes con ≤ {threshold} unidades se marcan como &quot;stock bajo&quot;.
              </p>
            </div>
          )}

          {/* Historial de movimientos */}
          <div className="rounded-xl border border-border bg-card p-4">
            <p className="font-semibold text-sm mb-3">📋 Últimos movimientos</p>
            {movements.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin movimientos aún.</p>
            ) : (
              <div className="space-y-2.5 max-h-96 overflow-y-auto">
                {movements.map(m => (
                  <div key={m.id} className="text-xs border-b border-border pb-2 last:border-0">
                    <div className="flex justify-between items-center">
                      <span className={`font-bold ${m.delta > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {m.delta > 0 ? `+${m.delta}` : m.delta} u.
                      </span>
                      <span className="text-muted-foreground">→ {m.new_stock} u.</span>
                    </div>
                    <p className="text-muted-foreground truncate">{m.reason ?? 'Sin motivo'}</p>
                    <p className="text-muted-foreground/60 text-[10px]">
                      {new Date(m.created_at).toLocaleString('es-MX', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
