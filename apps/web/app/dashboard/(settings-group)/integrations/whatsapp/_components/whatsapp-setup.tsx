/**
 * Tab Setup — WhatsApp Business.
 *
 * Estructura canónica unificada (Sem 7 F2 cierre):
 *   1. Identidad — WABA + Phone Number + tokens
 *   2. Webhook & Eventos — URL + status topics
 *   3. Cumplimiento — ventana 24h · opt-out · Habeas Data
 *   4. Zona de riesgo — desconectar (deshabilitado hoy)
 *   + Banner migración
 */
import { MessageSquareText, KeyRound, Webhook, Copy } from 'lucide-react'
import {
  SetupSection, SetupField, SetupGrid,
  ComplianceSection, DangerZoneSection,
  MigrationBanner, EmptyDisconnected,
} from '../../_components/setup-primitives'

type Props = {
  connected: boolean
  credentials: Record<string, string>
  canWrite: boolean
  tenantId: string
}

export default function WhatsAppSetup({ connected, credentials, tenantId }: Props) {
  if (!connected) {
    return (
      <EmptyDisconnected
        icon={MessageSquareText}
        providerLabel="WhatsApp Business"
        // ADR-0023 (Model B Direct Provider): cada tenant trae SU PROPIA Meta App. NO Embedded Signup.
        helpText="Cada negocio conecta su propia Meta App (Direct Provider): captura tus credenciales de WhatsApp Cloud API (App Secret, Verify Token, Phone Number ID, WABA ID, Access Token) desde el panel de Integraciones."
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
            <button
              type="button"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <Copy className="h-3 w-3" /> Copiar
            </button>
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

      {/* Banner migración */}
      <MigrationBanner>
        Editar credenciales o reconectar se hace desde{' '}
        <a href="/dashboard/integrations" className="underline font-medium">
          /dashboard/integrations
        </a>
        . Migración a este panel: Sem 8.
      </MigrationBanner>
    </div>
  )
}
