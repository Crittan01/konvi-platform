'use client'

import { useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { SubmitButton } from '@/components/ui/submit-button'
import ActionResultForm from '@/components/action-result-form'
import { Input } from '@/components/ui/input'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { Plus, Receipt, Calendar, Tag } from 'lucide-react'
import { addExpense } from '../actions'
import { EXPENSE_CATEGORIES } from '../lib/pnl'
import { formatCOPNegative, formatBogotaDate } from '../lib/format'

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

const todayBogota = () =>
  new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString().slice(0, 10)

export default function ExpensesManager({ expenses, canWrite }: Props) {
  const [showAdd, setShowAdd] = useState(false)

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center bg-muted/20 p-3 rounded-lg border border-border/50">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">Gastos Operativos</h2>
          <p className="text-xs text-muted-foreground">Egresos no atados a inventario (OPEX)</p>
        </div>
        {canWrite && !showAdd && (
          <Button onClick={() => setShowAdd(true)} size="sm" className="h-8 text-xs gap-1.5">
            <Plus className="h-3.5 w-3.5" /> Registrar Gasto
          </Button>
        )}
      </div>

      {showAdd && (
        <Card className="border-red-700/30">
          <CardContent className="pt-6">
            <ActionResultForm
              action={async (fd) => {
                const r = await addExpense(fd)
                if (r.ok) setShowAdd(false)
                return r
              }}
              className="space-y-4"
            >
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="space-y-1 lg:col-span-2">
                  <label htmlFor="exp-description" className="text-[10px] font-semibold text-muted-foreground uppercase">Descripción *</label>
                  <Input id="exp-description" name="description" placeholder="Ej: Pauta en Meta Ads" required className="h-8 text-xs" />
                </div>
                <div className="space-y-1">
                  <label htmlFor="exp-category" className="text-[10px] font-semibold text-muted-foreground uppercase">Categoría *</label>
                  <select id="exp-category" name="category" required className="w-full h-8 px-2 rounded-md border text-xs bg-background">
                    {Object.entries(EXPENSE_CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <label htmlFor="exp-amount" className="text-[10px] font-semibold text-muted-foreground uppercase">Monto ($) *</label>
                  <Input id="exp-amount" name="amount" type="number" min="1" step="1" placeholder="0" required className="h-8 text-xs font-mono border-red-700/30 text-red-700" />
                </div>
                <div className="space-y-1 lg:col-span-2">
                  <label htmlFor="exp-date" className="text-[10px] font-semibold text-muted-foreground uppercase">Fecha del Gasto</label>
                  <Input id="exp-date" name="expense_date" type="date" required defaultValue={todayBogota()} className="h-8 text-xs" />
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-3 border-t">
                <Button type="button" variant="ghost" size="sm" onClick={() => setShowAdd(false)} className="h-8 text-xs">Cancelar</Button>
                <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado" className="h-8 text-xs bg-red-700 hover:bg-red-800 text-white">Guardar Egreso</SubmitButton>
              </div>
            </ActionResultForm>
          </CardContent>
        </Card>
      )}

      {expenses.length === 0 && !showAdd && (
        <div className="border border-dashed p-8 text-center rounded-xl text-sm space-y-2">
          <Receipt className="h-8 w-8 text-muted-foreground/50 mx-auto" />
          <p className="font-medium text-foreground">Sin gastos operativos en este período</p>
          <p className="text-muted-foreground max-w-sm mx-auto">
            Un gasto operativo es un egreso del negocio que no es inventario: pauta publicitaria, nómina,
            suscripciones de software o logística. Registrarlos hace que tu Beneficio Neto sea real.
          </p>
          {canWrite && (
            <Button onClick={() => setShowAdd(true)} size="sm" className="h-8 text-xs gap-1.5 mt-1">
              <Plus className="h-3.5 w-3.5" /> Registrar el primer gasto
            </Button>
          )}
        </div>
      )}

      {expenses.length > 0 && (
        <div className="border border-border/50 rounded-lg bg-background">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Descripción</TableHead>
                <TableHead>Categoría</TableHead>
                <TableHead>Fecha</TableHead>
                <TableHead className="text-right">Monto</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {expenses.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="font-medium">
                    <span className="flex items-center gap-2">
                      <Receipt className="h-4 w-4 text-muted-foreground shrink-0" />
                      {e.description}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs">
                    <span className="bg-muted px-2 py-0.5 rounded flex w-fit items-center gap-1">
                      <Tag className="h-3 w-3" /> {EXPENSE_CATEGORIES[e.category] || e.category}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5" />
                      {formatBogotaDate(e.expense_date)}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono text-red-700 font-medium whitespace-nowrap">
                    {formatCOPNegative(e.amount)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
