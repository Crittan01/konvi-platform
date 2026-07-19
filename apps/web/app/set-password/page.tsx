import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { ShieldCheck, AlertCircle } from 'lucide-react'
import SetPasswordForm from './set-password-form'
import { translateAuthError, needsAal2 } from '@/app/auth/_lib/auth-errors'

export const metadata = {
  title: 'Crear contraseña — Konvi',
  description: 'Establece tu contraseña para acceder a la consola.',
}

export default async function SetPasswordPage(
  props: {
    // `mode=reset` lo pone forgot-password (olvidé mi clave); sin él es una
    // invitación nueva. El copy y el label del botón se adaptan al contexto.
    searchParams: Promise<{ error?: string; mode?: string }>
  }
) {
  const searchParams = await props.searchParams;
  const isReset = searchParams.mode === 'reset'
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()

  // Si no hay sesión activa el enlace expiró o ya fue usado
  if (!user) {
    redirect('/login?message=El+enlace+expiró+o+ya+fue+utilizado.+Solicita+una+nueva+invitación.')
  }

  // Preserva `mode` en los redirects de error para no perder el contexto de copy.
  const modeQS = isReset ? '&mode=reset' : ''

  async function setPassword(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    if (!u) redirect('/login')

    // El cliente valida primero, pero un submit sin JS / bypasseado NO puede
    // terminar en un no-op silencioso: devolvemos feedback explícito.
    const password = (formData.get('password') as string)?.trim()
    if (!password || password.length < 8) {
      redirect(`/set-password?error=${encodeURIComponent('La contraseña debe tener al menos 8 caracteres.')}${modeQS}`)
    }

    const { error } = await sb.auth.updateUser({ password })
    if (error) {
      // Callejón sin salida del reset con MFA: la sesión de recovery por email
      // es AAL1, pero updateUser exige AAL2 si hay factor TOTP verified. En vez
      // de fallar en crudo, mandamos al challenge y regresamos aquí (next).
      if (needsAal2(error)) {
        const back = isReset ? '/set-password?mode=reset' : '/set-password'
        redirect(`/login/mfa?next=${encodeURIComponent(back)}`)
      }
      const msg = translateAuthError(error, 'No pudimos guardar la contraseña. Solicita un enlace nuevo.')
      redirect(`/set-password?error=${encodeURIComponent(msg)}${modeQS}`)
    }

    revalidatePath('/dashboard')
    redirect('/dashboard')
  }

  const title = isReset ? 'Restablecer contraseña' : 'Crear contraseña'
  const description = isReset
    ? <>Elige una contraseña nueva para tu cuenta de <strong>Konvi</strong>.</>
    : <>Bienvenido a <strong>Konvi</strong>. Establece una contraseña segura para tu cuenta.</>
  const submitLabel = isReset ? 'Guardar y entrar' : 'Activar cuenta y entrar'

  return (
    <div className="light flex h-screen w-full items-center justify-center bg-[#131A19]">
      <div className="w-full max-w-[420px] p-6">
        <div className="flex flex-col items-center mb-6">
          <div className="h-12 w-12 rounded-xl bg-primary/20 text-primary flex items-center justify-center mb-3 shadow-lg ring-1 ring-white/10">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Konvi</h1>
        </div>
        <Card className="border-0 shadow-2xl bg-[#FBFAF6]">
          <CardHeader className="space-y-1">
            <div className="flex items-center gap-2 mb-1">
              <ShieldCheck className="h-5 w-5 text-primary" />
              <CardTitle className="text-xl font-bold">{title}</CardTitle>
            </div>
            <CardDescription>{description}</CardDescription>
            {user.email && (
              <p className="text-xs text-muted-foreground pt-1">
                Cuenta: <span className="font-mono text-foreground">{user.email}</span>
              </p>
            )}
          </CardHeader>
          <CardContent>
            {searchParams.error && (
              <div className="flex items-start gap-2 p-3 mb-4 rounded-lg border border-red-700/30 bg-red-500/8 text-sm text-red-700" role="alert">
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" aria-hidden="true" />
                <p>{decodeURIComponent(searchParams.error)}</p>
              </div>
            )}
            <SetPasswordForm action={setPassword} submitLabel={submitLabel} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
