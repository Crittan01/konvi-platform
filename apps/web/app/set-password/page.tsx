import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { ShieldCheck, AlertCircle } from 'lucide-react'

export const metadata = {
  title: 'Crear contraseña — Commerce Ops',
  description: 'Establece tu contraseña para acceder a la consola.',
}

export default async function SetPasswordPage({
  searchParams,
}: {
  searchParams: { error?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  // Si no hay sesión activa el enlace expiró o ya fue usado
  if (!user) {
    redirect('/login?message=El+enlace+expiró+o+ya+fue+utilizado.+Solicita+una+nueva+invitación.')
  }

  // Si ya tiene contraseña configurada (no es una invitación nueva), va al dashboard
  // user.identities[0].identity_data contiene el estado inicial; si ya tiene last_sign_in_at
  // significativo, podría estar intentando cambiar contraseña — lo permitimos igual.

  async function setPassword(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    if (!u) redirect('/login')

    const password  = (formData.get('password') as string)?.trim()
    const confirm   = (formData.get('confirm') as string)?.trim()

    if (!password || password.length < 8) {
      redirect('/set-password?error=La+contraseña+debe+tener+al+menos+8+caracteres.')
    }
    if (password !== confirm) {
      redirect('/set-password?error=Las+contraseñas+no+coinciden.')
    }

    const { error } = await sb.auth.updateUser({ password })
    if (error) {
      redirect(`/set-password?error=${encodeURIComponent(error.message)}`)
    }

    revalidatePath('/dashboard')
    redirect('/dashboard')
  }

  return (
    <div className="flex h-screen w-full items-center justify-center bg-background">
      <Card className="w-[420px]">
        <CardHeader className="space-y-1">
          <div className="flex items-center gap-2 mb-1">
            <ShieldCheck className="h-5 w-5 text-primary" />
            <CardTitle className="text-xl font-bold">Crear contraseña</CardTitle>
          </div>
          <CardDescription>
            Bienvenido a <strong>Commerce Ops</strong>. Establece una contraseña segura para tu cuenta.
          </CardDescription>
          {user.email && (
            <p className="text-xs text-muted-foreground pt-1">
              Cuenta: <span className="font-mono text-foreground">{user.email}</span>
            </p>
          )}
        </CardHeader>
        <CardContent>
          {searchParams.error && (
            <div className="flex items-start gap-2 p-3 mb-4 rounded-lg border border-red-500/30 bg-red-500/8 text-sm text-red-400">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <p>{decodeURIComponent(searchParams.error)}</p>
            </div>
          )}
          <form action={setPassword} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="password">Nueva contraseña</Label>
              <Input
                id="password"
                name="password"
                type="password"
                placeholder="Mínimo 8 caracteres"
                required
                minLength={8}
                autoComplete="new-password"
                className="h-10"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="confirm">Confirmar contraseña</Label>
              <Input
                id="confirm"
                name="confirm"
                type="password"
                placeholder="Repite la contraseña"
                required
                minLength={8}
                autoComplete="new-password"
                className="h-10"
              />
            </div>
            <Button className="w-full" type="submit" size="lg">
              Activar cuenta y entrar
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
