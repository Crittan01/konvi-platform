'use client'

/**
 * Security form — orquesta los 3 sub-flows del MFA:
 *   1. Enroll TOTP (mostrar QR + verificar 6-digit code)
 *   2. Mostrar recovery codes UNA VEZ con descarga .txt
 *   3. Estado enrolled: regenerar codes / cambiar autenticador / desactivar
 *
 * Rev. 109 J.2.4.3 — incluye flow recovery-session AAL2 bypass:
 *   Si user entró con recovery code (isRecoverySession=true), las
 *   operaciones AAL2-required (unenroll, change password) usan backend
 *   endpoints que validan recovery code adicional + admin API bypass.
 */
import { useState } from 'react'
import {
  Shield, ShieldCheck, AlertTriangle, Download, Copy,
  CheckCircle2, X, Loader2, KeyRound, RefreshCw, Trash2,
} from 'lucide-react'
import { createClient } from '@/utils/supabase/client'
import { useConfirm } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface MfaState {
  totpEnrolled: boolean
  factorId: string | null
  recoveryCodesCount: number
  /** false si el conteo de códigos no se pudo leer del backend (no
   *  confundir con "0 códigos"). Ver security/page.tsx getMfaState. */
  recoveryCountAvailable: boolean
}

interface Props {
  initialState: MfaState
  userId: string
  /** Rev. 109 J.2.4.3 — Si user entró con recovery code, AAL=1 y los
   *  flujos de change-password / unenroll requieren bypass backend. */
  isRecoverySession?: boolean
}

export function SecurityForm({ initialState, userId, isRecoverySession }: Props) {
  const confirm = useConfirm()
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

  // ── Dialogos custom (app-styled, no confirm() nativo del browser) ──
  type DialogKind = 'reenroll' | 'disable' | 'recovery-reenroll' | null
  const [openDialog, setOpenDialog] = useState<DialogKind>(null)
  const [recoveryCodeInput, setRecoveryCodeInput] = useState('')

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
      setState(s => ({ ...s, recoveryCodesCount: data.codes.length, recoveryCountAvailable: true }))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error desconocido')
    } finally {
      setBusy(null)
    }
  }

  // Regenerar desde el botón "Regenerar códigos": destructivo — invalida los
  // 8 códigos anteriores de inmediato. Exige confirmación explícita (a
  // diferencia de la generación interna del enroll, que no tiene previos que
  // revocar). Ver gap security_mfa "Regenerar revoca sin confirmación".
  const regenerateRecoveryCodes = async () => {
    const ok = await confirm({
      title: '¿Regenerar códigos de respaldo?',
      description:
        'Los códigos anteriores dejarán de funcionar de inmediato. Si tenías una copia guardada o descargada, ya no servirá. Guarda los nuevos apenas se muestren.',
      confirmLabel: 'Regenerar',
      cancelLabel: 'Cancelar',
      destructive: true,
    })
    if (!ok) return
    await generateRecoveryCodes()
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
      `Escribe a soporte@konvi.co con tu número de documento.`,
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

  // Abre el dialog correcto según tipo de sesión.
  const openReEnrollDialog = () => {
    setError(null)
    setRecoveryCodeInput('')
    setOpenDialog(isRecoverySession ? 'recovery-reenroll' : 'reenroll')
  }

  // Flow normal (AAL2): unenroll directo + auto-enroll nuevo.
  const performReEnroll = async () => {
    if (!state.factorId) return
    setError(null)
    setBusy('disable')
    setOpenDialog(null)
    const sb = createClient()
    try {
      const { error: unenrollErr } = await sb.auth.mfa.unenroll({ factorId: state.factorId })
      if (unenrollErr) throw new Error(unenrollErr.message)
      setState({ totpEnrolled: false, factorId: null, recoveryCodesCount: 0, recoveryCountAvailable: true })
      setFeedback('Autenticador anterior desactivado. Escanea el nuevo QR con tu authenticator.')

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

  // Flow recovery session: requiere recovery code adicional + backend bypass.
  const performRecoveryReEnroll = async () => {
    if (recoveryCodeInput.trim().length < 4) {
      setError('Ingresa un código de respaldo válido.')
      return
    }
    setError(null)
    setBusy('disable')
    const sb = createClient()
    try {
      const { data: { session } } = await sb.auth.getSession()
      if (!session) throw new Error('Sesión expirada — inicia sesión de nuevo.')

      // 1. Backend valida recovery code + elimina factor TOTP via admin API.
      const res = await fetch('/api/mfa/recovery/reset-totp', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ recovery_code: recoveryCodeInput.trim() }),
      })
      let data: { ok?: boolean; detail?: string }
      try {
        data = await res.json()
      } catch {
        throw new Error(`Error inesperado HTTP ${res.status}`)
      }
      if (!res.ok || !data.ok) throw new Error(data.detail || 'Código inválido o expirado')

      setState({ totpEnrolled: false, factorId: null, recoveryCodesCount: 0, recoveryCountAvailable: true })
      setFeedback('Autenticador anterior desactivado. Escanea el nuevo QR.')
      setOpenDialog(null)
      setRecoveryCodeInput('')

      // 2. Enroll nuevo (no requiere AAL2 ya que no hay factor verified).
      const { data: enrollData, error: e } = await sb.auth.mfa.enroll({ factorType: 'totp' })
      if (e || !enrollData) throw new Error(e?.message || 'Error iniciando enrollment')
      setEnrollment({
        factorId: enrollData.id,
        qrCode: enrollData.totp.qr_code,
        secret: enrollData.totp.secret,
        code: '',
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error desconocido')
    } finally {
      setBusy(null)
    }
  }

  // ── Unenroll MFA ───────────────────────────────────────────────────

  const openDisableDialog = () => {
    setError(null)
    setOpenDialog('disable')
  }

  const performDisableMfa = async () => {
    if (!state.factorId) return
    setError(null)
    setBusy('disable')
    setOpenDialog(null)
    const sb = createClient()
    try {
      const { error: e } = await sb.auth.mfa.unenroll({ factorId: state.factorId })
      if (e) throw new Error(e.message)
      // Limpiar recovery codes también. El factor TOTP ya quedó desactivado;
      // si el clear falla NO revertimos, pero SÍ lo surfaceamos: prometemos en
      // el diálogo que "los códigos también se eliminarán", así que un fallo
      // silencioso dejaría códigos vivos contradiciendo la UI.
      const { data: { session } } = await sb.auth.getSession()
      let clearFailed = false
      if (session) {
        try {
          const clearRes = await fetch('/api/mfa/recovery-codes/clear', {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${session.access_token}` },
          })
          if (!clearRes.ok) clearFailed = true
        } catch {
          clearFailed = true
        }
      } else {
        clearFailed = true
      }
      setState({ totpEnrolled: false, factorId: null, recoveryCodesCount: 0, recoveryCountAvailable: true })
      if (clearFailed) {
        setFeedback('MFA desactivada. Nota: no pudimos eliminar los códigos de respaldo anteriores en el servidor; ya no dan acceso porque MFA está apagado, pero regenera si reactivas MFA.')
      } else {
        setFeedback('MFA desactivada.')
      }
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
        <div role="status" aria-live="polite" className="rounded-md border border-emerald-700 bg-emerald-50 p-3 flex items-start gap-2">
          <CheckCircle2 className="h-4 w-4 text-emerald-700 mt-0.5 shrink-0" />
          <p className="text-sm text-emerald-800">{feedback}</p>
        </div>
      )}

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-md border border-red-700 bg-red-50 p-3 flex items-start gap-2">
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
              <label htmlFor="mfa-enroll-code" className="block text-sm font-medium">
                Código de 6 dígitos
              </label>
              <input
                id="mfa-enroll-code"
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
              <Shield className="h-6 w-6 text-slate-700 shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              <h2 className="text-base font-semibold">
                {state.totpEnrolled
                  ? 'MFA TOTP activada'
                  : 'MFA TOTP desactivada'}
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                {state.totpEnrolled
                  ? (state.recoveryCountAvailable
                      ? `Tu cuenta requiere código de 6 dígitos al iniciar sesión. Tienes ${state.recoveryCodesCount} código(s) de respaldo disponibles.`
                      : 'Tu cuenta requiere código de 6 dígitos al iniciar sesión.')
                  : 'Recomendado para proteger tu cuenta contra accesos no autorizados.'}
              </p>
            </div>
          </div>

          {state.totpEnrolled && !state.recoveryCountAvailable && (
            <div role="status" className="rounded-md border border-amber-700 bg-amber-50 p-2 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-700 mt-0.5 shrink-0" />
              <p className="text-xs text-amber-800">
                No pudimos consultar cuántos códigos de respaldo te quedan (el
                servicio no respondió). Recarga la página; si persiste, regenera
                tus códigos para asegurarte de tener acceso de respaldo.
              </p>
            </div>
          )}

          {state.totpEnrolled && state.recoveryCountAvailable && state.recoveryCodesCount < 3 && (
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
                  onClick={regenerateRecoveryCodes}
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
                  onClick={openReEnrollDialog}
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
                  onClick={openDisableDialog}
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

      {/* ── Dialog: Cambiar autenticador (sesión normal AAL2) ────────── */}
      <Dialog open={openDialog === 'reenroll'} onOpenChange={open => !open && setOpenDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="inline-flex items-center gap-2">
              <Shield className="h-5 w-5" /> Cambiar autenticador
            </DialogTitle>
            <DialogDescription>
              Vamos a desactivar tu MFA actual y guiarte para escanear un nuevo
              QR con otra app. Tu cuenta quedará temporalmente sin MFA hasta que
              verifiques el nuevo código.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button
              type="button"
              onClick={() => setOpenDialog(null)}
              className="px-4 py-2 rounded-md border border-border hover:bg-accent text-sm"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={performReEnroll}
              className="px-4 py-2 rounded-md bg-amber-700 text-white hover:bg-amber-800 text-sm inline-flex items-center gap-1.5"
            >
              <Shield className="h-4 w-4" /> Continuar
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Dialog: Cambiar autenticador (recovery session) — requiere otro code ─ */}
      <Dialog open={openDialog === 'recovery-reenroll'} onOpenChange={open => !open && setOpenDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="inline-flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-700" /> Verificación adicional
            </DialogTitle>
            <DialogDescription>
              Estás en sesión de recuperación. Para vincular un nuevo authenticator
              necesitamos otro código de respaldo como prueba de identidad.
              Cada código sirve UNA VEZ.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 my-2">
            <label htmlFor="mfa-reenroll-recovery-code" className="block text-sm font-medium">Código de respaldo</label>
            <input
              id="mfa-reenroll-recovery-code"
              type="text"
              value={recoveryCodeInput}
              onChange={e => setRecoveryCodeInput(e.target.value.toUpperCase())}
              onKeyDown={e => {
                if (e.key === 'Enter' && recoveryCodeInput.trim().length >= 4) {
                  performRecoveryReEnroll()
                }
              }}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              autoFocus
              disabled={busy === 'disable'}
              className="w-full px-3 py-2 rounded-md border border-border bg-background font-mono text-base text-center"
            />
            {error && (
              <p role="alert" className="text-xs text-red-700 bg-red-50 border border-red-700 rounded px-2 py-1">
                {error}
              </p>
            )}
          </div>
          <DialogFooter>
            <button
              type="button"
              onClick={() => { setOpenDialog(null); setRecoveryCodeInput(''); setError(null) }}
              disabled={busy === 'disable'}
              className="px-4 py-2 rounded-md border border-border hover:bg-accent text-sm disabled:opacity-50"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={performRecoveryReEnroll}
              disabled={busy === 'disable' || recoveryCodeInput.trim().length < 4}
              className="px-4 py-2 rounded-md bg-amber-700 text-white hover:bg-amber-800 text-sm inline-flex items-center gap-1.5 disabled:opacity-50"
            >
              {busy === 'disable' ? (
                <><Loader2 className="h-4 w-4 animate-spin" /> Verificando…</>
              ) : (
                <><Shield className="h-4 w-4" /> Verificar y continuar</>
              )}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Dialog: Desactivar MFA ──────────────────────────────────── */}
      <Dialog open={openDialog === 'disable'} onOpenChange={open => !open && setOpenDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="inline-flex items-center gap-2 text-red-700">
              <Trash2 className="h-5 w-5" /> Desactivar MFA
            </DialogTitle>
            <DialogDescription>
              ¿Estás seguro? Tu cuenta quedará protegida solo con contraseña.
              Los códigos de respaldo también se eliminarán. Podrás reactivar
              MFA después, pero requerirá enrolar un nuevo authenticator desde cero.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button
              type="button"
              onClick={() => setOpenDialog(null)}
              className="px-4 py-2 rounded-md border border-border hover:bg-accent text-sm"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={performDisableMfa}
              className="px-4 py-2 rounded-md bg-red-700 text-white hover:bg-red-800 text-sm inline-flex items-center gap-1.5"
            >
              <Trash2 className="h-4 w-4" /> Desactivar MFA
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
