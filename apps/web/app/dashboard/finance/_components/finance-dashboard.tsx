'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar, Cell } from 'recharts'
import ExpensesManager from './expenses-manager'
import { DollarSign, TrendingDown, TrendingUp, Activity, PieChart } from 'lucide-react'

type Props = {
  orders: any[]
  expenses: any[]
  canWrite: boolean
}

export default function FinanceDashboard({ orders, expenses, canWrite }: Props) {
  // 1. Calcular métricas principales
  let totalRevenue = 0
  let totalCOGS = 0 // Costo de mercancía vendida
  
  orders.forEach(o => {
    if (o.status === 'cancelled') return
    totalRevenue += o.total_amount
    o.order_items.forEach((item: any) => {
      // Si unit_cost es 0, históricamente no teníamos costo. Lo manejamos como COGS 0
      totalCOGS += (item.unit_cost * item.quantity)
    })
  })

  const totalOpex = expenses.reduce((acc, e) => acc + e.amount, 0)
  
  const grossProfit = totalRevenue - totalCOGS
  const grossMargin = totalRevenue > 0 ? (grossProfit / totalRevenue) * 100 : 0
  
  const netProfit = grossProfit - totalOpex
  const netMargin = totalRevenue > 0 ? (netProfit / totalRevenue) * 100 : 0

  // Datos para gráfico simple (Resumen general)
  const summaryData = [
    { name: 'Ventas Netas', value: totalRevenue, full: totalRevenue },
    { name: 'COGS', value: totalCOGS, full: totalRevenue },
    { name: 'OPEX', value: totalOpex, full: totalRevenue },
    { name: 'Beneficio', value: netProfit < 0 ? 0 : netProfit, full: totalRevenue }
  ]

  // Render helpers
  const fmt = (n: number) => `$${Math.round(n).toLocaleString()}`

  return (
    <div className="space-y-6">
       
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="border-border/50 shadow-sm">
          <CardContent className="p-5 flex flex-col items-center justify-center text-center">
             <div className="h-10 w-10 rounded-full bg-blue-500/10 flex items-center justify-center mb-3">
               <DollarSign className="h-5 w-5 text-blue-500" />
             </div>
             <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Ingresos Netos</p>
             <h3 className="text-2xl font-bold mt-1 text-primary">{fmt(totalRevenue)}</h3>
             <p className="text-[10px] text-muted-foreground mt-1 text-blue-500">De pedidos pagados</p>
          </CardContent>
        </Card>
        <Card className="border-border/50 shadow-sm">
          <CardContent className="p-5 flex flex-col items-center justify-center text-center relative overflow-hidden">
             <div className="absolute -right-4 -bottom-4 opacity-5 pointer-events-none">
                <PieChart className="h-32 w-32" />
             </div>
             <div className="h-10 w-10 rounded-full bg-amber-500/10 flex items-center justify-center mb-3">
               <TrendingDown className="h-5 w-5 text-amber-500" />
             </div>
             <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Costo Mercancía (COGS)</p>
             <h3 className="text-2xl font-bold mt-1 text-amber-500">-{fmt(totalCOGS)}</h3>
             <p className="text-[10px] text-muted-foreground mt-1">Inventario vendido</p>
          </CardContent>
        </Card>
        <Card className="border-border/50 shadow-sm">
          <CardContent className="p-5 flex flex-col items-center justify-center text-center">
             <div className="h-10 w-10 rounded-full bg-red-500/10 flex items-center justify-center mb-3">
               <Activity className="h-5 w-5 text-red-500" />
             </div>
             <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Gastos (OPEX)</p>
             <h3 className="text-2xl font-bold mt-1 text-red-500">-{fmt(totalOpex)}</h3>
             <p className="text-[10px] text-muted-foreground mt-1">Marketing, nómina, etc.</p>
          </CardContent>
        </Card>
        <Card className={`border-border/50 shadow-sm relative overflow-hidden ${netProfit > 0 ? 'border-b-green-500 border-b-4' : 'border-b-red-500 border-b-4'}`}>
          <CardContent className="p-5 flex flex-col items-center justify-center text-center">
             <div className={`h-10 w-10 rounded-full flex items-center justify-center mb-3 ${netProfit > 0 ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
               <TrendingUp className={`h-5 w-5 ${netProfit > 0 ? 'text-green-500' : 'text-red-500'}`} />
             </div>
             <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Beneficio Neto</p>
             <h3 className={`text-2xl font-bold mt-1 ${netProfit > 0 ? 'text-green-500' : 'text-red-500'}`}>{fmt(netProfit)}</h3>
             <p className={`text-[11px] font-bold mt-1 ${netProfit > 0 ? 'text-green-500' : 'text-red-500'}`}>
                {netMargin.toFixed(1)}% Margen
             </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          <Card className="h-full border-border/50 shadow-sm">
            <CardHeader className="pb-2 text-center border-b">
              <CardTitle className="text-sm">Estructura de Gastos Financieros</CardTitle>
            </CardHeader>
            <CardContent className="pt-6 h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                 <BarChart data={summaryData} margin={{ top: 10, right: 10, left: 0, bottom: 20 }}>
                   <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" vertical={false} />
                   <XAxis dataKey="name" tick={{fill: '#888', fontSize: 10}} tickLine={false} axisLine={false} />
                   <Tooltip 
                     formatter={(value: number) => [fmt(value), 'Monto']}
                     contentStyle={{ backgroundColor: '#111', border: '1px solid #333', borderRadius: '8px', fontSize: '12px' }}
                   />
                   <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                     {summaryData.map((entry, index) => (
                       <Cell key={`cell-${index}`} fill={
                         entry.name === 'Ventas Netas' ? '#3b82f6' : 
                         entry.name === 'COGS' ? '#f59e0b' : 
                         entry.name === 'OPEX' ? '#ef4444' : '#22c55e'
                       } />
                     ))}
                   </Bar>
                 </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
        
        <div className="lg:col-span-2">
           <ExpensesManager expenses={expenses} canWrite={canWrite} />
        </div>
      </div>
      
    </div>
  )
}
