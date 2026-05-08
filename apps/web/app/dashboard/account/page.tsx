import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { KeyRound } from 'lucide-react'
import SetPasswordForm from '@/app/set-password/set-password-form'

export const metadata = {
  title: 'Mi cuenta — Konvi',
}

export default async function AccountPage({
  searchParams,
}: {
  searchParams: { error?: string; success?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) redirect('/login')

  async function changePassword(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    if (!u) redirect('/login')

    const password = (formData.get('password') as string)?.trim()
    if (!password || password.length < 8) return

    const { error } = await sb.auth.updateUser({ password })
    if (error) {
      redirect(`/dashboard/account?error=${encodeURIComponent(error.message)}`)
    }

    revalidatePath('/dashboard')
    redirect('/dashboard/account?success=1')
  }

  return (
    <div className="max-w-md space-y-6">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <KeyRound className="h-5 w-5 text-primary" />
          Mi cuenta
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {user.email}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Cambiar contraseña</CardTitle>
          <CardDescription>
            Actualiza tu contraseña de acceso a la consola.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {searchParams.success && (
            <p className="text-sm text-emerald-400 mb-4">Contraseña actualizada correctamente.</p>
          )}
          {searchParams.error && (
            <p className="text-sm text-destructive mb-4">{decodeURIComponent(searchParams.error)}</p>
          )}
          <SetPasswordForm action={changePassword} submitLabel="Actualizar contraseña" />
        </CardContent>
      </Card>
    </div>
  )
}
