import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Card, CardContent } from '@/components/ui/card'
import LoginForm from './login-form'

export default async function LoginPage({
  searchParams,
}: {
  searchParams: { message?: string; error?: string }
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
    <div className="flex h-screen w-full items-center justify-center bg-[#131A19]">
      <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-5 mix-blend-overlay pointer-events-none"></div>
      
      <div className="relative w-full max-w-[420px] p-6 sm:p-8">
        <div className="flex flex-col items-center mb-8">
          {/* Logo mock / Brand */}
          <div className="h-12 w-12 rounded-xl bg-primary/20 text-primary flex items-center justify-center mb-4 shadow-lg ring-1 ring-white/10">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          </div>
          <h1 className="text-3xl font-bold text-white tracking-tight">Konvi</h1>
          <p className="text-emerald-500/80 mt-2 text-sm text-center font-medium">Tu tienda en WhatsApp</p>
        </div>

        <Card className="border-0 shadow-2xl bg-[#FBFAF6]">
          <CardContent className="pt-6">
            <LoginForm action={loginAction} message={searchParams.error ?? searchParams.message} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
