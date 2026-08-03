'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { EmptyState } from '@/components/ui/empty-state'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'
import { XAxis, CartesianGrid, Tooltip as RTooltip, ResponsiveContainer, BarChart, Bar, Cell } from 'recharts'
import ExpensesManager from './expenses-manager'
import FinanceFilters from './finance-filters'
import { DollarSign, TrendingDown, TrendingUp, Activity, HelpCircle, AlertTriangle, Download, ExternalLink } from 'lucide-react'
import Link from 'next/link'
import type { PnlResult, ExpenseRow } from '../lib/pnl'
import { isReversed } from '../lib/pnl'
import type { FinanceRange } from '../lib/window'
import { formatCOP, formatCOPNegative, formatBogotaDate } from '../lib/format'

type Props = {
  pnl: PnlResult
  expenses: ExpenseRow[]
  range: FinanceRange
  windowLabel: string
  canWrite: boolean
  ordersCount: number
  truncated: boolean
  aggLimit: number
}

// Colores de las barras: tokens del tema (fondo claro Kaiu Cream), no literales
// oscuros. Grid/tooltip via CSS vars → coherente con el design system.
const BAR_COLORS: Record<string, string> = {
  Ingresos: 'hsl(var(--primary))',
  COGS: 'hsl(var(--amber))',
  OPEX: 'hsl(var(--chart-opex))',
  Beneficio: 'hsl(var(--chart-beneficio))',
}

export default function FinanceDashboard({
  pnl, expenses, range, windowLabel, canWrite, ordersCount, truncated, aggLimit,
}: Props) {
  const { revenue, cogs, opex, netProfit, netMargin, paidOrders, zeroCostItems, totalItems, opexByCategory } = pnl

  const isGlobalEmpty = paidOrders === 0 && expenses.length === 0 && opex === 0

  const summaryData = [
    { name: 'Ingresos', value: revenue },
    { name: 'COGS', value: cogs },
    { name: 'OPEX', value: opex },
    { name: 'Beneficio', value: netProfit < 0 ? 0 : netProfit },
  ]

  const chartAria = `Estructura del P&L en ${windowLabel}: Ingresos ${formatCOP(revenue)}, COGS ${formatCOP(cogs)}, OPEX ${formatCOP(opex)}, Beneficio Neto ${formatCOP(netProfit)}.`

  const exportCsv = () => {
    const rows: string[][] = [
      ['Konvi — P&L', windowLabel],
      [],
      ['Concepto', 'Monto (COP)'],
      ['Ingresos (pedidos pagados)', String(Math.round(revenue))],
      ['COGS (costo de mercancía)', String(-Math.round(cogs))],
      ['OPEX (gastos operativos)', String(-Math.round(opex))],
      ['Beneficio Neto', String(Math.round(netProfit))],
      ['Margen Neto (%)', netMargin.toFixed(1)],
      [],
      ['Gastos operativos del período'],
      ['Fecha', 'Categoría', 'Descripción', 'Monto (COP)', 'Estado'],
      ...expenses.map((e) => [
        formatBogotaDate(e.expense_date),
        e.category,
        e.description,
        String(Math.round(Number(e.amount) || 0)),
        isReversed(e) ? 'Anulado' : 'Vigente',
      ]),
    ]
    const csv = rows
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `konvi-pnl-${range}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-6">

        {/* Controles */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FinanceFilters current={range} />
            <span className="text-xs text-muted-foreground hidden sm:inline">· {windowLabel}</span>
          </div>
          {!isGlobalEmpty && (
            <Button variant="outline" size="sm" className="h-7 text-xs gap-1.5" onClick={exportCsv}>
              <Download className="h-3.5 w-3.5" /> Exportar CSV
            </Button>
          )}
        </div>

        {/* Aviso de truncamiento: la agregación cliente-side es incompleta */}
        {truncated && (
          <Alert variant="warning">
            <AlertTriangle />
            <AlertTitle>P&amp;L aproximado en este rango</AlertTitle>
            <AlertDescription>
              Tienes {ordersCount.toLocaleString('es-CO')} pedidos en el período y el cálculo en el navegador
              solo agrega los primeros {aggLimit.toLocaleString('es-CO')}. Elige un rango más corto (Mes Actual)
              para ver cifras exactas. Estamos habilitando la agregación completa en el servidor.
            </AlertDescription>
          </Alert>
        )}

        {/* Aviso de costos faltantes → margen inflado */}
        {!isGlobalEmpty && totalItems > 0 && zeroCostItems > 0 && (
          <Alert variant="warning">
            <AlertTriangle />
            <AlertTitle>Tu margen puede estar inflado</AlertTitle>
            <AlertDescription>
              {zeroCostItems} de {totalItems} productos vendidos no tienen costo cargado, así que su COGS se
              contó como $0. Carga el costo en el Catálogo para que el beneficio sea real.{' '}
              <Link href="/dashboard/catalog" className="inline-flex items-center gap-1 font-medium underline underline-offset-2">
                Ir al Catálogo <ExternalLink className="h-3 w-3" />
              </Link>
            </AlertDescription>
          </Alert>
        )}

        {isGlobalEmpty ? (
          <>
            <EmptyState
              icon={DollarSign}
              title="Aún no hay movimiento financiero en este período"
              description={
                <>
                  Cuando recibas pedidos pagados verás aquí tus Ingresos, el Costo de Mercancía (COGS) y tu Beneficio Neto.
                  {canWrite && ' Puedes empezar registrando tus gastos operativos (pauta, nómina, software) abajo.'}
                </>
              }
              className="p-10"
            />
            <ExpensesManager expenses={expenses} canWrite={canWrite} />
          </>
        ) : (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <KpiCard
                icon={<DollarSign className="h-5 w-5 text-primary" />} iconBg="bg-primary/10"
                label="Ingresos" value={formatCOP(revenue)} valueClass="text-primary"
                sub={`${paidOrders} ${paidOrders === 1 ? 'pedido pagado' : 'pedidos pagados'}`}
                help="Suma de pedidos con pago confirmado (confirmado, en proceso, enviado, entregado). Excluye carritos sin pagar y cancelados."
              />
              <KpiCard
                icon={<TrendingDown className="h-5 w-5 text-amber-700" />} iconBg="bg-amber-500/10"
                label="Costo Mercancía (COGS)" value={formatCOPNegative(cogs)} valueClass="text-amber-700"
                sub="Costo del inventario vendido"
                help="Cost of Goods Sold: lo que te costó comprar/producir lo que vendiste. Sale del costo unitario cargado en el Catálogo."
              />
              <KpiCard
                icon={<Activity className="h-5 w-5 text-red-700" />} iconBg="bg-red-500/10"
                label="Gastos (OPEX)" value={formatCOPNegative(opex)} valueClass="text-red-700"
                sub="Marketing, nómina, software…"
                help="Operating Expenses: gastos operativos no atados a un producto vendido (pauta, nómina, suscripciones, logística)."
              />
              <Card className={`border-border/50 shadow-xs relative overflow-hidden border-b-4 ${netProfit >= 0 ? 'border-b-emerald-700' : 'border-b-red-700'}`}>
                <CardContent className="p-5 flex flex-col items-center justify-center text-center">
                  <div className={`h-10 w-10 rounded-full flex items-center justify-center mb-3 ${netProfit >= 0 ? 'bg-emerald-500/10' : 'bg-red-500/10'}`}>
                    <TrendingUp className={`h-5 w-5 ${netProfit >= 0 ? 'text-emerald-700' : 'text-red-700'}`} />
                  </div>
                  <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1">
                    Beneficio Neto
                    <JargonTip text="Ingresos − COGS − OPEX. Lo que realmente ganó (o perdió) el negocio en el período." />
                  </p>
                  <h3 className={`text-2xl font-bold mt-1 ${netProfit >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>{formatCOP(netProfit)}</h3>
                  <p className={`text-[11px] font-bold mt-1 ${netProfit >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>
                    {netMargin.toFixed(1)}% Margen
                  </p>
                </CardContent>
              </Card>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Gráfico + desglose OPEX */}
              <div className="lg:col-span-1 space-y-6">
                <Card className="border-border/50 shadow-xs">
                  <CardHeader className="pb-2 text-center border-b">
                    <CardTitle className="text-sm">Estructura del P&amp;L</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-6 h-[280px]" role="img" aria-label={chartAria}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={summaryData} margin={{ top: 10, right: 10, left: 0, bottom: 10 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                        <XAxis dataKey="name" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 10 }} tickLine={false} axisLine={false} />
                        <RTooltip
                          cursor={{ fill: 'hsl(var(--muted) / 0.4)' }}
                          formatter={(value: unknown) => [formatCOP(Number(value) || 0), 'Monto']}
                          contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                          labelStyle={{ color: 'hsl(var(--foreground))' }}
                        />
                        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                          {summaryData.map((entry) => (
                            <Cell key={entry.name} fill={BAR_COLORS[entry.name]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>

                {opexByCategory.length > 0 && (
                  <Card className="border-border/50 shadow-xs">
                    <CardHeader className="pb-2 border-b">
                      <CardTitle className="text-sm">OPEX por categoría</CardTitle>
                    </CardHeader>
                    <CardContent className="pt-4 space-y-2.5">
                      {opexByCategory.map((c) => (
                        <div key={c.key} className="flex items-center justify-between text-sm">
                          <span className="text-muted-foreground">{c.label}</span>
                          <div className="flex items-center gap-2">
                            <div className="w-16 h-1.5 rounded-full bg-border overflow-hidden hidden sm:block">
                              <div className="h-full bg-red-700 rounded-full" style={{ width: `${opex > 0 ? Math.round((c.amount / opex) * 100) : 0}%` }} />
                            </div>
                            <span className="font-mono font-medium text-red-700 w-24 text-right">{formatCOPNegative(c.amount)}</span>
                          </div>
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                )}
              </div>

              <div className="lg:col-span-2">
                <ExpensesManager expenses={expenses} canWrite={canWrite} />
              </div>
            </div>
          </>
        )}
      </div>
    </TooltipProvider>
  )
}

function KpiCard({ icon, iconBg, label, value, valueClass, sub, help }: {
  icon: React.ReactNode; iconBg: string; label: string; value: string; valueClass: string; sub: string; help: string
}) {
  return (
    <Card className="border-border/50 shadow-xs">
      <CardContent className="p-5 flex flex-col items-center justify-center text-center">
        <div className={`h-10 w-10 rounded-full ${iconBg} flex items-center justify-center mb-3`}>{icon}</div>
        <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1">
          {label}
          <JargonTip text={help} />
        </p>
        <h3 className={`text-2xl font-bold mt-1 ${valueClass}`}>{value}</h3>
        <p className="text-[10px] text-muted-foreground mt-1">{sub}</p>
      </CardContent>
    </Card>
  )
}

function JargonTip({ text }: { text: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="text-muted-foreground hover:text-foreground" aria-label={`Qué es: ${text}`}>
          <HelpCircle className="h-3.5 w-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  )
}

