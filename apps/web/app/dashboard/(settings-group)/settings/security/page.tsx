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
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { KeyRound } from 'lucide-react'
import SetPasswordForm from '@/app/set-password/set-password-form'
import { SecurityForm } from './_components/security-form'

export const dynamic = 'force-dynamic'

interface MfaState {
  totpEnrolled: boolean
  factorId: string | null
  recoveryCodesCount: number
}

async function getMfaState(): Promise<{ state: MfaState; userId: string }> {
  const sb = createClient()
  const { data: { user } } = await sb.auth.getUser()
  const { data: { session } } = await sb.auth.getSession()
  if (!user || !session) redirect('/login')

  // Listar factores MFA del user (Supabase Auth nativo).
  const { data: factorsData } = await sb.auth.mfa.listFactors()
  const totpFactor = factorsData?.totp?.find(f => f.status === 'verified') || null

  // Contar recovery codes (backend custom).
  let count = 0
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/mfa/recovery-codes/count`, {
      headers: { 'Authorization': `Bearer ${session.access_token}` },
      cache: 'no-store',
    })
    if (res.ok) {
      const data = await res.json()
      count = Number(data.count || 0)
    }
  } catch {
    // best-effort
  }

  return {
    state: {
      totpEnrolled: !!totpFactor,
      factorId: totpFactor?.id || null,
      recoveryCodesCount: count,
    },
    userId: user.id,
  }
}

export default async function SecurityPage({
  searchParams,
}: {
  searchParams: { pwd_success?: string; pwd_error?: string }
}) {
  const { state, userId } = await getMfaState()
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  // Server action: cambiar contraseña (movido desde /dashboard/account).
  async function changePassword(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    if (!u) redirect('/login')

    const password = (formData.get('password') as string)?.trim()
    if (!password || password.length < 8) {
      redirect('/dashboard/settings/security?pwd_error=' + encodeURIComponent('La contraseña debe tener al menos 8 caracteres.'))
    }

    const { error } = await sb.auth.updateUser({ password })
    if (error) {
      redirect(`/dashboard/settings/security?pwd_error=${encodeURIComponent(error.message)}`)
    }

    revalidatePath('/dashboard/settings/security')
    redirect('/dashboard/settings/security?pwd_success=1')
  }

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Seguridad</h1>
        <p className="text-sm text-muted-foreground">
          Gestiona tu contraseña y autenticación de dos factores (MFA TOTP) para
          proteger tu cuenta personal: <code className="text-xs">{user.email}</code>.
        </p>
      </header>

      {/* ── Sección 1: Cambiar contraseña ────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base inline-flex items-center gap-2">
            <KeyRound className="h-4 w-4" /> Contraseña
          </CardTitle>
          <CardDescription>
            Actualiza tu contraseña de acceso. Requerido: mínimo 8 caracteres.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {searchParams.pwd_success && (
            <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-1">
              Contraseña actualizada correctamente.
            </p>
          )}
          {searchParams.pwd_error && (
            <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1">
              {decodeURIComponent(searchParams.pwd_error)}
            </p>
          )}
          <SetPasswordForm action={changePassword} submitLabel="Actualizar contraseña" />
        </CardContent>
      </Card>

      {/* ── Sección 2: MFA TOTP ─────────────────────────────────────────── */}
      <div className="border-t border-border pt-6 space-y-3">
        <header className="space-y-1">
          <h2 className="text-lg font-semibold">Autenticación de dos factores (MFA)</h2>
          <p className="text-sm text-muted-foreground">
            Compatible con Google Authenticator, Authy, 1Password.
          </p>
        </header>
        <SecurityForm initialState={state} userId={userId} />
      </div>

      <footer className="text-xs text-muted-foreground border-t border-border pt-4 space-y-1">
        <p>
          <strong>¿Perdiste tu authenticator?</strong> Inicia sesión con uno de
          tus códigos de respaldo. Si también los perdiste, escribe a
          soporte@konvi.com.
        </p>
        <p>
          Recomendado: regenera los códigos cada 3-6 meses o si sospechas
          que fueron comprometidos.
        </p>
      </footer>
    </div>
  )
}
