'use client'

/**
 * AgentsList — Rev. 109 ADR-0017 Multi-agente per tenant.
 *
 * Renderiza:
 *   • Lista de agentes del tenant (badges role + default).
 *   • Botón "+ Crear agente" → drawer con selector rol → template →
 *     opcional botón "✨ Sugerir con IA" → editable → guardar.
 *
 * Tools NO duplica lógica: el guardado real usa supabase desde el
 * cliente (mismo patrón que catalog-form.tsx). El endpoint
 * /api/v1/ai-agents/suggest provee el draft con IA.
 */

import { useState } from 'react'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Bot, Plus, Sparkles, Loader2, Check } from 'lucide-react'
import { createClient } from '@/utils/supabase/client'
import { useRouter } from 'next/navigation'

interface Agent {
  id?: string
  name: string
  role_description: string
  strict_guardrails: boolean
  role?: string | null
  is_default?: boolean | null
}

interface Props {
  agents: Agent[]
}

const ROLE_LABEL: Record<string, string> = {
  sales:     'Ventas',
  support:   'Soporte',
  marketing: 'Marketing',
  claims:    'Reclamos',
  custom:    'Personalizado',
}

const ROLE_BADGE: Record<string, string> = {
  sales:     'bg-emerald-500/10 text-emerald-700 border-emerald-500/25',
  support:   'bg-sky-500/10 text-sky-700 border-sky-500/25',
  marketing: 'bg-fuchsia-500/10 text-fuchsia-700 border-fuchsia-500/25',
  claims:    'bg-amber-500/10 text-amber-700 border-amber-500/25',
  custom:    'bg-muted/40 text-muted-foreground border-border',
}

export function AgentsList({ agents }: Props) {
  const router = useRouter()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedRole, setSelectedRole] = useState<string>('sales')
  const [agentName, setAgentName] = useState('')
  const [roleDescription, setRoleDescription] = useState('')
  const [suggesting, setSuggesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const openCreate = () => {
    setSelectedRole('sales')
    setAgentName('')
    setRoleDescription('')
    setError(null)
    setDrawerOpen(true)
  }

  const onRoleChange = (role: string) => {
    setSelectedRole(role)
    // Cuando cambia el rol, limpiamos el prompt para que el operador
    // pueda usar "Sugerir con IA" sobre el nuevo rol.
    setRoleDescription('')
  }

  const onSuggest = async () => {
    setSuggesting(true)
    setError(null)
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      if (!session?.access_token) {
        setError('Sesión expirada')
        return
      }
      const resp = await fetch('/api/ai-agents/suggest', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({ role: selectedRole, agent_name: agentName }),
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        setError(body.detail || 'No se pudo generar la sugerencia')
        return
      }
      const data = await resp.json()
      setRoleDescription(data.suggested_role_description || '')
      if (!agentName && data.agent_name) {
        setAgentName(data.agent_name)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al sugerir con IA')
    } finally {
      setSuggesting(false)
    }
  }

  const onSave = async () => {
    if (!agentName.trim()) { setError('El nombre del agente es obligatorio'); return }
    if (!roleDescription.trim()) { setError('El prompt maestro es obligatorio'); return }
    if (roleDescription.length > 2500) { setError('Máximo 2500 caracteres'); return }

    setSaving(true)
    setError(null)
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string }
      if (!session?.access_token || !meta.tenant_id) {
        setError('Sesión expirada')
        return
      }
      const { error: e1 } = await sb.from('ai_agents').insert({
        tenant_id: meta.tenant_id,
        name: agentName.trim(),
        role: selectedRole,
        role_description: roleDescription.trim(),
        strict_guardrails: true,
        is_default: false,  // nuevos agentes NO son default (uno solo)
      })
      if (e1) throw new Error(e1.message)
      setDrawerOpen(false)
      router.refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al crear agente')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" /> Tus agentes IA
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {agents.length === 0
              ? 'Aún no tienes agentes — crea el primero.'
              : `${agents.length} agente${agents.length === 1 ? '' : 's'} configurado${agents.length === 1 ? '' : 's'}. Cuando tienes varios, el bot enruta cada mensaje al agente apropiado por intent.`}
          </p>
        </div>
        <Button onClick={openCreate} size="sm" className="gap-1.5">
          <Plus className="h-4 w-4" /> Crear agente
        </Button>
      </div>

      {agents.length > 0 && (
        <div className="space-y-1.5">
          {agents.map(a => {
            const role = a.role ?? 'sales'
            return (
              <div
                key={a.id ?? a.name}
                className="flex items-center justify-between rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2.5">
                  <span className="font-medium">{a.name}</span>
                  <span className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full border ${ROLE_BADGE[role] ?? ROLE_BADGE.custom}`}>
                    {ROLE_LABEL[role] ?? role}
                  </span>
                  {a.is_default && (
                    <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full border border-primary/30 bg-primary/10 text-primary">
                      Default
                    </span>
                  )}
                </div>
                <span className="text-xs text-muted-foreground italic">
                  {a.is_default ? 'editable abajo' : 'creado'}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Drawer crear */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-primary" /> Crear agente
            </SheetTitle>
          </SheetHeader>

          <div className="space-y-5 py-4">
            <div className="space-y-2">
              <Label>Rol funcional</Label>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {Object.entries(ROLE_LABEL).map(([key, label]) => (
                  <button
                    type="button"
                    key={key}
                    onClick={() => onRoleChange(key)}
                    className={`text-xs font-medium px-3 py-2 rounded-md border transition-colors ${
                      selectedRole === key
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border bg-background text-foreground hover:bg-muted/40'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground">
                Útil para router pre-LLM (decide qué agente atiende cada mensaje).
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="agent_name_new">Nombre del agente</Label>
              <Input
                id="agent_name_new"
                value={agentName}
                onChange={e => setAgentName(e.target.value)}
                placeholder="Ej: Sara Camila, Andrés Soporte"
                maxLength={80}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="prompt_new">Prompt Maestro</Label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={suggesting}
                  onClick={onSuggest}
                  className="gap-1.5 h-7 text-xs"
                >
                  {suggesting
                    ? <><Loader2 className="h-3 w-3 animate-spin" /> Generando...</>
                    : <><Sparkles className="h-3 w-3" /> Sugerir con IA</>
                  }
                </Button>
              </div>
              <Textarea
                id="prompt_new"
                value={roleDescription}
                onChange={e => setRoleDescription(e.target.value)}
                placeholder="Eres [nombre], asesor/a de [negocio]..."
                className="min-h-[280px] font-mono text-xs"
                maxLength={2500}
              />
              <p className="text-[11px] text-muted-foreground">
                {roleDescription.length}/2500 — La IA lee la filosofía del negocio + catálogo para personalizar.
              </p>
            </div>

            {error && (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                {error}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t border-border">
              <Button variant="ghost" onClick={() => setDrawerOpen(false)}>
                Cancelar
              </Button>
              <Button onClick={onSave} disabled={saving} className="gap-1.5">
                {saving
                  ? <><Loader2 className="h-4 w-4 animate-spin" /> Guardando</>
                  : <><Check className="h-4 w-4" /> Crear agente</>
                }
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
