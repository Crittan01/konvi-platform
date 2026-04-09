import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'

type Contact = {
  id: string
  phone: string
  name: string | null
  notes: string | null
  created_at: string
}

export default async function ContactsPage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  let contacts: Contact[] = []

  if (tenantId) {
    const { data } = await supabase
      .from('contacts')
      .select('id, phone, name, notes, created_at')
      .eq('tenant_id', tenantId)
      .order('name', { ascending: true, nullsFirst: false })
    contacts = (data as Contact[]) || []
  }

  // ── Server Actions ────────────────────────────────────────────────────────

  async function addContact(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    await sb.from('contacts').insert({
      tenant_id: m.tenant_id,
      phone: formData.get('phone') as string,
      name: formData.get('name') as string || null,
      notes: formData.get('notes') as string || null,
    })
    revalidatePath('/dashboard/contacts')
  }

  async function editContact(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    await sb.from('contacts')
      .update({
        name: formData.get('name') as string || null,
        notes: formData.get('notes') as string || null,
      })
      .eq('id', formData.get('contact_id') as string)
      .eq('tenant_id', m.tenant_id)

    revalidatePath('/dashboard/contacts')
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Contactos</h1>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">{contacts.length} contactos</span>
          <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* Formulario agregar */}
        {canWrite && (
          <div className="col-span-1">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Agregar Contacto</CardTitle>
              </CardHeader>
              <CardContent>
                <form action={addContact} className="space-y-4">
                  <div className="space-y-2">
                    <Label>Teléfono</Label>
                    <Input name="phone" placeholder="+52 55 1234 5678" required />
                    <p className="text-xs text-muted-foreground">Debe ser único por tenant.</p>
                  </div>
                  <div className="space-y-2">
                    <Label>Nombre</Label>
                    <Input name="name" placeholder="Juan García" />
                  </div>
                  <div className="space-y-2">
                    <Label>Notas</Label>
                    <Input name="notes" placeholder="Cliente frecuente..." />
                  </div>
                  <Button type="submit" className="w-full">Guardar contacto</Button>
                </form>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Lista */}
        <div className={canWrite ? 'col-span-2' : 'col-span-3'}>
          <div className="space-y-3">
            {contacts.length === 0 ? (
              <div className="p-8 border rounded-lg border-dashed text-center">
                <p className="text-muted-foreground">No hay contactos registrados.</p>
                {canWrite && (
                  <p className="text-sm text-muted-foreground mt-1">
                    Agrégalos manualmente. En futuras versiones se auto-poblarán desde conversaciones WhatsApp.
                  </p>
                )}
              </div>
            ) : (
              contacts.map((c) => (
                <Card key={c.id}>
                  <CardContent className="p-5">
                    <div className="flex justify-between items-start mb-1">
                      <div>
                        <p className="font-medium">{c.name || <span className="text-muted-foreground italic">Sin nombre</span>}</p>
                        <p className="text-sm font-mono text-muted-foreground">{c.phone}</p>
                        {c.notes && <p className="text-xs text-muted-foreground mt-1">{c.notes}</p>}
                      </div>
                      <p className="text-xs text-muted-foreground shrink-0 ml-4">
                        {new Date(c.created_at).toLocaleDateString('es-MX')}
                      </p>
                    </div>

                    {canWrite && (
                      <details className="mt-3">
                        <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground select-none">
                          Editar
                        </summary>
                        <form action={editContact} className="mt-3 space-y-3">
                          <input type="hidden" name="contact_id" value={c.id} />
                          <div className="grid grid-cols-2 gap-3">
                            <div className="space-y-1">
                              <Label className="text-xs">Nombre</Label>
                              <Input name="name" defaultValue={c.name ?? ''} />
                            </div>
                            <div className="space-y-1">
                              <Label className="text-xs">Notas</Label>
                              <Input name="notes" defaultValue={c.notes ?? ''} />
                            </div>
                          </div>
                          <Button type="submit" size="sm">Guardar</Button>
                        </form>
                      </details>
                    )}
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
