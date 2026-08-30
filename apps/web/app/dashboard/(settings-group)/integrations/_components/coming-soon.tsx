/**
 * Placeholder visual para tabs aún no implementadas.
 */
import { Sparkles } from 'lucide-react'

type Props = {
  title: string
  description: string
  /** Semana del roadmap donde se entrega — informativo. */
  eta?: string
}

export default function ComingSoon({ title, description, eta }: Props) {
  return (
    <div className="rounded-xl border border-warning-border bg-warning-bg p-6 space-y-3">
      <div className="flex items-start gap-3">
        <Sparkles className="h-5 w-5 text-warning-fg mt-0.5 shrink-0" />
        <div className="space-y-1">
          <h3 className="font-semibold text-warning-fg">{title}</h3>
          <p className="text-sm text-warning-fg/80">{description}</p>
          {eta && (
            <p className="text-xs text-warning-fg/70 italic">Disponible {eta}.</p>
          )}
        </div>
      </div>
    </div>
  )
}
