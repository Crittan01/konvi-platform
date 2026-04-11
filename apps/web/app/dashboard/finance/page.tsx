import { DollarSign, ArrowRight, CheckCircle2, TrendingUp, PieChart, Bot, CreditCard, Receipt, Building2, BarChart2 } from 'lucide-react'

const FEATURES = [
  { icon: TrendingUp, label: 'Seguimiento de ingresos (Ventas) y egresos (Compras, Gastos logísticos)' },
  { icon: PieChart, label: 'Cálculo de rentabilidad por producto, categoría y canal' },
  { icon: Bot, label: 'IA: Análisis de salud financiera y alertas de márgenes decrecientes' },
  { icon: CreditCard, label: 'Conciliación de cobros de Mercado Libre y pasarelas de pago' },
  { icon: Receipt, label: 'Control de gastos fijos y variables recurrentes' },
  { icon: Building2, label: 'Múltiples cajas y cuentas bancarias' },
]

export default function FinancePage() {
  return (
    <div className="space-y-6 max-w-3xl">

      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <h1 className="text-xl sm:text-2xl font-bold flex items-center gap-2 text-foreground">
            <DollarSign className="h-5 w-5 text-primary" /> Finanzas
          </h1>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-400">
            En desarrollo
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Control total sobre la rentabilidad, gastos e ingresos de tu e-commerce.
        </p>
      </div>

      <div className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/5 to-background p-6">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-emerald-500/15 border border-emerald-500/25 flex items-center justify-center shrink-0">
            <TrendingUp className="h-6 w-6 text-emerald-500" />
          </div>
          <div>
            <p className="font-semibold text-foreground">Conoce tu margen neto real con precisión.</p>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              Vender no siempre significa ganar. Este módulo cruzará tus ventas (ingresos) con tus compras,
              envíos y devoluciones (egresos) para calcular la rentabilidad precisa de cada SKU,
              mientras la IA te alerta sobre productos no rentables o tendencias a la baja.
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
        <p className="text-sm font-semibold mb-3">Mientras tanto, mide tu desempeño de ingresos en:</p>
        <a href="/dashboard/metrics"
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-muted/50 transition-colors group">
          <BarChart2 className="h-5 w-5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground group-hover:text-foreground flex-1">Ver panel de analítica de ventas históricas</span>
          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-primary transition-all group-hover:translate-x-0.5" />
        </a>
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
        <span>Planificado para Fase 12.3 · impacto financiero transversal</span>
      </div>
    </div>
  )
}
