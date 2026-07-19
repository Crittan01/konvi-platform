'use client'

import { Download } from 'lucide-react'
import { useEffect, useState } from 'react'

// `beforeinstallprompt` no está tipado en el lib estándar de TS.
type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

/**
 * Botón "Instalar" — aparece SOLO cuando el navegador ofrece la instalación
 * (evento beforeinstallprompt) y se oculta tras instalar. Pensado para el topbar.
 */
export function InstallButton() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null)

  useEffect(() => {
    const onPrompt = (e: Event) => {
      e.preventDefault()
      setDeferred(e as BeforeInstallPromptEvent)
    }
    const onInstalled = () => setDeferred(null)
    window.addEventListener('beforeinstallprompt', onPrompt)
    window.addEventListener('appinstalled', onInstalled)
    return () => {
      window.removeEventListener('beforeinstallprompt', onPrompt)
      window.removeEventListener('appinstalled', onInstalled)
    }
  }, [])

  if (!deferred) return null

  return (
    <button
      type="button"
      onClick={async () => {
        await deferred.prompt()
        try {
          await deferred.userChoice
        } finally {
          setDeferred(null)
        }
      }}
      title="Instalar Konvi como app"
      className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs opacity-90 transition-colors hover:bg-white/10 hover:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current"
    >
      <Download className="h-4 w-4" />
      <span className="hidden sm:inline">Instalar</span>
    </button>
  )
}
