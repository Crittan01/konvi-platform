'use client'

import { CheckCircle2, XCircle, AlertCircle, HelpCircle } from 'lucide-react'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'

// Rev. 71 — Lista de defaults conocidos. Si el nombre del agente coincide con
// cualquiera de estos, el check considera "no personalizado". Cubre el default
// histórico ('Bot Asistente') y el default real de DB ('Vendedor Oficial',
// migración 20260412000000_ai_agents_and_vectors.sql).
const DEFAULT_AGENT_NAMES = new Set(['Bot Asistente', 'Vendedor Oficial'])

interface ReadinessItem {
  label: string
  ok: boolean
  detail?: string
  tooltip?: string
  link?: string
}

interface Props {
  // Identidad y comportamiento (existentes)
  hasFilosofia:  boolean
  totalDocs:     number
  activeDocs:    number
  indexedDocs:   number
  agentName:     string
  hasPrompt:     boolean
  // Rev. 68 — fuentes adicionales que el bot consume
  hasTono?:           boolean
  hasSedesHorario?:   boolean
  hasCatalog?:        boolean
  wompiConnected?:    boolean
  aveonlineConnected?: boolean
  // Rev. 71 — checks ampliados a 10
  hasIdentidadLegal?: boolean   // NIT / email_contacto / telefono_contacto
  kbCriticalCoverage?: {
    politicas: number  // # docs activos
    envios:    number
    pagos:     number
  }
}

export function ReadinessCard({
  hasFilosofia, activeDocs, indexedDocs, agentName, hasPrompt,
  hasTono = false, hasSedesHorario = false, hasCatalog = false,
  wompiConnected = false, aveonlineConnected = false,
  hasIdentidadLegal = false,
  kbCriticalCoverage = { politicas: 0, envios: 0, pagos: 0 },
}: Props) {
  const criticalEmpty = (['politicas', 'envios', 'pagos'] as const).filter(
    k => kbCriticalCoverage[k] === 0
  )
  const items: ReadinessItem[] = [
    {
      label: 'Identidad del negocio',
      ok: hasFilosofia,
      detail: hasFilosofia ? 'Misión / visión / valores configurados' : 'Sin configurar',
      tooltip: 'El bot habla con coherencia de marca usando tu Filosofía configurada (se inyecta automáticamente al system prompt).',
      link: hasFilosofia ? undefined : '/dashboard/settings#section-filosofia',
    },
    {
      label: 'Tono de comunicación',
      ok: hasTono,
      detail: hasTono ? 'Configurado (formal/amigable/cercano/etc.)' : 'Sin configurar — el bot usa tono "amigable" por defecto',
      tooltip: 'El bot adapta su lenguaje al tono que elegiste. Si no configuras uno, usa "amigable" por defecto.',
      link: hasTono ? undefined : '/dashboard/settings#section-filosofia',
    },
    {
      label: 'Sedes y horario',
      ok: hasSedesHorario,
      detail: hasSedesHorario ? 'Sedes y horario de atención configurados' : 'Sin configurar',
      tooltip: 'El bot responde dónde estás y cuándo atiendes. Configura al menos una sede o el origen de despacho + el horario.',
      link: hasSedesHorario ? undefined : '/dashboard/settings#section-presencia',
    },
    {
      label: 'Catálogo de productos',
      ok: hasCatalog,
      detail: hasCatalog ? 'Hay productos activos con stock' : 'Sin productos activos — el bot no puede vender',
      tooltip: 'El bot consulta tu catálogo en tiempo real para dar precios reales y stock disponible (nunca alucina).',
      link: hasCatalog ? undefined : '/dashboard/catalog',
    },
    {
      label: 'Knowledge Base',
      ok: activeDocs > 0,
      detail: activeDocs > 0
        ? `${activeDocs} documento${activeDocs !== 1 ? 's' : ''} activo${activeDocs !== 1 ? 's' : ''}`
        : 'KB vacío — el bot no tiene políticas, envíos ni pagos',
      tooltip: 'El bot busca semánticamente en tu KB respuestas que no están en catálogo. Llena al menos las categorías Políticas, Envíos y Pagos.',
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
      tooltip: 'Cada documento KB se convierte en un vector de embeddings para que el bot lo encuentre por significado, no por palabras exactas.',
      link: indexedDocs < activeDocs ? '/dashboard/knowledge-base' : undefined,
    },
    {
      label: 'Agente IA — comportamiento',
      ok: hasPrompt && !DEFAULT_AGENT_NAMES.has(agentName),
      detail: hasPrompt && !DEFAULT_AGENT_NAMES.has(agentName)
        ? `"${agentName}" con directrices personalizadas`
        : 'Usando configuración por defecto',
      tooltip: 'Define cómo se comporta tu bot en ventas: nombre, qué ofrece primero, cómo cierra. La identidad del negocio (misión) va aparte en Configuración.',
      link: '/dashboard/ai-agents',
    },
    {
      label: 'Identidad legal del negocio',
      ok: hasIdentidadLegal,
      detail: hasIdentidadLegal
        ? 'NIT / email / teléfono corporativo configurados'
        : 'Faltan datos de identidad — el bot no podrá responder NIT, email o teléfono si el cliente lo pregunta',
      tooltip: 'NIT, email_contacto y telefono_contacto se inyectan al system prompt bajo guard "solo si el cliente lo pregunta". Sin ellos, el bot no tiene una verdad a la cual responder.',
      link: hasIdentidadLegal ? undefined : '/dashboard/settings#section-identidad',
    },
    {
      label: 'KB cobertura crítica (Políticas / Envíos / Pagos)',
      ok: criticalEmpty.length === 0,
      detail: criticalEmpty.length === 0
        ? 'Las 3 categorías críticas tienen al menos un documento'
        : `Faltan: ${criticalEmpty.join(', ')} — el bot escalará en vez de responder`,
      tooltip: 'Si un cliente pregunta sobre pagos/envíos/políticas y el KB no tiene documentos de esa categoría, el bot detecta el vacío y escala con cordialidad en vez de inventar (anti-alucinación rev. 71).',
      link: criticalEmpty.length === 0 ? undefined : '/dashboard/knowledge-base',
    },
    {
      label: 'Pasarela y courier',
      ok: wompiConnected && aveonlineConnected,
      detail: wompiConnected && aveonlineConnected
        ? 'Wompi y Aveonline conectados'
        : !wompiConnected && !aveonlineConnected
          ? 'Wompi y Aveonline sin conectar — el bot no puede generar links de pago ni cotizar envío'
          : !wompiConnected
            ? 'Falta conectar Wompi (links de pago)'
            : 'Falta conectar Aveonline (cotizar envío)',
      tooltip: 'El bot necesita Wompi para generar links de pago y Aveonline para cotizar envíos. Sin estos, el flujo conversacional se queda sin cierre transaccional.',
      link: '/dashboard/integrations',
    },
  ]

  const score = items.filter(i => i.ok).length
  const total = items.length
  const allOk = score === total

  return (
    <div className={`rounded-xl border p-5 space-y-3 ${
      allOk
        ? 'border-emerald-700/25 bg-emerald-500/5'
        : score >= 2
          ? 'border-amber-700/25 bg-amber-500/5'
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
          allOk ? 'bg-emerald-500/15 text-emerald-700' : score >= 2 ? 'bg-amber-500/15 text-amber-700' : 'bg-muted text-muted-foreground'
        }`}>
          {score}/{total}
        </div>
      </div>

      {/* Tooltip primitivo del DS: accesible por teclado (focus) y touch
          (long-press), anuncia el contenido vía aria — reemplaza el `title=`
          nativo que era invisible en móvil y para lectores de pantalla. */}
      <TooltipProvider delayDuration={150}>
        <div className="space-y-1.5">
          {items.map(item => (
            <div key={item.label} className="flex items-center gap-2.5">
              {item.ok
                ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-700 shrink-0" />
                : score === 0 || !item.detail
                  ? <XCircle className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />
                  : <AlertCircle className="h-3.5 w-3.5 text-amber-700 shrink-0" />
              }
              <div className="flex-1 min-w-0 flex items-center gap-1">
                <span className="text-xs font-medium">{item.label}</span>
                {item.tooltip && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        aria-label={`Más información: ${item.label}`}
                        className="shrink-0 text-muted-foreground/60 hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring rounded-full"
                      >
                        <HelpCircle className="h-3 w-3" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs leading-relaxed">
                      {item.tooltip}
                    </TooltipContent>
                  </Tooltip>
                )}
                {item.detail && (
                  <span className="text-xs text-muted-foreground truncate"> — {item.detail}</span>
                )}
              </div>
              {item.link && (
                <a href={item.link}
                  className="text-[10px] text-primary underline underline-offset-2 shrink-0 hover:no-underline">
                  {item.ok ? 'Editar' : 'Configurar'}
                </a>
              )}
            </div>
          ))}
        </div>
      </TooltipProvider>
    </div>
  )
}
