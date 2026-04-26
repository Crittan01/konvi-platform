'use client'

import { useState, useTransition } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter,
} from '@/components/ui/dialog'
import { Loader2, PauseCircle } from 'lucide-react'

interface Props {
  userId:      string
  memberEmail: string
  action:      (formData: FormData) => Promise<void>
}

export default function InactivateMemberButton({ userId, memberEmail, action }: Props) {
  const [open, setOpen]              = useState(false)
  const [reason, setReason]          = useState('')
  const [isPending, startTransition] = useTransition()

  const handleConfirm = () => {
    const fd = new FormData()
    fd.set('user_id', userId)
    if (reason.trim()) fd.set('reason', reason.trim())
    startTransition(async () => {
      await action(fd)
      setOpen(false)
    })
  }

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => setOpen(true)}
        className="text-xs h-7 px-2.5 text-amber-400 border-amber-500/30 hover:bg-amber-500/10"
      >
        <PauseCircle className="h-3 w-3 mr-1" />
        Inactivar
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>¿Inactivar miembro?</DialogTitle>
            <DialogDescription className="pt-1">
              <span className="font-medium text-foreground">{memberEmail}</span> perderá acceso inmediatamente.
              Puedes activarlo de nuevo cuando sea necesario.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-1.5">
            <Label className="text-xs">
              Motivo <span className="text-muted-foreground font-normal">(opcional)</span>
            </Label>
            <Input
              value={reason}
              onChange={e => setReason(e.target.value)}
              placeholder="ej: vacaciones, baja temporal, proyecto finalizado…"
              className="h-9 text-xs"
            />
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" size="sm" onClick={() => setOpen(false)} disabled={isPending}>
              Cancelar
            </Button>
            <Button
              size="sm"
              className="bg-amber-500 hover:bg-amber-400 text-white"
              onClick={handleConfirm}
              disabled={isPending}
            >
              {isPending
                ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Inactivando...</>
                : 'Sí, inactivar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
