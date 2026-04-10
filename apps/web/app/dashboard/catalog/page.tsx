import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import CatalogForm from './catalog-form'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

type Variation = { id: string; price: number; stock_quantity: number; attributes: Record<string, string> | null }
type Product = {
  id: string
  title: string
  description: string | null
  status: string
  product_variations: Variation[]
}

export default async function CatalogPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  let products: Product[] = []
  if (tenantId) {
    const { data } = await supabase
      .from('products')
      .select('id, title, description, status, product_variations(id, price, stock_quantity, attributes)')
      .eq('tenant_id', tenantId)
      .eq('status', 'active')
      .order('title')
    products = (data as Product[]) || []
  }

  // ── Server Actions ────────────────────────────────────────────────────────

  async function editProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const meta = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) return
    const t = meta.tenant_id

    const productId = formData.get('product_id') as string
    const variationId = formData.get('variation_id') as string

    await sb.from('products')
      .update({
        title: formData.get('title') as string,
        description: formData.get('description') as string || null,
      })
      .eq('id', productId)
      .eq('tenant_id', t)

    if (variationId) {
      await sb.from('product_variations')
        .update({
          price: parseFloat(formData.get('price') as string),
          stock_quantity: parseInt(formData.get('stock') as string),
        })
        .eq('id', variationId)
        .eq('tenant_id', t)
    }
    revalidatePath('/dashboard/catalog')
  }

  async function deactivateProduct(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const meta = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!meta.tenant_id || !['owner', 'manager'].includes(meta.role ?? '')) return
    const t = meta.tenant_id

    await sb.from('products')
      .update({ status: 'inactive' })
      .eq('id', formData.get('product_id') as string)
      .eq('tenant_id', t)

    revalidatePath('/dashboard/catalog')
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Catálogo</h1>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* Formulario multi-variante — Client Component */}
        {canWrite && (
          <div className="col-span-1">
            <CatalogForm
              apiUrl={API_URL}
            />
          </div>
        )}

        {/* Lista de productos */}
        <div className={canWrite ? 'col-span-2' : 'col-span-3'}>
          <div className="space-y-4">
            {products.length === 0 ? (
              <div className="p-8 border rounded-lg border-dashed text-center">
                <p className="text-muted-foreground">El catálogo está vacío.</p>
                {canWrite && (
                  <p className="text-sm text-muted-foreground mt-1">Agrega productos para que la IA pueda venderlos por WhatsApp.</p>
                )}
              </div>
            ) : (
              products.map((p) => {
                const vars = p.product_variations ?? []
                const v0 = vars[0]
                const priceRange = vars.length > 1
                  ? `$${Math.min(...vars.map(v => v.price))} – $${Math.max(...vars.map(v => v.price))}`
                  : `$${v0?.price ?? '—'}`
                const totalStock = vars.reduce((s, v) => s + (v.stock_quantity ?? 0), 0)

                return (
                  <Card key={p.id}>
                    <CardContent className="p-6 space-y-4">
                      {/* Vista */}
                      <div className="flex justify-between items-start">
                        <div className="space-y-1">
                          <h4 className="font-semibold text-lg">{p.title}</h4>
                          {p.description && (
                            <p className="text-sm text-muted-foreground">{p.description}</p>
                          )}
                          {/* Variantes */}
                          {vars.length > 1 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {vars.map(v => {
                                const attrStr = v.attributes && Object.keys(v.attributes).length
                                  ? Object.entries(v.attributes).map(([k, val]) => `${k}: ${val}`).join(', ')
                                  : 'Estándar'
                                return (
                                  <span key={v.id} className="text-xs bg-muted px-2 py-0.5 rounded-full text-muted-foreground">
                                    {attrStr} · ${v.price} · {v.stock_quantity} uds
                                  </span>
                                )
                              })}
                            </div>
                          )}
                        </div>
                        <div className="text-right shrink-0 ml-4">
                          <p className="font-bold text-xl text-primary">{priceRange}</p>
                          <p className="text-sm text-muted-foreground">Stock: {totalStock}</p>
                          <p className="text-xs text-muted-foreground">{vars.length} variante{vars.length !== 1 ? 's' : ''}</p>
                        </div>
                      </div>

                      {/* Formulario de edición — solo nombre/descripción + primera variante */}
                      {canWrite && (
                        <details className="group">
                          <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground select-none">
                            Editar nombre / descripción
                          </summary>
                          <form action={editProduct} className="mt-3 space-y-3">
                            <input type="hidden" name="product_id" value={p.id} />
                            <input type="hidden" name="variation_id" value={v0?.id ?? ''} />
                            <div className="grid grid-cols-2 gap-3">
                              <div className="col-span-2 space-y-1">
                                <Label className="text-xs">Nombre</Label>
                                <Input name="title" defaultValue={p.title} required />
                              </div>
                              <div className="col-span-2 space-y-1">
                                <Label className="text-xs">Descripción</Label>
                                <Input name="description" defaultValue={p.description ?? ''} />
                              </div>
                              {vars.length === 1 && (
                                <>
                                  <div className="space-y-1">
                                    <Label className="text-xs">Precio ($)</Label>
                                    <Input name="price" type="number" step="0.01" min="0.01" defaultValue={v0?.price ?? 0} required />
                                  </div>
                                  <div className="space-y-1">
                                    <Label className="text-xs">Stock</Label>
                                    <Input name="stock" type="number" min="0" defaultValue={v0?.stock_quantity ?? 0} required />
                                  </div>
                                </>
                              )}
                            </div>
                            <div className="flex gap-2">
                              <Button type="submit" size="sm">Guardar</Button>
                              <form action={deactivateProduct}>
                                <input type="hidden" name="product_id" value={p.id} />
                                <Button type="submit" size="sm" variant="destructive">Desactivar</Button>
                              </form>
                            </div>
                          </form>
                        </details>
                      )}
                    </CardContent>
                  </Card>
                )
              })
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
