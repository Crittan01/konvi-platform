import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Card, CardContent } from '@/components/ui/card'
import LoginForm from './login-form'

export default async function LoginPage({
  searchParams,
}: {
  searchParams: { message?: string; error?: string; force?: string }
}) {
  const supabase = createClient()
  const { data } = await supabase.auth.getUser()

  // Rev. 109 J.2.4.3 — flow multi-user en mismo browser.
  // Si `?force=1` → mostrar form para login como otra cuenta.
  // Si sesión activa sin force → mostrar pantalla intermedia con opciones
  // (continuar como X / cambiar de cuenta).
  const forceLogin = searchParams.force === '1'

  if (data?.user && !forceLogin) {
    // Sesión activa con MFA pendiente → al challenge (no a intermedia).
    const { data: aalData } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
    if (aalData?.nextLevel === 'aal2' && aalData.currentLevel === 'aal1') {
      redirect('/login/mfa')
    }
    // Sesión válida sin ?force → renderizar intermedia abajo (NO auto-redirect).
  }

  const continueAction = async () => {
    'use server'
    redirect('/dashboard')
  }

  const switchUserAction = async () => {
    'use server'
    const sb = createClient()
    await sb.auth.signOut()
    redirect('/login?force=1')
  }

  const loginAction = async (formData: FormData) => {
    'use server'
    const email = formData.get('email') as string
    const password = formData.get('password') as string
    const supabase = createClient()

    // Rev. 109 J.2.4.3 — Si hay sesión activa de otro usuario, cerrarla
    // antes de iniciar sesión nueva. Evita que la cookie residual de A
    // se mezcle con la nueva sesión de B (Supabase Auth lo manejaría
    // sobreescribiendo, pero el signOut explícito limpia la sesión SSR
    // sin race condition).
    const { data: existing } = await supabase.auth.getUser()
    if (existing?.user && existing.user.email !== email) {
      await supabase.auth.signOut()
    }

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    })

    if (error) {
      return redirect('/login?message=Correo+o+contraseña+incorrectos')
    }

    // Rev. 109 J.2.4.3 — Si el usuario tiene MFA activa, el AAL inicial
    // post-password es 'aal1'. Necesita challenge para subir a 'aal2'.
    const { data: aalData } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
    if (aalData?.nextLevel === 'aal2' && aalData.currentLevel === 'aal1') {
      // Tiene factor verified pero sesión actual es solo password.
      return redirect('/login/mfa')
    }

    return redirect('/dashboard')
  }

  return (
    <div className="flex h-screen w-full items-center justify-center bg-[#131A19]">
      <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-5 mix-blend-overlay pointer-events-none"></div>
      
      <div className="relative w-full max-w-[420px] p-6 sm:p-8">
        <div className="flex flex-col items-center mb-8">
          {/* Logo mock / Brand */}
          <div className="h-12 w-12 rounded-xl bg-primary/20 text-primary flex items-center justify-center mb-4 shadow-lg ring-1 ring-white/10">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Konvi</h1>
          <p className="text-emerald-500/80 mt-2 text-sm text-center font-medium">Tenant Administrativo de Comercio</p>
        </div>

        {forceLogin && data?.user && (
          <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-50/95 p-3 text-sm text-amber-900">
            <p className="font-medium">Sesión activa de otro usuario</p>
            <p className="text-xs mt-1 text-amber-800">
              Actualmente: <code className="font-mono">{data.user.email}</code>.
              Si te logueas ahora, esa sesión se cerrará automáticamente.
            </p>
          </div>
        )}

        {data?.user && !forceLogin ? (
          /* Sesión activa SIN ?force → pantalla intermedia con opciones */
          <Card className="border-0 shadow-2xl bg-[#FBFAF6]">
            <CardContent className="pt-6 space-y-4">
              <div className="text-center space-y-1">
                <p className="text-sm text-muted-foreground">Sesión activa</p>
                <p className="font-mono text-base font-medium break-all">{data.user.email}</p>
              </div>
              <form action={continueAction}>
                <button
                  type="submit"
                  className="w-full px-4 py-2.5 rounded-md bg-foreground text-background hover:opacity-90 font-medium text-sm"
                >
                  Continuar al dashboard
                </button>
              </form>
              <form action={switchUserAction}>
                <button
                  type="submit"
                  className="w-full px-4 py-2.5 rounded-md border border-border hover:bg-accent text-sm"
                >
                  Cambiar de cuenta
                </button>
              </form>
              <p className="text-[10px] text-center text-muted-foreground">
                Si esta no es tu sesión y no reconoces el email,
                usa "Cambiar de cuenta" para iniciar como otro usuario.
              </p>
            </CardContent>
          </Card>
        ) : (
          <Card className="border-0 shadow-2xl bg-[#FBFAF6]">
            <CardContent className="pt-6">
              <LoginForm action={loginAction} message={searchParams.error ?? searchParams.message} />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
