'use client'

import { useFormStatus } from 'react-dom'
import { Button } from '@/components/ui/button'
import { Loader2, Check } from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { useActionResultStatus } from '@/components/action-result-form'

interface Props {
  children: React.ReactNode
  pendingText?: string
  savedText?: string
  variant?: 'default' | 'outline' | 'ghost'
  size?: 'default' | 'sm' | 'lg'
  className?: string
}

/**
 * SubmitButton — botón de submit con estados honestos (F1 2026-07-04).
 *
 * ANTES mentía: inferia "Guardado ✓" de pending→false, mostrando éxito aunque
 * la server action hubiera fallado (falso verde en 11 pantallas).
 *
 * AHORA:
 * - Dentro de <ActionResultForm>: muestra "Guardado" SOLO si la action
 *   devolvió ok:true (el error lo surfacea el toast del form).
 * - En un <form> sin canal de resultado: pending → idle, sin afirmar éxito
 *   que no puede verificar.
 */
export function SubmitButton({
  children,
  pendingText = 'Guardando...',
  savedText = 'Guardado',
  variant = 'default',
  size = 'sm',
  className,
}: Props) {
  const { pending } = useFormStatus()
  const resultStatus = useActionResultStatus() // null = sin canal
  const [saved, setSaved] = useState(false)
  const prevPending = useRef(false)

  useEffect(() => {
    // Éxito confirmado: terminó el submit Y la action reportó ok.
    if (prevPending.current && !pending && resultStatus === 'ok') {
      setSaved(true)
      const t = setTimeout(() => setSaved(false), 2500)
      prevPending.current = pending
      return () => clearTimeout(t)
    }
    prevPending.current = pending
  }, [pending, resultStatus])

  return (
    <Button type="submit" size={size} variant={variant}
      disabled={pending} className={className}>
      {pending
        ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />{pendingText}</>
        : saved
          ? <><Check className="h-3.5 w-3.5 mr-1.5 text-success-fg" />{savedText}</>
          : children}
    </Button>
  )
}
