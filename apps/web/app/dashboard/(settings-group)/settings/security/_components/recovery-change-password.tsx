'use client'

/**
 * Recovery change password — flow especial cuando el user está en sesión
 * AAL1 + recovery code cookie.
 *
 * Rev. 109 J.2.4.3 — Supabase Auth requiere AAL2 para updateUser({password}).
 * Como recovery code session NO upgrade a AAL2, usamos endpoint backend que
 * valida recovery code adicional + admin API bypass.
 */
import { useState } from 'react'
import { Loader2, KeyRound, CheckCircle2, AlertTriangle } from 'lucide-react'
import { createClient } from '@/utils/supabase/client'

export function RecoveryChangePassword() {
  const [recoveryCode, setRecoveryCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const submit = async () => {
    setError(null)
    setSuccess(false)
    if (recoveryCode.trim().length < 4) {
      setError('Ingresa un código de respaldo válido.')
      return
    }
    if (newPassword.length < 8) {
      setError('La contraseña debe tener al menos 8 caracteres.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('Las contraseñas no coinciden.')
      return
    }
    setBusy(true)
    try {
      const sb = createClient()
      const { data: { session } } = await sb.auth.getSession()
      if (!session) throw new Error('Sesión expirada')
      const res = await fetch('/api/mfa/recovery/change-password', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          recovery_code: recoveryCode.trim(),
          new_password: newPassword,
        }),
      })
      let data: { ok?: boolean; detail?: string }
      try {
        data = await res.json()
      } catch {
        throw new Error(`Error inesperado HTTP ${res.status}`)
      }
      if (!res.ok || !data.ok) throw new Error(data.detail || 'Error al cambiar contraseña')
      setSuccess(true)
      setRecoveryCode('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error desconocido')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      {success && (
        <div className="rounded-md border border-emerald-300 bg-emerald-50 p-2 flex items-start gap-2">
          <CheckCircle2 className="h-4 w-4 text-emerald-700 mt-0.5 shrink-0" />
          <p className="text-sm text-emerald-800">
            Contraseña actualizada. Tu próximo inicio de sesión usará la nueva.
          </p>
        </div>
      )}
      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-2 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-red-700 mt-0.5 shrink-0" />
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      <div>
        <label className="block text-sm font-medium mb-1">
          Código de respaldo (verificación adicional)
        </label>
        <input
          type="text"
          value={recoveryCode}
          onChange={e => setRecoveryCode(e.target.value.toUpperCase())}
          placeholder="XXXX-XXXX-XXXX-XXXX"
          disabled={busy}
          className="w-full px-3 py-2 rounded-md border border-border bg-background font-mono text-sm text-center disabled:opacity-50"
        />
        <p className="text-[10px] text-muted-foreground mt-1">
          Uno de tus 8 códigos de respaldo. Se consume al usar.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Nueva contraseña</label>
        <input
          type="password"
          value={newPassword}
          onChange={e => setNewPassword(e.target.value)}
          disabled={busy}
          minLength={8}
          className="w-full px-3 py-2 rounded-md border border-border bg-background text-sm disabled:opacity-50"
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Confirmar contraseña</label>
        <input
          type="password"
          value={confirmPassword}
          onChange={e => setConfirmPassword(e.target.value)}
          disabled={busy}
          className="w-full px-3 py-2 rounded-md border border-border bg-background text-sm disabled:opacity-50"
        />
      </div>

      <button
        type="button"
        onClick={submit}
        disabled={busy || !recoveryCode || !newPassword || !confirmPassword}
        className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-md bg-foreground text-background hover:opacity-90 disabled:opacity-50 text-sm font-medium"
      >
        {busy ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" /> Actualizando…
          </>
        ) : (
          <>
            <KeyRound className="h-4 w-4" /> Verificar y cambiar contraseña
          </>
        )}
      </button>
    </div>
  )
}
