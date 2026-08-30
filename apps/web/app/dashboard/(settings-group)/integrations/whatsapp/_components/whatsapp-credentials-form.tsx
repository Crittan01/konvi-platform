'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { KeyRound, Loader2, Check } from 'lucide-react'
import { createClient } from '@/utils/supabase/client'

// F3 activación (ADR-0023 Model B Direct Provider) — captura self-service de las 6 credenciales de la
// Meta App del tenant. app_secret + access_token se cifran en Vault (server); el resto va en
// tenant_integrations. Habilita onboarding multi-tenant sin script.

type Field = { key: string; label: string; hint: string; secret?: boolean }
const FIELDS: Field[] = [
  { key: 'app_id', label: 'App ID', hint: 'Meta App → Configuración → Básica' },
  { key: 'app_secret', label: 'App Secret', hint: 'Meta App → Configuración → Básica → Mostrar', secret: true },
  { key: 'verify_token', label: 'Verify Token', hint: 'String que tú eliges; el mismo va en el webhook de Meta' },
  { key: 'phone_number_id', label: 'Phone Number ID', hint: 'WhatsApp → Configuración de la API' },
  { key: 'waba_id', label: 'WABA ID', hint: 'WhatsApp → Configuración de la API' },
  { key: 'access_token', label: 'Access Token (System User)', hint: 'Business Settings → Usuarios del sistema → Generar token', secret: true },
]

export function WhatsAppCredentialsForm({
  apiUrl, connected, prefill,
}: {
  apiUrl: string
  connected: boolean
  prefill?: Partial<Record<string, string>>
}) {
  const router = useRouter()
  const [open, setOpen] = useState(!connected)   // si no está conectado, mostrar el form abierto
  const [values, setValues] = useState<Record<string, string>>(() => ({
    app_id: prefill?.app_id ?? '',
    verify_token: prefill?.verify_token ?? '',
    phone_number_id: prefill?.phone_number_id ?? '',
    waba_id: prefill?.waba_id ?? '',
    app_secret: '',
    access_token: '',
  }))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const set = (k: string, v: string) => setValues(prev => ({ ...prev, [k]: v }))

  const handleSave = async () => {
    for (const f of FIELDS) {
      if (!values[f.key]?.trim()) { setError(`Falta: ${f.label}`); return }
    }
    setSaving(true); setError(null); setSaved(false)
    try {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (!session?.access_token) { setError('Sesión expirada.'); return }
      const res = await fetch(`${apiUrl}/api/v1/integrations/whatsapp/credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${session.access_token}` },
        body: JSON.stringify(Object.fromEntries(FIELDS.map(f => [f.key, values[f.key].trim()]))),
      })
      if (!res.ok) { setError((await res.text()) || `Error ${res.status}`); return }
      setSaved(true)
      setValues(prev => ({ ...prev, app_secret: '', access_token: '' }))  // no retener secretos en el estado
      router.refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }

  if (connected && !open) {
    return (
      <button onClick={() => setOpen(true)}
        className="text-xs text-primary hover:underline inline-flex items-center gap-1">
        <KeyRound className="h-3 w-3" /> Editar / rotar credenciales
      </button>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 text-primary" />
        <p className="text-sm font-semibold text-foreground">
          {connected ? 'Editar credenciales de tu Meta App' : 'Conecta tu WhatsApp (Meta App propia)'}
        </p>
      </div>
      <p className="text-xs text-muted-foreground">
        Cada negocio conecta su propia Meta App (Direct Provider, ADR-0023). El App Secret y el Access Token
        se cifran en Vault; nunca se muestran de nuevo. Al editar, re-ingresa los 6 campos.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {FIELDS.map(f => (
          <div key={f.key} className="space-y-1">
            <label className="text-[10px] font-semibold text-muted-foreground uppercase">{f.label}</label>
            <input
              type={f.secret ? 'password' : 'text'}
              value={values[f.key] ?? ''}
              onChange={e => set(f.key, e.target.value)}
              placeholder={f.secret ? '••••••••' : ''}
              autoComplete="off"
              className="w-full h-8 rounded-md border border-input bg-background text-sm px-2 text-foreground"
            />
            <p className="text-[10px] text-muted-foreground/70">{f.hint}</p>
          </div>
        ))}
      </div>
      {error && <p className="text-xs text-danger-fg bg-danger-bg border border-danger-border rounded px-2 py-1">{error}</p>}
      {saved && <p className="text-xs text-success-fg inline-flex items-center gap-1"><Check className="h-3 w-3" /> Guardado. El bot ya usa estas credenciales.</p>}
      <div className="flex items-center gap-2 justify-end">
        {connected && (
          <button onClick={() => setOpen(false)} className="text-xs text-muted-foreground hover:text-foreground px-2">Cancelar</button>
        )}
        <button
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-1.5 h-8 px-4 text-xs font-medium rounded-lg bg-foreground text-background hover:bg-foreground/80 disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          {connected ? 'Actualizar credenciales' : 'Conectar WhatsApp'}
        </button>
      </div>
    </div>
  )
}
