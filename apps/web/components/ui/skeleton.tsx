import { cn } from "@/lib/utils"

/** Skeleton — primitivo del DS (F1 2026-07-04). Para loading states. */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />
}

export { Skeleton }
