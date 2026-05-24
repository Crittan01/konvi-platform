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

import { useState, useTransition } from 'react'
import { KeyRound, Package, Phone, UserCheck, AlertCircle, CheckCircle2, Truck } from 'lucide-react'

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

  const handleDisconnect = () => {
    if (!confirm('¿Desconectar Aveonline? Las cotizaciones futuras no usarán este provider hasta reconectar.')) {
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
        idagente ? 'border-border bg-card' : 'border-amber-500/30 bg-amber-500/5'
      }`}>
        <div className="flex items-center gap-2 text-foreground">
          <Truck className="h-5 w-5 text-muted-foreground" />
          <h3 className="font-semibold">ID Agente — Punto de despacho</h3>
        </div>
        {!idagente && (
          <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
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
          las guías. Lo encuentras en{' '}
          <a
            href="https://app.aveonline.co"
            target="_blank"
            rel="noreferrer"
            className="underline text-foreground"
          >
            app.aveonline.co
          </a>
          {' '}→ Configuración → Agentes/Puntos de despacho. Tu asesor logístico también puede confirmártelo.
        </p>
        <form action={handleSaveIdagente} className="flex items-end gap-3">
          <div className="flex-1 space-y-1.5">
            <label htmlFor="idagente" className="text-sm font-medium text-foreground">
              ID Agente (numérico)
            </label>
            <input
              id="idagente"
              name="idagente"
              type="text"
              inputMode="numeric"
              pattern="\d{1,10}"
              defaultValue={idagente ?? ''}
              placeholder="ej. 12345"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <button
            type="submit"
            disabled={isPending}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 shrink-0"
          >
            {isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </form>
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

      {/* Zona de riesgo */}
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-5 space-y-3">
        <h3 className="font-semibold text-destructive">Zona de riesgo</h3>
        <p className="text-sm text-muted-foreground">
          Desconectar Aveonline detiene cotizaciones de este provider. El bot
          volverá a usar Envia si está configurado como provider activo. Las
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
          onClick={handleDisconnect}
          disabled={isPending}
          className="rounded-md border border-destructive bg-background px-4 py-2 text-sm font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50"
        >
          {isPending ? 'Desconectando…' : 'Desconectar Aveonline'}
        </button>
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
