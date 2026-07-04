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
    <div className="flex h-screen w-full items-center justify-center bg-[#131A19]">
      <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-5 mix-blend-overlay pointer-events-none"></div>

      <div className="relative w-full max-w-[420px] p-6 sm:p-8">
        <div className="flex flex-col items-center mb-8">
          <div className="h-12 w-12 rounded-xl bg-primary/20 text-primary flex items-center justify-center mb-4 shadow-lg ring-1 ring-white/10">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Verificación 2FA</h1>
          <p className="text-emerald-500/80 mt-2 text-sm text-center font-medium">
            Ingresa el código de tu authenticator
          </p>
        </div>

        <Card className="border-0 shadow-2xl bg-[#FBFAF6]">
          <CardContent className="pt-6">
            <MfaChallengeForm
              factorId={totpFactor.id}
              message={searchParams.error ?? searchParams.message}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
