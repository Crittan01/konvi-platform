/**
 * Settings → Seguridad → MFA TOTP.
 *
 * Rev. 109 J.2.4.3 — multi-factor auth con códigos de respaldo.
 *
 * Cualquier usuario autenticado puede activar MFA en su sesión (NO requiere
 * role owner). Pen testing OWASP recomienda MFA para todos los roles que
 * pueden modificar datos.
 *
 * Flow:
 *   1. Página muestra estado actual (enrolled / not).
 *   2. Si NOT enrolled: botón "Activar MFA" → enrollment client-side
 *      (supabase-js .auth.mfa.enroll + verify code).
 *   3. Tras enrollment exitoso: backend genera 8 recovery codes,
 *      UI los muestra UNA VEZ con botón descarga .txt.
 *   4. Si enrolled: opciones "Regenerar recovery codes" / "Desactivar MFA".
 */
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'
import { verifyRecoveryCookie } from '@/lib/mfa-recovery-cookie'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { PageHeader } from '@/components/ui/page-header'
import { StaggerItem, StaggerList } from '@/components/ui/motion'
import { KeyRound, Shield, ShieldCheck } from 'lucide-react'
import SetPasswordForm from '@/app/set-password/set-password-form'
import { SecurityForm } from './_components/security-form'
import { RecoveryChangePassword } from './_components/recovery-change-password'

export const metadata = { title: 'Seguridad' }

export const dynamic = 'force-dynamic'

interface MfaState {
  totpEnrolled: boolean
  factorId: string | null
  recoveryCodesCount: number
  /** false si CORE_API no respondió el conteo — la UI NO debe mostrar "0
   *  códigos" ni la alarma de "pocos códigos" en ese caso (sería falsa). */
  recoveryCountAvailable: boolean
}

async function getMfaState(): Promise<{ state: MfaState; userId: string; userEmail: string | undefined }> {
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const { data: { session } } = await sb.auth.getSession()
  if (!user || !session) redirect('/login')

  // Listar factores MFA del user (Supabase Auth nativo).
  const { data: factorsData } = await sb.auth.mfa.listFactors()
  const totpFactor = factorsData?.totp?.find(f => f.status === 'verified') || null

  // Contar recovery codes (backend custom). Distinguimos "0 códigos" (dato
  // real) de "no se pudo consultar" (fallo de red/servicio) — enmascarar el
  // segundo como 0 dispararía una alarma falsa de "te quedan pocos códigos".
  let count = 0
  let countAvailable = false
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/mfa/recovery-codes/count`, {
      headers: { 'Authorization': `Bearer ${session.access_token}` },
      cache: 'no-store',
    })
    if (res.ok) {
      const data = await res.json()
      count = Number(data.count || 0)
      countAvailable = true
    }
  } catch {
    // best-effort — countAvailable queda en false y la UI lo surfacea.
  }

  return {
    state: {
      totpEnrolled: !!totpFactor,
      factorId: totpFactor?.id || null,
      recoveryCodesCount: count,
      recoveryCountAvailable: countAvailable,
    },
    userId: user.id,
    userEmail: user.email,
  }
}

export default async function SecurityPage(
  props: {
    searchParams: Promise<{ pwd_success?: string; pwd_error?: string }>
  }
) {
  const searchParams = await props.searchParams;
  // getMfaState ya autentica (getUser) y redirige a /login si no hay sesión;
  // reutilizamos su resultado en vez de crear un segundo client + getUser.
  const { state, userId, userEmail } = await getMfaState()

  // Rev. 109 J.2.4.3 — detectar sesión recovery (cookie HttpOnly seteada
  // por /api/mfa/recovery-codes/verify cuando user usó recovery code).
  // En esa sesión, AAL=1 y operaciones AAL2-required (changePassword,
  // unenroll) deben pasar por endpoints backend que validan recovery code
  // adicional + admin API bypass.
  const { cookies: cookiesFn } = await import('next/headers')
  const recoveryCookieStore = await cookiesFn()   // Next 15: cookies() es async
  // F83: verificar firma HMAC (ligada al user + expiry), no `=== '1'`.
  const isRecoverySession = await verifyRecoveryCookie(
    recoveryCookieStore.get('mfa_recovery_session')?.value,
    userId,
    Math.floor(Date.now() / 1000),
  )

  // Server action: cambiar contraseña.
  // - Si AAL2 (sesión normal): usa supabase.auth.updateUser directo.
  // - Si AAL1 + recovery: NO disponible aquí — UI cliente lo maneja con
  //   dialog que pide recovery code y llama al endpoint backend.
  async function changePassword(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    if (!u) redirect('/login')

    const password = (formData.get('password') as string)?.trim()
    if (!password || password.length < 8) {
      redirect('/dashboard/settings/security?pwd_error=' + encodeURIComponent('La contraseña debe tener al menos 8 caracteres.'))
    }

    const { error } = await sb.auth.updateUser({ password })
    if (error) {
      // Si el error es AAL2-related (sesión recovery) → guiar al user.
      const friendlyError = error.message.includes('AAL2')
        ? 'Necesitas verificación adicional. Usa "Cambiar contraseña con código de respaldo" debajo.'
        : error.message
      redirect(`/dashboard/settings/security?pwd_error=${encodeURIComponent(friendlyError)}`)
    }

    revalidatePath('/dashboard/settings/security')
    redirect('/dashboard/settings/security?pwd_success=1')
  }

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      {/* Cabecera de módulo con identidad (firma Kaiu, T7.11 — piloto PageHeader) */}
      <PageHeader
        icon={ShieldCheck}
        title="Seguridad"
        description={
          <>
            Gestiona tu contraseña y autenticación de dos factores (MFA TOTP) para
            proteger tu cuenta personal: <code className="text-xs">{userEmail}</code>.
          </>
        }
      />

      {/* Revelado escalonado de las superficies (wrappers DS — §4.1). */}
      <StaggerList className="space-y-6" stagger={0.08}>
      <StaggerItem>
      {/* ── Sección 1: Cambiar contraseña ────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base inline-flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-primary" /> Contraseña
          </CardTitle>
          <CardDescription>
            Actualiza tu contraseña de acceso. Requerido: mínimo 8 caracteres.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {isRecoverySession && (
            <Alert variant="warning">
              <AlertDescription>
                Estás en sesión de recuperación. Para cambiar la contraseña
                necesitas verificación con código de respaldo (ver abajo).
              </AlertDescription>
            </Alert>
          )}
          {searchParams.pwd_success && (
            <Alert variant="success" role="status">
              <AlertDescription>Contraseña actualizada correctamente.</AlertDescription>
            </Alert>
          )}
          {searchParams.pwd_error && (
            <Alert variant="destructive">
              <AlertDescription>{decodeURIComponent(searchParams.pwd_error)}</AlertDescription>
            </Alert>
          )}
          {!isRecoverySession ? (
            <SetPasswordForm action={changePassword} submitLabel="Actualizar contraseña" />
          ) : (
            <RecoveryChangePassword />
          )}
        </CardContent>
      </Card>
      </StaggerItem>

      {/* ── Sección 2: MFA TOTP ─────────────────────────────────────────── */}
      <StaggerItem>
      <Card>
        <CardHeader>
          <CardTitle className="text-base inline-flex items-center gap-2">
            <Shield className="h-4 w-4 text-primary" /> Autenticación de dos factores (MFA)
          </CardTitle>
          <CardDescription>
            Compatible con Google Authenticator, Authy, 1Password.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SecurityForm initialState={state} userId={userId} isRecoverySession={isRecoverySession} />
        </CardContent>
      </Card>
      </StaggerItem>

      <StaggerItem>
      <footer className="text-xs text-muted-foreground border-t border-border pt-4 space-y-1">
        <p>
          <strong>¿Perdiste tu authenticator?</strong> Inicia sesión con uno de
          tus códigos de respaldo. Si también los perdiste, escribe a
          soporte@konvi.co.
        </p>
        <p>
          Recomendado: regenera los códigos cada 3-6 meses o si sospechas
          que fueron comprometidos.
        </p>
      </footer>
      </StaggerItem>
      </StaggerList>
    </div>
  )
}
