import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Card, CardContent } from '@/components/ui/card'
import LoginForm from './login-form'
import { isBannedError, translateAuthError, safeNextPath } from '@/app/auth/_lib/auth-errors'

/** Añade `?next=<ruta>` a un destino sólo si el deep-link es una ruta interna. */
function withNext(base: string, next?: string): string {
  const safe = next ? safeNextPath(next, '') : ''
  return safe ? `${base}?next=${encodeURIComponent(safe)}` : base
}

export default async function LoginPage(
  props: {
    searchParams: Promise<{ message?: string; error?: string; force?: string; next?: string }>
  }
) {
  const searchParams = await props.searchParams;
  const nextParam = searchParams.next
  const supabase = await createClient()
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
      redirect(withNext('/login/mfa', nextParam))
    }
    // Sesión válida sin ?force → renderizar intermedia abajo (NO auto-redirect).
  }

  const continueAction = async () => {
    'use server'
    redirect(safeNextPath(nextParam))
  }

  const switchUserAction = async () => {
    'use server'
    const sb = await createClient()
    await sb.auth.signOut()
    redirect('/login?force=1')
  }

  const loginAction = async (formData: FormData) => {
    'use server'
    const email = formData.get('email') as string
    const password = formData.get('password') as string
    const nextField = (formData.get('next') as string) || undefined
    const supabase = await createClient()

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
      // El ban nativo (ban_duration aplicado por el owner desde Equipo) llega
      // aquí como error de sign-in. Antes colapsaba al genérico y el miembro
      // suspendido creía haber olvidado su clave. Ahora va a la pantalla real.
      if (isBannedError(error)) {
        return redirect('/cuenta-suspendida')
      }
      // Discrimina rate-limit / email sin confirmar / etc. sin filtrar inglés
      // ni revelar si el correo existe (fallback = credenciales inválidas).
      const msg = translateAuthError(error, 'Correo o contraseña incorrectos.')
      const params = new URLSearchParams({ message: msg })
      const safeNext = nextField ? safeNextPath(nextField, '') : ''
      if (safeNext) params.set('next', safeNext)
      return redirect(`/login?${params.toString()}`)
    }

    // Rev. 109 J.2.4.3 — Si el usuario tiene MFA activa, el AAL inicial
    // post-password es 'aal1'. Necesita challenge para subir a 'aal2'.
    const { data: aalData } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
    if (aalData?.nextLevel === 'aal2' && aalData.currentLevel === 'aal1') {
      // Tiene factor verified pero sesión actual es solo password. Propaga el
      // deep-link para que el challenge aterrice en el destino pedido.
      return redirect(withNext('/login/mfa', nextField))
    }

    return redirect(safeNextPath(nextField))
  }

  return (
    <div className="light relative flex h-screen w-full items-center justify-center overflow-hidden bg-[#131A19]">
      {/* Textura grano — SVG inline (sin dependencia runtime de terceros en la
          puerta de entrada del producto; el asset externo era un vector de
          supply-chain en el login). */}
      <div
        aria-hidden="true"
        className="absolute inset-0 opacity-5 mix-blend-overlay pointer-events-none"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
        }}
      ></div>
      <div className="relative w-full max-w-[420px] p-6 sm:p-8">
        <div className="flex flex-col items-center mb-8">
          {/* Logo mock / Brand */}
          <div className="h-12 w-12 rounded-xl bg-primary/20 text-primary flex items-center justify-center mb-4 shadow-lg ring-1 ring-white/10">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Konvi</h1>
          <p className="text-white/60 mt-2 text-sm text-center font-medium">Consola de administración de tu negocio</p>
        </div>

        {forceLogin && data?.user && (
          <div className="mb-4 rounded-lg border border-amber-700/40 bg-amber-50/95 p-3 text-sm text-amber-900">
            <p className="font-medium">Sesión activa de otro usuario</p>
            <p className="text-xs mt-1 text-amber-800">
              Actualmente: <code className="font-mono">{data.user.email}</code>.
              Si te logueas ahora, esa sesión se cerrará automáticamente.
            </p>
          </div>
        )}

        {data?.user && !forceLogin ? (
          /* Sesión activa SIN ?force → pantalla intermedia con opciones */
          (<Card className="border-0 shadow-2xl bg-[#FBFAF6]">
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
          </Card>)
        ) : (
          <Card className="border-0 shadow-2xl bg-[#FBFAF6]">
            <CardContent className="pt-6">
              <LoginForm action={loginAction} message={searchParams.error ?? searchParams.message} next={nextParam} />
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
