/**
 * Tab Setup — Envia.
 *
 * Estructura canónica unificada (Sem 7 F2 cierre):
 *   1. Identidad — API token + ambiente
 *   2. Webhook & Eventos — URL polling backup
 *   3. Cumplimiento — idempotency + HMAC + polling + scope CO
 *   4. Zona de riesgo — desconectar (deshabilitado hoy)
 *   + Banner migración
 */
import { Truck, KeyRound, Webhook, MapPin } from 'lucide-react'
import {
  SetupSection, SetupField, SetupGrid,
  ComplianceSection, DangerZoneSection,
  MigrationBanner, EmptyDisconnected,
} from '../../_components/setup-primitives'

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
      <EmptyDisconnected
        icon={Truck}
        providerLabel="Envia"
        helpText="La conexión se realiza configurando tu API token desde el panel principal de Integraciones."
      />
    )
  }

  const apiTokenSecretId = credentials.api_token_secret_id as string | undefined

  return (
    <div className="space-y-5">
      {/* 1. Identidad */}
      <SetupSection
        icon={KeyRound}
        title="Identidad / API Token"
        badge={`Ambiente: ${sandbox ? 'Sandbox' : 'Producción'}`}
      >
        <SetupGrid>
          <SetupField
            label="Token (Vault)"
            value={
              apiTokenSecretId
                ? `secret_${apiTokenSecretId.slice(0, 8)}…`
                : null
            }
          />
          <SetupField
            label="Scope geográfico"
            value="Solo Colombia (country='CO')"
            mono={false}
          />
        </SetupGrid>
      </SetupSection>

      {/* Origen despacho (sub-sección dentro de Identidad logística) */}
      <SetupSection icon={MapPin} title="Origen de despacho">
        <SetupField
          label="Código postal DANE"
          value={
            danePostal ?? (
              <span className="text-muted-foreground italic font-sans">
                — configurar en Configuración → General
              </span>
            )
          }
        />
        <p className="text-xs text-muted-foreground">
          Usado por todos los carriers para calcular tarifas desde tu ciudad.
        </p>
      </SetupSection>

      {/* 2. Webhook & Eventos */}
      <SetupSection icon={Webhook} title="Webhook & Eventos">
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">URL configurada en panel Envia</div>
          <code className="block font-mono text-xs bg-muted/30 rounded px-2 py-1.5 border">
            https://api.konvi.co/api/v1/envia/webhook/{'<tenant_id>'}/{'<secret>'}
          </code>
        </div>
        <div className="text-xs text-muted-foreground pt-1 border-t border-border">
          Eventos: <span className="font-mono">tracking.update · label.generated · shipment.cancelled</span>
        </div>
      </SetupSection>

      {/* 3. Cumplimiento */}
      <ComplianceSection
        gates={[
          { label: 'Idempotency-Key local', value: 'Activo (H.2.1)' },
          { label: 'Webhook HMAC propio', value: 'Activo (H.2.2)' },
          { label: 'Polling backup tracking', value: 'Activo (H.2.3)' },
          { label: "Scope country='CO'", value: 'Enforced (H.2.12)' },
        ]}
      />

      {/* 4. Zona de riesgo */}
      <DangerZoneSection
        description={
          <>
            Desconectar Envia detiene cotizaciones, generación de etiquetas y
            polling de tracking. Los envíos en curso se siguen sirviendo via
            sus tracking_numbers existentes pero sin actualizaciones automáticas.
          </>
        }
        actionLabel="Desconectar Envia"
        actionDisabled
      />

      {/* Banner migración */}
      <MigrationBanner>
        Editar token o desconectar se hace desde{' '}
        <a href="/dashboard/integrations" className="underline font-medium">
          /dashboard/integrations
        </a>
        . Migración a este panel: Sem 8.
      </MigrationBanner>
    </div>
  )
}
