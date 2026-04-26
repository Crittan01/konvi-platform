'use client'

import { useState, useTransition } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Eye, EyeOff, Loader2 } from 'lucide-react'
import Link from 'next/link'

interface Props {
  action:  (formData: FormData) => Promise<void>
  message?: string
}

export default function LoginForm({ action, message }: Props) {
  const [showPwd,   setShowPwd]   = useState(false)
  const [isPending, startTransition] = useTransition()

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    startTransition(async () => { await action(fd) })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="space-y-2">
        <Label htmlFor="email">Correo Corporativo</Label>
        <Input
          id="email"
          name="email"
          type="email"
          placeholder="admin@commerce.local"
          required
          autoComplete="email"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="password">Contraseña</Label>
          <Link href="/forgot-password"
            className="text-[11px] text-muted-foreground hover:text-foreground underline underline-offset-4 transition-colors">
            ¿Olvidaste tu contraseña?
          </Link>
        </div>
        <div className="relative">
          <Input
            id="password"
            name="password"
            type={showPwd ? 'text' : 'password'}
            required
            autoComplete="current-password"
            className="pr-10"
          />
          <button
            type="button"
            onClick={() => setShowPwd(v => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            tabIndex={-1}
          >
            {showPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {message && (
        <p className="text-sm text-destructive text-center">{message}</p>
      )}

      <Button className="w-full" type="submit" disabled={isPending}>
        {isPending
          ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Ingresando...</>
          : 'Entrar'}
      </Button>
    </form>
  )
}
