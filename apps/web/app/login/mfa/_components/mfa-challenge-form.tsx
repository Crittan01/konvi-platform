'use client'

/**
 * MFA challenge form — input código 6 dígitos del authenticator + opción
 * alterna recovery code.
 *
 * Rev. 109 J.2.4.3.
 */
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2, KeyRound, ArrowLeft, ShieldAlert } from 'lucide-react'
import { createClient } from '@/utils/supabase/client'

interface Props {
  factorId: string
  message?: string
}

export function MfaChallengeForm({ factorId, message }: Props) {
  const router = useRouter()
  const [mode, setMode] = useState<'totp' | 'recovery'>('totp')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(message || null)

  const submitTotp = async () => {
    if (code.length !== 6) {
      setError('El código debe tener 6 dígitos.')
      return
    }
    setError(null)
    setBusy(true)
    const sb = createClient()
    try {
      const challenge = await sb.auth.mfa.challenge({ factorId })
      if (challenge.error) throw new Error(challenge.error.message)
      const verify = await sb.auth.mfa.verify({
        factorId,
        challengeId: challenge.data.id,
        code,
      })
      if (verify.error) throw new Error(verify.error.message)
      // Éxito → AAL2. Refresh server-side state.
      router.push('/dashboard')
      router.refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Código inválido')
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  const submitRecovery = async () => {
    if (code.trim().length < 4) {
      setError('Ingresa un código de respaldo válido.')
      return
    }
    setError(null)
    setBusy(true)
    const sb = createClient()
    try {
      const { data: { session } } = await sb.auth.getSession()
      if (!session) throw new Error('Sesión expirada — inicia de nuevo.')

      // Verificar recovery code via backend.
      // El proxy /api/mfa/recovery-codes/verify setea cookie HttpOnly
      // `mfa_recovery_session` (24h) que el middleware acepta como bypass
      // AAL2. NO se requiere sessionStorage — la cookie cubre el flow.
      const res = await fetch('/api/mfa/recovery-codes/verify', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ code: code.trim() }),
      })

      // Defensive: si el proxy retorna HTML (404, 500), .json() falla.
      let data: { ok?: boolean; detail?: string }
      try {
        data = await res.json()
      } catch {
        throw new Error(
          `Error inesperado del servidor (HTTP ${res.status}). Reintenta o usa el código del authenticator.`
        )
      }
      if (!res.ok) throw new Error(data.detail || 'Código inválido')

      router.push('/dashboard?recovery_used=1')
      router.refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Código inválido')
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 flex items-start gap-2">
          <ShieldAlert className="h-4 w-4 text-red-700 mt-0.5 shrink-0" />
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {mode === 'totp' ? (
        <>
          <div>
            <label className="block text-sm font-medium text-foreground mb-2">
              Código de 6 dígitos
            </label>
            <input
              type="text"
              value={code}
              onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              onKeyDown={e => {
                if (e.key === 'Enter' && code.length === 6) submitTotp()
              }}
              placeholder="000000"
              autoFocus
              disabled={busy}
              inputMode="numeric"
              pattern="\d{6}"
              className="w-full px-3 py-3 rounded-md border border-border bg-background font-mono text-2xl tracking-[0.5em] text-center disabled:opacity-50"
            />
          </div>
          <button
            type="button"
            onClick={submitTotp}
            disabled={code.length !== 6 || busy}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-md bg-foreground text-background hover:opacity-90 disabled:opacity-50 font-medium"
          >
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Verificando…
              </>
            ) : (
              'Verificar y entrar'
            )}
          </button>
          <button
            type="button"
            onClick={() => { setMode('recovery'); setCode(''); setError(null) }}
            disabled={busy}
            className="w-full text-sm text-muted-foreground hover:text-foreground inline-flex items-center justify-center gap-1.5 disabled:opacity-50"
          >
            <KeyRound className="h-3.5 w-3.5" />
            Usar código de respaldo
          </button>
        </>
      ) : (
        <>
          <div>
            <label className="block text-sm font-medium text-foreground mb-2">
              Código de respaldo
            </label>
            <input
              type="text"
              value={code}
              onChange={e => setCode(e.target.value.toUpperCase())}
              onKeyDown={e => {
                if (e.key === 'Enter' && code.trim().length >= 4) submitRecovery()
              }}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              autoFocus
              disabled={busy}
              className="w-full px-3 py-2.5 rounded-md border border-border bg-background font-mono text-base text-center disabled:opacity-50"
            />
            <p className="text-[10px] text-muted-foreground mt-1">
              Uno de los 8 códigos que guardaste al activar MFA. Cada uno sirve UNA VEZ.
            </p>
          </div>
          <button
            type="button"
            onClick={submitRecovery}
            disabled={code.trim().length < 4 || busy}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-md bg-foreground text-background hover:opacity-90 disabled:opacity-50 font-medium"
          >
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Verificando…
              </>
            ) : (
              'Verificar y entrar'
            )}
          </button>
          <button
            type="button"
            onClick={() => { setMode('totp'); setCode(''); setError(null) }}
            disabled={busy}
            className="w-full text-sm text-muted-foreground hover:text-foreground inline-flex items-center justify-center gap-1.5 disabled:opacity-50"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Volver a código del authenticator
          </button>
        </>
      )}
    </div>
  )
}
