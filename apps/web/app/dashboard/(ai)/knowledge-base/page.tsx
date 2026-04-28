import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SubmitButton } from '@/components/ui/submit-button'
import { BookOpen, Search, BrainCircuit, HelpCircle, FileText, Building2, Package, StickyNote, PenLine, AlertCircle } from 'lucide-react'
import { DocCard } from './doc-card'
import { TemplatesSection } from './templates-section'
import { STARTER_TEMPLATES } from './starter-templates'
import { IndexPendingBanner } from './index-pending-banner'
import { KbMigrationBanner } from './kb-migration-banner'

const MAX_DOCS    = 30
const MAX_CONTENT = 3000
const MAX_TITLE   = 120

// Debe estar a nivel de módulo — NO dentro del componente.
// Los server actions serializan su closure y no pueden capturar funciones del scope del componente.
async function getGeminiEmbedding(text: string): Promise<number[] | null> {
  const key = process.env.GEMINI_API_KEY
  if (!key) {
    console.error('[KB-Embed] GEMINI_API_KEY no configurada en el web service')
    return null
  }
  try {
    const res = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=${key}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: 'models/gemini-embedding-001', content: { parts: [{ text }] }, outputDimensionality: 3072 }),
      }
    )
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      console.error(`[KB-Embed] Gemini ${res.status}: ${body.slice(0, 200)}`)
      return null
    }
    const data = await res.json()
    const values = data.embedding?.values
    if (!values?.length) {
      console.error('[KB-Embed] Respuesta sin values:', JSON.stringify(data).slice(0, 200))
      return null
    }
    return values
  } catch (e) {
    console.error('[KB-Embed] Excepción llamando a Gemini:', e)
    return null
  }
}

// Rev. 68 — 6 categorías canónicas con CHECK constraint en DB.
// "general" eliminada (cajón de sastre). "envios" + "pagos" agregadas.
const CATEGORIES = [
  { value: 'faq',       label: 'FAQ',          icon: HelpCircle },
  { value: 'negocio',   label: 'Negocio',      icon: Building2 },
  { value: 'politicas', label: 'Políticas',    icon: FileText },
  { value: 'productos', label: 'Productos',    icon: Package },
  { value: 'envios',    label: 'Envíos',       icon: StickyNote },
  { value: 'pagos',     label: 'Pagos',        icon: StickyNote },
]

const CATEGORY_COLORS: Record<string, string> = {
  faq:       'bg-blue-500/15 text-blue-400 border border-blue-500/30',
  negocio:   'bg-green-500/15 text-green-400 border border-green-500/30',
  politicas: 'bg-purple-500/15 text-purple-400 border border-purple-500/30',
  productos: 'bg-orange-500/15 text-orange-400 border border-orange-500/30',
  envios:    'bg-cyan-500/15 text-cyan-600 border border-cyan-500/30',
  pagos:     'bg-emerald-500/15 text-emerald-600 border border-emerald-500/30',
}

// Rev. 68 — guía por categoría: qué SÍ y qué NO escribir para evitar
// duplicación con otras fuentes (catálogo, Filosofía del negocio).
const CATEGORY_GUIDES: Record<string, { placeholder: string; doYes: string; doNo: string }> = {
  faq: {
    placeholder: "Ej: ¿Hacen envíos a domicilio? Sí, despachamos a todo Colombia con cobertura por carrier.",
    doYes: "Preguntas frecuentes con respuestas cortas y claras.",
    doNo: "Misión, descripción de productos, info legal.",
  },
  negocio: {
    placeholder: "Ej: Somos una marca colombiana fundada en 2018 por dos hermanos. Hoy tenemos 4 sedes y atendemos toda Latinoamérica.",
    doYes: "Historia, equipo, hitos, alianzas.",
    doNo: "Misión/visión/valores (van en Configuración → Filosofía del negocio).",
  },
  politicas: {
    placeholder: "Ej: Aceptamos devoluciones dentro de los 15 días después de la compra, siempre que el producto esté en su empaque original.",
    doYes: "Devoluciones, cambios, garantía, RMA, privacidad.",
    doNo: "Métodos de pago (Pagos), tarifas de envío (Envíos).",
  },
  productos: {
    placeholder: "Ej: La camiseta de algodón orgánico se debe lavar en agua fría y secar a la sombra para preservar el color.",
    doYes: "Guía de uso, talla, cuidado, accesorios compatibles, instalación.",
    doNo: "Precio, stock, descripción del catálogo (ya están en Productos).",
  },
  envios: {
    placeholder: "Ej: Envíos a Bogotá: 1-2 días, $12.000. Resto del país: 3-5 días, $15.000-$25.000 según ciudad.",
    doYes: "Tarifas/zonas/tiempos por carrier, restricciones, pickup.",
    doNo: "Política de devolución (eso va en Políticas).",
  },
  pagos: {
    placeholder: "Ej: Aceptamos PSE, tarjetas de crédito y débito, Bancolombia, Nequi y efectivo en Efecty. Pago contado: 5% de descuento.",
    doYes: "Métodos aceptados, financiamiento, descuentos por pago contado.",
    doNo: "Datos del banco (sensibles, no deben ir en KB).",
  },
}

type KbDocument = {
  id: string
  title: string
  content: string
  category: string
  is_active: boolean
  updated_at: string
  has_embedding?: boolean
}

export default async function KnowledgeBasePage({
  searchParams,
}: {
  searchParams?: { q?: string; cat?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const canWrite = role === 'owner' || role === 'manager'
  const q   = searchParams?.q ?? ''
  const cat = searchParams?.cat ?? ''

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const [{ data }, { data: withEmb }] = await Promise.all([
    supabase
      .from('kb_documents')
      .select('id, title, content, category, is_active, updated_at')
      .eq('tenant_id', tenantId)
      .order('category')
      .order('updated_at', { ascending: false }),
    // IDs de documentos que ya tienen embedding (RAG activo)
    supabase
      .from('kb_documents')
      .select('id')
      .eq('tenant_id', tenantId)
      .not('embedding', 'is', null),
  ])

  const embeddingIds = new Set((withEmb ?? []).map((r: { id: string }) => r.id))
  let documents = ((data as KbDocument[]) ?? []).map(d => ({
    ...d,
    has_embedding: embeddingIds.has(d.id),
  }))

  // Filtros en memoria
  if (cat) documents = documents.filter(d => d.category === cat)
  if (q)   documents = documents.filter(d =>
    d.title.toLowerCase().includes(q.toLowerCase()) ||
    d.content.toLowerCase().includes(q.toLowerCase())
  )

  const allDocs      = (data as KbDocument[]) ?? []
  const activeCount  = allDocs.filter(d => d.is_active).length
  const totalCount   = allDocs.length
  const embCount     = embeddingIds.size
  const pendingCount = allDocs.filter(d => d.is_active && !embeddingIds.has(d.id)).length
  const atLimit      = totalCount >= MAX_DOCS

  // ── Server Actions ─────────────────────────────────────────────────────────

  async function createDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const title    = (formData.get('title') as string).trim()
    const content  = (formData.get('content') as string).trim()
    const category = formData.get('category') as string
    if (!title || !content) return
    // Límite de caracteres
    if (content.length > MAX_CONTENT || title.length > MAX_TITLE) return
    // Límite de documentos por tenant
    const { count } = await sb.from('kb_documents').select('*', { count: 'exact', head: true }).eq('tenant_id', m.tenant_id)
    if ((count ?? 0) >= MAX_DOCS) return

    const embedding = await getGeminiEmbedding(`Título: ${title}\nContenido: ${content}`)
    await sb.from('kb_documents').insert({
      tenant_id: m.tenant_id, title, content,
      category: category || 'faq', is_active: true,
      embedding: embedding ? `[${embedding.join(',')}]` : null,
    })
    revalidatePath('/dashboard/knowledge-base')
  }

  async function updateDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const docId    = (formData.get('doc_id') as string).trim()
    const title    = (formData.get('title') as string).trim()
    const content  = (formData.get('content') as string).trim()
    const category = formData.get('category') as string
    if (!docId || !title || !content) return
    if (content.length > MAX_CONTENT || title.length > MAX_TITLE) return
    const embedding = await getGeminiEmbedding(`Título: ${title}\nContenido: ${content}`)
    await sb.from('kb_documents').update({
      title, content,
      category: category || 'faq',
      embedding: embedding ? `[${embedding.join(',')}]` : null,
      updated_at: new Date().toISOString(),
    }).eq('id', docId).eq('tenant_id', m.tenant_id)
    redirect('/dashboard/knowledge-base')
  }

  async function regenerateEmbedding(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const docId = formData.get('doc_id') as string
    const { data: doc } = await sb.from('kb_documents').select('title, content')
      .eq('id', docId).eq('tenant_id', m.tenant_id).single()
    if (!doc) return
    const embedding = await getGeminiEmbedding(`Título: ${doc.title}\nContenido: ${doc.content}`)
    if (!embedding) return
    await sb.from('kb_documents').update({
      embedding: `[${embedding.join(',')}]`,
      updated_at: new Date().toISOString(),
    }).eq('id', docId).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/knowledge-base')
  }

  async function activateDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const docId = formData.get('doc_id') as string
    const { data: doc } = await sb.from('kb_documents')
      .select('title, content, embedding')
      .eq('id', docId).eq('tenant_id', m.tenant_id).single()
    if (!doc) return
    const needsEmbed = !doc.embedding
    const embedding = needsEmbed
      ? await getGeminiEmbedding(`Título: ${doc.title}\nContenido: ${doc.content}`)
      : null
    await sb.from('kb_documents').update({
      is_active: true,
      ...(embedding ? { embedding: `[${embedding.join(',')}]` } : {}),
      updated_at: new Date().toISOString(),
    }).eq('id', docId).eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/knowledge-base')
  }

  async function desactivateDocument(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('kb_documents').update({ is_active: false })
      .eq('id', formData.get('doc_id') as string).eq('tenant_id', m.tenant_id)
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

  async function loadSelectedTemplates(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const selectedIds = formData.getAll('template_ids') as string[]
    if (!selectedIds.length) return

    const tenantId = m.tenant_id
    const toInsert = STARTER_TEMPLATES
      .filter(t => selectedIds.includes(t.id))
      .map(t => ({ tenant_id: tenantId, title: t.title, content: t.content, category: t.category, is_active: true }))

    if (!toInsert.length) return
    await sb.from('kb_documents').insert(toInsert)
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
            <span className={totalCount >= MAX_DOCS ? 'text-amber-400 font-medium' : ''}>
              {totalCount}/{MAX_DOCS} documentos
            </span>
            {' · '}{activeCount} activos
            {' · '}<span className="text-emerald-400">{embCount} con RAG</span>
            {embCount < activeCount && <span className="text-muted-foreground/60"> · {activeCount - embCount} sin embedding</span>}
          </p>
        </div>
      </div>

      {/* AI badge */}
      <div className="flex items-start gap-3 rounded-xl border border-green-500/30 bg-green-500/5 px-4 py-3 text-sm text-green-400">
        <BrainCircuit className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          <span className="font-semibold">Base de Conocimiento activa en respuestas.</span>{' '}
          Cuando el cliente pregunta por WhatsApp, el asistente prioriza estos documentos antes de responder para mantener consistencia con tus políticas, productos y operación.
        </span>
      </div>

      {/* Rev. 69 — Banner one-time migración rev. 68 (general → faq + nuevas categorías) */}
      <KbMigrationBanner canWrite={canWrite} />

      {/* Banner documentos pendientes de indexar */}
      <IndexPendingBanner pendingCount={pendingCount} />

      {/* Plantillas — siempre visible, colapsadas si ya hay documentos */}
      {canWrite && (
        <TemplatesSection
          loadSelectedTemplates={loadSelectedTemplates}
          defaultExpanded={totalCount === 0}
        />
      )}

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
              <h2 className="font-semibold text-base mb-1 flex items-center gap-2">
                <PenLine className="h-4 w-4" /> Nuevo documento
              </h2>
              {atLimit ? (
                <div className="flex items-start gap-2 p-3 rounded-lg border border-amber-500/30 bg-amber-500/8 text-xs text-amber-400 mt-3">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                  <span>Límite de {MAX_DOCS} documentos alcanzado. Elimina alguno para agregar nuevos.</span>
                </div>
              ) : (
                <form action={createDocument} className="space-y-3 mt-3">
                  <div className="space-y-1">
                    <Label className="text-xs">Título * <span className="text-muted-foreground font-normal">(máx {MAX_TITLE} chars)</span></Label>
                    <Input name="title" placeholder="Política de devoluciones" required maxLength={MAX_TITLE} className="h-8 text-sm" />
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
                    <Label className="text-xs">Contenido * <span className="text-muted-foreground font-normal">(máx {MAX_CONTENT} chars)</span></Label>
                    <textarea name="content" rows={7} required maxLength={MAX_CONTENT}
                      placeholder="Escribe el texto tal como quieres que la IA lo lea (ver guía abajo según la categoría que elegiste)."
                      className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-primary" />
                    <p className="text-xs text-muted-foreground">La IA usará búsqueda semántica para encontrar el doc más relevante.</p>
                  </div>
                  {/* Rev. 68 — guía por categoría: qué SÍ y qué NO escribir */}
                  <details className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs">
                    <summary className="cursor-pointer font-medium text-foreground/80">
                      💡 Guía por categoría — ejemplos de qué escribir en cada una
                    </summary>
                    <div className="mt-2 space-y-2.5">
                      {CATEGORIES.map(c => {
                        const g = CATEGORY_GUIDES[c.value]
                        if (!g) return null
                        return (
                          <div key={c.value} className="border-l-2 border-primary/30 pl-2.5">
                            <p className="font-semibold text-foreground/90">{c.label}</p>
                            <p className="text-muted-foreground italic">{g.placeholder}</p>
                            <p className="text-emerald-600 mt-0.5">✓ Sí: <span className="text-foreground/80">{g.doYes}</span></p>
                            <p className="text-red-500">✗ No: <span className="text-foreground/80">{g.doNo}</span></p>
                          </div>
                        )
                      })}
                    </div>
                  </details>
                  <SubmitButton className="w-full h-8 text-sm" pendingText="Guardando y generando embedding...">
                    Agregar documento
                  </SubmitButton>
                </form>
              )}
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
              {documents.map(doc => (
                <DocCard
                  key={doc.id}
                  doc={{ ...doc, has_embedding: doc.has_embedding ?? false }}
                  updateDocument={updateDocument}
                  activateDocument={activateDocument}
                  desactivateDocument={desactivateDocument}
                  deleteDocument={deleteDocument}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
