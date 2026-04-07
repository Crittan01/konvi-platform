import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default async function CatalogPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  // 1. Resolver Tenant
  const { data: tenantUsers } = await supabase
    .from('tenant_users')
    .select('tenant_id')
    .eq('user_id', user?.id)
  
  const tenantId = tenantUsers?.[0]?.tenant_id

  // 2. Traer el inventario atado al Tenant
  let products = []
  if (tenantId) {
    const { data } = await supabase
      .from('products')
      .select('id, title, description, product_variations(price, stock_quantity)')
      .eq('tenant_id', tenantId)
      .order('created_at', { ascending: false })
      
    products = data || []
  }

  // 3. Server Action Estricto
  async function addProduct(formData: FormData) {
    'use server'
    const title = formData.get('title') as string
    const desc = formData.get('description') as string
    const price = parseFloat(formData.get('price') as string)
    const stock = parseInt(formData.get('stock') as string)

    const sb = createClient()
    const { data: u } = await sb.auth.getUser()
    const { data: tu } = await sb.from('tenant_users').select('tenant_id').eq('user_id', u.user?.id)
    const t_id = tu?.[0]?.tenant_id

    if (t_id) {
      // Inserción transaccional cruda simple MVP
      const { data: pData } = await sb.from('products').insert({
        tenant_id: t_id,
        title: title,
        description: desc
      }).select().single()

      if (pData) {
        await sb.from('product_variations').insert({
          product_id: pData.id,
          tenant_id: t_id,
          stock_quantity: stock,
          price: price,
          attributes: {"default": "Standard"}
        })
      }
    }
    revalidatePath('/dashboard/catalog')
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Catálogo B2B</h1>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        
        {/* Formulario Lateral */}
        <div className="col-span-1">
          <Card>
            <CardHeader>
              <CardTitle className="text-xl">Añadir Nuevo Artículo</CardTitle>
            </CardHeader>
            <CardContent>
              <form action={addProduct} className="space-y-4">
                <div className="space-y-2">
                  <Label>Nombre de Producto</Label>
                  <Input name="title" placeholder="Ej: Zapatillas Pro V2" required />
                </div>
                <div className="space-y-2">
                  <Label>Descripción Breve</Label>
                  <Input name="description" placeholder="Zapatillas talla 42..." required />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Precio ($)</Label>
                    <Input name="price" type="number" step="0.01" min="0" placeholder="0.00" required />
                  </div>
                  <div className="space-y-2">
                    <Label>Stock</Label>
                    <Input name="stock" type="number" min="0" placeholder="10" required />
                  </div>
                </div>
                <Button type="submit" className="w-full mt-4">Guardar en Base de Datos</Button>
              </form>
            </CardContent>
          </Card>
        </div>

        {/* Tabla Viva */}
        <div className="col-span-2">
          <div className="space-y-4">
            {products.length === 0 ? (
              <div className="p-8 border rounded-lg border-dashed text-center mt-6">
                <p className="text-muted-foreground">Tu catálogo está vacío.</p>
                <p className="text-sm">Agrega productos para que tu IA pueda venderlos por Méta (WhatsApp).</p>
              </div>
            ) : (
              products.map((p) => {
                const varData = p.product_variations?.[0] || { price: 0, stock_quantity: 0 }
                return (
                  <Card key={p.id}>
                    <CardContent className="flex justify-between items-center p-6">
                      <div className="space-y-1">
                        <h4 className="font-semibold text-lg">{p.title}</h4>
                        <p className="text-sm text-muted-foreground">{p.description}</p>
                      </div>
                      <div className="text-right">
                        <p className="font-bold text-xl text-primary">${varData.price}</p>
                        <p className="text-sm">Stock: {varData.stock_quantity}</p>
                      </div>
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
