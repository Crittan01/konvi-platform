/**
 * Tab Bot — Telegram.
 *
 * Display-only hoy. Save/disconnect/test siguen en /integrations (manager legacy).
 */
import {
  Send, KeyRound, Webhook, ShieldCheck, AlertCircle,
} from 'lucide-react'

type Props = {
  connected: boolean
  config: Record<string, string>
}

export default function TelegramSetup({ connected, config }: Props) {
  if (!connected) {
    return (
      <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center space-y-3">
        <Send className="h-8 w-8 mx-auto text-muted-foreground/60" />
        <p className="text-sm text-muted-foreground">
          Telegram aún no está configurado para este tenant.
        </p>
        <p className="text-xs text-muted-foreground">
          Configurá el bot_token + chat_id del operador desde el panel principal
          de Integraciones.
        </p>
      </div>
    )
  }

  const botTokenSecretId = config.bot_token_secret_id
  const hasPlaintextToken = !!config.bot_token  // legacy
  const botUsername = config.bot_username
  const chatId = config.chat_id

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-border bg-card p-4 space-y-4">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Bot</h3>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground">Bot username</div>
            <div className="font-mono text-sm">
              {botUsername ? `@${botUsername}` : '—'}
            </div>
          </div>
          <div className="space-y-0.5">
            <div className="text-xs text-muted-foreground">Bot Token (Vault)</div>
            <div className="font-mono text-sm">
              {botTokenSecretId
                ? `secret_${botTokenSecretId.slice(0, 8)}…`
                : hasPlaintextToken
                  ? <span className="text-amber-800">Legacy (texto plano) — migrar a Vault</span>
                  : '—'}
            </div>
          </div>
        </div>
        <div className="space-y-0.5">
          <div className="text-xs text-muted-foreground">Chat ID operador</div>
          <div className="font-mono text-sm">{chatId ?? '—'}</div>
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Webhook className="h-4 w-4 text-primary" />
          <h3 className="font-semibold text-foreground">Webhook</h3>
        </div>
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">URL configurada en Telegram</div>
          <code className="block font-mono text-xs bg-muted/30 rounded px-2 py-1.5 border">
            https://api.konvi.co/api/v1/telegram/webhook
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
            <span className="text-muted-foreground">Webhook secret_token</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              Activo
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Comandos operador</span>
            <span className="text-xs text-emerald-900 bg-emerald-700/10 border border-emerald-700/40 rounded-full px-2 py-0.5">
              /resolver · /estado
            </span>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-amber-700/30 bg-amber-700/5 p-4 flex items-start gap-3">
        <AlertCircle className="h-4 w-4 text-amber-800 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-900">
          Editar bot_token, chat_id o probar conexión se hace desde la página
          principal de Integraciones. Migración a este panel: Sem 11 (H.6).
        </p>
      </section>
    </div>
  )
}
