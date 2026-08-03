import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

// EmptyState — estado vacío compartido del DS (Kaiu). Referencia de estilo:
// el <EmptyState> local de finance-dashboard (borde dashed + icono muted +
// título + descripción). `plain` es para vacíos que viven dentro de una Card
// o panel ya enmarcado (audit, inbox list) y no deben doblar el borde.
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
    <div className={cn(emptyStateVariants({ variant }), className)} {...props}>
      {Icon && (
        <Icon className="h-10 w-10 text-muted-foreground/40 mb-3" aria-hidden />
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
