import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

// EmptyState — estado vacío compartido del DS (Kaiu). Referencia de estilo:
// el <EmptyState> local de finance-dashboard (borde dashed + icono muted +
// título + descripción). `plain` es para vacíos que viven dentro de una Card
// o panel ya enmarcado (audit, inbox list) y no deben doblar el borde.
// Pulido WOW (frente 2): pop de entrada una vez (`empty-state-pop`) + halo
// radial estático tras el icono + flotación lenta (`icon-float`). Ambas
// animaciones son UTILITIES CSS del DS (globals.css) y no framer-motion a
// propósito: EmptyState se usa desde server components (audit, media) y así
// el módulo sigue server-safe — cero frontera client, hidratación trivial y
// reduced-motion por media query (mismo patrón que card-hover, §4.1).
const emptyStateVariants = cva(
  "flex flex-col items-center justify-center text-center",
  {
    variants: {
      variant: {
        default: "rounded-xl border border-dashed border-border px-6 py-12",
        plain: "",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface EmptyStateProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title">,
    VariantProps<typeof emptyStateVariants> {
  icon?: LucideIcon
  title?: React.ReactNode
  description?: React.ReactNode
  /** CTA opcional (botón, link…) renderizado bajo la descripción. */
  action?: React.ReactNode
}

function EmptyState({
  className,
  variant,
  icon: Icon,
  title,
  description,
  action,
  ...props
}: EmptyStateProps) {
  return (
    <div className={cn(emptyStateVariants({ variant }), "empty-state-pop", className)} {...props}>
      {Icon && (
        <div className="relative mb-3">
          {/* Halo radial estático detrás del icono (pulido WOW frente 2). */}
          <div aria-hidden className="absolute inset-0 -m-2 rounded-full bg-primary/10 blur-lg" />
          <Icon className="icon-float relative h-10 w-10 text-muted-foreground/40" aria-hidden />
        </div>
      )}
      {title && <p className="text-sm font-medium text-foreground">{title}</p>}
      {description && (
        <p className={cn("text-sm text-muted-foreground max-w-md", title && "mt-1")}>
          {description}
        </p>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

export { EmptyState, emptyStateVariants }
