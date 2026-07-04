/**
 * Tab Setup — WhatsApp Business.
 *
 * Estructura canónica unificada (Sem 7 F2 cierre):
 *   1. Identidad — WABA + Phone Number + tokens
 *   2. Webhook & Eventos — URL + status topics
 *   3. Cumplimiento — ventana 24h · opt-out · Habeas Data
 *   4. Zona de riesgo — desconectar (deshabilitado hoy, gated founder)
 */
import { MessageSquareText, KeyRound, Webhook } from 'lucide-react'
import {
  SetupSection, SetupField, SetupGrid,
  ComplianceSection, DangerZoneSection,
  EmptyDisconnected,
} from '../../_components/setup-primitives'
import { WhatsAppCredentialsForm } from './whatsapp-credentials-form'
import { CopyInlineButton } from './copy-inline-button'

type Props = {
  connected: boolean
  credentials: Record<string, string>
  canWrite: boolean
  tenantId: string
  apiUrl: string
}

export default function WhatsAppSetup({ connected, credentials, canWrite, tenantId, apiUrl }: Props) {
  if (!connected) {
    // ADR-0023 (Model B Direct Provider): cada tenant trae SU PROPIA Meta App. NO Embedded Signup.
    // Un owner/manager captura las 6 credenciales aquí (self-service, multi-tenant).
    return canWrite ? (
      <WhatsAppCredentialsForm apiUrl={apiUrl} connected={false} />
    ) : (
      <EmptyDisconnected
        icon={MessageSquareText}
        providerLabel="WhatsApp Business"
        helpText="Aún no hay WhatsApp conectado. Un owner o manager debe capturar las credenciales de la Meta App del negocio."
      />
    )
  }

  const wabaId = credentials.waba_id ?? null
  const phoneNumberId = credentials.phone_number_id ?? null
  const displayPhone = credentials.display_phone_number ?? null
  const accessTokenSecretId = credentials.access_token_secret_id ?? null
  const tokenRotatedAt = credentials.access_token_rotated_at ?? null

  return (
    <div className="space-y-5">
      {/* 1. Identidad */}
      <SetupSection icon={KeyRound} title="Identidad">
        <SetupGrid>
          <SetupField label="WABA ID" value={wabaId} />
          <SetupField label="Phone Number ID" value={phoneNumberId} />
          <SetupField label="Número visible" value={displayPhone} />
          <SetupField
            label="Access Token (Vault)"
            value={
              accessTokenSecretId
                ? `secret_${accessTokenSecretId.slice(0, 8)}…`
                : null
            }
          />
        </SetupGrid>
        {tokenRotatedAt && (
          <p className="text-xs text-muted-foreground">
            Última rotación de token:{' '}
            {new Date(tokenRotatedAt).toLocaleDateString('es-CO')}
          </p>
        )}
        {canWrite && (
          <div className="pt-2 border-t border-border/50">
            <WhatsAppCredentialsForm
              apiUrl={apiUrl}
              connected
              prefill={{
                app_id: credentials.app_id,
                verify_token: credentials.verify_token,
                phone_number_id: credentials.phone_number_id,
                waba_id: credentials.waba_id,
              }}
            />
          </div>
        )}
      </SetupSection>

      {/* 2. Webhook & Eventos */}
      <SetupSection icon={Webhook} title="Webhook & Eventos">
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">
            URL de Callback (Meta → Configuración → Webhooks). Es PER-TENANT: incluye tu ID. Sin el ID, Meta recibe 404.
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate font-mono text-xs bg-muted/30 rounded px-2 py-1.5 border">
              https://api.konvi.co/api/v1/whatsapp/webhook/{tenantId}
            </code>
            <CopyInlineButton
              value={`https://api.konvi.co/api/v1/whatsapp/webhook/${tenantId}`}
            />
          </div>
        </div>
        <div className="text-xs text-muted-foreground pt-1 border-t border-border">
          Eventos: <span className="font-mono">messages · message_template_status_update · message_template_quality_update · phone_number_quality_update</span>
        </div>
      </SetupSection>

      {/* 3. Cumplimiento */}
      <ComplianceSection
        gates={[
          { label: 'Ventana 24h CSW Meta', value: 'Enforcement activo' },
          { label: 'Auto opt-out STOP', value: 'Activo' },
          { label: 'Habeas Data Ley 1581', value: 'Certified' },
        ]}
      />

      {/* 4. Zona de riesgo */}
      <DangerZoneSection
        description={
          <>
            Desconectar WhatsApp interrumpe el bot conversacional y deja al cliente
            sin canal automático. Tus plantillas aprobadas se conservan; podrás
            reconectar luego sin perderlas.
          </>
        }
        actionLabel="Desconectar WhatsApp"
        actionDisabled
      />
    </div>
  )
}
