'use client'

/**
 * Security form — orquesta los 3 sub-flows del MFA:
 *   1. Enroll TOTP (mostrar QR + verificar 6-digit code)
 *   2. Mostrar recovery codes UNA VEZ con descarga .txt
 *   3. Estado enrolled: regenerar codes / desactivar MFA
 *
 * Rev. 109 J.2.4.3.
 */
import { useState } from 'react'
import {
  Shield, ShieldCheck, AlertTriangle, Download, Copy,
  CheckCircle2, X, Loader2, KeyRound, RefreshCw, Trash2,
} from 'lucide-react'
import { createClient } from '@/utils/supabase/client'

interface MfaState {
  totpEnrolled: boolean
  factorId: string | null
  recoveryCodesCount: number
}

interface Props {
  initialState: MfaState
  userId: string
}

export function SecurityForm({ initialState, userId }: Props) {
  const [state, setState] = useState(initialState)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  // Enrollment flow state.
  const [enrollment, setEnrollment] = useState<{
    factorId: string
    qrCode: string
    secret: string
    code: string
  } | null>(null)

  // Recovery codes display state (mostrados UNA VEZ).
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)

  // ── Enroll flow ──────────────────────────────────────────────────────

  const startEnrollment = async () => {
    setError(null)
    setBusy('enroll')
    const sb = createClient()
    try {
      const { data, error: e } = await sb.auth.mfa.enroll({ factorType: 'totp' })
      if (e || !data) throw new Error(e?.message || 'Error al iniciar MFA')
      setEnrollment({
        factorId: data.id,
        qrCode: data.totp.qr_code,
        secret: data.totp.secret,
        code: '',
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error desconocido')
    } finally {
      setBusy(null)
    }
  }

  const verifyEnrollment = async () => {
    if (!enrollment || enrollment.code.length !== 6) return
    setError(null)
    setBusy('verify')
    const sb = createClient()
    try {
      const challengeRes = await sb.auth.mfa.challenge({
        factorId: enrollment.factorId,
      })
      if (challengeRes.error) throw new Error(challengeRes.error.message)
      const verifyRes = await sb.auth.mfa.verify({
        factorId: enrollment.factorId,
        challengeId: challengeRes.data.id,
        code: enrollment.code,
      })
      if (verifyRes.error) throw new Error(verifyRes.error.message)

      // Éxito → ahora generar recovery codes desde el backend.
      await generateRecoveryCodes()
      setState(s => ({ ...s, totpEnrolled: true, factorId: enrollment.factorId }))
      setEnrollment(null)
      setFeedback('MFA activada exitosamente. Guarda los códigos de respaldo abajo.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al verificar el código')
    } finally {
      setBusy(null)
    }
  }

  const cancelEnrollment = async () => {
    if (!enrollment) return
    const sb = createClient()
    try {
      await sb.auth.mfa.unenroll({ factorId: enrollment.factorId })
    } catch {
      // best-effort cleanup
    }
    setEnrollment(null)
    setError(null)
  }

  // ── Recovery codes flow ─────────────────────────────────────────────

  const generateRecoveryCodes = async () => {
    setError(null)
    setBusy('codes')
    const sb = createClient()
    try {
      const { data: { session } } = await sb.auth.getSession()
      if (!session) throw new Error('Sesión expirada')
      const res = await fetch('/api/mfa/recovery-codes/regenerate', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${session.access_token}` },
      })
      if (!res.ok) throw new Error('Error generando códigos')
      const data = await res.json()
      setRecoveryCodes(data.codes)
      setState(s => ({ ...s, recoveryCodesCount: data.codes.length }))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error desconocido')
    } finally {
      setBusy(null)
    }
  }

  const downloadCodes = () => {
    if (!recoveryCodes) return
    const content = [
      `Códigos de respaldo MFA — Konvi`,
      `Usuario: ${userId}`,
      `Generados: ${new Date().toLocaleString('es-CO')}`,
      ``,
      `Cada código sirve UNA SOLA VEZ. Guárdalos en lugar seguro.`,
      ``,
      ...recoveryCodes,
      ``,
      `Si pierdes acceso al authenticator + estos códigos:`,
      `Escribe a soporte@konvi.com con tu document_number.`,
    ].join('\n')
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `konvi-mfa-recovery-${new Date().toISOString().slice(0, 10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const copyCodes = () => {
    if (!recoveryCodes) return
    navigator.clipboard.writeText(recoveryCodes.join('\n'))
    setFeedback('Códigos copiados al portapapeles.')
  }

  // ── Re-enroll TOTP (cambiar authenticator) ─────────────────────────
  // Caso uso: user perdió phone con autenticador, entró con recovery code,
  // ahora quiere asociar un nuevo autenticador. Mismo flow que enroll
  // inicial pero sin requerir "Activar MFA" desde 0.

  const reEnrollMfa = async () => {
    if (!state.factorId) return
    if (!confirm(
      '¿Cambiar autenticador? Vamos a desactivar tu MFA actual y guiarte ' +
      'para escanear un nuevo QR con otra app. Tu cuenta quedará ' +
      'temporalmente sin MFA hasta que verifiques el nuevo código.'
    )) {
      return
    }
    setError(null)
    setBusy('disable')
    const sb = createClient()
    try {
      // 1. Unenroll factor actual.
      const { error: unenrollErr } = await sb.auth.mfa.unenroll({ factorId: state.factorId })
      if (unenrollErr) throw new Error(unenrollErr.message)
      setState({ totpEnrolled: false, factorId: null, recoveryCodesCount: 0 })
      setFeedback('Autenticador anterior desactivado. Escanea el nuevo QR con tu authenticator.')

      // 2. Iniciar enrollment nuevo automáticamente.
      const { data, error: e } = await sb.auth.mfa.enroll({ factorType: 'totp' })
      if (e || !data) throw new Error(e?.message || 'Error al iniciar nuevo MFA')
      setEnrollment({
        factorId: data.id,
        qrCode: data.totp.qr_code,
        secret: data.totp.secret,
        code: '',
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error desconocido')
    } finally {
      setBusy(null)
    }
  }

  // ── Unenroll MFA ───────────────────────────────────────────────────

  const disableMfa = async () => {
    if (!state.factorId) return
    if (!confirm('¿Desactivar MFA? Tu cuenta quedará protegida solo con contraseña.')) {
      return
    }
    setError(null)
    setBusy('disable')
    const sb = createClient()
    try {
      const { error: e } = await sb.auth.mfa.unenroll({ factorId: state.factorId })
      if (e) throw new Error(e.message)
      // Limpiar recovery codes también.
      const { data: { session } } = await sb.auth.getSession()
      if (session) {
        await fetch('/api/mfa/recovery-codes/clear', {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${session.access_token}` },
        }).catch(() => null)
      }
      setState({ totpEnrolled: false, factorId: null, recoveryCodesCount: 0 })
      setFeedback('MFA desactivada.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error desconocido')
    } finally {
      setBusy(null)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {feedback && (
        <div className="rounded-md border border-emerald-700 bg-emerald-50 p-3 flex items-start gap-2">
          <CheckCircle2 className="h-4 w-4 text-emerald-700 mt-0.5 shrink-0" />
          <p className="text-sm text-emerald-800">{feedback}</p>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-red-700 bg-red-50 p-3 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-red-700 mt-0.5 shrink-0" />
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      {/* Recovery codes — display ONCE (post-enrollment o post-regenerate) */}
      {recoveryCodes && (
        <section className="rounded-lg border border-amber-700 bg-amber-50 p-4 space-y-3">
          <div className="flex items-start gap-2">
            <KeyRound className="h-5 w-5 text-amber-700 mt-0.5 shrink-0" />
            <div className="flex-1">
              <h2 className="text-base font-semibold text-amber-900">
                Guarda estos códigos AHORA
              </h2>
              <p className="text-sm text-amber-800 mt-1">
                Solo se muestran UNA VEZ. Si pierdes tu authenticator, los
                necesitarás para iniciar sesión.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 bg-white border border-amber-700 rounded p-3 font-mono text-sm">
            {recoveryCodes.map(c => (
              <code key={c} className="px-2 py-1 rounded bg-amber-50">{c}</code>
            ))}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={downloadCodes}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-700 text-white hover:bg-amber-800 text-sm"
            >
              <Download className="h-4 w-4" /> Descargar .txt
            </button>
            <button
              type="button"
              onClick={copyCodes}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-amber-700 hover:bg-amber-100 text-sm"
            >
              <Copy className="h-4 w-4" /> Copiar
            </button>
            <button
              type="button"
              onClick={() => setRecoveryCodes(null)}
              className="ml-auto inline-flex items-center px-3 py-1.5 rounded-md border border-border hover:bg-accent text-sm"
            >
              Ya los guardé
            </button>
          </div>
        </section>
      )}

      {/* Enrollment in progress */}
      {enrollment && (
        <section className="rounded-lg border border-border bg-card p-5 space-y-4">
          <div className="flex items-start justify-between">
            <h2 className="text-base font-semibold inline-flex items-center gap-2">
              <Shield className="h-5 w-5" /> Activar MFA
            </h2>
            <button
              type="button"
              onClick={cancelEnrollment}
              disabled={busy === 'verify'}
              aria-label="Cancelar"
              className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-accent disabled:opacity-50"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <ol className="list-decimal list-inside space-y-2 text-sm">
            <li>Abre Google Authenticator, Authy o 1Password en tu teléfono.</li>
            <li>Escanea este QR (o ingresa el secret manual).</li>
            <li>Ingresa el código de 6 dígitos que aparece.</li>
          </ol>
          <div className="grid sm:grid-cols-2 gap-4 items-start">
            <div>
              <div className="border border-border rounded bg-white p-2 inline-block">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={enrollment.qrCode}
                  alt="QR para autenticador"
                  className="w-48 h-48"
                />
              </div>
              <p className="text-[10px] text-muted-foreground mt-2 font-mono break-all">
                Secret manual: {enrollment.secret}
              </p>
            </div>
            <div className="space-y-2">
              <label className="block text-sm font-medium">
                Código de 6 dígitos
              </label>
              <input
                type="text"
                value={enrollment.code}
                onChange={e =>
                  setEnrollment({
                    ...enrollment,
                    code: e.target.value.replace(/\D/g, '').slice(0, 6),
                  })
                }
                placeholder="123456"
                disabled={busy === 'verify'}
                inputMode="numeric"
                pattern="\d{6}"
                className="w-full px-3 py-2 rounded-md border border-border font-mono text-lg tracking-widest text-center disabled:opacity-50"
              />
              <button
                type="button"
                onClick={verifyEnrollment}
                disabled={enrollment.code.length !== 6 || busy === 'verify'}
                className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-md bg-foreground text-background hover:opacity-90 disabled:opacity-50"
              >
                {busy === 'verify' ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Verificando…
                  </>
                ) : (
                  'Verificar y activar'
                )}
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Estado principal */}
      {!enrollment && (
        <section className="rounded-lg border border-border bg-card p-5 space-y-3">
          <div className="flex items-start gap-3">
            {state.totpEnrolled ? (
              <ShieldCheck className="h-6 w-6 text-emerald-600 shrink-0 mt-0.5" />
            ) : (
              <Shield className="h-6 w-6 text-slate-400 shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              <h2 className="text-base font-semibold">
                {state.totpEnrolled
                  ? 'MFA TOTP activada'
                  : 'MFA TOTP desactivada'}
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                {state.totpEnrolled
                  ? `Tu cuenta requiere código de 6 dígitos al iniciar sesión. Tienes ${state.recoveryCodesCount} código(s) de respaldo disponibles.`
                  : 'Recomendado para proteger tu cuenta contra accesos no autorizados.'}
              </p>
            </div>
          </div>

          {state.totpEnrolled && state.recoveryCodesCount < 3 && (
            <div className="rounded-md border border-amber-700 bg-amber-50 p-2 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-700 mt-0.5 shrink-0" />
              <p className="text-xs text-amber-800">
                Te quedan pocos códigos de respaldo. Regenera nuevos para mantener
                acceso si pierdes tu authenticator.
              </p>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {!state.totpEnrolled ? (
              <button
                type="button"
                onClick={startEnrollment}
                disabled={busy === 'enroll'}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-foreground text-background hover:opacity-90 disabled:opacity-50"
              >
                {busy === 'enroll' ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Iniciando…
                  </>
                ) : (
                  <>
                    <Shield className="h-4 w-4" /> Activar MFA
                  </>
                )}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={generateRecoveryCodes}
                  disabled={busy === 'codes'}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-md border border-border hover:bg-accent disabled:opacity-50 text-sm"
                >
                  {busy === 'codes' ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  Regenerar códigos de respaldo
                </button>
                <button
                  type="button"
                  onClick={reEnrollMfa}
                  disabled={busy === 'disable'}
                  title="Vincular un nuevo authenticator (perdiste el actual o quieres cambiarlo)"
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-md border border-amber-700 text-amber-800 hover:bg-amber-50 disabled:opacity-50 text-sm"
                >
                  {busy === 'disable' ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Shield className="h-4 w-4" />
                  )}
                  Cambiar autenticador
                </button>
                <button
                  type="button"
                  onClick={disableMfa}
                  disabled={busy === 'disable'}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-md border border-red-700 text-red-700 hover:bg-red-50 disabled:opacity-50 text-sm"
                >
                  {busy === 'disable' ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                  Desactivar MFA
                </button>
              </>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
