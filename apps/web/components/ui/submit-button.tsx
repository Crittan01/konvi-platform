'use client'

import { useFormStatus } from 'react-dom'
import { Button } from '@/components/ui/button'
import { Loader2, Check } from 'lucide-react'
import { useState, useEffect, useRef } from 'react'

interface Props {
  children: React.ReactNode
  pendingText?: string
  savedText?: string
  variant?: 'default' | 'outline' | 'ghost'
  size?: 'default' | 'sm' | 'lg'
  className?: string
}

export function SubmitButton({
  children,
  pendingText = 'Guardando...',
  savedText = 'Guardado',
  variant = 'default',
  size = 'sm',
  className,
}: Props) {
  const { pending } = useFormStatus()
  const [saved, setSaved] = useState(false)
  const prevPending = useRef(false)

  useEffect(() => {
    // Cuando pasa de pending→false detectamos que terminó
    if (prevPending.current && !pending) {
      setSaved(true)
      const t = setTimeout(() => setSaved(false), 2500)
      return () => clearTimeout(t)
    }
    prevPending.current = pending
  }, [pending])

  return (
    <Button type="submit" size={size} variant={variant}
      disabled={pending} className={className}>
      {pending
        ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />{pendingText}</>
        : saved
          ? <><Check className="h-3.5 w-3.5 mr-1.5 text-emerald-400" />{savedText}</>
          : children}
    </Button>
  )
}
