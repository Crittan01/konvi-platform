/**
 * Login MFA challenge page.
 *
 * Rev. 109 J.2.4.3 — segundo factor TOTP post-password.
 *
 * Flow:
 *   1. Usuario hace login con password → sesión AAL1.
 *   2. /login redirect aquí si user tiene factor TOTP verified.
 *   3. Esta página pide código 6-dígitos del authenticator.
 *   4. supabase.auth.mfa.challenge + verify → sesión AAL2.
 *   5. Redirect a /dashboard.
 *
 * También permite recovery code como alternativa.
 */
import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Card, CardContent } from '@/components/ui/card'
import { AuthBrand, AuthCardReveal, AuthScene } from '@/components/auth/auth-scene'
import { MfaChallengeForm } from './_components/mfa-challenge-form'

export const dynamic = 'force-dynamic'

export default async function MfaChallengePage(
  props: {
    searchParams: Promise<{ message?: string; error?: string }>
  }
) {
  const searchParams = await props.searchParams;
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()

  // Sin sesión → al login.
  if (!user) {
    redirect('/login')
  }

  // Ya está AAL2 → al dashboard (no debería re-aparecer aquí).
  const { data: aalData } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
  if (aalData?.currentLevel === 'aal2') {
    redirect('/dashboard')
  }

  // Sin factor verified → al dashboard directo (no debería tener MFA).
  const { data: factorsData } = await supabase.auth.mfa.listFactors()
  const totpFactor = factorsData?.totp?.find(f => f.status === 'verified')
  if (!totpFactor) {
    redirect('/dashboard')
  }

  return (
    <AuthScene>
      <AuthBrand subtitle="Verificación en dos pasos — ingresa el código de tu authenticator" />
      <AuthCardReveal>
        <Card className="dark border-white/10 bg-card/75 backdrop-blur-xl shadow-2xl">
          <CardContent className="pt-6">
            <MfaChallengeForm
              factorId={totpFactor.id}
              message={searchParams.error ?? searchParams.message}
            />
          </CardContent>
        </Card>
      </AuthCardReveal>
    </AuthScene>
  )
}
