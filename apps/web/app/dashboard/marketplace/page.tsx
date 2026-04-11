import { Store, ArrowRight, CheckCircle2, ShoppingBag, Target, LineChart, Bot, Image as ImageIcon, AlertTriangle, Ruler, RefreshCw, ShoppingCart, Link as LinkIcon } from 'lucide-react'

const FEATURES = [
  { icon: ShoppingBag, label: 'Gestión de publicaciones MeLi: crear, editar, pausar, activar' },
  { icon: Target, label: 'Central de ofertas: descuentos y campañas de precio' },
  { icon: LineChart, label: 'Reglas automáticas de precio y stock sincronizado con tu inventario' },
  { icon: Bot, label: 'Agente IA: optimizador de títulos, descripción y keywords' },
  { icon: ImageIcon, label: 'Gestión de fotos desde tu galería Media' },
  { icon: AlertTriangle, label: 'Monitor de infracciones y moderación MeLi' },
  { icon: Ruler, label: 'Guías de talles y atributos por categoría MeLi' },
  { icon: RefreshCw, label: 'Sync bidireccional: cambios en catálogo → actualización automática en MeLi' },
]

export default function MarketplacePage() {
  return (
    <div className="space-y-6 max-w-3xl">

      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <h1 className="text-xl sm:text-2xl font-bold flex items-center gap-2 text-foreground">
            <Store className="h-5 w-5 text-primary" /> Publicaciones
          </h1>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-400">
            En desarrollo
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Gestiona tus publicaciones en Mercado Libre directamente desde la consola, con ayuda de IA.
        </p>
      </div>

      <div className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/5 to-background p-6">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-yellow-400/15 border border-yellow-400/25 flex items-center justify-center shrink-0">
            <ShoppingCart className="h-6 w-6 text-yellow-500" />
          </div>
          <div>
            <p className="font-semibold text-foreground">MeLi conectado — gestión de listings próximamente</p>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              Tu cuenta de Mercado Libre ya está autenticada (OAuth 2.0). Este módulo te permitirá
              crear y actualizar publicaciones, gestionar precios y stock, y optimizar tus listings
              con IA para mejorar CTR y conversión — todo sin salir de la consola.
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
        <p className="text-sm font-semibold mb-3">Mientras tanto, tu integración MeLi está activa en:</p>
        <a href="/dashboard/integrations"
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-muted/50 transition-colors group">
          <LinkIcon className="h-5 w-5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground group-hover:text-foreground flex-1">Ver estado de integración Mercado Libre</span>
          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-primary transition-all group-hover:translate-x-0.5" />
        </a>
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
        <span>Planificado para Fase 13 · requiere MeLi API v2 listings endpoints</span>
      </div>
    </div>
  )
}
