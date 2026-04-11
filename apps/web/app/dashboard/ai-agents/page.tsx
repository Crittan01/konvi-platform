import { Bot, ArrowRight, CheckCircle2, Brain, SlidersHorizontal, BarChart3, Wrench, ShieldCheck, Speech, BrainCircuit, Library } from 'lucide-react'

const FEATURES = [
  { icon: Brain, label: 'Gestión de prompts maestros para el Agente Conversacional (WhatsApp)' },
  { icon: SlidersHorizontal, label: 'Ajuste de creatividad (temperature) y umbral de seguridad para takeover manual' },
  { icon: BarChart3, label: 'Monitor de desempeño de Agentes: eficacia y tasa de resolución' },
  { icon: Wrench, label: 'Asignación de "Skills" (ej: Cotizar Envíos, Crear Pedidos, Consultar Stock)' },
  { icon: ShieldCheck, label: 'Agente de Supervisión: validación de respuestas antes del despacho' },
  { icon: Speech, label: 'Configuración de tono y personalidad de marca' },
]

export default function AiAgentsPage() {
  return (
    <div className="space-y-6 max-w-3xl">

      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <h1 className="text-xl sm:text-2xl font-bold flex items-center gap-2 text-foreground">
            <Bot className="h-5 w-5 text-primary" /> Agentes IA
          </h1>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-400">
            En desarrollo
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Configura y entrena la inteligencia que atiende y gestiona tu negocio autónomamente.
        </p>
      </div>

      <div className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/5 to-background p-6">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-purple-500/15 border border-purple-500/25 flex items-center justify-center shrink-0">
            <BrainCircuit className="h-6 w-6 text-purple-500" />
          </div>
          <div>
            <p className="font-semibold text-foreground">Tu fuerza laboral digital, a tu medida.</p>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              El Orchestrator actual ya procesa intenciones y transacciona con tus clientes (Fase 1-7).
              Este módulo será la interfaz gráfica (GUI) que te permitirá ajustar el comportamiento fino del bot:
              sus directrices, su capacidad para ejecutar acciones (Skills) y su tono, sin tocar una línea de código.
            </p>
          </div>
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">
          Funcionalidades planificadas
        </p>
        <div className="space-y-2">
          {FEATURES.map(f => (
            <div key={f.label} className="flex items-center gap-3 rounded-lg border border-border bg-muted/20 px-4 py-3">
              <f.icon className="h-5 w-5 text-muted-foreground shrink-0" />
              <p className="text-sm text-muted-foreground">{f.label}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-sm font-semibold mb-3">Mientras tanto, alimenta el contexto actual de la IA en:</p>
        <a href="/dashboard/knowledge-base"
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-muted/50 transition-colors group">
          <Library className="h-5 w-5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground group-hover:text-foreground flex-1">Gestionar documentos de la Base de Conocimiento</span>
          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-primary transition-all group-hover:translate-x-0.5" />
        </a>
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
        <span>Planificado para Fase 14 · evolución del Orchestrator Core</span>
      </div>
    </div>
  )
}
