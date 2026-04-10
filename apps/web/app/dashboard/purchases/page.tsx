import { ClipboardList, ArrowRight, CheckCircle2 } from 'lucide-react'

const FEATURES = [
  { icon: '📦', label: 'Gestión de proveedores y catálogos de compra' },
  { icon: '📝', label: 'Creación y seguimiento de Órdenes de Compra (OC)' },
  { icon: '🤖', label: 'Agente IA: predicción de quiebre de stock y sugerencias de recompra' },
  { icon: '📅', label: 'Cálculo de lead time automático por proveedor' },
  { icon: '✅', label: 'Recepción total o parcial contra de órdenes de compra' },
  { icon: '📈', label: 'Actualización automática del costo promedio ponderado' },
]

export default function PurchasesPage() {
  return (
    <div className="space-y-6 max-w-3xl">

      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <h1 className="text-xl sm:text-2xl font-bold flex items-center gap-2 text-foreground">
            <ClipboardList className="h-5 w-5 text-primary" /> Compras
          </h1>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-400">
            En desarrollo
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Control de proveedores, abastecimiento y sugerencias de recompra potenciadas por IA.
        </p>
      </div>

      <div className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/5 to-background p-6">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-blue-500/15 border border-blue-500/25 flex items-center justify-center shrink-0 text-2xl">
            🤝
          </div>
          <div>
            <p className="font-semibold text-foreground">No te quedes sin stock. Recompra antes del quiebre.</p>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              El módulo de compras cerrará el ciclo del e-commerce. La IA analizará tu ritmo de ventas y el lead time de
              tus proveedores para sugerirte qué, cuánto y cuándo comprar, automatizando la creación de la Orden de Compra.
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
              <span className="text-lg shrink-0">{f.icon}</span>
              <p className="text-sm text-muted-foreground">{f.label}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-sm font-semibold mb-3">Mientras tanto, controla tu stock en:</p>
        <a href="/dashboard/inventory"
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-muted/50 transition-colors group">
          <span className="text-lg">📦</span>
          <span className="text-sm text-muted-foreground group-hover:text-foreground flex-1">Ajustar inventario y umbrales de alerta manuales</span>
          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-primary transition-all group-hover:translate-x-0.5" />
        </a>
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
        <span>Planificado para Fase 12.2 · integrado con Inventario</span>
      </div>
    </div>
  )
}
