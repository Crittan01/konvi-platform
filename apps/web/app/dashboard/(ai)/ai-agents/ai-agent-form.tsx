'use client'

import { useFormStatus } from 'react-dom'
import { Bot, Save, ShieldAlert, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useState } from 'react'

const MAX_NAME = 80
const MAX_ROLE = 1500

function SubmitButton() {
  const { pending } = useFormStatus()
  return (
    <Button type="submit" disabled={pending} className="gap-2">
      {pending
        ? <><Loader2 className="h-4 w-4 animate-spin" />Guardando...</>
        : <><Save className="h-4 w-4" />Guardar Configuración IA</>
      }
    </Button>
  )
}

interface AiAgentFormProps {
  agent: {
    name: string
    role_description: string
    strict_guardrails: boolean
    // Rev. 109 backlog #2 — campos multi-vertical agnósticos.
    role?: string | null         // sales | support | marketing | claims
    pitch?: string | null         // pitch inyectado al system prompt
    tone?: string | null          // tono conversacional
  }
  canWrite: boolean
  saveAiAgent: (formData: FormData) => Promise<void>
}

export function AiAgentForm({ agent, canWrite, saveAiAgent }: AiAgentFormProps) {
  const [nameLen, setNameLen] = useState(agent.name.length)
  const [roleLen, setRoleLen] = useState(agent.role_description.length)

  return (
    <form action={saveAiAgent} className="space-y-6 bg-card border border-border p-6 rounded-xl">
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="name">Nombre del Analista / Bot</Label>
          <span className={`text-xs tabular-nums ${nameLen > MAX_NAME ? 'text-destructive' : 'text-muted-foreground'}`}>
            {nameLen}/{MAX_NAME}
          </span>
        </div>
        <Input
          id="name"
          name="name"
          defaultValue={agent.name}
          maxLength={MAX_NAME}
          placeholder="Ej: Sofia (Ventas), Bot Automático"
          readOnly={!canWrite}
          onChange={e => setNameLen(e.target.value.length)}
        />
        <p className="text-xs text-muted-foreground">Este es el rol que el modelo asumirá implícitamente.</p>
      </div>

      {/* Rev. 109 backlog #2 — Multi-agente per-tenant (Plan I.5).
          Campos extendidos para soportar verticales distintas. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="role">Rol funcional</Label>
          <select
            id="role"
            name="role"
            defaultValue={agent.role ?? 'sales'}
            disabled={!canWrite}
            className="w-full h-9 rounded-md border border-input bg-background text-sm px-2 text-foreground"
          >
            <option value="sales">Ventas</option>
            <option value="support">Soporte</option>
            <option value="marketing">Marketing</option>
            <option value="claims">Reclamos</option>
          </select>
          <p className="text-xs text-muted-foreground">
            Útil cuando un tenant tenga varios agentes (router pre-LLM elige por intent).
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="tone">Tono conversacional</Label>
          <Input
            id="tone"
            name="tone"
            defaultValue={agent.tone ?? ''}
            placeholder="Ej: cordial y profesional, español Colombia"
            readOnly={!canWrite}
            maxLength={120}
          />
          <p className="text-xs text-muted-foreground">
            Estilo del bot al conversar. Inyectado al system prompt.
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="pitch">Pitch del negocio (1 línea, multi-vertical)</Label>
        <Textarea
          id="pitch"
          name="pitch"
          defaultValue={agent.pitch ?? ''}
          placeholder="Ej KAIU: asesora de KAIU Living Natural, cosmética artesanal natural"
          readOnly={!canWrite}
          maxLength={240}
          className="min-h-[60px] text-sm"
        />
        <p className="text-xs text-muted-foreground">
          Inyectado en el system prompt cada turno. Multi-vertical agnóstico — cosmética,
          tecnología, comida, etc. Si lo dejas vacío, el bot usa pitch genérico.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="role_description" className="text-base font-semibold">
            Directrices de Comportamiento (Prompt Maestro)
          </Label>
          <span className={`text-xs tabular-nums ${roleLen > MAX_ROLE ? 'text-destructive' : 'text-muted-foreground'}`}>
            {roleLen}/{MAX_ROLE}
          </span>
        </div>
        <Textarea
          id="role_description"
          name="role_description"
          defaultValue={agent.role_description}
          maxLength={MAX_ROLE}
          className="min-h-[300px] font-mono text-sm leading-relaxed"
          placeholder="Ej: Eres Sofia, especialista en ventas. Tu objetivo es guiar al cliente desde la consulta hasta el cierre. Cuando alguien pregunta por tallas, siempre pregunta el peso también."
          readOnly={!canWrite}
          onChange={e => setRoleLen(e.target.value.length)}
        />
        <p className="text-xs text-muted-foreground">
          Define <strong>el COMPORTAMIENTO del bot</strong>: qué ofrece primero, cómo cierra, qué pregunta extra hace.
          La <strong>IDENTIDAD del negocio</strong> (misión, visión, valores, tono) se configura aparte en
          Configuración → General → Filosofía del negocio y se inyecta automáticamente — no la repitas aquí.
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
              Si se activa, el bot se negará rotundamente a inventar precios, reglas o información no registrada
              en el catálogo y escalará a un humano.
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
          <SubmitButton />
        </div>
      )}
    </form>
  )
}
