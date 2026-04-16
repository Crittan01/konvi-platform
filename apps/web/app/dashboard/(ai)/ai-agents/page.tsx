import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { Bot, Save, ShieldAlert, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

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

  // Obtener config
  const { data } = await supabase.from('ai_agents').select('*').eq('tenant_id', tenantId).maybeSingle()
  const agent = data || {
    name: 'Bot Asistente',
    role_description: 'Eres el agente de atención al cliente de esta tienda por WhatsApp. Te encargas de asistir e informar cordialmente.',
    strict_guardrails: true
  }

  async function saveAiAgent(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

    const name = (formData.get('name') as string).trim() || 'Bot Asistente'
    const role_description = (formData.get('role_description') as string).trim() || 'Asistente de ventas.'
    const strict_guardrails = formData.get('strict_guardrails') !== null

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

      <form action={saveAiAgent} className="space-y-6 bg-card border border-border p-6 rounded-xl">
        <div className="space-y-2">
          <Label htmlFor="name">Nombre del Analista / Bot</Label>
          <Input 
            id="name" 
            name="name" 
            defaultValue={agent.name} 
            placeholder="Ej: Sofia (Ventas), Bot Automático" 
            readOnly={!canWrite}
          />
          <p className="text-xs text-muted-foreground">Este es el rol que el modelo asumirá implícitamente.</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="role_description" className="text-base font-semibold">Directrices de Comportamiento (Prompt Maestro)</Label>
          <Textarea 
            id="role_description" 
            name="role_description" 
            defaultValue={agent.role_description} 
            className="min-h-[350px] font-mono text-sm leading-relaxed"
            placeholder="Escribe cómo debe interactuar el bot... Ej: Eres muy formal y nunca das descuentos."
            readOnly={!canWrite}
          />
          <p className="text-xs text-muted-foreground">
            Instrucciones explícitas de actuación. Define su actitud, manejo de disputas y forma de hablar. Cuanto más detallado sea el prompt, más exacto será su comportamiento.
          </p>
        </div>

        <div className="space-y-4 pt-2">
          <div className="flex items-center justify-between rounded-lg border border-border p-4 bg-muted/20">
            <div className="space-y-0.5">
              <Label className="text-base flex items-center gap-2">
                <ShieldAlert className="h-4 w-4 text-emerald-500" />
                Umbral de Seguridad Estricto (Guardrails)
              </Label>
              <p className="text-sm text-muted-foreground">
                Si se activa, el bot se negará rotúndamente a inventar precios, reglas o información no registrada en el catálogo y escalará a un humano.
              </p>
            </div>
            <div className="flex items-center gap-2">
               <Label htmlFor="strict_guardrails" className="text-sm">Activado</Label>
               <input
                 type="checkbox"
                 id="strict_guardrails"
                 name="strict_guardrails"
                 defaultChecked={agent.strict_guardrails}
                 disabled={!canWrite}
                 className="h-4 w-4 accent-primary"
               />
            </div>
          </div>
        </div>

        {canWrite && (
          <div className="flex justify-end pt-4 border-t border-border">
             {/* Note: In a production App router, we'd use useFormStatus in a subcomponent for loading states. Doing simple button to keep it clean */}
            <Button type="submit" className="gap-2">
              <Save className="h-4 w-4" />
              Guardar Configuración IA
            </Button>
          </div>
        )}
      </form>
    </div>
  )
}
