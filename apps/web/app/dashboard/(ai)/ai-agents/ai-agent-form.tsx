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
    role?: string | null  // sales | support | marketing | claims
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

      {/* Rev. 109 auditoría — Rol funcional (multi-agente futuro). Tono
          y Pitch viven en Settings → Filosofía del Negocio para evitar
          duplicación (única fuente de verdad). */}
      <div className="space-y-2">
        <Label htmlFor="role">Rol funcional</Label>
        <select
          id="role"
          name="role"
          defaultValue={agent.role ?? 'sales'}
          disabled={!canWrite}
          className="w-full sm:w-1/2 h-9 rounded-md border border-input bg-background text-sm px-2 text-foreground"
        >
          <option value="sales">Ventas</option>
          <option value="support">Soporte</option>
          <option value="marketing">Marketing</option>
          <option value="claims">Reclamos</option>
        </select>
        <p className="text-xs text-muted-foreground">
          Útil cuando tu tenant tenga varios agentes (router elige por intent del cliente).
        </p>
      </div>

      {/* Card readonly: Tono y Pitch vienen de Settings. NO se editan aquí. */}
      <div className="rounded-lg border border-border/40 bg-muted/20 p-4 space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Identidad del negocio (heredada — única fuente)
        </p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          El <strong>pitch</strong> (qué vende), <strong>tono de marca</strong>,
          <strong> misión / visión / valores</strong> se inyectan automáticamente
          al bot desde la configuración del negocio. NO los repitas aquí — se
          mantienen únicos para evitar conflictos.
        </p>
        <a
          href="/dashboard/settings"
          className="inline-block text-xs font-medium text-primary hover:underline"
        >
          → Editar en Configuración → Filosofía del Negocio
        </a>
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
