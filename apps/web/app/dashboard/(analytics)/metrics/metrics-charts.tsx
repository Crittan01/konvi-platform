'use client'

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from 'recharts'
import { EmptyState } from '@/components/ui/empty-state'
import { ORDER_STATUS_LABELS, ORDER_STATUS_HEX, STATUS_HEX_FALLBACK } from './_lib/metrics'

interface BarData { day: string; mensajes: number }
interface PieData  { name: string; value: number }

export function MessagesBarChart({ data }: { data: BarData[] }) {
  if (data.length === 0) return <EmptyState variant="plain" className="py-8" description="Sin datos." />

  // Alternativa accesible: la gráfica recharts es invisible para lectores de
  // pantalla → tabla oculta con los mismos datos + role/aria en el contenedor.
  const total = data.reduce((s, d) => s + d.mensajes, 0)
  return (
    <div role="img" aria-label={`Mensajes por día de semana. Total ${total} mensajes: ${data.map(d => `${d.day} ${d.mensajes}`).join(', ')}.`}>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis dataKey="day" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
          <YAxis tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} allowDecimals={false} />
          <Tooltip
            cursor={{ fill: 'hsl(var(--muted))' }}
            contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8 }}
            labelStyle={{ color: 'hsl(var(--foreground))', fontSize: 12 }}
            itemStyle={{ color: 'hsl(var(--primary))' }}
          />
          <Bar dataKey="mensajes" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function OrdersPieChart({ data }: { data: PieData[] }) {
  if (data.length === 0) return <EmptyState variant="plain" className="py-8" description="Sin datos." />

  const label = data.map(d => `${ORDER_STATUS_LABELS[d.name] ?? d.name}: ${d.value}`).join(', ')
  return (
    <div role="img" aria-label={`Pedidos por estado. ${label}.`}>
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
            {/* Color POR ESTADO (estable entre recargas), no por índice. */}
            {data.map((d) => (
              <Cell key={d.name} fill={ORDER_STATUS_HEX[d.name] ?? STATUS_HEX_FALLBACK} />
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
    </div>
  )
}
