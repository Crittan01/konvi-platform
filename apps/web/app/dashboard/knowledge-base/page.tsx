import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'

const CATEGORIES = [
  { value: 'faq',      label: 'Preguntas frecuentes' },
  { value: 'politica', label: 'Políticas' },
  { value: 'negocio',  label: 'Información del negocio' },
  { value: 'producto', label: 'Información de productos' },
  { value: 'general',  label: 'General' },
]

const CATEGORY_COLORS: Record<string, string> = {
  faq:      'bg-blue-100 text-blue-800',
  politica: 'bg-purple-100 text-purple-800',
  negocio:  'bg-green-100 text-green-800',
  producto: 'bg-orange-100 text-orange-800',
  general:  'bg-gray-100 text-gray-800',
}

type KbDocument = {
  id: string
  title: string
  content: string
  category: string
  is_active: boolean
  updated_at: string
}

export default async function KnowledgeBasePage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const { data } = await supabase
    .from('kb_documents')
    .select('id, title, content, category, is_active, updated_at')
    .eq('tenant_id', tenantId)
    .order('category')
    .order('updated_at', { ascending: false })

  const documents = (data as KbDocument[]) ?? []
  const activeCount = documents.filter(d => d.is_active).length

  // ── Server Actions ────────────────────────────────────────────────────────

  async function createDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const title    = (formData.get('title') as string).trim()
    const content  = (formData.get('content') as string).trim()
    const category = formData.get('category') as string

    if (!title || !content) return

    await sb.from('kb_documents').insert({
      tenant_id: m.tenant_id,
      title,
      content,
      category: category || 'general',
      is_active: true,
    })
    revalidatePath('/dashboard/knowledge-base')
  }

  async function toggleDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const docId    = formData.get('doc_id') as string
    const isActive = formData.get('is_active') === 'true'

    await sb.from('kb_documents')
      .update({ is_active: !isActive })
      .eq('id', docId)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/knowledge-base')
  }

  async function deleteDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    await sb.from('kb_documents')
      .delete()
      .eq('id', formData.get('doc_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/knowledge-base')
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-primary">Knowledge Base</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {activeCount} documentos activos · La IA los usa al responder por WhatsApp
          </p>
        </div>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      <div className="grid md:grid-cols-3 gap-6">

        {/* ── Formulario nuevo documento ── */}
        {canWrite && (
          <div className="md:col-span-1">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Nuevo documento</CardTitle>
              </CardHeader>
              <CardContent>
                <form action={createDocument} className="space-y-3">
                  <div className="space-y-1">
                    <Label>Título</Label>
                    <Input name="title" placeholder="ej: Política de devoluciones" required />
                  </div>
                  <div className="space-y-1">
                    <Label>Categoría</Label>
                    <select name="category" className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm">
                      {CATEGORIES.map(c => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <Label>Contenido</Label>
                    <textarea
                      name="content"
                      rows={6}
                      required
                      placeholder="Escribe el texto que la IA usará para responder. Ej: 'Aceptamos devoluciones dentro de los 15 días posteriores a la compra. El producto debe estar en perfectas condiciones...'"
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                    <p className="text-xs text-muted-foreground">
                      Escribe en lenguaje natural. La IA lo leerá antes de responder al cliente.
                    </p>
                  </div>
                  <Button type="submit" className="w-full" size="sm">Agregar documento</Button>
                </form>
              </CardContent>
            </Card>
          </div>
        )}

        {/* ── Lista de documentos ── */}
        <div className={canWrite ? 'md:col-span-2' : 'md:col-span-3'}>
          {documents.length === 0 ? (
            <div className="p-8 border border-dashed rounded-lg text-center text-muted-foreground">
              <p className="font-medium">Sin documentos aún.</p>
              <p className="text-sm mt-1">Agrega información sobre tu negocio para que la IA pueda responder mejor.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {documents.map(doc => (
                <Card key={doc.id} className={!doc.is_active ? 'opacity-60' : ''}>
                  <CardContent className="p-4">
                    <div className="flex justify-between items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${CATEGORY_COLORS[doc.category] ?? 'bg-gray-100 text-gray-800'}`}>
                            {CATEGORIES.find(c => c.value === doc.category)?.label ?? doc.category}
                          </span>
                          {!doc.is_active && (
                            <span className="text-xs text-muted-foreground">Inactivo — la IA no lo usa</span>
                          )}
                        </div>
                        <p className="font-medium text-sm">{doc.title}</p>
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{doc.content}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Actualizado: {new Date(doc.updated_at).toLocaleDateString('es-MX')}
                        </p>
                      </div>

                      {canWrite && (
                        <div className="flex gap-2 shrink-0">
                          <form action={toggleDocument}>
                            <input type="hidden" name="doc_id"    value={doc.id} />
                            <input type="hidden" name="is_active" value={String(doc.is_active)} />
                            <Button type="submit" size="sm" variant="outline" className="text-xs">
                              {doc.is_active ? 'Desactivar' : 'Activar'}
                            </Button>
                          </form>
                          <form action={deleteDocument}>
                            <input type="hidden" name="doc_id" value={doc.id} />
                            <Button type="submit" size="sm" variant="ghost" className="text-destructive hover:text-destructive text-xs">
                              Eliminar
                            </Button>
                          </form>
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
