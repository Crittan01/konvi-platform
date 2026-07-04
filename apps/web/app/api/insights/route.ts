import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'

// ── Tipos ─────────────────────────────────────────────────────────────────────

type InsightModule = 'inventory' | 'orders' | 'contacts' | 'metrics'

type InsightResult = {
  resumen: string
  hallazgos: string[]
  acciones: { prioridad: 'alta' | 'media' | 'baja'; accion: string }[]
  alerta: string | null
  generated_at: string
  tokens_used?: number
}

// ── Prompts por módulo ────────────────────────────────────────────────────────

function buildPrompt(module: InsightModule, data: Record<string, unknown>): string {
  const base = `Eres un analista experto en e-commerce latinoamericano con especialización en WhatsApp Commerce y Mercado Libre. Responde siempre en español, de forma directa y accionable.`

  const prompts: Record<InsightModule, string> = {
    inventory: `${base}

Analiza el siguiente inventario de un negocio e-commerce y proporciona recomendaciones específicas y accionables.

DATOS DE INVENTARIO:
${JSON.stringify(data, null, 2)}

Considera:
- Productos con stock agotado → impacto en ventas perdidas
- Productos con stock bajo (< umbral) → riesgo de quiebre
- Tendencia de ventas por variante
- Oportunidades de recompra

Responde ÚNICAMENTE con este JSON válido (sin texto adicional):
{
  "resumen": "Una oración directa sobre el estado del inventario hoy",
  "hallazgos": [
    "Hallazgo específico 1 con números concretos",
    "Hallazgo específico 2 con números concretos",
    "Hallazgo específico 3 con números concretos"
  ],
  "acciones": [
    { "prioridad": "alta", "accion": "Acción concreta con producto/cantidad/plazo específico" },
    { "prioridad": "media", "accion": "Segunda acción concreta" },
    { "prioridad": "baja", "accion": "Tercera acción concreta" }
  ],
  "alerta": "Mensaje de alerta crítica si existe, o null si todo está bien"
}`,

    orders: `${base}

Analiza los siguientes pedidos de un negocio e-commerce.

DATOS DE PEDIDOS:
${JSON.stringify(data, null, 2)}

Considera:
- Pedidos pendientes de confirmar → urgencia
- Tasa de conversión (conversations → pedidos)
- Pedidos sin envío generado
- Patrones de cancelación

Responde ÚNICAMENTE con este JSON válido:
{
  "resumen": "Una oración directa sobre el estado de los pedidos",
  "hallazgos": ["hallazgo 1", "hallazgo 2", "hallazgo 3"],
  "acciones": [
    { "prioridad": "alta", "accion": "..." },
    { "prioridad": "media", "accion": "..." }
  ],
  "alerta": "Alerta crítica o null"
}`,

    contacts: `${base}

Analiza los siguientes contactos/clientes de un negocio e-commerce.

DATOS DE CONTACTOS:
${JSON.stringify(data, null, 2)}

Considera:
- Clientes recurrentes vs. únicos
- Clientes sin Habeas Data (riesgo legal)
- Segmentos de valor (VIP, frecuentes, dormidos)
- Oportunidades de reactivación

Responde ÚNICAMENTE con este JSON válido:
{
  "resumen": "Una oración directa sobre la base de clientes",
  "hallazgos": ["hallazgo 1", "hallazgo 2", "hallazgo 3"],
  "acciones": [
    { "prioridad": "alta", "accion": "..." },
    { "prioridad": "media", "accion": "..." }
  ],
  "alerta": "Alerta crítica o null"
}`,

    metrics: `${base}

Analiza las siguientes métricas del negocio.

DATOS DE MÉTRICAS:
${JSON.stringify(data, null, 2)}

Considera:
- Tendencias de crecimiento/caída
- Eficiencia del canal WhatsApp
- Tasa de conversación → venta
- Comparativa vs. período anterior

Responde ÚNICAMENTE con este JSON válido:
{
  "resumen": "Una oración directa sobre el rendimiento del negocio",
  "hallazgos": ["hallazgo 1", "hallazgo 2", "hallazgo 3"],
  "acciones": [
    { "prioridad": "alta", "accion": "..." },
    { "prioridad": "media", "accion": "..." }
  ],
  "alerta": "Alerta crítica o null"
}`,
  }

  return prompts[module]
}

// ── Fetcher de datos por módulo ───────────────────────────────────────────────

async function fetchModuleData(
  module: InsightModule,
  tenantId: string
): Promise<Record<string, unknown>> {
  const supabase = await createClient()
  const since30d = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString()

  if (module === 'inventory') {
    const [varRes, movRes, threshRes] = await Promise.all([
      supabase.from('product_variations').select('id, product_id, attributes, stock_quantity, price')
        .eq('tenant_id', tenantId).order('stock_quantity'),
      supabase.from('stock_movements').select('variation_id, delta, reason, created_at')
        .eq('tenant_id', tenantId).gte('created_at', since30d).order('created_at', { ascending: false }).limit(50),
      supabase.from('tenants').select('low_stock_threshold').eq('id', tenantId).single(),
    ])
    return {
      variations:       varRes.data ?? [],
      recent_movements: movRes.data ?? [],
      low_stock_threshold: (threshRes.data as { low_stock_threshold?: number } | null)?.low_stock_threshold ?? 5,
      total_variants:   (varRes.data ?? []).length,
      out_of_stock:     (varRes.data ?? []).filter(v => (v as { stock_quantity: number }).stock_quantity === 0).length,
      low_stock:        (varRes.data ?? []).filter(v => {
        const t = (threshRes.data as { low_stock_threshold?: number } | null)?.low_stock_threshold ?? 5
        return (v as { stock_quantity: number }).stock_quantity > 0 && (v as { stock_quantity: number }).stock_quantity <= t
      }).length,
    }
  }

  if (module === 'orders') {
    const ordRes = await supabase.from('orders').select('id, status, total_amount, created_at')
      .eq('tenant_id', tenantId).gte('created_at', since30d).order('created_at', { ascending: false })
    const orders = ordRes.data ?? []
    const byStatus = orders.reduce((acc: Record<string, number>, o) => {
      const o2 = o as { status: string }
      acc[o2.status] = (acc[o2.status] ?? 0) + 1
      return acc
    }, {})
    return {
      total_orders: orders.length,
      by_status: byStatus,
      total_revenue: orders.filter(o => !['cancelled'].includes((o as { status: string }).status))
        .reduce((s, o) => s + Number((o as { total_amount: number }).total_amount), 0),
      period_days: 30,
    }
  }

  if (module === 'contacts') {
    const ctRes = await supabase.from('contacts').select('id, consent_given, created_at')
      .eq('tenant_id', tenantId)
    const contacts = ctRes.data ?? []
    return {
      total_contacts: contacts.length,
      with_consent: contacts.filter(c => (c as { consent_given: boolean }).consent_given).length,
      without_consent: contacts.filter(c => !(c as { consent_given: boolean }).consent_given).length,
      new_last_30d: contacts.filter(c => new Date((c as { created_at: string }).created_at) >= new Date(since30d)).length,
    }
  }

  // metrics
  const [msgRes, ordRes, convRes] = await Promise.all([
    supabase.from('messages').select('id, direction').eq('tenant_id', tenantId).gte('created_at', since30d),
    supabase.from('orders').select('id, status, total_amount').eq('tenant_id', tenantId).gte('created_at', since30d),
    supabase.from('conversations').select('id, status').eq('tenant_id', tenantId),
  ])
  const msgs  = msgRes.data ?? []
  const ords  = ordRes.data ?? []
  const convs = convRes.data ?? []
  return {
    messages_total: msgs.length,
    messages_inbound: msgs.filter(m => (m as { direction: string }).direction === 'inbound').length,
    orders_total: ords.length,
    conversations_total: convs.length,
    bot_active: convs.filter(c => (c as { status: string }).status === 'bot_active').length,
    human_takeover: convs.filter(c => (c as { status: string }).status === 'human_takeover').length,
    conversion_rate: convs.length > 0 ? Math.round((ords.length / convs.length) * 100) : 0,
  }
}

// ── Route Handler ─────────────────────────────────────────────────────────────

export async function POST(req: NextRequest) {
  try {
    // 1. Auth
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'No autorizado' }, { status: 401 })

    const meta = (user.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!meta.tenant_id) return NextResponse.json({ error: 'Tenant no configurado' }, { status: 403 })
    if (!['owner', 'manager'].includes(meta.role ?? ''))
      return NextResponse.json({ error: 'Sin permisos' }, { status: 403 })

    // 2. Parse body
    const body = await req.json() as { module?: string }
    const insightModule = body.module as InsightModule
    const validModules: InsightModule[] = ['inventory', 'orders', 'contacts', 'metrics']
    if (!validModules.includes(insightModule))
      return NextResponse.json({ error: 'Módulo no válido' }, { status: 400 })

    // 3. Fetch data
    const data = await fetchModuleData(insightModule, meta.tenant_id)

    // 4. Build prompt
    const prompt = buildPrompt(insightModule, data)

    // 5. Call Gemini REST API
    const apiKey = process.env.GEMINI_API_KEY
    const model  = process.env.GEMINI_MODEL ?? 'gemini-2.5-flash'
    if (!apiKey) return NextResponse.json({ error: 'GEMINI_API_KEY no configurada' }, { status: 500 })

    const geminiRes = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: { temperature: 0.2, maxOutputTokens: 1024 },
        }),
        signal: AbortSignal.timeout(30000),
      }
    )

    if (!geminiRes.ok) {
      const errText = await geminiRes.text()
      console.error('Gemini error:', errText)
      return NextResponse.json({ error: 'Error al consultar Gemini' }, { status: 502 })
    }

    // 6. Parse Gemini response
    const geminiData = await geminiRes.json() as {
      candidates?: { content?: { parts?: { text?: string }[] } }[]
      usageMetadata?: { totalTokenCount?: number }
    }
    const rawText = geminiData.candidates?.[0]?.content?.parts?.[0]?.text ?? ''

    // Remove markdown fences if present
    const jsonText = rawText.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim()

    let parsed: InsightResult
    try {
      parsed = JSON.parse(jsonText) as InsightResult
    } catch {
      console.error('JSON parse error. Raw:', rawText)
      return NextResponse.json({ error: 'Respuesta inválida de Gemini' }, { status: 500 })
    }

    const result: InsightResult = {
      ...parsed,
      generated_at: new Date().toISOString(),
      tokens_used: geminiData.usageMetadata?.totalTokenCount,
    }

    return NextResponse.json(result)

  } catch (err) {
    console.error('Insights route error:', err)
    return NextResponse.json({ error: 'Error interno' }, { status: 500 })
  }
}
