'use client'

import { useState, useTransition } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter,
} from '@/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Loader2 } from 'lucide-react'

interface Props {
  userId:      string
  memberEmail: string
  action:      (formData: FormData) => Promise<void>
}

export default function RemoveMemberButton({ userId, memberEmail, action }: Props) {
  const [open, setOpen]          = useState(false)
  const [isPending, startTransition] = useTransition()

  const handleConfirm = () => {
    const fd = new FormData()
    fd.set('user_id', userId)
    startTransition(async () => {
      await action(fd)
      setOpen(false)
    })
  }

  return (
    <>
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setOpen(true)}
              className="text-xs h-7 px-2 text-destructive hover:bg-destructive/10"
            >
              Eliminar
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Quita al miembro del equipo de forma permanente. No es reversible: para volver a darle acceso tendrás que invitarlo de nuevo. ¿Es temporal? Usa &quot;Inactivar&quot;.
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>¿Eliminar miembro?</DialogTitle>
            <DialogDescription className="pt-1">
              Se eliminará <span className="font-medium text-foreground">{memberEmail}</span> del
              equipo. El usuario perderá acceso de inmediato y esta acción no se puede deshacer.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" size="sm" onClick={() => setOpen(false)} disabled={isPending}>
              Cancelar
            </Button>
            <Button variant="destructive" size="sm" onClick={handleConfirm} disabled={isPending}>
              {isPending
                ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Eliminando...</>
                : 'Sí, eliminar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
