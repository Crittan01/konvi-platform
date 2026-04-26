'use client'

import { useState, useTransition } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter,
} from '@/components/ui/dialog'
import { AlertTriangle, Loader2 } from 'lucide-react'

const WARNINGS: Record<string, string> = {
  whatsapp: 'El bot dejará de responder a los clientes de inmediato. Los mensajes entrantes quedarán sin atención hasta reconectar.',
  envia:    'No podrás cotizar ni generar guías de envío hasta reconectar la integración.',
  mercadolibre: 'Las publicaciones y órdenes de Mercado Libre dejarán de sincronizarse con la plataforma.',
  telegram: 'Las alertas de escalamiento ya no llegarán al asesor por Telegram.',
}

interface Props {
  provider:      string
  providerLabel: string
  action:        () => Promise<void>
  className?:    string
  children?:     React.ReactNode
}

export function DisconnectIntegrationButton({
  provider, providerLabel, action, className, children,
}: Props) {
  const [open, setOpen]              = useState(false)
  const [isPending, startTransition] = useTransition()

  const handleConfirm = () => {
    startTransition(async () => {
      await action()
      setOpen(false)
    })
  }

  const warning = WARNINGS[provider] ?? `La integración con ${providerLabel} se desactivará.`

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => setOpen(true)}
        className={className}
      >
        {children ?? `Desconectar ${providerLabel}`}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
              ¿Desconectar {providerLabel}?
            </DialogTitle>
            <DialogDescription className="pt-1 text-sm">
              {warning}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" size="sm" onClick={() => setOpen(false)} disabled={isPending}>
              Cancelar
            </Button>
            <Button variant="destructive" size="sm" onClick={handleConfirm} disabled={isPending}>
              {isPending
                ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Desconectando...</>
                : 'Sí, desconectar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
