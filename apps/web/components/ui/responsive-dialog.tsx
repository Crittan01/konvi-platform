'use client'

import * as React from 'react'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Drawer, DrawerContent, DrawerDescription, DrawerFooter, DrawerHeader, DrawerTitle,
} from '@/components/ui/drawer'
import { useMediaQuery } from '@/lib/use-media-query'

/**
 * ResponsiveDialog — una acción, dos presentaciones (Spec WOW §4.4):
 * en ≥ lg se comporta como el Dialog actual del DS; en < lg es un bottom-sheet
 * nativo (vaul) con drag-to-dismiss y handle. Mismo contenido, mismo contrato.
 *
 * Es la presentación para "acciones rápidas" móviles (ajuste de stock, cambio
 * de estado de pedido) que en pantalla pequeña no deben ser modales centrados.
 * No reemplaza al ConfirmDialog global (21 consumidores): los flujos que lo
 * adoptan lo hacen de forma explícita y acotada.
 */
interface ResponsiveDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: React.ReactNode
  description?: React.ReactNode
  /** Cuerpo (formularios, contenido del flujo). */
  children?: React.ReactNode
  /** Acciones (botones confirmar/cancelar). */
  footer?: React.ReactNode
  /** className extra para el contenedor (DialogContent / DrawerContent). */
  className?: string
}

export function ResponsiveDialog({
  open, onOpenChange, title, description, children, footer, className,
}: ResponsiveDialogProps) {
  const isDesktop = useMediaQuery('(min-width: 1024px)')

  if (isDesktop) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className={className ?? 'sm:max-w-md'}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description && <DialogDescription>{description}</DialogDescription>}
          </DialogHeader>
          {children}
          {footer && <DialogFooter className="gap-2 sm:gap-2">{footer}</DialogFooter>}
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent className={className}>
        <DrawerHeader className="text-left">
          <DrawerTitle>{title}</DrawerTitle>
          {description && <DrawerDescription>{description}</DrawerDescription>}
        </DrawerHeader>
        {children && <div className="px-4 pb-2 overflow-y-auto">{children}</div>}
        {footer && <DrawerFooter>{footer}</DrawerFooter>}
      </DrawerContent>
    </Drawer>
  )
}
