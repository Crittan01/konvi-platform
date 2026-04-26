import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { Bot, BookOpen, Sparkles } from 'lucide-react'
import { AiAgentForm } from './ai-agent-form'

const TONO_LABEL: Record<string, string> = {
  amigable: 'Amigable y cercano',
  formal: 'Formal y profesional',
  neutro: 'Neutro',
  energico: 'Enérgico y motivador',
}

export default async function AiAgentsPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const canWrite = ['owner', 'manager'].includes(meta.role ?? '')

  if (!tenantId) {
    return <div className="p-8 text-center text-muted-foreground">Sin acceso — tenant no configurado.</div>
  }

  const [{ data }, { data: tenant }] = await Promise.all([
    supabase.from('ai_agents').select('*').eq('tenant_id', tenantId).maybeSingle(),
    supabase.from('tenants').select('mision, vision, valores, tono_comunicacion').eq('id', tenantId).maybeSingle(),
  ])

  const agent = data || {
    name: 'Bot Asistente',
    role_description: 'Eres el agente de atención al cliente de esta tienda por WhatsApp. Te encargas de asistir e informar cordialmente.',
    strict_guardrails: true
  }

  const hasFilosofia = !!(tenant?.mision || tenant?.valores)

  async function saveAiAgent(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const name = (formData.get('name') as string).trim() || 'Bot Asistente'
    const role_description = (formData.get('role_description') as string).trim() || 'Asistente de ventas.'
    const strict_guardrails = formData.get('strict_guardrails') !== null

    if (role_description.length > 1500) return

    await sb.from('ai_agents').upsert({
      tenant_id: m.tenant_id,
      name,
      role_description,
      strict_guardrails
    }, { onConflict: 'tenant_id' })

    revalidatePath('/dashboard/ai-agents')
  }

  return (
    <div className="space-y-6 max-w-7xl">

      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <h1 className="text-xl sm:text-2xl font-bold flex items-center gap-2 text-foreground">
            <Bot className="h-5 w-5 text-primary" /> Configuración de la Inteligencia Artificial
          </h1>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full border border-green-500/30 bg-green-500/10 text-green-400">
            Zero-Hallucinations Activo
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Ajusta la personalidad, rol y los límites estrictos de tu asistente virtual de WhatsApp.
        </p>
      </div>

      <div className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/5 to-background p-6">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-purple-500/15 border border-purple-500/25 flex items-center justify-center shrink-0">
            <Sparkles className="h-6 w-6 text-purple-500" />
          </div>
          <div>
            <p className="font-semibold text-foreground">Anti-Spam & RAG en Tiempo Real</p>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              La IA solo puede nutrirse de la base de conocimientos y catálogos explícitos.
              Además, está controlada por guardrails de Meta (WhatsApp) que le obligan a emitir mensajes cortos.
            </p>
          </div>
        </div>
      </div>

      {/* Card: Filosofía del negocio — contexto inyectado automáticamente */}
      <div className={`rounded-xl border p-5 space-y-3 ${hasFilosofia ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-amber-500/25 bg-amber-500/5'}`}>
        <div className="flex items-center gap-2">
          <BookOpen className={`h-4 w-4 ${hasFilosofia ? 'text-emerald-500' : 'text-amber-500'}`} />
          <p className="text-sm font-semibold">
            Filosofía del negocio — inyectada automáticamente al bot
          </p>
        </div>
        {hasFilosofia ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
            {tenant?.mision && (
              <div>
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide mb-1">Misión</p>
                <p className="text-foreground leading-relaxed">{tenant.mision}</p>
              </div>
            )}
            {tenant?.vision && (
              <div>
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide mb-1">Visión</p>
                <p className="text-foreground leading-relaxed">{tenant.vision}</p>
              </div>
            )}
            {tenant?.valores && (
              <div>
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide mb-1">Valores</p>
                <p className="text-foreground leading-relaxed">{tenant.valores}</p>
              </div>
            )}
            {tenant?.tono_comunicacion && (
              <div>
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wide mb-1">Tono de marca</p>
                <p className="text-foreground">{TONO_LABEL[tenant.tono_comunicacion] ?? tenant.tono_comunicacion}</p>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-amber-600 dark:text-amber-400">
            No has configurado la Filosofía del negocio todavía.{' '}
            <a href="/dashboard/settings" className="underline hover:no-underline">
              Configúrala en Ajustes → General
            </a>{' '}
            para que el bot conozca tu marca.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Esta información se combina con el Prompt Maestro abajo. No la repitas — usa el Prompt para definir
          cómo actúa el bot en ventas: su nombre, qué ofrece primero, cómo cierra.
        </p>
      </div>

      <AiAgentForm agent={agent} canWrite={canWrite} saveAiAgent={saveAiAgent} />
    </div>
  )
}
