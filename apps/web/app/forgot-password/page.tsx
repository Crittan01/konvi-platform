import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Mail } from 'lucide-react'
import { AuthBrand, AuthCardReveal, AuthScene } from '@/components/auth/auth-scene'
import ForgotPasswordForm from './forgot-password-form'

export const metadata = {
  title: 'Recuperar contraseña — Konvi',
}

export default function ForgotPasswordPage() {
  return (
    <AuthScene>
      <AuthBrand subtitle="Recupera el acceso a tu consola" />
      <AuthCardReveal>
        <Card className="dark border-white/10 bg-card/75 backdrop-blur-xl shadow-2xl">
          <CardHeader className="space-y-1">
            <div className="flex items-center gap-2 mb-1">
              <Mail className="h-5 w-5 text-primary" />
              <CardTitle className="text-xl font-bold">Recuperar contraseña</CardTitle>
            </div>
            <CardDescription>
              Te enviaremos un enlace para restablecer tu contraseña.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ForgotPasswordForm />
          </CardContent>
        </Card>
      </AuthCardReveal>
    </AuthScene>
  )
}
