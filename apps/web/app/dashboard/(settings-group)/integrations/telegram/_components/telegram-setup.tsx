/**
 * Tab Setup — Telegram.
 *
 * Estructura canónica unificada (Sem 7 F2 cierre):
 *   1. Identidad — Bot username + bot token + chat_id operador
 *   2. Webhook & Eventos — URL Telegram → Konvi
 *   3. Cumplimiento — secret_token + comandos operador
 *   4. Zona de riesgo — desconectar (deshabilitado hoy)
 *   + Banner migración
 */
import { Send, KeyRound, Webhook } from 'lucide-react'
import {
  SetupSection, SetupField, SetupGrid,
  ComplianceSection, DangerZoneSection,
  MigrationBanner, EmptyDisconnected,
} from '../../_components/setup-primitives'

type Props = {
  connected: boolean
  config: Record<string, string>
}

export default function TelegramSetup({ connected, config }: Props) {
  if (!connected) {
    return (
      <EmptyDisconnected
        icon={Send}
        providerLabel="Telegram (canal interno operadores)"
        helpText="La conexión se realiza configurando bot_token + chat_id del operador desde el panel principal de Integraciones."
      />
    )
  }

  const botTokenSecretId = config.bot_token_secret_id
  const hasPlaintextToken = !!config.bot_token  // legacy
  const botUsername = config.bot_username
  const chatId = config.chat_id

  return (
    <div className="space-y-5">
      {/* 1. Identidad */}
      <SetupSection icon={KeyRound} title="Identidad / Bot">
        <SetupGrid>
          <SetupField
            label="Bot username"
            value={botUsername ? `@${botUsername}` : null}
          />
          <SetupField
            label="Bot Token (Vault)"
            value={
              botTokenSecretId
                ? `secret_${botTokenSecretId.slice(0, 8)}…`
                : hasPlaintextToken
                  ? (
                    <span className="text-amber-800 font-sans">
                      Legacy (texto plano) — migrar a Vault
                    </span>
                  )
                  : null
            }
          />
          <SetupField label="Chat ID operador" value={chatId ?? null} />
        </SetupGrid>
      </SetupSection>

      {/* 2. Webhook & Eventos */}
      <SetupSection icon={Webhook} title="Webhook & Eventos">
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">URL configurada en Telegram</div>
          <code className="block font-mono text-xs bg-muted/30 rounded px-2 py-1.5 border">
            https://api.konvi.co/api/v1/telegram/webhook
          </code>
        </div>
        <div className="text-xs text-muted-foreground pt-1 border-t border-border">
          Eventos: <span className="font-mono">message · callback_query (comandos operador)</span>
        </div>
      </SetupSection>

      {/* 3. Cumplimiento */}
      <ComplianceSection
        gates={[
          { label: 'Webhook secret_token', value: 'Activo' },
          { label: 'Comandos operador', value: '/resolver · /estado' },
        ]}
      />

      {/* 4. Zona de riesgo */}
      <DangerZoneSection
        description={
          <>
            Desconectar Telegram detiene las notificaciones al operador (human
            takeover, pagos pendientes, calidad WhatsApp baja). El bot Telegram
            sigue existiendo en Telegram side — solo dejamos de recibir webhooks.
          </>
        }
        actionLabel="Desconectar Telegram"
        actionDisabled
      />

      {/* Banner migración */}
      <MigrationBanner>
        Editar bot_token, chat_id o probar conexión se hace desde{' '}
        <a href="/dashboard/integrations" className="underline font-medium">
          /dashboard/integrations
        </a>
        . Migración a este panel: Sem 11 (H.6).
      </MigrationBanner>
    </div>
  )
}
