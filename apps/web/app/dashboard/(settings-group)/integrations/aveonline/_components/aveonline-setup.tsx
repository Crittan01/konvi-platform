'use client'

/**
 * Tab Setup — Aveonline. Rev. 107 O.2.
 *
 * NOTA Next.js: `'use client'` DEBE ser la primera línea del archivo
 * (antes de cualquier comentario o import). Cualquier código previo
 * hace que Next.js no detecte la directiva y trate el archivo como
 * Server Component → "Invalid hook call" en useState/useTransition.
 *
 * Comportamiento:
 *   • Si NO connected → form inline (usuario + password + versión auth).
 *     Submit → server action `connectAveonline` que hace POST de prueba
 *     a Aveonline y persiste credentials en Vault.
 *   • Si connected → muestra status: empresa_id + asesor + JWT info.
 *     Acción "Desconectar" disponible para owner/manager.
 *
 * NO usa SetupPrimitives genéricos (Envia los reusa) — Aveonline tiene
 * un flujo más activo (form de conexión inline) que justifica wiring
 * custom. Estructura visual mantenida coherente con Envia.
 */

import { useEffect, useState, useTransition } from 'react'
import { KeyRound, Package, UserCheck, AlertCircle, CheckCircle2, Truck, Loader2, RefreshCw, Webhook, Copy, Trash2 } from 'lucide-react'
import { useConfirm } from '@/components/ui/confirm-dialog'

type AveonlineAgent = {
  id: string
  nombre: string
  direccion: string
  idciudad: string
  telefono: string
  email: string
  principal: boolean
}

type Props = {
  connected: boolean
  credentials: Record<string, unknown>
  connectAction: (formData: FormData) => Promise<{ ok: boolean; error?: string }>
  disconnectAction: () => Promise<{ ok: boolean; error?: string }>
  saveIdagenteAction: (formData: FormData) => Promise<{ ok: boolean; error?: string }>
}

export default function AveonlineSetup({
  connected, credentials, connectAction, disconnectAction, saveIdagenteAction,
}: Props) {
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [isPending, startTransition] = useTransition()
  const confirmar = useConfirm()

  const handleConnect = (formData: FormData) => {
    setError(null)
    setSuccess(null)
    startTransition(async () => {
      const result = await connectAction(formData)
      if (result.ok) {
        setSuccess('Conexión Aveonline establecida correctamente.')
      } else {
        setError(result.error ?? 'Error desconocido')
      }
    })
  }

  const handleDisconnect = async () => {
    if (!(await confirmar({
      title: '¿Desconectar Aveonline?',
      description: 'Las cotizaciones futuras no usarán este provider hasta que vuelvas a conectarlo.',
      confirmLabel: 'Desconectar',
      destructive: true,
    }))) {
      return
    }
    setError(null)
    setSuccess(null)
    startTransition(async () => {
      const result = await disconnectAction()
      if (result.ok) {
        setSuccess('Aveonline desconectado.')
      } else {
        setError(result.error ?? 'Error al desconectar')
      }
    })
  }

  const handleSaveIdagente = (formData: FormData) => {
    setError(null)
    setSuccess(null)
    startTransition(async () => {
      const result = await saveIdagenteAction(formData)
      if (result.ok) {
        setSuccess('ID Agente guardado. Las próximas guías Aveonline lo incluirán.')
      } else {
        setError(result.error ?? 'Error al guardar ID Agente.')
      }
    })
  }

  // Galería de agentes desde Aveonline live — se carga al montar cuando connected.
  const [agents, setAgents] = useState<AveonlineAgent[]>([])
  const [agentsLoading, setAgentsLoading] = useState(false)
  const [agentsError, setAgentsError] = useState<string | null>(null)

  const fetchAgents = async () => {
    setAgentsLoading(true)
    setAgentsError(null)
    try {
      const resp = await fetch('/api/integrations/aveonline/agents', {
        method: 'GET',
        credentials: 'include',
      })
      if (!resp.ok) {
        const body = await resp.text()
        throw new Error(`HTTP ${resp.status}: ${body.slice(0, 200)}`)
      }
      const body = await resp.json() as {
        agents: AveonlineAgent[]
        warning?: string
        current_idagente?: string | null
      }
      setAgents(body.agents || [])
      if (body.warning) setAgentsError(body.warning)
    } catch (err) {
      setAgentsError(err instanceof Error ? err.message : 'Error consultando Aveonline')
    } finally {
      setAgentsLoading(false)
    }
  }

  useEffect(() => {
    if (connected) {
      void fetchAgents()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected])

  if (!connected) {
    return (
      <div className="space-y-5">
        <div className="rounded-lg border border-border bg-card p-5 space-y-4">
          <div className="flex items-center gap-2 text-foreground">
            <KeyRound className="h-5 w-5 text-muted-foreground" />
            <h3 className="font-semibold">Conectar cuenta Aveonline</h3>
          </div>

          <p className="text-sm text-muted-foreground">
            Ingresa las credenciales de tu cuenta Aveonline. Validaremos
            la conexión contra <code className="font-mono text-xs">app.aveonline.co/api/comunes/v1.0/autenticarusuario.php</code>{' '}
            antes de guardar. Tu password se almacena cifrada en Supabase Vault.
          </p>

          <form action={handleConnect} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="usuario" className="text-sm font-medium text-foreground">
                  Usuario
                </label>
                <input
                  id="usuario"
                  name="usuario"
                  type="text"
                  required
                  minLength={3}
                  autoComplete="username"
                  placeholder="ej. mi-empresa-ecommerce"
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="password" className="text-sm font-medium text-foreground">
                  Password
                </label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  required
                  minLength={4}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            </div>

            <details className="text-sm">
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors">
                Opciones avanzadas <span className="text-xs text-muted-foreground/70">(usuario técnico — valores por defecto funcionan)</span>
              </summary>
              <div className="mt-3 space-y-5 pl-3 border-l-2 border-border">
                <div className="space-y-1.5">
                  <label htmlFor="auth_version" className="text-sm font-medium text-foreground">
                    Versión de autenticación de Aveonline
                  </label>
                  <select
                    id="auth_version"
                    name="auth_version"
                    defaultValue="v1.0"
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="v1.0">v1.0 — legacy, vigente (recomendado)</option>
                    <option value="v2.0">v2.0 — JWT 12h (más reciente)</option>
                  </select>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    Aveonline ofrece varias versiones de auth coexistentes. La <strong>v1.0</strong> (legacy)
                    es la más usada y permite extender la duración del JWT vía <code className="font-mono text-[11px]">tiempoToken</code>.
                    La <strong>v2.0</strong> usa JWT con TTL fijo de 12h sin extensión. Si no estás seguro, deja v1.0.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="tiempo_token" className="text-sm font-medium text-foreground">
                    Duración del token JWT (segundos)
                  </label>
                  <input
                    id="tiempo_token"
                    name="tiempo_token"
                    type="number"
                    min="3600"
                    max="31536000"
                    defaultValue="100000"
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    Cuánto dura el JWT antes de expirar y necesitar re-autenticar.
                    Valores comunes: <code className="font-mono text-[11px]">3600</code> (1h, mínimo),{' '}
                    <code className="font-mono text-[11px]">100000</code> (~27h, default),{' '}
                    <code className="font-mono text-[11px]">31536000</code> (1 año, máximo, usado por plugin
                    WooCommerce oficial). Solo aplica a v1.0; v2.0 ignora este campo.
                  </p>
                </div>
              </div>
            </details>

            {error && (
              <div className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {success && (
              <div className="flex items-start gap-2 rounded-md border border-green-700/50 bg-green-50 px-3 py-2 text-sm text-green-800">
                <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
                <span>{success}</span>
              </div>
            )}

            <div className="flex items-center justify-between pt-2">
              <p className="text-xs text-muted-foreground">
                ¿No tienes cuenta? Contacta a{' '}
                <a href="mailto:desarrollo1@aveonline.co" className="underline">
                  desarrollo1@aveonline.co
                </a>
              </p>
              <button
                type="submit"
                disabled={isPending}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {isPending ? 'Conectando…' : 'Conectar Aveonline'}
              </button>
            </div>
          </form>
        </div>

        <div className="rounded-lg border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
          <strong className="text-foreground">Cuenta DEMO para pruebas:</strong>{' '}
          Aveonline ofrece cuenta pública <code className="font-mono text-xs">demointegracion</code>
          {' '}/ <code className="font-mono text-xs">demointegra2021</code> para
          validar la integración sin afectar tu cuenta productiva. Usa esa
          si quieres probar antes de configurar la real.
        </div>
      </div>
    )
  }

  // Connected state.
  const empresaId = credentials.empresa_id as number | undefined
  const usuario = credentials.usuario as string | undefined
  const razonSocial = credentials.razon_social as string | undefined
  const asesorLogistico = credentials.asesor_logistico as string | undefined
  const nombreAsesor = credentials.nombre_asesor as string | undefined
  const authVersion = credentials.auth_version as string | undefined
  const jwtExpiresAt = credentials.jwt_expires_at as string | undefined
  const passwordSecretId = credentials.password_secret_id as string | undefined
  const idagente = credentials.idagente as string | undefined

  return (
    <div className="space-y-5">
      {/* Identidad de cuenta */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-3">
        <div className="flex items-center gap-2 text-foreground">
          <Package className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-semibold">Cuenta Aveonline</h3>
        </div>
        <dl className="grid gap-3 sm:grid-cols-2 text-sm">
          <Row label="Empresa ID" value={empresaId?.toString() ?? '—'} mono />
          <Row label="Usuario" value={usuario ?? '—'} mono />
          <Row label="Razón social" value={razonSocial ?? '—'} />
          <Row label="Auth version" value={authVersion ?? 'v1.0'} mono />
        </dl>
      </div>

      {/* Asesor logístico (campo único de Aveonline — cuenta tiene asesor asignado) */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-3">
        <div className="flex items-center gap-2 text-foreground">
          <UserCheck className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-semibold">Asesor logístico asignado</h3>
        </div>
        <dl className="grid gap-3 sm:grid-cols-2 text-sm">
          <Row label="Nombre" value={nombreAsesor ?? '—'} />
          <Row label="ID asesor" value={asesorLogistico ?? '—'} mono />
        </dl>
        <p className="text-xs text-muted-foreground border-t border-border pt-2">
          Tu asesor es el contacto directo para escalación P0/P1 + SLA contractual.
          Aveonline no opera portal de tickets — contacto por email + WhatsApp business
          (+57 305 420 21 25, L-V 8-5 hora Colombia).
        </p>
      </div>

      {/* ID Agente — REQUERIDO para generación de guías (§3.5 dossier) */}
      <div className={`rounded-lg border p-5 space-y-3 ${
        idagente ? 'border-border bg-card' : 'border-amber-700/30 bg-amber-500/5'
      }`}>
        <div className="flex items-center gap-2 text-foreground">
          <Truck className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-semibold">ID Agente — Punto de despacho</h3>
        </div>
        {!idagente && (
          <div className="flex items-start gap-2 rounded-md border border-amber-700/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <div className="space-y-0.5">
              <p className="font-medium">ID Agente NO configurado</p>
              <p className="text-xs text-amber-200/80 leading-relaxed">
                Sin este ID, Aveonline rechazará la generación automática de guías
                con error{' '}
                <code className="font-mono text-[11px] bg-amber-500/10 px-1 rounded">999</code>{' '}
                tras el pago. Configúralo abajo para destrabar las guías post-pago.
              </p>
            </div>
          </div>
        )}
        <p className="text-sm text-muted-foreground leading-relaxed">
          Aveonline asigna un <strong className="text-foreground font-medium">ID
          numérico al punto de despacho/agencia</strong> con el que se generan
          las guías. Selecciona el agente que quieres usar como remitente
          por defecto:
        </p>

        {/* Loading galería de agentes */}
        {agentsLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Consultando agentes desde Aveonline…
          </div>
        )}
        {agentsError && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <div className="flex-1">
              <p>Error consultando agentes: {agentsError}</p>
              <button
                type="button"
                onClick={fetchAgents}
                className="mt-1 inline-flex items-center gap-1 text-xs text-foreground underline"
              >
                <RefreshCw className="h-3 w-3" /> Reintentar
              </button>
            </div>
          </div>
        )}

        {!agentsLoading && !agentsError && agents.length === 0 && (
          <div className="rounded-md border border-amber-700/30 bg-amber-500/5 p-3 text-sm text-amber-700">
            No hay agentes registrados en tu cuenta Aveonline. Pídele a tu
            asesor logístico que active al menos uno desde el panel
            Aveonline → Configuración → Agentes.
          </div>
        )}

        {!agentsLoading && agents.length > 0 && (
          <form action={handleSaveIdagente} className="space-y-3">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="idagente" className="text-sm font-medium text-foreground">
                  Agente seleccionado
                </label>
                <button
                  type="button"
                  onClick={fetchAgents}
                  className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                  title="Refrescar lista desde Aveonline"
                >
                  <RefreshCw className="h-3 w-3" /> Refrescar
                </button>
              </div>
              <select
                id="idagente"
                name="idagente"
                defaultValue={idagente ?? agents.find(a => a.principal)?.id ?? ''}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">— sin asignar —</option>
                {agents.map(a => (
                  <option key={a.id} value={a.id}>
                    {a.principal ? '★ ' : ''}{a.nombre} · ID {a.id} · {a.idciudad}
                    {a.direccion ? ` · ${a.direccion}` : ''}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-muted-foreground">
                {agents.length} agente{agents.length !== 1 ? 's' : ''} disponible
                {agents.length !== 1 ? 's' : ''} · ★ = principal de la cuenta
              </p>
            </div>
            <button
              type="submit"
              disabled={isPending}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {isPending ? 'Guardando…' : 'Guardar selección'}
            </button>
          </form>
        )}

        <p className="text-xs text-muted-foreground border-t border-border pt-2">
          La lista viene en vivo desde tu cuenta Aveonline. Si agregas un
          nuevo agente en{' '}
          <a
            href="https://app.aveonline.co"
            target="_blank"
            rel="noreferrer"
            className="underline text-foreground"
          >
            app.aveonline.co
          </a>
          {' '}→ Configuración → Agentes, presiona &quot;Refrescar&quot; para verlo aquí.
        </p>
      </div>

      {/* Credenciales / Vault */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-3">
        <div className="flex items-center gap-2 text-foreground">
          <KeyRound className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-semibold">Credenciales</h3>
        </div>
        <dl className="grid gap-3 sm:grid-cols-2 text-sm">
          <Row
            label="Password (Vault)"
            value={passwordSecretId ? `secret_${passwordSecretId.slice(0, 8)}…` : '—'}
            mono
          />
          <Row
            label="JWT expira en"
            value={
              jwtExpiresAt
                ? new Date(jwtExpiresAt).toLocaleString('es-CO')
                : '—'
            }
          />
        </dl>
        <p className="text-xs text-muted-foreground border-t border-border pt-2">
          JWT se auto-refresca antes de expirar (buffer 10 min) cuando el bot
          cotiza. No requiere acción manual.
        </p>
      </div>

      {/* Webhook estados de guía (Rev. 108) */}
      <AveonlineWebhookSection />

      {/* Zona de riesgo */}
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-5 space-y-3">
        <h3 className="font-semibold text-destructive">Zona de riesgo</h3>
        <p className="text-sm text-muted-foreground">
          Desconectar Aveonline detiene las cotizaciones de envío: el bot dejará
          de ofrecer costos de despacho hasta que vuelvas a conectarlo. Las
          guías ya generadas siguen rastreándose por sus tracking_numbers.
        </p>
        {error && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {success && (
          <div className="flex items-start gap-2 rounded-md border border-green-700/50 bg-green-50 px-3 py-2 text-sm text-green-800">
            <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{success}</span>
          </div>
        )}
        <button
          type="button"
          onClick={() => void handleDisconnect()}
          disabled={isPending}
          className="rounded-md border border-destructive bg-background px-4 py-2 text-sm font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50"
        >
          {isPending ? 'Desconectando…' : 'Desconectar Aveonline'}
        </button>
      </div>
    </div>
  )
}

function AveonlineWebhookSection() {
  type Status = {
    configured: boolean
    url: string
    rotated_at: string | null
    expires_at: string | null
    has_grace_period: boolean
    audit_log_count: number
  }
  const [status, setStatus] = useState<Status | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [secret, setSecret] = useState<string | null>(null)
  const confirmar = useConfirm()

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/integrations/aveonline/webhook', {
        method: 'GET',
        credentials: 'include',
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json() as Status
      setStatus(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error consultando webhook')
    } finally {
      setLoading(false)
    }
  }

  // Solo al montar: carga inicial del estado del webhook. `refresh` no va en deps a
  // propósito (recrearía el efecto en cada render → re-fetch en loop).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void refresh() }, [])

  const configure = async () => {
    if (!(await confirmar({
      title: '¿Configurar webhook Aveonline?',
      description: 'Se generará un secret nuevo y se registrará automáticamente en tu cuenta Aveonline.',
      confirmLabel: 'Configurar webhook',
    }))) {
      return
    }
    setBusy(true)
    setError(null)
    setSuccess(null)
    setSecret(null)
    try {
      const resp = await fetch('/api/integrations/aveonline/webhook/configure', {
        method: 'POST',
        credentials: 'include',
      })
      const data = await resp.json()
      if (!resp.ok || !data.ok) {
        throw new Error(data.detail || data.aveonline_message || 'Error configurando')
      }
      setSecret(data.plaintext_secret as string)
      setSuccess(
        data.aveonline_registered
          ? 'Webhook registrado en Aveonline correctamente.'
          : `Secret guardado localmente. Registro Aveonline: ${data.aveonline_message || 'sin confirmación'}`,
      )
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error configurando webhook')
    } finally {
      setBusy(false)
    }
  }

  const rotate = async () => {
    if (!(await confirmar({
      title: '¿Rotar el secret del webhook?',
      description: 'El secret actual seguirá válido 7 días (periodo de gracia) mientras Aveonline migra al nuevo.',
      confirmLabel: 'Rotar secret',
    }))) {
      return
    }
    setBusy(true)
    setError(null)
    setSuccess(null)
    setSecret(null)
    try {
      const resp = await fetch('/api/integrations/aveonline/webhook/rotate', {
        method: 'POST',
        credentials: 'include',
      })
      const data = await resp.json()
      if (!resp.ok || !data.ok) {
        throw new Error(data.detail || 'Error rotando')
      }
      setSecret(data.plaintext_secret as string)
      setSuccess('Secret rotado. Aveonline usa automáticamente el nuevo.')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error rotando webhook')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!(await confirmar({
      title: '¿Eliminar el webhook?',
      description: 'Dejarás de recibir estados de envío en tiempo real. El tracking on-demand sigue funcionando.',
      confirmLabel: 'Eliminar webhook',
      destructive: true,
    }))) {
      return
    }
    setBusy(true)
    setError(null)
    setSuccess(null)
    setSecret(null)
    try {
      const resp = await fetch('/api/integrations/aveonline/webhook', {
        method: 'DELETE',
        credentials: 'include',
      })
      if (resp.status !== 204) {
        const data = await resp.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }
      setSuccess('Webhook eliminado.')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error eliminando webhook')
    } finally {
      setBusy(false)
    }
  }

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setSuccess('Copiado al portapapeles.')
    } catch {
      setError('No se pudo copiar.')
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-foreground">
          <Webhook className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-semibold">Webhook de estados</h3>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading || busy}
          className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Actualizar
        </button>
      </div>

      <p className="text-sm text-muted-foreground">
        Recibe en tiempo real cambios de estado del envío (en ruta, entregado,
        novedad) reportados por la transportadora. Te avisamos al cliente
        automáticamente vía WhatsApp + email solo cuando el courier confirma
        el cambio físico — no antes.
      </p>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Consultando estado…
        </div>
      )}

      {!loading && status && (
        <div className="rounded-md border border-border bg-muted/30 p-4 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-0.5">
              <div className="text-xs text-muted-foreground">Estado</div>
              <div className="text-sm font-medium text-foreground flex items-center gap-2">
                {status.configured ? (
                  <>
                    <CheckCircle2 className="h-4 w-4 text-green-700" />
                    Configurado
                  </>
                ) : (
                  <>
                    <AlertCircle className="h-4 w-4 text-amber-700" />
                    Sin configurar
                  </>
                )}
              </div>
            </div>
            {status.configured && status.has_grace_period && (
              <span className="text-xs px-2 py-1 rounded-md bg-amber-100 text-amber-900 border border-amber-700">
                Rotación reciente — grace activo
              </span>
            )}
          </div>

          <div className="space-y-1.5">
            <div className="text-xs text-muted-foreground">URL del webhook</div>
            <div className="flex items-center gap-2">
              <code className="font-mono text-xs px-2 py-1.5 rounded-md bg-background border border-border flex-1 truncate">
                {status.url}
              </code>
              <button
                type="button"
                onClick={() => void copyToClipboard(status.url)}
                className="text-muted-foreground hover:text-foreground p-1.5 rounded-md hover:bg-muted"
                title="Copiar URL"
              >
                <Copy className="h-4 w-4" />
              </button>
            </div>
          </div>

          {status.configured && status.rotated_at && (
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <div className="text-muted-foreground">Última rotación</div>
                <div className="text-foreground">
                  {new Date(status.rotated_at).toLocaleString('es-CO')}
                </div>
              </div>
              {status.expires_at && (
                <div>
                  <div className="text-muted-foreground">Recomendado rotar antes de</div>
                  <div className="text-foreground">
                    {new Date(status.expires_at).toLocaleDateString('es-CO')}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {secret && (
        <div className="rounded-md border border-amber-700 bg-amber-50 p-4 space-y-2">
          <div className="flex items-center gap-2 text-amber-900 font-medium text-sm">
            <KeyRound className="h-4 w-4" />
            Secret generado — guárdalo ahora
          </div>
          <p className="text-xs text-amber-800">
            Este secret se muestra una sola vez. Aveonline ya lo recibió y lo
            usará automáticamente al enviar webhooks. Solo lo necesitas si
            quieres reconfigurar manualmente en el panel Aveonline.
          </p>
          <div className="flex items-center gap-2">
            <code className="font-mono text-xs px-2 py-1.5 rounded-md bg-background border border-amber-700 flex-1 break-all">
              {secret}
            </code>
            <button
              type="button"
              onClick={() => void copyToClipboard(secret)}
              className="text-amber-900 hover:bg-amber-100 p-1.5 rounded-md"
              title="Copiar secret"
            >
              <Copy className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && !secret && (
        <div className="flex items-start gap-2 rounded-md border border-green-700/50 bg-green-50 px-3 py-2 text-sm text-green-800">
          <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {!status?.configured ? (
          <button
            type="button"
            onClick={() => void configure()}
            disabled={busy}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {busy ? 'Configurando…' : 'Configurar webhook'}
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={() => void rotate()}
              disabled={busy}
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50 flex items-center gap-2"
            >
              <RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />
              Rotar secret
            </button>
            <button
              type="button"
              onClick={() => void remove()}
              disabled={busy}
              className="rounded-md border border-destructive/40 bg-background px-4 py-2 text-sm font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50 flex items-center gap-2"
            >
              <Trash2 className="h-4 w-4" />
              Eliminar webhook
            </button>
          </>
        )}
      </div>
    </div>
  )
}


function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={`text-sm text-foreground ${mono ? 'font-mono' : ''}`}>
        {value}
      </dd>
    </div>
  )
}
