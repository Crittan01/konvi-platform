'use client'

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from 'recharts'

interface BarData { day: string; mensajes: number }
interface PieData  { name: string; value: number }

const COLORS = ['#a3e635', '#facc15', '#60a5fa', '#f472b6', '#34d399', '#f87171']

const ORDER_STATUS_LABELS: Record<string, string> = {
  pending:    'Pendiente',
  pending_payment: 'Esperando pago',  // F62: órdenes bot con link Wompi
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

export function MessagesBarChart({ data }: { data: BarData[] }) {
  if (data.length === 0) return <p className="text-sm text-muted-foreground">Sin datos.</p>
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
        <XAxis dataKey="day" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
        <YAxis tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} allowDecimals={false} />
        <Tooltip
          contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8 }}
          labelStyle={{ color: 'hsl(var(--foreground))', fontSize: 12 }}
          itemStyle={{ color: 'hsl(var(--primary))' }}
        />
        <Bar dataKey="mensajes" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function OrdersPieChart({ data }: { data: PieData[] }) {
  if (data.length === 0) return <p className="text-sm text-muted-foreground">Sin datos.</p>
  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="45%"
          innerRadius={55}
          outerRadius={80}
          paddingAngle={3}
          dataKey="value"
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          formatter={(value, name) => [value, ORDER_STATUS_LABELS[String(name)] ?? name]}
          contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8 }}
          labelStyle={{ color: 'hsl(var(--foreground))', fontSize: 12 }}
        />
        <Legend
          formatter={(value) => ORDER_STATUS_LABELS[value] ?? value}
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: 11, color: 'hsl(var(--muted-foreground))' }}
        />
      </PieChart>
    </ResponsiveContainer>
  )
}
