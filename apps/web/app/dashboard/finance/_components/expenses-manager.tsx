'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { SubmitButton } from '@/components/ui/submit-button'
import ActionResultForm from '@/components/action-result-form'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription,
} from '@/components/ui/dialog'
import { Plus, Receipt, Calendar, Tag, Ban } from 'lucide-react'
import { addExpense, reverseExpense } from '../actions'
import { EXPENSE_CATEGORIES, isReversed, type ExpenseRow } from '../lib/pnl'
import { formatCOPNegative, formatBogotaDate } from '../lib/format'

/** @deprecated usar ExpenseRow de ../lib/pnl */
export type Expense = ExpenseRow

type Props = {
  expenses: ExpenseRow[]
  canWrite: boolean
}

const todayBogota = () =>
  new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString().slice(0, 10)

export default function ExpensesManager({ expenses, canWrite }: Props) {
  const [showAdd, setShowAdd] = useState(false)
  const [target, setTarget] = useState<ExpenseRow | null>(null)
  const [reason, setReason] = useState('')
  const [pending, startTransition] = useTransition()
  const router = useRouter()

  const closeReverse = () => {
    if (pending) return
    setTarget(null)
    setReason('')
  }

  const submitReverse = () => {
    if (!target) return
    const motivo = reason.trim()
    if (motivo.length < 3) {
      toast.error('Indica el motivo de la anulación (mínimo 3 caracteres).')
      return
    }
    startTransition(async () => {
      const r = await reverseExpense(target.id, motivo)
      if (r.ok) {
        toast.success(r.message ?? 'Gasto anulado.')
        setTarget(null)
        setReason('')
        router.refresh()
      } else {
        toast.error(r.error ?? 'No se pudo anular el gasto.')
      }
    })
  }

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
                {canWrite && <TableHead className="text-right w-16">Acción</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {expenses.map((e) => {
                const reversed = isReversed(e)
                return (
                  <TableRow key={e.id} className={reversed ? 'opacity-60' : undefined}>
                    <TableCell className="font-medium">
                      <span className="flex items-center gap-2">
                        <Receipt className="h-4 w-4 text-muted-foreground shrink-0" />
                        <span className={reversed ? 'line-through' : undefined}>{e.description}</span>
                        {reversed && (
                          <Badge
                            variant="warning"
                            className="text-[10px]"
                            title={e.reversal_reason ? `Motivo: ${e.reversal_reason}` : undefined}
                          >
                            Anulado
                          </Badge>
                        )}
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
                    <TableCell className={`text-right font-mono text-red-700 font-medium whitespace-nowrap ${reversed ? 'line-through' : ''}`}>
                      {formatCOPNegative(e.amount)}
                    </TableCell>
                    {canWrite && (
                      <TableCell className="text-right">
                        {!reversed && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-xs text-red-700 hover:text-red-800 hover:bg-red-500/10 gap-1"
                            onClick={() => { setTarget(e); setReason('') }}
                            title="Anular este gasto (no se borra: queda registrado como anulado)"
                          >
                            <Ban className="h-3.5 w-3.5" /> Anular
                          </Button>
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={target !== null} onOpenChange={(open) => { if (!open) closeReverse() }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Anular gasto</DialogTitle>
            <DialogDescription>
              El gasto no se borra: queda registrado como anulado (con su motivo) y deja de contar en el
              beneficio. Si fue un error de monto, anúlalo y registra el gasto corregido.
            </DialogDescription>
          </DialogHeader>

          {target && (
            <div className="rounded-md border border-border/50 bg-muted/30 p-3 text-sm space-y-1">
              <p className="font-medium">{target.description}</p>
              <p className="font-mono text-red-700">{formatCOPNegative(target.amount)}</p>
            </div>
          )}

          <div className="space-y-1">
            <label htmlFor="reverse-reason" className="text-[10px] font-semibold text-muted-foreground uppercase">
              Motivo de la anulación *
            </label>
            <Textarea
              id="reverse-reason"
              value={reason}
              onChange={(ev) => setReason(ev.target.value)}
              maxLength={300}
              rows={3}
              placeholder="Ej: monto digitado por error, gasto duplicado…"
              className="text-sm"
            />
          </div>

          <DialogFooter className="gap-2 sm:gap-2">
            <Button type="button" variant="outline" size="sm" onClick={closeReverse} disabled={pending}>
              Cancelar
            </Button>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              onClick={submitReverse}
              disabled={pending || reason.trim().length < 3}
            >
              {pending ? 'Anulando…' : 'Anular gasto'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
