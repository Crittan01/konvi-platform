'use client'

import { useState, useTransition } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter,
} from '@/components/ui/dialog'
import { Loader2 } from 'lucide-react'

const ROLE_LABELS: Record<string, string> = {
  manager:  'Supervisor',
  operator: 'Gestor',
}

interface Props {
  userId:      string
  memberEmail: string
  currentRole: string
  action:      (formData: FormData) => Promise<void>
}

export default function ChangeRoleButton({ userId, memberEmail, currentRole, action }: Props) {
  const [selectedRole, setSelectedRole] = useState(
    currentRole === 'owner' ? 'manager' : currentRole
  )
  const [open, setOpen]              = useState(false)
  const [isPending, startTransition] = useTransition()

  const handleConfirm = () => {
    const fd = new FormData()
    fd.set('user_id', userId)
    fd.set('role', selectedRole)
    startTransition(async () => {
      await action(fd)
      setOpen(false)
    })
  }

  return (
    <>
      <div className="flex items-center gap-1.5">
        <select
          value={selectedRole}
          onChange={e => setSelectedRole(e.target.value)}
          className="text-xs rounded-lg border border-input bg-background px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="manager">Supervisor</option>
          <option value="operator">Gestor</option>
        </select>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setOpen(true)}
          className="text-xs h-7 px-2.5"
        >
          Cambiar
        </Button>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>¿Cambiar rol?</DialogTitle>
            <DialogDescription className="pt-1 space-y-1">
              <span>
                Se cambiará el rol de <span className="font-medium text-foreground">{memberEmail}</span>{' '}
                a <span className="font-medium text-foreground">{ROLE_LABELS[selectedRole] ?? selectedRole}</span>.
              </span>
              <span className="block text-amber-400/90 text-xs">
                La sesión activa de este miembro se cerrará y deberá iniciar sesión de nuevo para obtener el nuevo rol.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" size="sm" onClick={() => setOpen(false)} disabled={isPending}>
              Cancelar
            </Button>
            <Button size="sm" onClick={handleConfirm} disabled={isPending}>
              {isPending
                ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Cambiando...</>
                : 'Confirmar cambio'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
