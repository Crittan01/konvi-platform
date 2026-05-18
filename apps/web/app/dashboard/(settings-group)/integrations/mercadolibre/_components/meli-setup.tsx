/**
 * Tab Setup — Mercado Libre.
 *
 * Display-only hoy. Conectar/desconectar via OAuth sigue en /integrations
 * (manager legacy).
 */
import { ShoppingBag, KeyRound, Shield, AlertCircle } from 'lucide-react'

type Props = {
  connected: boolean
  sellerId: string | null
  tokenExpiresAt: string | null
}

export default function MeLiSetup({ connected, sellerId, tokenExpiresAt }: Props) {
  if (!connected) {
    return (
      <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center space-y-3">
        <ShoppingBag className="h-8 w-8 mx-auto text-muted-foreground/60" />
        <p className="text-sm text-muted-foreground">
          Mercado Libre aún no está conectado para este tenant.
        </p>
        <p className="text-xs text-muted-foreground">
          La conexión se realiza vía OAuth desde el panel principal de Integraciones.
          Próximamente podrás iniciar el flujo desde aquí.
        </p>
      </div>
    )
  }

  const expiresInDays = tokenExpiresAt
    ? Math.round((new Date(tokenExpiresAt).getTime() - Date.now()) / (1000 * 60 * 60 * 24))
    : null

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-border bg-card p-4 space-y-4">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">OAuth Mercado Libre</h3>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground">Seller ID</div>
            <div className="font-mono text-sm">{sellerId ?? '—'}</div>
          </div>
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground">Token expira</div>
            <div className="font-mono text-sm">
              {tokenExpiresAt
                ? new Date(tokenExpiresAt).toLocaleDateString('es-CO')
                : '—'}
              {expiresInDays !== null && expiresInDays > 0 && (
                <span className="text-xs text-muted-foreground"> · en {expiresInDays} días</span>
              )}
              {expiresInDays !== null && expiresInDays <= 0 && (
                <span className="text-xs text-rose-800"> · expirado</span>
              )}
            </div>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Refresh automático activo cada vez que el token está cerca de expirar.
        </p>
      </section>

      <section className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-emerald-700" />
          <h3 className="font-semibold text-foreground">Webhook + IP allowlist</h3>
        </div>
        <div className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Webhook signature</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              IP allowlist activo
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Topics suscritos</span>
            <span className="text-xs text-muted-foreground">
              orders_v2 · items · shipments
            </span>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-amber-700/30 bg-amber-700/5 p-4 flex items-start gap-3">
        <AlertCircle className="h-4 w-4 text-amber-800 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-900">
          Desconectar / reconectar Mercado Libre se realiza desde la página
          principal de Integraciones (proceso OAuth). Migración a este panel:
          Sem 9.
        </p>
      </section>
    </div>
  )
}
