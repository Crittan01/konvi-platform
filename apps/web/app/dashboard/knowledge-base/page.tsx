import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { BookOpen, Search, BrainCircuit, HelpCircle, FileText, Building2, Package, StickyNote, PenLine } from 'lucide-react'

const CATEGORIES = [
  { value: 'faq',      label: 'FAQ',          icon: HelpCircle },
  { value: 'politica', label: 'Políticas',    icon: FileText },
  { value: 'negocio',  label: 'Negocio',      icon: Building2 },
  { value: 'producto', label: 'Productos',    icon: Package },
  { value: 'general',  label: 'General',      icon: StickyNote },
]

const CATEGORY_COLORS: Record<string, string> = {
  faq:      'bg-blue-500/15 text-blue-400 border border-blue-500/30',
  politica: 'bg-purple-500/15 text-purple-400 border border-purple-500/30',
  negocio:  'bg-green-500/15 text-green-400 border border-green-500/30',
  producto: 'bg-orange-500/15 text-orange-400 border border-orange-500/30',
  general:  'bg-muted text-muted-foreground border border-border',
}

type KbDocument = {
  id: string
  title: string
  content: string
  category: string
  is_active: boolean
  updated_at: string
}

export default async function KnowledgeBasePage({
  searchParams,
}: {
  searchParams?: { q?: string; cat?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'
  const q   = searchParams?.q ?? ''
  const cat = searchParams?.cat ?? ''

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const { data } = await supabase
    .from('kb_documents')
    .select('id, title, content, category, is_active, updated_at')
    .eq('tenant_id', tenantId)
    .order('category')
    .order('updated_at', { ascending: false })

  let documents = (data as KbDocument[]) ?? []

  // Filtros en memoria
  if (cat) documents = documents.filter(d => d.category === cat)
  if (q)   documents = documents.filter(d =>
    d.title.toLowerCase().includes(q.toLowerCase()) ||
    d.content.toLowerCase().includes(q.toLowerCase())
  )

  const activeCount = ((data as KbDocument[]) ?? []).filter(d => d.is_active).length
  const totalCount  = ((data as KbDocument[]) ?? []).length

  // ── Server Actions ─────────────────────────────────────────────────────────

  async function createDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const title   = (formData.get('title') as string).trim()
    const content = (formData.get('content') as string).trim()
    const category = formData.get('category') as string
    if (!title || !content) return
    await sb.from('kb_documents').insert({
      tenant_id: m.tenant_id, title, content, category: category || 'general', is_active: true,
    })
    revalidatePath('/dashboard/knowledge-base')
  }

  async function toggleDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const docId    = formData.get('doc_id') as string
    const isActive = formData.get('is_active') === 'true'
    await sb.from('kb_documents').update({ is_active: !isActive }).eq('id', docId).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/knowledge-base')
  }

  async function deleteDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('kb_documents').delete()
      .eq('id', formData.get('doc_id') as string).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/knowledge-base')
  }

  // ── UI ─────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-primary" /> Knowledge Base
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {totalCount} documentos · {activeCount} activos · La IA los usa al responder por WhatsApp
          </p>
        </div>
      </div>

      {/* AI badge */}
      <div className="flex items-start gap-3 rounded-xl border border-yellow-500/30 bg-yellow-500/5 px-4 py-3 text-sm text-yellow-400">
        <BrainCircuit className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          <span className="font-semibold">Modo: inyección de texto plano.</span>{' '}
          Los documentos activos se incluyen como contexto en cada conversación. RAG con embeddings (pgvector) planificado — ver OQ-T03.
        </span>
      </div>

      {/* Búsqueda y filtros de categoría */}
      <div className="flex flex-col sm:flex-row gap-3">
        <form method="GET" className="flex gap-2 flex-1">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              name="q"
              defaultValue={q}
              placeholder="Buscar en título o contenido..."
              className="w-full pl-9 pr-3 py-2 text-sm rounded-xl border border-border bg-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
          {cat && <input type="hidden" name="cat" value={cat} />}
          <Button type="submit" size="sm" variant="outline" className="h-9">Buscar</Button>
        </form>
        {/* Filtros de categoría — scrollable */}
        <div className="flex gap-1.5 overflow-x-auto pb-0.5">
          {[{ value: '', label: 'Todas', icon: Search }, ...CATEGORIES].map(opt => {
            const Icon = opt.icon
            return (
              <a key={opt.value}
                href={`/dashboard/knowledge-base?cat=${opt.value}${q ? `&q=${encodeURIComponent(q)}` : ''}`}
                className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                  cat === opt.value
                    ? 'bg-primary/15 text-primary border-primary/40'
                    : 'border-border text-muted-foreground hover:text-foreground'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {opt.label}
              </a>
            )
          })}
        </div>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

        {/* Formulario nuevo documento */}
        {canWrite && (
          <div className="xl:col-span-1">
            <div className="rounded-xl border border-border bg-card p-5 sticky top-4">
              <h2 className="font-semibold text-base mb-4 flex items-center gap-2"><PenLine className="h-4 w-4" /> Nuevo documento</h2>
              <form action={createDocument} className="space-y-3">
                <div className="space-y-1">
                  <Label className="text-xs">Título *</Label>
                  <Input name="title" placeholder="Política de devoluciones" required className="h-8 text-sm" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Categoría</Label>
                  <select name="category"
                    className="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary">
                    {CATEGORIES.map(c => (
                      <option key={c.value} value={c.value}>{c.label}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Contenido *</Label>
                  <textarea
                    name="content"
                    rows={7}
                    required
                    placeholder="Escribe el texto tal como quieres que la IA lo lea. Ej: 'Aceptamos devoluciones dentro de los 15 días...'"
                    className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                  <p className="text-xs text-muted-foreground">La IA lo leerá antes de responder al cliente.</p>
                </div>
                <Button type="submit" className="w-full h-8 text-sm">Agregar documento</Button>
              </form>
            </div>
          </div>
        )}

        {/* Lista de documentos */}
        <div className={canWrite ? 'xl:col-span-2' : 'xl:col-span-3'}>
          {documents.length === 0 ? (
            <div className="flex flex-col items-center py-16 rounded-xl border border-dashed border-border text-center">
              <BookOpen className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground text-sm font-medium">
                {q || cat ? 'Sin resultados para los filtros aplicados.' : 'Sin documentos aún.'}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {!q && !cat && 'Agrega información sobre tu negocio para mejorar las respuestas de la IA.'}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {documents.map(doc => {
                const catInfo = CATEGORIES.find(c => c.value === doc.category)
                return (
                  <div key={doc.id}
                    className={`rounded-xl border bg-card p-4 transition-all hover:shadow-sm ${
                      doc.is_active ? 'border-border' : 'border-border/50 opacity-60'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        {/* Categoría + estado */}
                        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                          <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full ${CATEGORY_COLORS[doc.category] ?? 'bg-muted text-muted-foreground'}`}>
                            {catInfo?.icon && <catInfo.icon className="h-3 w-3 shrink-0" />}
                            {catInfo?.label ?? doc.category}
                          </span>
                          {!doc.is_active && (
                            <span className="text-[11px] text-muted-foreground border border-border rounded-full px-2 py-0.5">
                              Inactivo
                            </span>
                          )}
                        </div>
                        <p className="font-medium text-sm">{doc.title}</p>
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2 leading-relaxed">{doc.content}</p>
                        <p className="text-[11px] text-muted-foreground/70 mt-2">
                          Actualizado: {new Date(doc.updated_at).toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' })}
                        </p>
                      </div>

                      {/* Acciones */}
                      {canWrite && (
                        <div className="flex flex-col gap-1.5 shrink-0">
                          <form action={toggleDocument}>
                            <input type="hidden" name="doc_id"    value={doc.id} />
                            <input type="hidden" name="is_active" value={String(doc.is_active)} />
                            <Button type="submit" size="sm" variant="outline" className="text-xs h-7 w-full">
                              {doc.is_active ? 'Desactivar' : 'Activar'}
                            </Button>
                          </form>
                          <form action={deleteDocument}>
                            <input type="hidden" name="doc_id" value={doc.id} />
                            <Button type="submit" size="sm" variant="ghost"
                              className="text-destructive hover:text-destructive hover:bg-destructive/10 text-xs h-7 w-full">
                              Eliminar
                            </Button>
                          </form>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
