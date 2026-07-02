'use client'

import { useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { SubmitButton } from '@/components/ui/submit-button'
import { Input } from '@/components/ui/input'
import { Plus, Receipt, Calendar, Tag } from 'lucide-react'
import { addExpense } from '../actions'

const CATEGORIES: Record<string, string> = {
  marketing: 'Marketing y Publicidad',
  payroll: 'Nómina',
  software: 'Suscripciones / Software',
  logistics: 'Logística',
  other: 'Otros'
}

export type Expense = {
  id: string
  description: string
  category: string
  expense_date: string
  amount: number
}

type Props = {
  expenses: Expense[]
  canWrite: boolean
}

export default function ExpensesManager({ expenses, canWrite }: Props) {
  const [showAdd, setShowAdd] = useState(false)

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center bg-muted/20 p-3 rounded-lg border border-border/50">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">Gastos Operativos</h2>
          <p className="text-xs text-muted-foreground">Egresos no atados a inventario</p>
        </div>
        {canWrite && !showAdd && (
          <Button onClick={() => setShowAdd(true)} size="sm" className="h-8 text-xs gap-1.5">
            <Plus className="h-3.5 w-3.5" /> Registrar Gasto
          </Button>
        )}
      </div>

      {showAdd && (
        <Card className="border-red-500/30">
           <CardContent className="pt-6">
              <form action={async (fd) => { await addExpense(fd); setShowAdd(false) }} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                  <div className="space-y-1 lg:col-span-2">
                    <label className="text-[10px] font-semibold text-muted-foreground uppercase">Descripción *</label>
                    <Input name="description" placeholder="Ej: Pauta en Meta Ads" required className="h-8 text-xs" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-muted-foreground uppercase">Categoría *</label>
                    <select name="category" required className="w-full h-8 px-2 rounded-md border text-xs bg-background">
                      {Object.entries(CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold text-muted-foreground uppercase">Monto ($) *</label>
                    <Input name="amount" type="number" min="1" step="1" placeholder="0" required className="h-8 text-xs font-mono border-red-500/30 text-red-500" />
                  </div>
                  <div className="space-y-1 lg:col-span-2">
                    <label className="text-[10px] font-semibold text-muted-foreground uppercase">Fecha del Gasto</label>
                    <Input name="expense_date" type="date" required defaultValue={new Date().toISOString().split('T')[0]} className="h-8 text-xs" />
                  </div>
                </div>
                <div className="flex justify-end gap-2 pt-3 border-t">
                  <Button type="button" variant="ghost" size="sm" onClick={() => setShowAdd(false)} className="h-8 text-xs">Cancelar</Button>
                  <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado" className="h-8 text-xs bg-red-600 hover:bg-red-700 text-white">Guardar Egreso</SubmitButton>
                </div>
              </form>
           </CardContent>
        </Card>
      )}

      {expenses.length === 0 && !showAdd && (
         <div className="border border-dashed p-8 text-center text-muted-foreground rounded-xl text-sm mt-4">
            No has registrado gastos operativos aún.
         </div>
      )}

      {expenses.length > 0 && (
         <div className="border border-border/50 rounded-lg overflow-hidden bg-background">
            <table className="w-full text-left text-sm">
               <thead className="bg-muted">
                 <tr>
                   <th className="px-4 py-2 font-medium">Descripción</th>
                   <th className="px-4 py-2 font-medium">Categoría</th>
                   <th className="px-4 py-2 font-medium">Fecha</th>
                   <th className="px-4 py-2 font-medium text-right">Monto</th>
                 </tr>
               </thead>
               <tbody className="divide-y divide-border/20">
                 {expenses.map(e => (
                   <tr key={e.id} className="hover:bg-muted/30 transition-colors">
                     <td className="px-4 py-3 font-medium flex items-center gap-2">
                       <Receipt className="h-4 w-4 text-muted-foreground" />
                       {e.description}
                     </td>
                     <td className="px-4 py-3 text-xs">
                       <span className="bg-muted px-2 py-0.5 rounded flex w-fit items-center gap-1">
                         <Tag className="h-3 w-3" /> {CATEGORIES[e.category] || e.category}
                       </span>
                     </td>
                     <td className="px-4 py-3 text-xs text-muted-foreground">
                       <span className="flex items-center gap-1">
                         <Calendar className="h-3.5 w-3.5" />
                         {new Date(e.expense_date).toLocaleDateString()}
                       </span>
                     </td>
                     <td className="px-4 py-3 text-right font-mono text-red-500 font-medium">
                       -${e.amount.toLocaleString()}
                     </td>
                   </tr>
                 ))}
               </tbody>
            </table>
         </div>
      )}
    </div>
  )
}
