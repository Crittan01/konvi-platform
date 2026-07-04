'use client'

/**
 * AgentsList — Rev. 109 ADR-0017 Multi-agente CRUD consolidado.
 *
 * Reemplaza el form legacy inline que solo editaba el agente default.
 * Ahora UN solo componente maneja: lista, crear, editar, borrar.
 *
 * Reglas arquitectónicas (decididas con founder UAT):
 *   • Solo 1 agente por rol (no 2 agentes Ventas).
 *   • Default: editable pero NO borrable, rol bloqueado (sales).
 *   • Crear: solo roles disponibles (no asignados) aparecen seleccionables.
 *   • Drawer mismo UI para crear/editar (modo distingue).
 */

import { useState, useTransition } from 'react'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Bot, Plus, Sparkles, Loader2, Check, Pencil, Trash2 } from 'lucide-react'
import { createClient } from '@/utils/supabase/client'
import { useConfirm } from '@/components/ui/confirm-dialog'
import { toast } from 'sonner'

interface Agent {
  id?: string
  name: string
  role_description: string
  strict_guardrails: boolean
  role?: string | null
  is_default?: boolean | null
  fallback_for_roles?: string[] | null
}

const FALLBACK_ROLES_CANONICAL = ['sales', 'support', 'marketing', 'claims'] as const
type CanonicalRole = (typeof FALLBACK_ROLES_CANONICAL)[number]

interface Props {
  agents: Agent[]
  canWrite: boolean
  createAgent: (fd: FormData) => Promise<{ ok: boolean; error?: string }>
  updateAgent: (fd: FormData) => Promise<{ ok: boolean; error?: string }>
  deleteAgent: (fd: FormData) => Promise<{ ok: boolean; error?: string }>
}

const ROLE_LABEL: Record<string, string> = {
  sales:     'Ventas',
  support:   'Soporte',
  marketing: 'Marketing',
  claims:    'Reclamos',
  custom:    'Personalizado',
}
const ALL_ROLES = ['sales', 'support', 'marketing', 'claims', 'custom']

const ROLE_BADGE: Record<string, string> = {
  sales:     'bg-emerald-500/10 text-emerald-700 border-emerald-700/25',
  support:   'bg-sky-500/10 text-sky-700 border-sky-500/25',
  marketing: 'bg-fuchsia-500/10 text-fuchsia-700 border-fuchsia-500/25',
  claims:    'bg-amber-500/10 text-amber-700 border-amber-700/25',
  custom:    'bg-muted/40 text-muted-foreground border-border',
}

type Mode = 'create' | 'edit'

export function AgentsList({ agents, canWrite, createAgent, updateAgent, deleteAgent }: Props) {
  const confirmar = useConfirm()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('create')
  const [editing, setEditing] = useState<Agent | null>(null)
  const [selectedRole, setSelectedRole] = useState<string>('sales')
  const [agentName, setAgentName] = useState('')
  const [roleDescription, setRoleDescription] = useState('')
  const [strictGuardrails, setStrictGuardrails] = useState(true)
  const [fallbackRoles, setFallbackRoles] = useState<Set<CanonicalRole>>(
    new Set(FALLBACK_ROLES_CANONICAL),
  )
  const [suggesting, setSuggesting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isPending, startTransition] = useTransition()

  // Roles ya asignados en este tenant (para validación UI).
  const takenRoles = new Set(
    agents.map(a => (a.role ?? 'sales')),
  )

  const openCreate = () => {
    setMode('create')
    setEditing(null)
    // Pre-seleccionar primer rol disponible.
    const available = ALL_ROLES.find(r => !takenRoles.has(r)) ?? 'custom'
    setSelectedRole(available)
    setAgentName('')
    setRoleDescription('')
    setStrictGuardrails(true)
    setFallbackRoles(new Set(FALLBACK_ROLES_CANONICAL))
    setError(null)
    setDrawerOpen(true)
  }

  const openEdit = (a: Agent) => {
    setMode('edit')
    setEditing(a)
    setSelectedRole(a.role ?? 'sales')
    setAgentName(a.name)
    setRoleDescription(a.role_description)
    setStrictGuardrails(a.strict_guardrails)
    const persisted = (a.fallback_for_roles ?? FALLBACK_ROLES_CANONICAL).filter(
      (r): r is CanonicalRole =>
        (FALLBACK_ROLES_CANONICAL as readonly string[]).includes(r),
    )
    setFallbackRoles(new Set(persisted))
    setError(null)
    setDrawerOpen(true)
  }

  const onSuggest = async () => {
    setSuggesting(true)
    setError(null)
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      if (!session?.access_token) {
        setError('Sesión expirada'); return
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
      if (!agentName && data.agent_name) setAgentName(data.agent_name)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al sugerir con IA')
    } finally {
      setSuggesting(false)
    }
  }

  const onSave = () => {
    if (!agentName.trim()) { setError('El nombre del agente es obligatorio'); return }
    if (!roleDescription.trim()) { setError('El prompt maestro es obligatorio'); return }
    if (roleDescription.length > 2500) { setError('Máximo 2500 caracteres'); return }

    const fd = new FormData()
    fd.set('name', agentName.trim())
    fd.set('role', selectedRole)
    fd.set('role_description', roleDescription.trim())
    if (strictGuardrails) fd.set('strict_guardrails', 'on')
    // Solo enviar fallback_for_roles si estamos editando el default
    // (server action ignora para non-default igual, pero limpiamos payload).
    if (mode === 'edit' && editing?.is_default) {
      // Array.from() en vez de for-of directo: el tsconfig del proyecto NO
      // tiene downlevelIteration habilitado, e iterar Set<T> directo rompe
      // `next build` (baseline 2026-05-29 — bug detectado al validar build).
      Array.from(fallbackRoles).forEach(r => {
        fd.append('fallback_for_roles', r)
      })
    }

    startTransition(async () => {
      let result: { ok: boolean; error?: string }
      if (mode === 'create') {
        result = await createAgent(fd)
      } else {
        fd.set('id', editing?.id ?? '')
        result = await updateAgent(fd)
      }
      if (result.ok) {
        setDrawerOpen(false)
      } else {
        setError(result.error ?? 'Error al guardar')
      }
    })
  }

  const onDelete = async (a: Agent) => {
    if (!a.id) return
    if (a.is_default) { toast.error('No puedes borrar el agente default.'); return }
    if (!(await confirmar({
      title: `¿Borrar agente "${a.name}"?`,
      description: 'Esta acción no se puede deshacer.',
      confirmLabel: 'Borrar', destructive: true,
    }))) return
    const fd = new FormData()
    fd.set('id', a.id)
    startTransition(async () => {
      const result = await deleteAgent(fd)
      if (!result.ok) toast.error(result.error ?? 'Error al borrar')
    })
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" /> Tus Agentes IA
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {agents.length === 0
              ? 'Aún no tienes agentes — crea el primero.'
              : `${agents.length} agente${agents.length === 1 ? '' : 's'} configurado${agents.length === 1 ? '' : 's'}. El router pre-LLM elige cuál atiende cada mensaje según el rol.`}
          </p>
        </div>
        {canWrite && (
          <Button onClick={openCreate} size="sm" className="gap-1.5" disabled={isPending}>
            <Plus className="h-4 w-4" /> Crear agente
          </Button>
        )}
      </div>

      {/* Decisión 2 — Sugerencia roles no creados.
          Card discreta que invita (NO obliga) a crear los faltantes.
          Cuando un cliente envía un mensaje que NO tiene rol especialista
          asignado, el AGENTE DEFAULT lo atiende (decisión 1 = A). Eso
          funciona, pero crear el especialista da mejor UX + tools
          enforcement específico por rol. */}
      {canWrite && agents.length > 0 && agents.length < ALL_ROLES.length && (() => {
        const missingRoles = ALL_ROLES.filter(r => !takenRoles.has(r) && r !== 'custom')
        if (missingRoles.length === 0) return null
        const ROLE_VALUE: Record<string, string> = {
          sales:     'Atención a ventas y compras',
          support:   'Tracking, post-venta, dudas de envíos',
          marketing: 'Promociones y comunicación HSM proactiva',
          claims:    'Devoluciones, reclamos, garantías (Ley 1480)',
        }
        return (
          <div className="rounded-lg border border-amber-700/25 bg-amber-500/5 p-3.5 mt-1 space-y-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-amber-700" />
              <p className="text-sm font-semibold text-foreground">
                Sugerencia: mejora la cobertura de tu bot
              </p>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Hoy el agente <strong>default</strong> recibe los mensajes que no
              encajan en un rol específico. Crear especialistas para los roles
              faltantes mejora la precisión + activa guardrails por rol.
            </p>
            <div className="space-y-1 pt-1">
              {missingRoles.map(r => (
                <div key={r} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">•</span>
                    <span className={`text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full border ${ROLE_BADGE[r] ?? ROLE_BADGE.custom}`}>
                      {ROLE_LABEL[r]}
                    </span>
                    <span className="text-muted-foreground">{ROLE_VALUE[r]}</span>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground pt-1 italic">
              Opcional — el bot funciona sin estos. Crear es 1 click + IA genera el prompt.
            </p>
          </div>
        )
      })()}

      {/* Lista agentes */}
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
                {canWrite && (
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => openEdit(a)}
                      disabled={isPending}
                      className="inline-flex items-center gap-1 h-7 px-2.5 text-xs font-medium rounded-md border border-border hover:bg-muted/40 transition-colors"
                    >
                      <Pencil className="h-3 w-3" /> Editar
                    </button>
                    {!a.is_default && (
                      <button
                        type="button"
                        onClick={() => onDelete(a)}
                        disabled={isPending}
                        className="inline-flex items-center gap-1 h-7 px-2 text-xs font-medium rounded-md border border-destructive/30 text-destructive hover:bg-destructive/5 transition-colors"
                        title="Borrar agente"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Drawer crear/editar */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-primary" />
              {mode === 'create' ? 'Crear agente' : `Editar agente: ${editing?.name}`}
            </SheetTitle>
          </SheetHeader>

          <div className="space-y-5 py-4">
            <div className="space-y-2">
              <Label>Rol funcional {editing?.is_default && <span className="text-xs text-muted-foreground font-normal">(bloqueado para el agente default)</span>}</Label>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {ALL_ROLES.map(key => {
                  const isThisAgent = mode === 'edit' && (editing?.role ?? 'sales') === key
                  // En crear: rol bloqueado si ya tomado
                  // En editar: rol bloqueado si es default O si otro agente lo tiene
                  const disabled = editing?.is_default
                    ? key !== 'sales'
                    : (mode === 'create' ? takenRoles.has(key) : (takenRoles.has(key) && !isThisAgent))
                  return (
                    <button
                      type="button"
                      key={key}
                      onClick={() => !disabled && setSelectedRole(key)}
                      disabled={disabled || isPending}
                      className={`text-xs font-medium px-3 py-2 rounded-md border transition-colors ${
                        selectedRole === key
                          ? 'border-primary bg-primary/10 text-primary'
                          : disabled
                            ? 'border-border/30 bg-muted/20 text-muted-foreground/40 cursor-not-allowed line-through'
                            : 'border-border bg-background text-foreground hover:bg-muted/40'
                      }`}
                    >
                      {ROLE_LABEL[key]}
                    </button>
                  )
                })}
              </div>
              <p className="text-[11px] text-muted-foreground">
                Solo 1 agente por rol. Los tachados ya están asignados a otro agente.
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
                disabled={isPending}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="prompt_new">Prompt Maestro</Label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={suggesting || isPending}
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
                disabled={isPending}
              />
              <p className="text-[11px] text-muted-foreground">
                {roleDescription.length}/2500 — La IA lee la filosofía del negocio + catálogo para personalizar.
              </p>
            </div>

            {mode === 'edit' && editing?.is_default && (
              <div className="rounded-lg border border-border p-3.5 bg-muted/20 space-y-2.5">
                <div>
                  <Label className="text-sm">Suplir cuando NO exista agente especialista</Label>
                  <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">
                    Este agente <strong>default</strong> atiende los roles marcados
                    cuando el tenant no tiene especialista para ellos. Los roles
                    desmarcados escalan automáticamente a un asesor humano.
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-1.5 pt-1">
                  {FALLBACK_ROLES_CANONICAL.map(r => {
                    const checked = fallbackRoles.has(r)
                    const hasSpecialist = agents.some(
                      a => !a.is_default && (a.role ?? '') === r,
                    )
                    return (
                      <label
                        key={r}
                        className={`flex items-center gap-2 text-xs px-2.5 py-1.5 rounded-md border ${
                          hasSpecialist
                            ? 'border-border/30 bg-muted/10 text-muted-foreground/60'
                            : 'border-border bg-background cursor-pointer hover:bg-muted/30'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={hasSpecialist || isPending}
                          onChange={e => {
                            const next = new Set(fallbackRoles)
                            if (e.target.checked) next.add(r)
                            else next.delete(r)
                            setFallbackRoles(next)
                          }}
                          className="h-3.5 w-3.5 accent-primary"
                        />
                        <span className="font-medium">{ROLE_LABEL[r]}</span>
                        {hasSpecialist && (
                          <span className="text-[10px] text-muted-foreground/70 italic ml-auto">
                            ya tiene especialista
                          </span>
                        )}
                      </label>
                    )
                  })}
                </div>
                <p className="text-[10px] text-muted-foreground/70 pt-1 italic">
                  Marca un rol como NO cubierto si prefieres que un humano lo atienda
                  (ej. reclamos legales). Backward-compat: todos marcados = comportamiento anterior.
                </p>
              </div>
            )}

            <div className="flex items-center justify-between rounded-lg border border-border p-3 bg-muted/20">
              <div>
                <Label className="text-sm">Guardrails estrictos</Label>
                <p className="text-[11px] text-muted-foreground">
                  Si activo, el bot NUNCA inventa precios ni inventa categorías; escala a humano si no tiene certeza.
                </p>
              </div>
              <input
                type="checkbox"
                checked={strictGuardrails}
                onChange={e => setStrictGuardrails(e.target.checked)}
                disabled={isPending}
                className="h-4 w-4 accent-primary"
              />
            </div>

            {error && (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                {error}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2 border-t border-border">
              <Button variant="ghost" onClick={() => setDrawerOpen(false)} disabled={isPending}>
                Cancelar
              </Button>
              <Button onClick={onSave} disabled={isPending} className="gap-1.5">
                {isPending
                  ? <><Loader2 className="h-4 w-4 animate-spin" /> Guardando</>
                  : <><Check className="h-4 w-4" /> {mode === 'create' ? 'Crear agente' : 'Guardar cambios'}</>
                }
              </Button>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
