/**
 * POST /api/ai/index-pending
 * Genera embeddings para todos los documentos KB activos sin embedding del tenant.
 * Separado del server action para evitar timeouts — cada llamada a Gemini toma ~1s.
 *
 * Seguridad (paridad con el router API /reindex): exige rol de escritura
 * (owner/manager) y aplica rate-limit por tenant — un operator no puede disparar
 * embeds masivos facturables. Cada corrida deja un evento en audit_log.
 */
import { type NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'

export const maxDuration = 60  // API Route puede tomar hasta 60s

// gemini-embedding-001 se retira 2026-07-14 → gemini-embedding-2 (3072-dim, mismo
// modelo que el orchestrator; override por env GEMINI_EMBEDDING_MODEL de render.yaml
// para que los embeddings web y del worker sean del MISMO espacio vectorial).
const EMBED_MODEL = process.env.GEMINI_EMBEDDING_MODEL ?? 'gemini-embedding-2'
const EMBED_DIM = 3072
// Versión registrada en kb_documents.embedding_model_version — MISMO formato que
// llm_embed.get_embedding_model_version() ("<model>:<dim>") para detección de drift.
const EMBED_MODEL_VERSION = `${EMBED_MODEL}:${EMBED_DIM}`
const EMBED_URL = (key: string) =>
  `https://generativelanguage.googleapis.com/v1beta/models/${EMBED_MODEL}:embedContent?key=${key}`

// Rate limit: 6 corridas / hora / tenant. In-memory (instancia única Render Free),
// mismo patrón que /api/ai/preview e /api/insights. Cada corrida es facturable.
const INDEX_LIMIT = 6
const INDEX_WINDOW = 60 * 60 * 1000
const _rl = new Map<string, { count: number; resetAt: number }>()

function checkLimit(tenantId: string): { ok: boolean; resetIn: number } {
  const now = Date.now()
  const entry = _rl.get(tenantId)
  if (!entry || now > entry.resetAt) {
    _rl.set(tenantId, { count: 1, resetAt: now + INDEX_WINDOW })
    return { ok: true, resetIn: INDEX_WINDOW }
  }
  if (entry.count >= INDEX_LIMIT) return { ok: false, resetIn: entry.resetAt - now }
  entry.count++
  return { ok: true, resetIn: entry.resetAt - now }
}

async function embedText(text: string, key: string): Promise<number[] | null> {
  try {
    const res = await fetch(EMBED_URL(key), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: `models/${EMBED_MODEL}`, content: { parts: [{ text }] }, outputDimensionality: EMBED_DIM }),
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      console.error(`[index-pending] Gemini ${res.status}: ${body.slice(0, 200)}`)
      return null
    }
    const data = await res.json()
    return data.embedding?.values ?? null
  } catch (e) {
    console.error('[index-pending] Excepción Gemini:', e)
    return null
  }
}

export async function POST(_request: NextRequest) {
  const key = process.env.GEMINI_API_KEY
  if (!key) return NextResponse.json({ error: 'GEMINI_API_KEY no configurada' }, { status: 503 })

  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'No autenticado' }, { status: 401 })

  const m = (user.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id) return NextResponse.json({ error: 'Sin tenant' }, { status: 403 })
  // Paridad con /api/v1/knowledge-base/{id}/reindex: solo roles de escritura.
  if (!['owner', 'manager'].includes(m.role ?? '')) {
    return NextResponse.json({ error: 'No tienes permiso para preparar documentos.' }, { status: 403 })
  }

  const tenantId = m.tenant_id

  const rl = checkLimit(tenantId)
  if (!rl.ok) {
    const minutos = Math.ceil(rl.resetIn / 60000)
    return NextResponse.json(
      { error: `Límite de preparaciones por hora alcanzado. Disponible en ${minutos} min.` },
      { status: 429 },
    )
  }

  // Cargar docs sin embedding
  const { data: pending } = await supabase
    .from('kb_documents')
    .select('id, title, content')
    .eq('tenant_id', tenantId)
    .eq('is_active', true)
    .is('embedding', null)

  if (!pending?.length) return NextResponse.json({ indexed: 0, total: 0 })

  let indexed = 0
  for (const doc of pending) {
    const embedding = await embedText(`Título: ${doc.title}\nContenido: ${doc.content}`, key)
    if (embedding) {
      await supabase.from('kb_documents').update({
        embedding: `[${embedding.join(',')}]`,
        embedding_model_version: EMBED_MODEL_VERSION,
        updated_at: new Date().toISOString(),
      }).eq('id', doc.id).eq('tenant_id', tenantId)
      indexed++
    }
  }

  // Audit trail (best-effort): quién preparó cuántos docs y con qué modelo.
  try {
    await supabase.from('audit_log').insert({
      tenant_id: tenantId,
      user_id: user.id,
      user_email: user.email,
      action: 'kb_doc.indexed_batch',
      entity_type: 'kb_doc',
      entity_id: null,
      payload: { indexed, total: pending.length, model_version: EMBED_MODEL_VERSION },
    })
  } catch (e) {
    console.error(`[index-pending] audit_log insert failed tenant=${tenantId}:`, e)
  }

  return NextResponse.json({ indexed, total: pending.length })
}
