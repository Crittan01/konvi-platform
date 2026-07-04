/**
 * Tab Setup — Mercado Libre.
 *
 * Estructura canónica unificada (Sem 7 F2 cierre):
 *   1. Identidad — Seller ID + token expiration
 *   2. Webhook & Eventos — URL + topics suscritos
 *   3. Cumplimiento — IP allowlist · refresh automático
 *   4. Zona de riesgo — desconectar (deshabilitado hoy)
 *   + Banner migración
 */
import { ShoppingBag, KeyRound, Webhook } from 'lucide-react'
import {
  SetupSection, SetupField, SetupGrid,
  ComplianceSection, DangerZoneSection,
  MigrationBanner, EmptyDisconnected,
} from '../../_components/setup-primitives'
import { webhookUrl } from '@/lib/webhook-urls'

type Props = {
  connected: boolean
  sellerId: string | null
  tokenExpiresAt: string | null
}

export default function MeLiSetup({
  connected, sellerId, tokenExpiresAt,
}: Props) {
  if (!connected) {
    return (
      <EmptyDisconnected
        icon={ShoppingBag}
        providerLabel="Mercado Libre"
        helpText="La conexión se realiza vía OAuth desde el panel principal de Integraciones."
      />
    )
  }

  const expiresInDays = tokenExpiresAt
    ? Math.round(
        (new Date(tokenExpiresAt).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
      )
    : null

  return (
    <div className="space-y-5">
      {/* 1. Identidad */}
      <SetupSection icon={KeyRound} title="Identidad OAuth">
        <SetupGrid>
          <SetupField label="Seller ID" value={sellerId} />
          <SetupField
            label="Token expira"
            value={
              tokenExpiresAt ? (
                <>
                  {new Date(tokenExpiresAt).toLocaleDateString('es-CO')}
                  {expiresInDays !== null && expiresInDays > 0 && (
                    <span className="text-xs text-muted-foreground font-sans">
                      {' · en '}{expiresInDays} días
                    </span>
                  )}
                  {expiresInDays !== null && expiresInDays <= 0 && (
                    <span className="text-xs text-rose-800 font-sans">
                      {' · expirado'}
                    </span>
                  )}
                </>
              ) : null
            }
          />
        </SetupGrid>
        <p className="text-xs text-muted-foreground">
          Refresh automático activo cada vez que el token está cerca de expirar.
        </p>
      </SetupSection>

      {/* 2. Webhook & Eventos */}
      <SetupSection icon={Webhook} title="Webhook & Eventos">
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">URL configurada en panel MeLi</div>
          <code className="block font-mono text-xs bg-muted/30 rounded px-2 py-1.5 border break-all">
            {webhookUrl('mercadolibre')}
          </code>
        </div>
        <div className="text-xs text-muted-foreground pt-1 border-t border-border">
          Topics: <span className="font-mono">orders_v2 · items · shipments</span>
        </div>
      </SetupSection>

      {/* 3. Cumplimiento */}
      <ComplianceSection
        gates={[
          { label: 'Verificación origen webhook', value: 'IP allowlist activo' },
          { label: 'Refresh token', value: 'Automático' },
          { label: 'OAuth state HMAC + nonce', value: 'Activo' },
        ]}
      />

      {/* 4. Zona de riesgo */}
      <DangerZoneSection
        description={
          <>
            Desconectar Mercado Libre detiene sincronización de listings y
            mensajes post-venta. El refresh token se revoca de forma
            irreversible — para reconectar habrá que reautorizar via OAuth.
          </>
        }
        actionLabel="Desconectar Mercado Libre"
        actionDisabled
      />

      {/* Banner migración */}
      <MigrationBanner>
        Reconectar o desconectar Mercado Libre se hace desde{' '}
        <a href="/dashboard/integrations" className="underline font-medium">
          el panel de Integraciones
        </a>
        . Este panel es de solo lectura.
      </MigrationBanner>
    </div>
  )
}
