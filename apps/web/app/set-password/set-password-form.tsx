'use client'

import { useState, useTransition } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Eye, EyeOff, Loader2 } from 'lucide-react'

interface Props {
  action: (formData: FormData) => Promise<void>
  submitLabel?: string
  /** YELLOW-8 (auditoría OWASP 2026-08-23): pide la contraseña ACTUAL
   *  (re-autenticación). Solo para cambio de contraseña con sesión activa
   *  (settings/seguridad); en el alta/reset no aplica (aún no hay clave). */
  requireCurrentPassword?: boolean
}

export default function SetPasswordForm({ action, submitLabel = 'Activar cuenta y entrar', requireCurrentPassword = false }: Props) {
  const [showCurrent,  setShowCurrent]    = useState(false)
  const [showPassword, setShowPassword]   = useState(false)
  const [showConfirm,  setShowConfirm]    = useState(false)
  const [error,        setError]          = useState<string | null>(null)
  const [isPending,    startTransition]   = useTransition()

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)

    const fd       = new FormData(e.currentTarget)
    const password = fd.get('password') as string
    const confirm  = fd.get('confirm') as string

    if (!password || password.length < 8) {
      setError('La contraseña debe tener al menos 8 caracteres.')
      return
    }
    if (password !== confirm) {
      setError('Las contraseñas no coinciden.')
      return
    }

    startTransition(async () => {
      await action(fd)
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <p className="text-sm text-destructive text-center" role="alert" aria-live="assertive">{error}</p>
      )}

      {/* Contraseña actual — re-auth (YELLOW-8), solo en cambio con sesión activa */}
      {requireCurrentPassword && (
        <div className="space-y-1.5">
          <Label htmlFor="current_password">Contraseña actual</Label>
          <div className="relative">
            <Input
              id="current_password"
              name="current_password"
              type={showCurrent ? 'text' : 'password'}
              placeholder="Tu contraseña actual"
              required
              autoComplete="current-password"
              className="h-10 pr-10"
            />
            <button
              type="button"
              onClick={() => setShowCurrent(v => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
              aria-label={showCurrent ? 'Ocultar contraseña actual' : 'Mostrar contraseña actual'}
              aria-pressed={showCurrent}
            >
              {showCurrent ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
            </button>
          </div>
        </div>
      )}

      {/* Contraseña */}
      <div className="space-y-1.5">
        <Label htmlFor="password">Nueva contraseña</Label>
        <div className="relative">
          <Input
            id="password"
            name="password"
            type={showPassword ? 'text' : 'password'}
            placeholder="Mínimo 8 caracteres"
            required
            minLength={8}
            autoComplete="new-password"
            className="h-10 pr-10"
          />
          <button
            type="button"
            onClick={() => setShowPassword(v => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'}
            aria-pressed={showPassword}
          >
            {showPassword ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
          </button>
        </div>
      </div>

      {/* Confirmar */}
      <div className="space-y-1.5">
        <Label htmlFor="confirm">Confirmar contraseña</Label>
        <div className="relative">
          <Input
            id="confirm"
            name="confirm"
            type={showConfirm ? 'text' : 'password'}
            placeholder="Repite la contraseña"
            required
            minLength={8}
            autoComplete="new-password"
            className="h-10 pr-10"
          />
          <button
            type="button"
            onClick={() => setShowConfirm(v => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            aria-label={showConfirm ? 'Ocultar contraseña' : 'Mostrar contraseña'}
            aria-pressed={showConfirm}
          >
            {showConfirm ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
          </button>
        </div>
      </div>

      <Button className="w-full" type="submit" size="lg" disabled={isPending}>
        {isPending
          ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Guardando...</>
          : submitLabel}
      </Button>
    </form>
  )
}
