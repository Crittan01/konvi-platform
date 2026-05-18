/**
 * Tab Setup — Envia.
 *
 * Display-only hoy. Save/disconnect siguen en /integrations (manager legacy).
 */
import {
  Truck, KeyRound, MapPin, ShieldCheck, AlertCircle,
} from 'lucide-react'

type Props = {
  connected: boolean
  credentials: Record<string, unknown>
  sandbox: boolean
  danePostal: string | null
}

export default function EnviaSetup({
  connected, credentials, sandbox, danePostal,
}: Props) {
  if (!connected) {
    return (
      <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center space-y-3">
        <Truck className="h-8 w-8 mx-auto text-muted-foreground/60" />
        <p className="text-sm text-muted-foreground">
          Envia aún no está conectado para este tenant.
        </p>
        <p className="text-xs text-muted-foreground">
          La conexión se realiza desde el panel principal de Integraciones.
        </p>
      </div>
    )
  }

  const apiTokenSecretId = credentials.api_token_secret_id as string | undefined

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-border bg-card p-4 space-y-4">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">API Token</h3>
          <span className="ml-auto text-xs text-muted-foreground bg-muted/30 border rounded-full px-2 py-0.5">
            Ambiente: {sandbox ? 'Sandbox' : 'Producción'}
          </span>
        </div>
        <div className="space-y-0.5">
          <div className="text-xs text-muted-foreground">Token (Vault)</div>
          <div className="font-mono text-sm">
            {apiTokenSecretId ? `secret_${apiTokenSecretId.slice(0, 8)}…` : '—'}
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-4 space-y-4">
        <div className="flex items-center gap-2">
          <MapPin className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Origen de despacho</h3>
        </div>
        <div className="space-y-0.5">
          <div className="text-xs text-muted-foreground">Código postal DANE</div>
          <div className="font-mono text-sm">
            {danePostal ?? '— (configurar en Configuración → General)'}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Usado por todos los carriers para calcular tarifas desde tu ciudad.
        </p>
      </section>

      <section className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-emerald-700" />
          <h3 className="font-semibold text-foreground">Gates de cumplimiento</h3>
        </div>
        <div className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Idempotency-Key local</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              Activo (H.2.1)
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Webhook HMAC</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              Activo (H.2.2)
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Polling backup tracking</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              Activo (H.2.3)
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Scope country='CO'</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              Enforced (H.2.12)
            </span>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-amber-700/30 bg-amber-700/5 p-4 flex items-start gap-3">
        <AlertCircle className="h-4 w-4 text-amber-800 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-900">
          Editar token o desconectar se hace desde la página principal de
          Integraciones. Migración a este panel: Sem 8.
        </p>
      </section>
    </div>
  )
}
