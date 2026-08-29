'use client'

// T7.10 — Despedida de logout: ejecuta el signOut (server action) mostrando un
// beat de marca breve y redirige al login. Best-effort: si el signOut falla,
// igual se redirige (las cookies mueren al expirar; la UI nunca se queda
// atrapada en la pantalla de despedida).

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'

interface Props {
  action: () => Promise<void>
}

// Beat de marca mínimo para que la despedida se perciba (no retrasa la tarea:
// es el momento de cierre, no un gate operativo).
const FAREWELL_MIN_MS = 800

export default function LogoutFarewell({ action }: Props) {
  const router = useRouter()
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    const run = async () => {
      const minBeat = new Promise(resolve => setTimeout(resolve, FAREWELL_MIN_MS))
      try {
        await Promise.all([action(), minBeat])
      } catch {
        // best-effort: redirect igual (ver docstring del módulo)
        await minBeat
      }
      router.replace('/login')
    }
    run()
  }, [action, router])

  return (
    <Card className="dark border-white/10 bg-card/75 backdrop-blur-xl shadow-2xl">
      <CardContent className="pt-6 pb-6 flex flex-col items-center gap-3 text-center">
        <p className="text-sm text-muted-foreground flex items-center gap-2" role="status" aria-live="polite">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Cerrando tu sesión de forma segura…
        </p>
      </CardContent>
    </Card>
  )
}
