import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'

export default async function LoginPage({
  searchParams,
}: {
  searchParams: { message?: string }
}) {
  const supabase = createClient()
  const { data } = await supabase.auth.getUser()

  if (data?.user) {
    redirect('/dashboard')
  }

  const loginAction = async (formData: FormData) => {
    'use server'
    const email = formData.get('email') as string
    const password = formData.get('password') as string
    const supabase = createClient()

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    })

    if (error) {
      return redirect('/login?message=Correo+o+contraseña+incorrectos')
    }
    return redirect('/dashboard')
  }

  return (
    <div className="flex h-screen w-full items-center justify-center sidebar-gradient">
      <Card className="w-[400px]">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold">Commerce Ops</CardTitle>
          <CardDescription>
            Ingresa a tu Tenant Administrativo de Comercio
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form action={loginAction} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Correo Corporativo</Label>
              <Input
                id="email"
                name="email"
                type="email"
                placeholder="admin@commerce.local"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Contraseña</Label>
              <Input id="password" name="password" type="password" required />
            </div>
            {searchParams.message && (
              <p className="text-sm text-destructive text-center">
                {searchParams.message}
              </p>
            )}
            <Button className="w-full" type="submit">Entrar</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
