import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { BookOpen, Search, BrainCircuit, PenLine, AlertCircle, ShieldAlert } from 'lucide-react'
import { DocCard } from './doc-card'
import { TemplatesSection } from './templates-section'
import { STARTER_TEMPLATES } from './starter-templates'
import { IndexPendingBanner } from './index-pending-banner'
import { KbMigrationBanner } from './kb-migration-banner'
import { NewDocForm } from './new-doc-form'
import { KB_CATEGORIES } from './categories'
import { ok, fail, type ActionResult } from '@/lib/action-result'
import { CORE_API_URL } from '@/lib/runtime-env'

const MAX_DOCS    = 30
const MAX_CONTENT = 3000
const MAX_TITLE   = 120

// Rev. 72 — los embeddings se calculan ahora server-side en el API
// (POST /api/v1/knowledge-base). GEMINI_API_KEY ya NO se expone al
// frontend (cierra drift D3). Helper local para autorizar las llamadas.
async function authedApi(supabase: Awaited<ReturnType<typeof createClient>>, path: string, options: RequestInit = {}): Promise<Response> {
  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token ?? ''
  return fetch(`${CORE_API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(options.headers ?? {}),
    },
  })
}

// Traduce el status del API a un mensaje accionable en es-CO para el toast.
// Consume el body una sola vez (Response.json no es reutilizable).
async function friendlyError(res: Response, fallback: string): Promise<string> {
  let detail = ''
  try {
    const j = await res.json()
    detail = typeof j?.detail === 'string' ? j.detail : ''
  } catch { /* body vacío o no-JSON */ }
  if (res.status === 401 || res.status === 403) return 'No tienes permiso para realizar esta acción.'
  if (res.status === 409) return detail || `Alcanzaste el límite de ${MAX_DOCS} documentos. Elimina o desactiva alguno para agregar nuevos.`
  if (res.status === 422) return detail || 'Los datos del documento no son válidos.'
  if (res.status === 502 || res.status === 503) return 'El servicio de preparación para IA no está disponible. Reintenta en unos minutos.'
  return detail || fallback
}

// Rev. 68 — 6 categorías canónicas con CHECK constraint en DB.
// Fuente única en ./categories.ts (empata router + DB, evita el drift legacy).
const CATEGORIES = KB_CATEGORIES

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

export default async function KnowledgeBasePage(
  props: {
    searchParams?: Promise<{ q?: string; cat?: string }>
  }
) {
  const searchParams = await props.searchParams;
  // Sem 5 perf: cached.
  const user = await getCachedUser()
  if (!user) redirect('/login')
  const { tenantId, role } = await getCachedTenantMeta()
  // Módulo exclusivo owner/manager (paridad con require_write_role del router
  // /api/v1/knowledge-base y con el sidebar, que ya oculta el link a operators).
  // Sin este guard, un operator podía cargar la ruta por URL directa en
  // solo-lectura — inconsistente con "quién puede escribir es quién ve el módulo".
  // Patrón canónico: mismo redirect que integrations/wompi/page.tsx.
  if (role === 'operator') redirect('/dashboard')
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = await createClient()
  const q   = searchParams?.q ?? ''
  const cat = searchParams?.cat ?? ''

  if (!tenantId) {
    return (
      <EmptyState
        variant="plain"
        icon={ShieldAlert}
        className="p-8"
        title="Sin acceso"
        description="Tenant no configurado."
      />
    )
  }

  const [{ data }, { data: withEmb }] = await Promise.all([
    supabase
      .from('kb_documents')
      .select('id, title, content, category, is_active, updated_at')
      .eq('tenant_id', tenantId)
      .order('category')
      .order('updated_at', { ascending: false }),
    // IDs de documentos LISTOS para IA. match_kb_documents exige is_active=true,
    // así que un doc inactivo con embedding NO cuenta como "listo" (evita inflar
    // el contador del header con docs que el bot nunca usa).
    supabase
      .from('kb_documents')
      .select('id')
      .eq('tenant_id', tenantId)
      .eq('is_active', true)
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
  // El cap acota los docs ACTIVOS (los inactivos no participan en RAG ni consumen
  // cupo). Empata knowledge_base.py: desactivar/eliminar libera cupo sin borrar datos.
  const atLimit      = activeCount >= MAX_DOCS

  // Rev. 71 — categorías sin docs activos. Se exponen al form para destacar
  // visualmente cuáles faltan (el bot no puede responder con verdad sin ellas).
  const filledCategories = new Set(allDocs.filter(d => d.is_active).map(d => d.category))
  const emptyCategories  = CATEGORIES.map(c => c.value).filter(v => !filledCategories.has(v))

  // ── Server Actions ─────────────────────────────────────────────────────────

  // Rev. 72 — todas las server actions delegan al router /api/v1/knowledge-base.
  // El embedding se calcula server-side en el API (GEMINI_API_KEY ya NO se expone al frontend).
  // F1 2026-07 — devuelven ActionResult: el fallo (409/422/403/502) se surfacea al
  // operador vía toast en vez de morir en un console.error del server.
  async function createDocument(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const title    = (formData.get('title') as string || '').trim()
    const content  = (formData.get('content') as string || '').trim()
    const category = (formData.get('category') as string) || 'faq'
    if (!title || !content) return fail('El título y el contenido son obligatorios.')
    if (title.length > MAX_TITLE) return fail(`El título excede ${MAX_TITLE} caracteres.`)
    if (content.length > MAX_CONTENT) return fail(`El contenido excede ${MAX_CONTENT} caracteres.`)
    const res = await authedApi(sb, '/api/v1/knowledge-base/', {
      method: 'POST',
      body: JSON.stringify({ title, content, category }),
    })
    if (!res.ok) {
      const msg = await friendlyError(res, 'No se pudo crear el documento.')
      console.error(`[kb] createDocument failed tenant=${tenantId} status=${res.status}: ${msg}`)
      return fail(msg)
    }
    revalidatePath('/dashboard/knowledge-base')
    return ok()
  }

  async function updateDocument(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const docId    = (formData.get('doc_id') as string || '').trim()
    const title    = (formData.get('title') as string || '').trim()
    const content  = (formData.get('content') as string || '').trim()
    const category = (formData.get('category') as string) || 'faq'
    if (!docId) return fail('Documento no identificado.')
    if (!title || !content) return fail('El título y el contenido son obligatorios.')
    if (title.length > MAX_TITLE) return fail(`El título excede ${MAX_TITLE} caracteres.`)
    if (content.length > MAX_CONTENT) return fail(`El contenido excede ${MAX_CONTENT} caracteres.`)
    const res = await authedApi(sb, `/api/v1/knowledge-base/${docId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title, content, category }),
    })
    if (!res.ok) {
      const msg = await friendlyError(res, 'No se pudieron guardar los cambios.')
      console.error(`[kb] updateDocument failed tenant=${tenantId} doc=${docId} status=${res.status}: ${msg}`)
      return fail(msg)
    }
    revalidatePath('/dashboard/knowledge-base')
    return ok()
  }

  async function activateDocument(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const docId = (formData.get('doc_id') as string || '').trim()
    if (!docId) return fail('Documento no identificado.')
    // Activar = solo PATCH is_active=true. Desactivar NO borra el embedding, así que
    // reactivar restaura el RAG sin re-embeber. Si el doc quedó sin preparar (embedding
    // NULL), la card muestra "Error al preparar — reintentar" → reindexDocument.
    const res = await authedApi(sb, `/api/v1/knowledge-base/${docId}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: true }),
    })
    if (!res.ok) {
      const msg = await friendlyError(res, 'No se pudo activar el documento.')
      console.error(`[kb] activateDocument failed tenant=${tenantId} doc=${docId} status=${res.status}: ${msg}`)
      return fail(msg)
    }
    revalidatePath('/dashboard/knowledge-base')
    return ok()
  }

  async function reindexDocument(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const docId = (formData.get('doc_id') as string || '').trim()
    if (!docId) return fail('Documento no identificado.')
    // Fuerza re-preparación (re-embed) — solo para docs que quedaron con embedding NULL
    // (Gemini caído al crear). NO se llama en cada activación (evita gasto Gemini inútil).
    const res = await authedApi(sb, `/api/v1/knowledge-base/${docId}/reindex`, { method: 'POST' })
    if (!res.ok) {
      const msg = await friendlyError(res, 'No se pudo preparar el documento para la IA.')
      console.error(`[kb] reindexDocument failed tenant=${tenantId} doc=${docId} status=${res.status}: ${msg}`)
      return fail(msg)
    }
    revalidatePath('/dashboard/knowledge-base')
    return ok()
  }

  async function desactivateDocument(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const docId = (formData.get('doc_id') as string || '').trim()
    if (!docId) return fail('Documento no identificado.')
    const res = await authedApi(sb, `/api/v1/knowledge-base/${docId}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: false }),
    })
    if (!res.ok) {
      const msg = await friendlyError(res, 'No se pudo desactivar el documento.')
      console.error(`[kb] desactivateDocument failed tenant=${tenantId} doc=${docId} status=${res.status}: ${msg}`)
      return fail(msg)
    }
    revalidatePath('/dashboard/knowledge-base')
    return ok()
  }

  async function deleteDocument(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const docId = (formData.get('doc_id') as string || '').trim()
    if (!docId) return fail('Documento no identificado.')
    const res = await authedApi(sb, `/api/v1/knowledge-base/${docId}`, { method: 'DELETE' })
    if (!res.ok) {
      const msg = await friendlyError(res, 'No se pudo eliminar el documento.')
      console.error(`[kb] deleteDocument failed tenant=${tenantId} doc=${docId} status=${res.status}: ${msg}`)
      return fail(msg)
    }
    revalidatePath('/dashboard/knowledge-base')
    return ok()
  }

  async function loadSelectedTemplates(formData: FormData): Promise<ActionResult> {
    'use server'
    const sb = await createClient()
    const selectedIds = formData.getAll('template_ids') as string[]
    if (!selectedIds.length) return fail('No seleccionaste ninguna plantilla.')

    const templates = STARTER_TEMPLATES.filter(t => selectedIds.includes(t.id))
    if (!templates.length) return fail('No seleccionaste ninguna plantilla válida.')

    // Idempotencia: no dupliques plantillas ya cargadas (doble clic / reintento).
    // Se dedupe por título contra los docs existentes del tenant.
    const { data: existing } = await sb
      .from('kb_documents')
      .select('title')
      .eq('tenant_id', tenantId)
    const existingTitles = new Set((existing ?? []).map((r: { title: string }) => r.title.trim()))
    const toCreate = templates.filter(t => !existingTitles.has(t.title.trim()))
    const skipped = templates.length - toCreate.length

    // Rev. 72 — cada template pasa por POST /api/v1/knowledge-base que calcula
    // embedding server-side. Serial para respetar rate-limit de Gemini.
    let created = 0
    for (const t of toCreate) {
      const res = await authedApi(sb, '/api/v1/knowledge-base/', {
        method: 'POST',
        body: JSON.stringify({ title: t.title, content: t.content, category: t.category }),
      })
      if (!res.ok) {
        const msg = await friendlyError(res, 'No se pudo cargar una de las plantillas.')
        console.error(`[kb] loadSelectedTemplates failed tenant=${tenantId} template=${t.id} status=${res.status}: ${msg}`)
        revalidatePath('/dashboard/knowledge-base')
        // Reporta lo que sí entró antes de abortar.
        return fail(created > 0 ? `Se cargaron ${created} plantilla(s); la siguiente falló: ${msg}` : msg)
      }
      created++
    }
    revalidatePath('/dashboard/knowledge-base')
    if (created === 0) return ok('Esas plantillas ya estaban cargadas.')
    const suffix = skipped > 0 ? ` (${skipped} ya existían y se omitieron)` : ''
    return ok(`${created} plantilla(s) cargada(s)${suffix}.`)
  }

  // ── UI ─────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-primary" /> Base de Conocimiento
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            <span className={atLimit ? 'text-amber-700 font-medium' : ''}>
              {activeCount}/{MAX_DOCS} activos
            </span>
            {totalCount > activeCount && <>{' · '}{totalCount - activeCount} inactivos</>}
            {' · '}<span className="text-emerald-700">{embCount} listos para IA</span>
            {embCount < activeCount && <span className="text-muted-foreground/60"> · {activeCount - embCount} por preparar</span>}
          </p>
        </div>
      </div>

      {/* AI badge */}
      <div className="flex items-start gap-3 rounded-xl border border-green-700/30 bg-green-500/5 px-4 py-3 text-sm text-green-700">
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
              className="w-full pl-9 pr-3 py-2 text-sm rounded-xl border border-border bg-background placeholder:text-muted-foreground focus:outline-hidden focus:ring-1 focus:ring-primary"
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
                className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
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
                <div className="flex items-start gap-2 p-3 rounded-lg border border-amber-700/30 bg-amber-500/8 text-xs text-amber-700 mt-3">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                  <span>Límite de {MAX_DOCS} documentos activos alcanzado. Desactiva o elimina alguno para agregar nuevos.</span>
                </div>
              ) : (
                <NewDocForm
                  categories={CATEGORIES.map(c => ({ value: c.value, label: c.label }))}
                  guides={CATEGORY_GUIDES}
                  emptyCategories={emptyCategories}
                  maxTitle={MAX_TITLE}
                  maxContent={MAX_CONTENT}
                  createDocument={createDocument}
                />
              )}
            </div>
          </div>
        )}

        {/* Lista de documentos */}
        <div className={canWrite ? 'xl:col-span-2' : 'xl:col-span-3'}>
          {documents.length === 0 ? (
            <EmptyState
              icon={BookOpen}
              className="py-16"
              title={q || cat ? 'Sin resultados para los filtros aplicados.' : 'Sin documentos aún.'}
              description={
                !q && !cat
                  ? 'Agrega información sobre tu negocio para mejorar las respuestas de la IA.'
                  : undefined
              }
            />
          ) : (
            <div className="space-y-3">
              {documents.map(doc => (
                <DocCard
                  key={doc.id}
                  doc={{ ...doc, has_embedding: doc.has_embedding ?? false }}
                  canWrite={canWrite}
                  updateDocument={updateDocument}
                  activateDocument={activateDocument}
                  reindexDocument={reindexDocument}
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
