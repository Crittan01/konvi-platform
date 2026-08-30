import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Card, CardContent } from '@/components/ui/card'
import { AuthBrand, AuthCardReveal, AuthScene } from '@/components/auth/auth-scene'
import LoginForm from './login-form'
import { isBannedError, translateAuthError, safeNextPath } from '@/app/auth/_lib/auth-errors'
import { RECOVERY_SESSION_COOKIE } from '@/lib/mfa-recovery-cookie'

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
    // G7 (auditoría frontend seguridad) — borrar también la cookie de bypass
    // AAL2 (`mfa_recovery_session`): si esta sesión entró con un recovery code,
    // el bypass no debe sobrevivir al cambio de cuenta (el próximo login AAL1
    // lo heredaría sin pasar TOTP). Es server action → se borra aquí mismo con
    // cookies() de next/headers, mismo patrón del logout del dashboard
    // (app/dashboard/layout.tsx).
    const { cookies } = await import('next/headers')
    const cookieStore = await cookies()   // Next 16: cookies() es async
    cookieStore.delete(RECOVERY_SESSION_COOKIE)
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
    <AuthScene>
      {/* Marca animada (T7.1) — el "Logo mock / Brand" murió: tile degradado
          primary→amber + glow y coreografía stagger vía wrappers del DS. */}
      <AuthBrand subtitle="Consola de administración de tu negocio" />

      {forceLogin && data?.user && (
        <div className="mb-4 rounded-lg border border-warning-border bg-warning-bg/95 p-3 text-sm text-warning-fg">
          <p className="font-medium">Sesión activa de otro usuario</p>
          <p className="text-xs mt-1 text-warning-fg">
            Actualmente: <code className="font-mono">{data.user.email}</code>.
            Si te logueas ahora, esa sesión se cerrará automáticamente.
          </p>
        </div>
      )}

      <AuthCardReveal>
        {data?.user && !forceLogin ? (
          /* Sesión activa SIN ?force → pantalla intermedia con opciones */
          (<Card className="dark border-white/10 bg-card/75 backdrop-blur-xl shadow-2xl">
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
          <Card className="dark border-white/10 bg-card/75 backdrop-blur-xl shadow-2xl">
            <CardContent className="pt-6">
              <LoginForm action={loginAction} message={searchParams.error ?? searchParams.message} next={nextParam} />
            </CardContent>
          </Card>
        )}
      </AuthCardReveal>
    </AuthScene>
  );
}
