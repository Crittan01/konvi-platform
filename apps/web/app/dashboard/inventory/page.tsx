import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'

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
  return Object.entries(attrs)
    .map(([k, v]) => `${k}: ${v}`)
    .join(' · ')
}

export default async function InventoryPage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
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

  const products = (productsRes.data as Product[]) ?? []
  const movements = (movementsRes.data as Movement[]) ?? []
  const threshold: number = (tenantRes.data as { low_stock_threshold?: number } | null)?.low_stock_threshold ?? DEFAULT_THRESHOLD

  // Totales para KPIs
  const allVariations = products.flatMap(p => p.product_variations)
  const totalUnits = allVariations.reduce((s, v) => s + v.stock_quantity, 0)
  const lowStockCount = allVariations.filter(v => v.stock_quantity > 0 && v.stock_quantity <= threshold).length
  const zeroStockCount = allVariations.filter(v => v.stock_quantity === 0).length

  // ── Server Actions ────────────────────────────────────────────────────────

  async function adjustStock(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
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

    const newStock = Math.max(0, variation.stock_quantity + delta)

    await Promise.all([
      sb.from('product_variations')
        .update({ stock_quantity: newStock })
        .eq('id', variationId)
        .eq('tenant_id', m.tenant_id),
      sb.from('stock_movements').insert({
        tenant_id:    m.tenant_id,
        product_id:   productId,
        variation_id: variationId,
        delta,
        new_stock:    newStock,
        reason,
        created_by:   s?.user?.id ?? null,
      }),
    ])

    revalidatePath('/dashboard/inventory')
  }

  async function saveThreshold(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const val = parseInt(formData.get('threshold') as string)
    if (isNaN(val) || val < 0) return

    await sb.from('tenants').update({ low_stock_threshold: val }).eq('id', m.tenant_id)
    revalidatePath('/dashboard/inventory')
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Inventario</h1>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Total en stock</p>
            <p className="text-3xl font-bold text-primary mt-1">{totalUnits}</p>
            <p className="text-xs text-muted-foreground mt-1">unidades en {allVariations.length} variantes</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Stock bajo</p>
            <p className={`text-3xl font-bold mt-1 ${lowStockCount > 0 ? 'text-yellow-400' : 'text-primary'}`}>
              {lowStockCount}
            </p>
            <p className="text-xs text-muted-foreground mt-1">variantes con ≤ {threshold} unidades</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Sin stock</p>
            <p className={`text-3xl font-bold mt-1 ${zeroStockCount > 0 ? 'text-red-400' : 'text-primary'}`}>
              {zeroStockCount}
            </p>
            <p className="text-xs text-muted-foreground mt-1">variantes en cero</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid md:grid-cols-3 gap-6">

        {/* ── Lista de productos y variantes ── */}
        <div className="md:col-span-2 space-y-4">
          {products.length === 0 ? (
            <div className="p-8 border border-dashed rounded-lg text-center text-muted-foreground">
              No hay productos activos.
            </div>
          ) : (
            products.map(product => (
              <Card key={product.id}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">{product.title}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  {product.product_variations.map(variation => {
                    const isLow  = variation.stock_quantity > 0 && variation.stock_quantity <= threshold
                    const isZero = variation.stock_quantity === 0
                    return (
                      <div key={variation.id} className="border rounded-md p-3 space-y-2">
                        <div className="flex justify-between items-start">
                          <div>
                            <p className="text-sm font-medium">{formatAttributes(variation.attributes)}</p>
                            <p className="text-xs text-muted-foreground">${variation.price} c/u</p>
                          </div>
                          <div className="text-right">
                            <p className={`text-xl font-bold ${isZero ? 'text-red-400' : isLow ? 'text-yellow-400' : 'text-primary'}`}>
                              {variation.stock_quantity}
                            </p>
                            {isZero && <span className="text-xs text-red-400 font-medium">Sin stock</span>}
                            {isLow  && <span className="text-xs text-yellow-400 font-medium">Stock bajo</span>}
                          </div>
                        </div>

                        {canWrite && (
                          <form action={adjustStock} className="flex gap-2 items-end pt-1 border-t">
                            <input type="hidden" name="variation_id" value={variation.id} />
                            <input type="hidden" name="product_id"   value={product.id} />
                            <div className="flex-1 space-y-1">
                              <Label className="text-xs">Ajuste (+ entrada / − salida)</Label>
                              <Input name="delta" type="number" placeholder="ej: 10 o -3" className="h-8 text-sm" required />
                            </div>
                            <div className="flex-1 space-y-1">
                              <Label className="text-xs">Motivo</Label>
                              <Input name="reason" placeholder="Compra, devolución..." className="h-8 text-sm" />
                            </div>
                            <Button type="submit" size="sm" className="h-8">Aplicar</Button>
                          </form>
                        )}
                      </div>
                    )
                  })}
                </CardContent>
              </Card>
            ))
          )}
        </div>

        {/* ── Panel lateral ── */}
        <div className="space-y-4">

          {/* Umbral de stock bajo */}
          {canWrite && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Umbral de stock bajo</CardTitle>
              </CardHeader>
              <CardContent>
                <form action={saveThreshold} className="flex gap-2 items-end">
                  <div className="flex-1 space-y-1">
                    <Label className="text-xs">Umbral (unidades)</Label>
                    <Input
                      name="threshold"
                      type="number"
                      min="0"
                      defaultValue={threshold}
                      className="h-8 text-sm"
                      required
                    />
                  </div>
                  <Button type="submit" size="sm" className="h-8">Guardar</Button>
                </form>
                <p className="text-xs text-muted-foreground mt-2">
                  Las variantes con ≤ {threshold} unidades se marcan como "stock bajo".
                </p>
              </CardContent>
            </Card>
          )}

          {/* Historial de movimientos */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Últimos movimientos</CardTitle>
            </CardHeader>
            <CardContent>
              {movements.length === 0 ? (
                <p className="text-sm text-muted-foreground">Sin movimientos aún.</p>
              ) : (
                <div className="space-y-3">
                  {movements.map(m => (
                    <div key={m.id} className="text-xs border-b pb-2 last:border-0">
                      <div className="flex justify-between items-center">
                        <span className={`font-semibold ${m.delta > 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {m.delta > 0 ? `+${m.delta}` : m.delta}
                        </span>
                        <span className="text-muted-foreground">→ {m.new_stock} u.</span>
                      </div>
                      <p className="text-muted-foreground truncate">{m.reason ?? 'Sin motivo'}</p>
                      <p className="text-muted-foreground">
                        {new Date(m.created_at).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

        </div>

      </div>
    </div>
  )
}
