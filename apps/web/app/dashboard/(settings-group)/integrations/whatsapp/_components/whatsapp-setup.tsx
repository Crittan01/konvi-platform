/**
 * Tab Setup — WhatsApp.
 *
 * Muestra credenciales + status de la integración. Read-only por ahora
 * (configuración via Embedded Signup en /dashboard/integrations hub).
 */
import { Copy, KeyRound, Webhook, Shield, ShieldCheck, ShieldOff } from 'lucide-react'

type Props = {
  connected: boolean
  credentials: Record<string, string>
  canWrite: boolean
}

function MaskedField({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) {
    return (
      <div className="space-y-0.5">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="text-sm text-muted-foreground italic">No configurado</div>
      </div>
    )
  }
  return (
    <div className="space-y-0.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  )
}

export default function WhatsAppSetup({ connected, credentials }: Props) {
  const wabaId = credentials.waba_id ?? null
  const phoneNumberId = credentials.phone_number_id ?? null
  const displayPhone = credentials.display_phone_number ?? null
  const accessTokenSecretId = credentials.access_token_secret_id ?? null
  const tokenRotatedAt = credentials.access_token_rotated_at ?? null

  if (!connected) {
    return (
      <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center space-y-3">
        <Shield className="h-8 w-8 mx-auto text-muted-foreground/60" />
        <p className="text-sm text-muted-foreground">
          WhatsApp Business aún no está conectado para este tenant.
        </p>
        <p className="text-xs text-muted-foreground">
          La conexión se realiza vía Embedded Signup desde el panel de Integraciones.
          Próximamente podrás iniciar el flujo desde aquí.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/* Credenciales WABA */}
      <section className="rounded-xl border border-border bg-card p-4 space-y-4">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Credenciales WABA</h3>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <MaskedField label="WABA ID" value={wabaId} />
          <MaskedField label="Phone Number ID" value={phoneNumberId} />
          <MaskedField label="Número visible" value={displayPhone} />
          <MaskedField
            label="Access Token (Vault)"
            value={accessTokenSecretId ? `secret_${accessTokenSecretId.slice(0, 8)}…` : null}
          />
        </div>
        {tokenRotatedAt && (
          <p className="text-xs text-muted-foreground">
            Última rotación de token: {new Date(tokenRotatedAt).toLocaleDateString('es-CO')}
          </p>
        )}
      </section>

      {/* Webhook */}
      <section className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Webhook className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Webhook</h3>
        </div>
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">URL recibido por Meta</div>
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate font-mono text-xs bg-muted/30 rounded px-2 py-1.5 border">
              https://api.konvi.co/api/v1/whatsapp/webhook
            </code>
            <button
              type="button"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              data-copy="https://api.konvi.co/api/v1/whatsapp/webhook"
            >
              <Copy className="h-3 w-3" /> Copiar
            </button>
          </div>
        </div>
      </section>

      {/* Compliance gates activos */}
      <section className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-emerald-700" />
          <h3 className="font-semibold text-foreground">Gates de cumplimiento</h3>
        </div>
        <div className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Ventana 24h CSW Meta</span>
            <span className="inline-flex items-center gap-1 text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              <ShieldCheck className="h-3 w-3" /> Enforcement activo
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Auto opt-out STOP</span>
            <span className="inline-flex items-center gap-1 text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              <ShieldCheck className="h-3 w-3" /> Activo
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Habeas Data Ley 1581</span>
            <span className="inline-flex items-center gap-1 text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              <ShieldCheck className="h-3 w-3" /> Certified
            </span>
          </div>
        </div>
      </section>

      {/* Danger zone */}
      <section className="rounded-xl border border-rose-700/30 bg-rose-700/5 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <ShieldOff className="h-4 w-4 text-rose-800" />
          <h3 className="font-semibold text-rose-900">Zona de riesgo</h3>
        </div>
        <p className="text-sm text-rose-900/80">
          Desconectar WhatsApp interrumpe el bot conversacional y deja al cliente
          sin canal automático. Tus plantillas aprobadas se conservan; podrás
          reconectar luego sin perderlas.
        </p>
        <button
          type="button"
          className="text-sm font-medium text-rose-800 hover:text-rose-900 underline"
          disabled
          title="Disponible próximamente"
        >
          Desconectar WhatsApp (próximamente)
        </button>
      </section>
    </div>
  )
}
