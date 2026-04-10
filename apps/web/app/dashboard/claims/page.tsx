import { createClient } from '@/utils/supabase/server'
import {
  AlertCircle, ArrowRight, CheckCircle2, Clock,
  MessageSquare, ShoppingCart, TrendingDown,
} from 'lucide-react'

const FEATURES = [
  { icon: '📋', label: 'Registro de reclamos MeLi y WhatsApp en un solo lugar' },
  { icon: '⚡', label: 'Clasificación automática por IA: devolución, daño, demora, fraude' },
  { icon: '📊', label: 'Dashboard de tasa de reclamos por categoría y producto' },
  { icon: '🤖', label: 'Respuestas sugeridas por IA basadas en tu política de devoluciones (KB)' },
  { icon: '🔔', label: 'Alertas automáticas antes del vencimiento del plazo MeLi' },
  { icon: '💰', label: 'Cálculo de impacto financiero por reclamo' },
]

export default async function ClaimsPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const role = ((user?.app_metadata ?? {}) as { role?: string }).role ?? 'agent'

  void role // future RBAC

  return (
    <div className="space-y-6 max-w-3xl">

      {/* Header */}
      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-primary" /> Reclamos
          </h1>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-400">
            En desarrollo
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Gestiona disputas de clientes y en Mercado Libre con apoyo de IA.
        </p>
      </div>

      {/* Vision card */}
      <div className="rounded-xl border border-primary/20 bg-gradient-to-br from-primary/5 to-background p-6">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-primary/15 border border-primary/25 flex items-center justify-center shrink-0">
            <AlertCircle className="h-6 w-6 text-primary" />
          </div>
          <div>
            <p className="font-semibold text-foreground">¿Por qué importan los reclamos?</p>
            <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
              Un reclamo mal gestionado en MeLi puede afectar tu reputación, pausar tus publicaciones
              y perderte posición en el ranking. Este módulo centraliza todos los reclamos y usa IA para
              sugerirte la mejor respuesta según tu historial y políticas.
            </p>
          </div>
        </div>
      </div>

      {/* Features list */}
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

      {/* Mientras tanto */}
      <div className="rounded-xl border border-border bg-card p-5">
        <p className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Clock className="h-4 w-4 text-muted-foreground" /> Mientras tanto puedes...
        </p>
        <div className="space-y-2">
          {[
            { href: '/dashboard/inbox', icon: MessageSquare, text: 'Gestionar conversaciones de reclamo vía Inbox WhatsApp' },
            { href: '/dashboard/orders', icon: ShoppingCart, text: 'Revisar el estado de los pedidos relacionados' },
            { href: '/dashboard/metrics', icon: TrendingDown, text: 'Ver métricas de órdenes canceladas en Analítica' },
          ].map(item => (
            <a key={item.href} href={item.href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-muted/50 transition-colors group">
              <item.icon className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
              <span className="text-sm text-muted-foreground group-hover:text-foreground transition-colors flex-1">{item.text}</span>
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-primary transition-all group-hover:translate-x-0.5" />
            </a>
          ))}
        </div>
      </div>

      {/* Status */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
        <span>Planificado para Fase 12 · sujeto a decisión OQ-P01 sobre canal de reclamos</span>
      </div>
    </div>
  )
}
