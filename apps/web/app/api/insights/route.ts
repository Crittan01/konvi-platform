import { NextRequest, NextResponse } from 'next/server'
import * as Sentry from '@sentry/nextjs'
import { createClient } from '@/utils/supabase/server'
import { bogotaWindowUTC } from '@/lib/date-window'
import { PAID_ORDER_STATUSES } from '@/app/dashboard/finance/lib/pnl'

// Ingreso reconocido (canónico, = Finanzas): pago confirmado en adelante.
const RECOGNIZED_STATUSES: ReadonlySet<string> = new Set(PAID_ORDER_STATUSES)

// ── Tipos ─────────────────────────────────────────────────────────────────────

type InsightModule = 'inventory' | 'orders' | 'contacts' | 'metrics'
type Prioridad = 'alta' | 'media' | 'baja'

type InsightResult = {
  resumen: string
  hallazgos: string[]
  acciones: { prioridad: Prioridad; accion: string }[]
  alerta: string | null
  generated_at: string
  tokens_used?: number
}

// PostgREST corta en max_rows (config.toml → 1000) SIN error.
const MAX_ROWS = 1000

// ── Rate limit: 10 llamadas / hora / tenant (patrón de /api/ai/preview) ───────
// In-memory — válido para instancia única (Render Free). Cada llamada es una
// invocación Gemini facturable; sin esto un owner podía spamear «Regenerar».
const INSIGHT_LIMIT  = 10
const INSIGHT_WINDOW = 60 * 60 * 1000
const _rl = new Map<string, { count: number; resetAt: number }>()

function checkLimit(tenantId: string): { ok: boolean; resetIn: number } {
  const now = Date.now()
  const entry = _rl.get(tenantId)
  if (!entry || now > entry.resetAt) {
    _rl.set(tenantId, { count: 1, resetAt: now + INSIGHT_WINDOW })
    return { ok: true, resetIn: INSIGHT_WINDOW }
  }
  if (entry.count >= INSIGHT_LIMIT) return { ok: false, resetIn: entry.resetAt - now }
  entry.count++
  return { ok: true, resetIn: entry.resetAt - now }
}

// ── Prompts por módulo ────────────────────────────────────────────────────────

function buildPrompt(module: InsightModule, data: Record<string, unknown>): string {
  const base = `Eres un analista experto en e-commerce latinoamericano con especialización en WhatsApp Commerce y Mercado Libre. Responde siempre en español, de forma directa y accionable. Usa ÚNICAMENTE los números presentes en los DATOS; no inventes tendencias, cifras ni comparaciones que no puedas derivar de ellos.`

  const jsonSpec = `Responde ÚNICAMENTE con este JSON válido (sin texto adicional):
{
  "resumen": "Una oración directa con números concretos de los DATOS",
  "hallazgos": ["hallazgo 1 con cifras", "hallazgo 2 con cifras", "hallazgo 3 con cifras"],
  "acciones": [
    { "prioridad": "alta", "accion": "Acción concreta" },
    { "prioridad": "media", "accion": "Segunda acción" }
  ],
  "alerta": "Alerta crítica si existe, o null"
}`

  const prompts: Record<InsightModule, string> = {
    inventory: `${base}

Analiza el siguiente inventario y da recomendaciones específicas y accionables.

DATOS DE INVENTARIO:
${JSON.stringify(data, null, 2)}

Considera: stock agotado (ventas perdidas), stock bajo (riesgo de quiebre), oportunidades de recompra.

${jsonSpec}`,

    orders: `${base}

Analiza los siguientes pedidos.

DATOS DE PEDIDOS:
${JSON.stringify(data, null, 2)}

Considera: pedidos pendientes de confirmar, tasa de conversión, patrones de cancelación. NOTA sobre dinero: 'recognized_revenue' es el INGRESO reconocido (pago confirmado en adelante) — úsalo como la cifra de ingreso; 'gross_sales' es ventas brutas (incluye pedidos sin pago) y es SECUNDARIA — nunca la llames ingreso.

${jsonSpec}`,

    contacts: `${base}

Analiza los siguientes contactos/clientes.

DATOS DE CONTACTOS:
${JSON.stringify(data, null, 2)}

Considera: clientes sin Habeas Data (riesgo legal), reactivación, crecimiento de la base.

${jsonSpec}`,

    metrics: `${base}

Analiza las siguientes métricas del negocio. El payload incluye el período actual (30 días) y el período previo (30 días anteriores) para que la comparación sea real; NO estimes tendencias fuera de estos datos.

DATOS DE MÉTRICAS:
${JSON.stringify(data, null, 2)}

Considera: variación vs. período previo (usa los campos *_prev, incl. recognized_revenue_prev_30d si no es null), eficiencia del canal WhatsApp, tasa conversación → venta. NOTA sobre dinero: 'recognized_revenue' es el INGRESO reconocido canónico (pago confirmado en adelante); 'gross_sales' es ventas brutas (incluye pedidos sin pago) y es SECUNDARIA — nunca la llames ingreso.

${jsonSpec}`,
  }

  return prompts[module]
}

// ── Fetcher de datos por módulo ───────────────────────────────────────────────

type SupabaseServerClient = Awaited<ReturnType<typeof createClient>>

type OrdersSummary = {
  orders_total: number
  orders_non_cancelled: number
  orders_cancelled: number
  gross_sales: number
  recognized_revenue: number
  delivered_revenue: number
  by_status: Record<string, number>
}

// Agregación EXACTA de pedidos vía RPC (sin cap 1000 de PostgREST). Feature-
// detected: si el RPC no existe (error) o falla → null y el caller cae al
// cálculo client-side acotado por ventana.
async function ordersSummaryRpc(
  supabase: SupabaseServerClient, from: string | null, to: string | null
): Promise<OrdersSummary | null> {
  try {
    const { data, error } = await supabase.rpc('metrics_orders_summary', { p_from: from, p_to: to })
    if (error || !Array.isArray(data) || !data[0]) return null
    const r = data[0] as Record<string, unknown>
    return {
      orders_total: Number(r.orders_total ?? 0),
      orders_non_cancelled: Number(r.orders_non_cancelled ?? 0),
      orders_cancelled: Number(r.orders_cancelled ?? 0),
      gross_sales: Number(r.gross_sales ?? 0),
      recognized_revenue: Number(r.recognized_revenue ?? 0),
      delivered_revenue: Number(r.delivered_revenue ?? 0),
      by_status: (r.by_status as Record<string, number>) ?? {},
    }
  } catch {
    return null
  }
}

async function fetchModuleData(
  module: InsightModule,
  tenantId: string
): Promise<Record<string, unknown>> {
  const supabase = await createClient()
  const curFrom  = bogotaWindowUTC(30).fromUTC
  const prevFrom = bogotaWindowUTC(60).fromUTC // [prevFrom, curFrom) = 30d previos

  if (module === 'inventory') {
    const [varRes, movRes, threshRes] = await Promise.all([
      supabase.from('product_variations').select('id, product_id, attributes, stock_quantity, price')
        .eq('tenant_id', tenantId).order('stock_quantity').limit(200),
      supabase.from('stock_movements').select('variation_id, delta, reason, created_at')
        .eq('tenant_id', tenantId).gte('created_at', curFrom).order('created_at', { ascending: false }).limit(50),
      supabase.from('tenants').select('low_stock_threshold').eq('id', tenantId).single(),
    ])
    const variations = varRes.data ?? []
    const threshold = (threshRes.data as { low_stock_threshold?: number } | null)?.low_stock_threshold ?? 5
    return {
      variations,
      recent_movements: movRes.data ?? [],
      low_stock_threshold: threshold,
      total_variants: variations.length,
      out_of_stock: variations.filter(v => (v as { stock_quantity: number }).stock_quantity === 0).length,
      low_stock: variations.filter(v => {
        const q = (v as { stock_quantity: number }).stock_quantity
        return q > 0 && q <= threshold
      }).length,
    }
  }

  if (module === 'orders') {
    const [totalRes, prevTotalRes, rowsRes, summary] = await Promise.all([
      supabase.from('orders').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', curFrom),
      supabase.from('orders').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', prevFrom).lt('created_at', curFrom),
      supabase.from('orders').select('status, total_amount', { count: 'exact' }).eq('tenant_id', tenantId).gte('created_at', curFrom),
      ordersSummaryRpc(supabase, curFrom, null),
    ])
    const rows = rowsRes.data ?? []
    const byStatus = summary?.by_status ?? rows.reduce((acc: Record<string, number>, o) => {
      const s = (o as { status: string }).status
      acc[s] = (acc[s] ?? 0) + 1
      return acc
    }, {})
    // Canónico: ingreso reconocido = confirmed+ ; ventas brutas = no canceladas (secundaria).
    const grossFallback = rows.filter(o => (o as { status: string }).status !== 'cancelled')
      .reduce((s, o) => s + Number((o as { total_amount: number }).total_amount || 0), 0)
    const recognizedFallback = rows.filter(o => RECOGNIZED_STATUSES.has((o as { status: string }).status))
      .reduce((s, o) => s + Number((o as { total_amount: number }).total_amount || 0), 0)
    return {
      total_orders: totalRes.count ?? rows.length,
      total_orders_prev_30d: prevTotalRes.count ?? 0,
      by_status: byStatus,
      recognized_revenue: summary?.recognized_revenue ?? recognizedFallback, // dinero comprometido (canónico)
      gross_sales: summary?.gross_sales ?? grossFallback,                     // secundaria: NO es ingreso
      revenue_is_exact: summary !== null,
      revenue_is_approximate: summary === null && (rowsRes.count ?? 0) > rows.length && rows.length >= MAX_ROWS,
      period_days: 30,
    }
  }

  if (module === 'contacts') {
    const [totalRes, consentRes, newRes] = await Promise.all([
      supabase.from('contacts').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
      supabase.from('contacts').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('consent_given', true),
      supabase.from('contacts').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', curFrom),
    ])
    const total = totalRes.count ?? 0
    const withConsent = consentRes.count ?? 0
    return {
      total_contacts: total,
      with_consent: withConsent,
      without_consent: Math.max(total - withConsent, 0),
      new_last_30d: newRes.count ?? 0,
    }
  }

  // metrics — conteos con count:'exact',head:true (exactos a escala); revenue
  // sobre filas acotadas + flag de aproximación; período previo real para el LLM.
  const [
    msgCurRes, msgPrevRes, msgInRes, ordCurRes, ordPrevRes,
    convTotalRes, convBotRes, convHumanRes, revRowsRes,
    summaryCur, summaryPrev,
  ] = await Promise.all([
    supabase.from('messages').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', curFrom),
    supabase.from('messages').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', prevFrom).lt('created_at', curFrom),
    supabase.from('messages').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', curFrom).eq('direction', 'inbound'),
    supabase.from('orders').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', curFrom),
    supabase.from('orders').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', prevFrom).lt('created_at', curFrom),
    supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', curFrom),
    supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', curFrom).eq('status', 'bot_active'),
    supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gte('created_at', curFrom).eq('status', 'human_takeover'),
    supabase.from('orders').select('status, total_amount', { count: 'exact' }).eq('tenant_id', tenantId).gte('created_at', curFrom),
    ordersSummaryRpc(supabase, curFrom, null),
    ordersSummaryRpc(supabase, prevFrom, curFrom),
  ])

  const msgCur = msgCurRes.count ?? 0
  const ordCur = ordCurRes.count ?? 0
  const convTotal = convTotalRes.count ?? 0
  const revRows = revRowsRes.data ?? []
  const grossFallback = revRows.filter(o => (o as { status: string }).status !== 'cancelled')
    .reduce((s, o) => s + Number((o as { total_amount: number }).total_amount || 0), 0)
  const recognizedFallback = revRows.filter(o => RECOGNIZED_STATUSES.has((o as { status: string }).status))
    .reduce((s, o) => s + Number((o as { total_amount: number }).total_amount || 0), 0)

  return {
    period_days: 30,
    messages_total: msgCur,
    messages_total_prev_30d: msgPrevRes.count ?? 0,
    messages_inbound: msgInRes.count ?? 0,
    orders_total: ordCur,
    orders_total_prev_30d: ordPrevRes.count ?? 0,
    // Canónico: 'ingreso' = recognized_revenue (confirmed+). gross_sales es
    // secundaria (no canceladas, incluye checkout sin pago) — nunca 'ingreso'.
    recognized_revenue: summaryCur?.recognized_revenue ?? recognizedFallback,
    recognized_revenue_prev_30d: summaryPrev?.recognized_revenue ?? null,
    gross_sales: summaryCur?.gross_sales ?? grossFallback,
    revenue_is_exact: summaryCur !== null,
    revenue_is_approximate: summaryCur === null && (revRowsRes.count ?? 0) > revRows.length && revRows.length >= MAX_ROWS,
    conversations_total: convTotal,
    bot_active: convBotRes.count ?? 0,
    human_takeover: convHumanRes.count ?? 0,
    conversion_rate: convTotal > 0 ? Math.round((ordCur / convTotal) * 100) : 0,
  }
}

// ── Validación de shape de la respuesta de Gemini ──────────────────────────────
// El panel cliente hace insight.hallazgos.map y PRIORITY_STYLES[a.prioridad]:
// un JSON válido con estructura inesperada lo rompería. Se valida y sanea aquí.

const PRIORIDADES: ReadonlySet<string> = new Set(['alta', 'media', 'baja'])

function validateInsight(x: unknown): Omit<InsightResult, 'generated_at' | 'tokens_used'> | null {
  if (!x || typeof x !== 'object') return null
  const o = x as Record<string, unknown>
  if (typeof o.resumen !== 'string' || !o.resumen.trim()) return null
  if (!Array.isArray(o.hallazgos) || !o.hallazgos.every(h => typeof h === 'string')) return null
  if (!Array.isArray(o.acciones)) return null
  const acciones = o.acciones
    .filter((a): a is { prioridad: Prioridad; accion: string } =>
      !!a && typeof a === 'object'
      && typeof (a as { accion?: unknown }).accion === 'string'
      && PRIORIDADES.has((a as { prioridad?: unknown }).prioridad as string))
    .map(a => ({ prioridad: a.prioridad, accion: a.accion }))
  return {
    resumen: o.resumen,
    hallazgos: (o.hallazgos as string[]).slice(0, 10),
    acciones: acciones.slice(0, 6),
    alerta: typeof o.alerta === 'string' && o.alerta.trim() ? o.alerta : null,
  }
}

// ── Route Handler ─────────────────────────────────────────────────────────────

export async function POST(req: NextRequest) {
  let insightModule: InsightModule | undefined
  let tenantId: string | undefined
  try {
    // 1. Auth
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'No autorizado' }, { status: 401 })

    const meta = (user.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!meta.tenant_id) return NextResponse.json({ error: 'Tenant no configurado' }, { status: 403 })
    if (!['owner', 'manager'].includes(meta.role ?? ''))
      return NextResponse.json({ error: 'Sin permisos' }, { status: 403 })
    tenantId = meta.tenant_id

    // 2. Rate limit (antes de gastar en Gemini)
    const rl = checkLimit(tenantId)
    if (!rl.ok) {
      const minutos = Math.ceil(rl.resetIn / 60000)
      return NextResponse.json(
        { error: `Límite de ${INSIGHT_LIMIT} análisis por hora alcanzado. Disponible en ${minutos} min.` },
        { status: 429 }
      )
    }

    // 3. Parse body
    const body = await req.json() as { module?: string }
    const validModules: InsightModule[] = ['inventory', 'orders', 'contacts', 'metrics']
    if (!validModules.includes(body.module as InsightModule))
      return NextResponse.json({ error: 'Módulo no válido' }, { status: 400 })
    insightModule = body.module as InsightModule

    // 4. Fetch data + prompt
    const data = await fetchModuleData(insightModule, tenantId)
    const prompt = buildPrompt(insightModule, data)

    // 5. Gemini REST
    const apiKey = process.env.GEMINI_API_KEY
    const model  = process.env.GEMINI_MODEL ?? 'gemini-3.5-flash' // 2.5-flash se retira 2026-10-16
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
      Sentry.captureMessage('insights: Gemini non-OK', {
        level: 'error',
        extra: { status: geminiRes.status, body: errText.slice(0, 500), module: insightModule, tenantId },
      })
      return NextResponse.json({ error: 'Error al consultar Gemini' }, { status: 502 })
    }

    // 6. Parse + validar shape
    const geminiData = await geminiRes.json() as {
      candidates?: { content?: { parts?: { text?: string }[] } }[]
      usageMetadata?: { totalTokenCount?: number }
    }
    const rawText = geminiData.candidates?.[0]?.content?.parts?.[0]?.text ?? ''
    const jsonText = rawText.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim()

    let parsedUnknown: unknown
    try {
      parsedUnknown = JSON.parse(jsonText)
    } catch {
      Sentry.captureMessage('insights: JSON.parse falló', {
        level: 'error', extra: { raw: rawText.slice(0, 500), module: insightModule, tenantId },
      })
      return NextResponse.json({ error: 'Respuesta inválida de Gemini' }, { status: 502 })
    }

    const validated = validateInsight(parsedUnknown)
    if (!validated || validated.acciones.length === 0) {
      Sentry.captureMessage('insights: shape inesperado', {
        level: 'warning', extra: { raw: rawText.slice(0, 500), module: insightModule, tenantId },
      })
      return NextResponse.json({ error: 'Respuesta con formato inesperado de Gemini' }, { status: 502 })
    }

    const tokensUsed = geminiData.usageMetadata?.totalTokenCount
    const result: InsightResult = {
      ...validated,
      generated_at: new Date().toISOString(),
      tokens_used: tokensUsed,
    }

    // 7. Audit trail (best-effort): uso de IA por tenant, para accounting/abuso.
    try {
      await supabase.from('audit_log').insert({
        tenant_id: tenantId,
        user_id: user.id,
        user_email: user.email,
        action: 'insight.generated',
        entity_type: 'insight',
        entity_id: insightModule,
        payload: { model, tokens_used: tokensUsed ?? null },
      })
    } catch (e) {
      Sentry.captureException(e, { extra: { where: 'insights.audit_log', module: insightModule, tenantId } })
    }

    // 8. Persistencia del último análisis por tenant/módulo (decisión F4): evita
    //    regenerar/gastar tokens al navegar. Best-effort + feature-detect: si la
    //    tabla ai_insights aún no existe, se registra y se sigue (el panel cae a
    //    idle sin persistencia).
    try {
      const { error: upsertErr } = await supabase.from('ai_insights').upsert({
        tenant_id: tenantId,
        module: insightModule,
        result,
        tokens_used: tokensUsed ?? null,
        generated_by: user.id,
        generated_at: result.generated_at,
      }, { onConflict: 'tenant_id,module' })
      if (upsertErr) {
        Sentry.captureMessage('insights: persistencia no disponible', {
          level: 'info', extra: { code: upsertErr.code, module: insightModule, tenantId },
        })
      }
    } catch (e) {
      Sentry.captureException(e, { extra: { where: 'insights.persist', module: insightModule, tenantId } })
    }

    return NextResponse.json(result)

  } catch (err) {
    Sentry.captureException(err, { extra: { where: 'insights.POST', module: insightModule, tenantId } })
    return NextResponse.json({ error: 'Error interno' }, { status: 500 })
  }
}

// ── GET: último análisis persistido por módulo (decisión F4) ────────────────────
// El panel lo consulta al montar para restaurar el último insight sin gastar
// tokens. Devuelve { insight: null } si no hay (o si la tabla no existe todavía).
export async function GET(req: NextRequest) {
  let tenantId: string | undefined
  try {
    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'No autorizado' }, { status: 401 })

    const meta = (user.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!meta.tenant_id) return NextResponse.json({ error: 'Tenant no configurado' }, { status: 403 })
    if (!['owner', 'manager'].includes(meta.role ?? ''))
      return NextResponse.json({ error: 'Sin permisos' }, { status: 403 })
    tenantId = meta.tenant_id

    const moduleParam = new URL(req.url).searchParams.get('module')
    const validModules: InsightModule[] = ['inventory', 'orders', 'contacts', 'metrics']
    if (!validModules.includes(moduleParam as InsightModule))
      return NextResponse.json({ error: 'Módulo no válido' }, { status: 400 })

    // Feature-detect: si la tabla no existe, `error` viene set → insight: null.
    const { data, error } = await supabase
      .from('ai_insights')
      .select('result')
      .eq('tenant_id', tenantId)
      .eq('module', moduleParam)
      .maybeSingle()

    if (error || !data) return NextResponse.json({ insight: null })
    return NextResponse.json({ insight: (data as { result: InsightResult }).result })

  } catch (err) {
    Sentry.captureException(err, { extra: { where: 'insights.GET', tenantId } })
    return NextResponse.json({ insight: null })
  }
}
