/**
 * Tab Setup — Wompi.
 *
 * Display-only hoy. Save/disconnect siguen en /integrations (manager legacy).
 */
import {
  CreditCard, KeyRound, Webhook, ShieldCheck, AlertCircle,
} from 'lucide-react'

type Props = {
  connected: boolean
  credentials: Record<string, unknown>
  mode: string | null
}

function maskedPreview(value: string | null | undefined, prefix?: string): string {
  if (!value) return '—'
  const visible = prefix && value.startsWith(prefix) ? value.slice(0, prefix.length + 4) : value.slice(0, 8)
  return `${visible}…●●●●`
}

export default function WompiSetup({ connected, credentials, mode }: Props) {
  if (!connected) {
    return (
      <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center space-y-3">
        <CreditCard className="h-8 w-8 mx-auto text-muted-foreground/60" />
        <p className="text-sm text-muted-foreground">
          Wompi aún no está conectado para este tenant.
        </p>
        <p className="text-xs text-muted-foreground">
          La conexión se realiza desde el panel principal de Integraciones.
        </p>
      </div>
    )
  }

  const publicKey = credentials.public_key as string | undefined
  const privateKeySecretId = credentials.private_key_secret_id as string | undefined
  const eventsKeySecretId = credentials.events_key_secret_id as string | undefined
  const integrityKeySecretId = credentials.integrity_key_secret_id as string | undefined

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-border bg-card p-4 space-y-4">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">API Keys</h3>
          {mode && (
            <span className="ml-auto text-xs text-muted-foreground bg-muted/30 border rounded-full px-2 py-0.5">
              Modo: {mode}
            </span>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground">Public key</div>
            <div className="font-mono text-sm">{maskedPreview(publicKey, 'pub_')}</div>
          </div>
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground">Private key</div>
            <div className="font-mono text-sm">
              {privateKeySecretId ? `secret_${privateKeySecretId.slice(0, 8)}…` : '—'}
            </div>
          </div>
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground">Events key</div>
            <div className="font-mono text-sm">
              {eventsKeySecretId ? `secret_${eventsKeySecretId.slice(0, 8)}…` : '—'}
            </div>
          </div>
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground">Integrity key</div>
            <div className="font-mono text-sm">
              {integrityKeySecretId ? `secret_${integrityKeySecretId.slice(0, 8)}…` : '—'}
            </div>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Las 3 claves privadas (private/events/integrity) están almacenadas
          encriptadas en Vault Supabase.
        </p>
      </section>

      <section className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Webhook className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Webhook</h3>
        </div>
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">URL configurada en panel Wompi</div>
          <code className="block font-mono text-xs bg-muted/30 rounded px-2 py-1.5 border">
            https://api.konvi.co/api/v1/wompi/webhook
          </code>
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-emerald-700" />
          <h3 className="font-semibold text-foreground">Gates de cumplimiento</h3>
        </div>
        <div className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Signature validation</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              HMAC-SHA256 enforced
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Idempotency lifecycle</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              ADR-0011 activo
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Retry + Circuit Breaker</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              Activo (H.3.2)
            </span>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-amber-700/30 bg-amber-700/5 p-4 flex items-start gap-3">
        <AlertCircle className="h-4 w-4 text-amber-800 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-900">
          Editar claves o desconectar se hace desde la página principal de
          Integraciones. Migración a este panel: Sem 8.
        </p>
      </section>
    </div>
  )
}
