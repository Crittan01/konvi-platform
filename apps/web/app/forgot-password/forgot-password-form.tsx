'use client'

/**
 * resetPasswordForEmail DEBE llamarse desde el browser (no server action).
 * PKCE almacena el code_verifier en cookies del browser via createBrowserClient.
 * Si se llama server-side, el verifier no llega al browser y /auth/confirm falla.
 */

import { useState, useTransition } from 'react'
import { createClient } from '@/utils/supabase/client'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { CheckCircle2, Loader2 } from 'lucide-react'
import Link from 'next/link'

export default function ForgotPasswordForm() {
  const [sent,      setSent]      = useState(false)
  const [error,     setError]     = useState<string | null>(null)
  const [isPending, startTransition] = useTransition()

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    const email = (new FormData(e.currentTarget).get('email') as string)?.trim().toLowerCase()

    startTransition(async () => {
      const supabase = createClient()
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/auth/confirm?next=/set-password`,
      })
      if (error) {
        setError(error.message)
      } else {
        // No revelar si el email existe o no — siempre mostrar éxito (seguridad)
        setSent(true)
      }
    })
  }

  if (sent) {
    return (
      <div className="space-y-4">
        <div className="flex items-start gap-3 p-4 rounded-lg border border-emerald-500/30 bg-emerald-500/8 text-sm text-emerald-400">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Revisa tu correo</p>
            <p className="text-xs text-emerald-400/70 mt-0.5">
              Si el email está registrado, recibirás el enlace en unos minutos.
              Revisa también la carpeta de spam.
            </p>
          </div>
        </div>
        <Link href="/login"
          className="block text-center text-xs text-muted-foreground hover:text-foreground underline underline-offset-4 transition-colors">
          Volver al inicio de sesión
        </Link>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <p className="text-sm text-destructive">{error}</p>
      )}
      <div className="space-y-1.5">
        <Label htmlFor="email">Correo electrónico</Label>
        <Input
          id="email"
          name="email"
          type="email"
          placeholder="tu@correo.com"
          required
          autoComplete="email"
          className="h-10"
        />
      </div>
      <Button className="w-full" type="submit" disabled={isPending}>
        {isPending
          ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Enviando...</>
          : 'Enviar enlace de recuperación'}
      </Button>
      <Link href="/login"
        className="block text-center text-xs text-muted-foreground hover:text-foreground underline underline-offset-4 transition-colors">
        Volver al inicio de sesión
      </Link>
    </form>
  )
}
