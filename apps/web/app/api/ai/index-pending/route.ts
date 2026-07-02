/**
 * POST /api/ai/index-pending
 * Genera embeddings para todos los documentos KB activos sin embedding del tenant.
 * Separado del server action para evitar timeouts — cada llamada a Gemini toma ~1s.
 */
import { type NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'

export const maxDuration = 60  // API Route puede tomar hasta 60s

const EMBED_URL = (key: string) =>
  `https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=${key}`

async function embedText(text: string, key: string): Promise<number[] | null> {
  try {
    const res = await fetch(EMBED_URL(key), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'models/gemini-embedding-001', content: { parts: [{ text }] }, outputDimensionality: 3072 }),
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

  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'No autenticado' }, { status: 401 })

  const m = (user.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id) return NextResponse.json({ error: 'Sin tenant' }, { status: 403 })

  const tenantId = m.tenant_id

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
        updated_at: new Date().toISOString(),
      }).eq('id', doc.id).eq('tenant_id', tenantId)
      indexed++
    }
  }

  return NextResponse.json({ indexed, total: pending.length })
}
