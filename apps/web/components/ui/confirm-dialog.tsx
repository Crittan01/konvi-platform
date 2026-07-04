'use client'

import { createContext, useCallback, useContext, useRef, useState, ReactNode } from 'react'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

/**
 * ConfirmDialog — confirmación del DS (F1 2026-07-04).
 *
 * Reemplaza los 34 `confirm()` nativos del browser: el diálogo nativo no es
 * estilizable, sus botones OK/Cancelar los renderiza el navegador (a veces en
 * inglés) y bloquea el hilo. Este patrón es promise-based para que el sweep
 * sea drop-in:
 *
 *   const confirmar = useConfirm()
 *   if (!(await confirmar({ title: '¿Eliminar producto?',
 *                           description: 'Esta acción no se puede deshacer.',
 *                           confirmLabel: 'Eliminar', destructive: true }))) return
 *
 * Requiere <ConfirmProvider> (montado en el root layout).
 */
export interface ConfirmOptions {
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>

const ConfirmContext = createContext<ConfirmFn | null>(null)

export function useConfirm(): ConfirmFn {
  const fn = useContext(ConfirmContext)
  if (!fn) throw new Error('useConfirm requiere <ConfirmProvider> en el árbol (root layout).')
  return fn
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null)
  const resolver = useRef<((v: boolean) => void) | null>(null)

  const confirm = useCallback<ConfirmFn>((o) => {
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve
      setOpts(o)
    })
  }, [])

  const close = (value: boolean) => {
    resolver.current?.(value)
    resolver.current = null
    setOpts(null)
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={opts !== null} onOpenChange={(open) => { if (!open) close(false) }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{opts?.title}</DialogTitle>
            {opts?.description && <DialogDescription>{opts.description}</DialogDescription>}
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => close(false)}>
              {opts?.cancelLabel ?? 'Cancelar'}
            </Button>
            <Button
              type="button"
              size="sm"
              variant={opts?.destructive ? 'destructive' : 'default'}
              onClick={() => close(true)}
            >
              {opts?.confirmLabel ?? 'Confirmar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ConfirmContext.Provider>
  )
}
