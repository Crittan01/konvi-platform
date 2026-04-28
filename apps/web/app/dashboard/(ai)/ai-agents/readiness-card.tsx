import { CheckCircle2, XCircle, AlertCircle } from 'lucide-react'

interface ReadinessItem {
  label: string
  ok: boolean
  detail?: string
  link?: string
}

interface Props {
  hasFilosofia:  boolean
  totalDocs:     number
  activeDocs:    number
  indexedDocs:   number
  agentName:     string
  hasPrompt:     boolean
}

export function ReadinessCard({ hasFilosofia, totalDocs, activeDocs, indexedDocs, agentName, hasPrompt }: Props) {
  const items: ReadinessItem[] = [
    {
      label: 'Filosofía del negocio',
      ok: hasFilosofia,
      detail: hasFilosofia ? 'Configurada — el bot conoce tu marca' : 'Sin configurar',
      link: hasFilosofia ? undefined : '/dashboard/settings#section-filosofia',
    },
    {
      label: 'Documentos en KB',
      ok: activeDocs > 0,
      detail: activeDocs > 0
        ? `${activeDocs} documento${activeDocs !== 1 ? 's' : ''} activo${activeDocs !== 1 ? 's' : ''}`
        : 'KB vacío — el bot no tiene políticas ni FAQ',
      link: activeDocs > 0 ? undefined : '/dashboard/knowledge-base',
    },
    {
      label: 'Indexación para IA',
      ok: indexedDocs > 0 && indexedDocs === activeDocs,
      detail: indexedDocs === 0
        ? 'Ningún documento está listo para búsqueda semántica'
        : indexedDocs < activeDocs
          ? `${indexedDocs}/${activeDocs} documentos listos — activa los pendientes`
          : `${indexedDocs} documento${indexedDocs !== 1 ? 's' : ''} listo${indexedDocs !== 1 ? 's' : ''} para IA`,
      link: indexedDocs < activeDocs ? '/dashboard/knowledge-base' : undefined,
    },
    {
      label: 'Nombre y directrices del bot',
      ok: hasPrompt && agentName !== 'Bot Asistente',
      detail: hasPrompt && agentName !== 'Bot Asistente'
        ? `"${agentName}" configurado con directrices personalizadas`
        : 'Usando configuración por defecto',
    },
  ]

  const score = items.filter(i => i.ok).length
  const total = items.length
  const allOk = score === total

  return (
    <div className={`rounded-xl border p-5 space-y-3 ${
      allOk
        ? 'border-emerald-500/25 bg-emerald-500/5'
        : score >= 2
          ? 'border-amber-500/25 bg-amber-500/5'
          : 'border-border bg-muted/20'
    }`}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="font-semibold text-sm">Estado del bot</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {allOk
              ? 'El bot está completamente configurado y listo.'
              : `${score}/${total} pasos completados — completa los pendientes para mejores respuestas.`}
          </p>
        </div>
        <div className={`text-xs font-bold px-2.5 py-1 rounded-full ${
          allOk ? 'bg-emerald-500/15 text-emerald-400' : score >= 2 ? 'bg-amber-500/15 text-amber-400' : 'bg-muted text-muted-foreground'
        }`}>
          {score}/{total}
        </div>
      </div>

      <div className="space-y-1.5">
        {items.map(item => (
          <div key={item.label} className="flex items-center gap-2.5">
            {item.ok
              ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
              : score === 0 || !item.detail
                ? <XCircle className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />
                : <AlertCircle className="h-3.5 w-3.5 text-amber-400 shrink-0" />
            }
            <div className="flex-1 min-w-0">
              <span className="text-xs font-medium">{item.label}</span>
              {item.detail && (
                <span className="text-xs text-muted-foreground"> — {item.detail}</span>
              )}
            </div>
            {!item.ok && item.link && (
              <a href={item.link}
                className="text-[10px] text-primary underline underline-offset-2 shrink-0 hover:no-underline">
                Configurar
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
