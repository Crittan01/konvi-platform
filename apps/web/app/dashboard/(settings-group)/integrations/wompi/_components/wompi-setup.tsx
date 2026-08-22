/**
 * Tab Setup — Wompi.
 *
 * Estructura canónica unificada (Sem 7 F2 cierre):
 *   1. Identidad — 2 API keys (private/events) + 2 opcionales (pub/integrity)
 *   2. Webhook & Eventos — URL Wompi → Konvi
 *   3. Cumplimiento — signature + idempotency lifecycle + retry+CB
 *   4. Zona de riesgo — desconectar (deshabilitado hoy)
 *   + Banner migración
 *
 * Track 6 (2026-08-22, doc oficial verificada live): las llaves pub/integrity
 * se capturan opcionales como punto de extensión del checkout embebido — la doc
 * confirma que el Widget/Web Checkout las exige (pub_ client-side + firma
 * integrity SHA256 server-side). El runtime de hoy (payment links hosted) no
 * las consume; el form las marca "opcional" y el guardado las conserva en
 * Vault con merge no-destructivo.
 */
import { CreditCard, KeyRound, Webhook } from 'lucide-react'
import {
  SetupSection, SetupField, SetupGrid,
  ComplianceSection, DangerZoneSection,
  MigrationBanner, EmptyDisconnected,
} from '../../_components/setup-primitives'
import { webhookUrl } from '@/lib/webhook-urls'

type Props = {
  connected: boolean
  credentials: Record<string, unknown>
  mode: string | null
}

export default function WompiSetup({ connected, credentials, mode }: Props) {
  if (!connected) {
    return (
      <EmptyDisconnected
        icon={CreditCard}
        providerLabel="Wompi"
        helpText="La conexión se realiza configurando la Llave Privada y la Llave de Eventos desde el panel principal de Integraciones."
      />
    )
  }

  const privateKeySecretId = credentials.private_key_secret_id as string | undefined
  const eventsKeySecretId = credentials.events_key_secret_id as string | undefined
  const publicKeySecretId = credentials.public_key_secret_id as string | undefined
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
            label="Public key (checkout embebido)"
            value={
              publicKeySecretId
                ? `secret_${publicKeySecretId.slice(0, 8)}…`
                : null
            }
          />
          <SetupField
            label="Integrity key (firma widget)"
            value={
              integrityKeySecretId
                ? `secret_${integrityKeySecretId.slice(0, 8)}…`
                : null
            }
          />
        </SetupGrid>
        <p className="text-xs text-muted-foreground">
          Las llaves están almacenadas encriptadas en Vault Supabase. La Llave
          Pública y la de Integridad son opcionales: habilitan el futuro checkout
          embebido (Widget/Web Checkout de Wompi); el flujo actual de links de
          pago no las requiere.
        </p>
      </SetupSection>

      {/* 2. Webhook & Eventos */}
      <SetupSection icon={Webhook} title="Webhook & Eventos">
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">URL configurada en panel Wompi</div>
          <code className="block font-mono text-xs bg-muted/30 rounded px-2 py-1.5 border break-all">
            {webhookUrl('wompi')}
          </code>
        </div>
        <div className="text-xs text-muted-foreground pt-1 border-t border-border">
          Eventos: <span className="font-mono">transaction.updated</span>
          <span className="block mt-1 text-[11px]">
            (Wompi también emite eventos de token — nequi_token.updated,
            bancolombia_transfer_token.updated — que solo aplican a suscripciones;
            Konvi no las procesa: el modelo es cobro por orden.)
          </span>
        </div>
      </SetupSection>

      {/* 3. Cumplimiento */}
      <ComplianceSection
        gates={[
          { label: 'Signature webhook', value: 'SHA256 (properties + timestamp + events key)' },
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
        Editar las API keys o desconectar Wompi se hace desde{' '}
        <a href="/dashboard/integrations" className="underline font-medium">
          el panel de Integraciones
        </a>
        . Este panel es de solo lectura.
      </MigrationBanner>
    </div>
  )
}
