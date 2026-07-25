import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-hidden focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
        outline: "text-foreground",
        // F1 2026-07-04: success/warning con contraste AA real (antes
        // bg-green-500/yellow-500 + text-white ≈ 2.3:1/2.0:1) y dentro de la
        // paleta del tema (emerald/amber, no green/yellow stock). Patrón wash
        // claro + texto 800: legible sobre el canvas crema.
        success:
          "border-emerald-700/25 bg-emerald-500/10 text-emerald-800",
        warning:
          "border-amber-700/25 bg-amber-500/10 text-amber-800",
        // Chips de estado neutros (para roles, estados de pedido, etc.)
        info: "border-primary/25 bg-primary/5 text-primary",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
