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
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'
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

export default async function SecurityPage() {
  const { state, userId } = await getMfaState()

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Seguridad</h1>
        <p className="text-sm text-muted-foreground">
          Activa la autenticación de dos factores (MFA TOTP) para proteger
          tu cuenta. Compatible con Google Authenticator, Authy, 1Password.
        </p>
      </header>

      <SecurityForm initialState={state} userId={userId} />

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
