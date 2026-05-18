/**
 * Tab Setup — Wompi.
 *
 * Estructura canónica unificada (Sem 7 F2 cierre):
 *   1. Identidad — 4 API keys (public/private/events/integrity)
 *   2. Webhook & Eventos — URL Wompi → Konvi
 *   3. Cumplimiento — signature + idempotency lifecycle + retry+CB
 *   4. Zona de riesgo — desconectar (deshabilitado hoy)
 *   + Banner migración
 */
import { CreditCard, KeyRound, Webhook } from 'lucide-react'
import {
  SetupSection, SetupField, SetupGrid,
  ComplianceSection, DangerZoneSection,
  MigrationBanner, EmptyDisconnected,
} from '../../_components/setup-primitives'

type Props = {
  connected: boolean
  credentials: Record<string, unknown>
  mode: string | null
}

function maskedPreview(value: string | null | undefined, prefix?: string): string {
  if (!value) return ''
  const visible = prefix && value.startsWith(prefix)
    ? value.slice(0, prefix.length + 4)
    : value.slice(0, 8)
  return `${visible}…●●●●`
}

export default function WompiSetup({ connected, credentials, mode }: Props) {
  if (!connected) {
    return (
      <EmptyDisconnected
        icon={CreditCard}
        providerLabel="Wompi"
        helpText="La conexión se realiza configurando las 4 API keys desde el panel principal de Integraciones."
      />
    )
  }

  const publicKey = credentials.public_key as string | undefined
  const privateKeySecretId = credentials.private_key_secret_id as string | undefined
  const eventsKeySecretId = credentials.events_key_secret_id as string | undefined
  const integrityKeySecretId = credentials.integrity_key_secret_id as string | undefined

  return (
    <div className="space-y-5">
      {/* 1. Identidad */}
      <SetupSection
        icon={KeyRound}
        title="Identidad / API Keys"
        badge={mode ? `Modo: ${mode}` : null}
      >
        <SetupGrid>
          <SetupField
            label="Public key"
            value={publicKey ? maskedPreview(publicKey, 'pub_') : null}
          />
          <SetupField
            label="Private key"
            value={
              privateKeySecretId
                ? `secret_${privateKeySecretId.slice(0, 8)}…`
                : null
            }
          />
          <SetupField
            label="Events key"
            value={
              eventsKeySecretId
                ? `secret_${eventsKeySecretId.slice(0, 8)}…`
                : null
            }
          />
          <SetupField
            label="Integrity key"
            value={
              integrityKeySecretId
                ? `secret_${integrityKeySecretId.slice(0, 8)}…`
                : null
            }
          />
        </SetupGrid>
        <p className="text-xs text-muted-foreground">
          Las 3 claves privadas (private/events/integrity) están almacenadas
          encriptadas en Vault Supabase.
        </p>
      </SetupSection>

      {/* 2. Webhook & Eventos */}
      <SetupSection icon={Webhook} title="Webhook & Eventos">
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">URL configurada en panel Wompi</div>
          <code className="block font-mono text-xs bg-muted/30 rounded px-2 py-1.5 border">
            https://api.konvi.co/api/v1/wompi/webhook
          </code>
        </div>
        <div className="text-xs text-muted-foreground pt-1 border-t border-border">
          Eventos: <span className="font-mono">transaction.updated · nequi_token.updated</span>
        </div>
      </SetupSection>

      {/* 3. Cumplimiento */}
      <ComplianceSection
        gates={[
          { label: 'Signature webhook', value: 'HMAC-SHA256 enforced' },
          { label: 'Idempotency lifecycle', value: 'ADR-0011 activo' },
          { label: 'Retry + Circuit Breaker', value: 'Activo (H.3.2)' },
        ]}
      />

      {/* 4. Zona de riesgo */}
      <DangerZoneSection
        description={
          <>
            Desconectar Wompi inhabilita la creación de links de pago. Las
            transacciones APPROVED previas se conservan en orden histórica;
            los webhooks pendientes (PENDING) ya no se recibirán.
          </>
        }
        actionLabel="Desconectar Wompi"
        actionDisabled
      />

      {/* Banner migración */}
      <MigrationBanner>
        Editar API keys o desconectar se hace desde{' '}
        <a href="/dashboard/integrations" className="underline font-medium">
          /dashboard/integrations
        </a>
        . Migración a este panel: Sem 8.
      </MigrationBanner>
    </div>
  )
}
