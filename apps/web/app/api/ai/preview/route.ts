/**
 * POST /api/ai/preview
 * Genera una respuesta de prueba del bot con RAG real + config actual del tenant.
 * Permite al operador ver cómo respondería el bot antes de activarlo en producción.
 */
import { type NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'

const GEMINI_API_KEY = process.env.GEMINI_API_KEY ?? ''
const EMBED_URL = `https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key=${GEMINI_API_KEY}`
const CHAT_URL  = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${GEMINI_API_KEY}`

// Rate limit: 20 llamadas / hora / tenant
// In-memory — válido para instancia única (Render Free). Suficiente para uso de configuración.
const PREVIEW_LIMIT   = 20
const PREVIEW_WINDOW  = 60 * 60 * 1000  // 1 hora en ms
const _rl = new Map<string, { count: number; resetAt: number }>()

function checkLimit(tenantId: string): { ok: boolean; remaining: number; resetIn: number } {
  const now = Date.now()
  const entry = _rl.get(tenantId)
  if (!entry || now > entry.resetAt) {
    _rl.set(tenantId, { count: 1, resetAt: now + PREVIEW_WINDOW })
    return { ok: true, remaining: PREVIEW_LIMIT - 1, resetIn: PREVIEW_WINDOW }
  }
  if (entry.count >= PREVIEW_LIMIT) {
    return { ok: false, remaining: 0, resetIn: entry.resetAt - now }
  }
  entry.count++
  return { ok: true, remaining: PREVIEW_LIMIT - entry.count, resetIn: entry.resetAt - now }
}

const TONO_DESC: Record<string, string> = {
  formal:       'Usa un tono formal y respetuoso.',
  profesional:  'Usa un tono profesional y preciso.',
  amigable:     'Usa un tono amigable y cercano.',
  cercano:      'Usa un tono casual y conversacional.',
  juvenil:      'Usa un tono dinámico, fresco y puedes usar algún emoji.',
}

export async function POST(request: NextRequest) {
  if (!GEMINI_API_KEY) {
    return NextResponse.json({ error: 'GEMINI_API_KEY no configurada' }, { status: 503 })
  }

  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) return NextResponse.json({ error: 'No autenticado' }, { status: 401 })

  const m = (user.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id) return NextResponse.json({ error: 'Sin tenant' }, { status: 403 })

  const rl = checkLimit(m.tenant_id)
  if (!rl.ok) {
    const minutos = Math.ceil(rl.resetIn / 60000)
    return NextResponse.json(
      { error: `Límite de ${PREVIEW_LIMIT} pruebas por hora alcanzado. Disponible en ${minutos} min.` },
      { status: 429 }
    )
  }

  let message = ''
  try {
    const body = await request.json()
    message = (body.message as string)?.trim() ?? ''
  } catch {
    return NextResponse.json({ error: 'Body inválido' }, { status: 400 })
  }
  if (!message) return NextResponse.json({ error: 'Mensaje requerido' }, { status: 400 })
  if (message.length > 500) return NextResponse.json({ error: 'Mensaje demasiado largo (máx 500 chars)' }, { status: 400 })

  const tenantId = m.tenant_id

  // ── 1. Cargar contexto del tenant en paralelo ─────────────────────────────
  const [tenantRes, agentRes, catalogRes] = await Promise.all([
    supabase.from('tenants')
      .select('name, mision, vision, valores, tono_comunicacion, store_type')
      .eq('id', tenantId).single(),
    supabase.from('ai_agents')
      .select('name, role_description, strict_guardrails')
      .eq('tenant_id', tenantId).maybeSingle(),
    supabase.from('products')
      // F7: la tabla products usa columnas title/status (no name/is_active, que nunca
      // existieron) — PostgREST erroraba y el catálogo salía SIEMPRE vacío → el preview
      // respondía sin conocer producto alguno. Alineado con dashboard/catalog/orders pages.
      .select('title, description, product_variations(price, stock_quantity, attributes)')
      .eq('tenant_id', tenantId)
      .eq('status', 'active')
      .limit(20),
  ])

  const tenant  = tenantRes.data
  const catalog = (catalogRes.data ?? []) as Array<{ title: string; description?: string; product_variations?: Array<{ price: number; stock_quantity: number; attributes?: Record<string, string> }> }>
  const agent  = agentRes.data ?? {
    name: 'Vendedor Oficial',
    role_description: 'Eres el asistente de ventas. Ayuda al cliente cordialmente.',
    strict_guardrails: true,
  }

  // ── 2. RAG: buscar documentos KB relevantes ───────────────────────────────
  let kbText   = ''
  let kbUsed   = false
  let kbCount  = 0
  try {
    const embedRes = await fetch(EMBED_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'models/gemini-embedding-001', content: { parts: [{ text: message }] }, outputDimensionality: 3072 }),
    })
    if (embedRes.ok) {
      const embedData = await embedRes.json()
      const vector = embedData.embedding?.values as number[] | undefined
      if (vector?.length) {
        const kbRes = await supabase.rpc('match_kb_documents', {
          query_embedding: vector,
          match_threshold: 0.4,
          match_count: 3,
          t_id: tenantId,
        })
        if (kbRes.data?.length) {
          kbUsed  = true
          kbCount = kbRes.data.length
          kbText  = kbRes.data
            .map((d: { title: string; content: string }) => `**${d.title}**\n${d.content}`)
            .join('\n\n')
        }
      }
    }
  } catch { /* KB no disponible — continuar sin contexto */ }

  // Si no hubo RAG, intentar fallback con top-3 docs activos
  if (!kbUsed) {
    const { data: fallbackDocs } = await supabase
      .from('kb_documents')
      .select('title, content')
      .eq('tenant_id', tenantId)
      .eq('is_active', true)
      .order('updated_at', { ascending: false })
      .limit(3)
    if (fallbackDocs?.length) {
      kbText  = fallbackDocs.map((d: { title: string; content: string }) => `**${d.title}**\n${d.content}`).join('\n\n')
      kbCount = fallbackDocs.length
    }
  }

  // ── 3. Construir system prompt simplificado ───────────────────────────────
  const tonoInst = TONO_DESC[tenant?.tono_comunicacion ?? 'amigable'] ?? TONO_DESC.amigable
  const tenantName = tenant?.name ?? 'la tienda'

  const systemLines: string[] = [
    `Eres ${agent.name}, asistente de ventas de ${tenantName} atendiendo por WhatsApp.`,
    agent.role_description ? `\nROL Y COMPORTAMIENTO:\n${agent.role_description}` : '',
    `\nTONO: ${tonoInst}`,
    tenant?.mision      ? `MISIÓN DEL NEGOCIO: ${tenant.mision}` : '',
    tenant?.valores     ? `VALORES: ${tenant.valores}` : '',
    catalog.length ? (() => {
      const lines = catalog.map(p => {
        const vars = (p.product_variations ?? []).map(v => {
          const attrs = v.attributes ? Object.entries(v.attributes).map(([k,val]) => `${k}: ${val}`).join(', ') : ''
          return `  - $${v.price?.toLocaleString('es-CO')} COP${attrs ? ` (${attrs})` : ''}${v.stock_quantity <= 0 ? ' [Agotado]' : ''}`
        }).join('\n')
        return `• ${p.title}${p.description ? ` — ${p.description}` : ''}${vars ? '\n' + vars : ''}`
      }).join('\n')
      return `\nCATÁLOGO DE PRODUCTOS:\n${lines}`
    })() : '',
    kbText ? `\nCONOCIMIENTO BASE (úsalo para responder):\n${kbText}` : '',
    agent.strict_guardrails
      ? '\nREGLA ESTRICTA: NO inventes información, precios ni políticas que no estén arriba. Si no sabes algo, dilo con honestidad.'
      : '',
    '\nResponde en español, de forma conversacional y breve (máx 3-4 líneas). Eres un bot de WhatsApp.',
  ]

  const systemPrompt = systemLines.filter(Boolean).join('\n')

  // ── 4. Llamar a Gemini 2.5 Flash ─────────────────────────────────────────
  let responseText = ''
  try {
    const chatRes = await fetch(CHAT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: systemPrompt }] },
        contents: [{ role: 'user', parts: [{ text: message }] }],
        generationConfig: { temperature: 0.35, maxOutputTokens: 400 },
      }),
    })
    if (!chatRes.ok) {
      const err = await chatRes.json().catch(() => ({}))
      return NextResponse.json(
        { error: `Gemini error ${chatRes.status}: ${err?.error?.message ?? 'desconocido'}` },
        { status: 502 }
      )
    }
    const chatData = await chatRes.json()
    responseText = chatData.candidates?.[0]?.content?.parts?.[0]?.text ?? ''
    if (!responseText) return NextResponse.json({ error: 'Sin respuesta del modelo' }, { status: 502 })
  } catch (e) {
    return NextResponse.json({ error: `Error llamando a Gemini: ${e instanceof Error ? e.message : e}` }, { status: 502 })
  }

  return NextResponse.json({
    response: responseText,
    kb_used:  kbUsed,
    kb_count: kbCount,
    agent_name: agent.name,
  })
}
