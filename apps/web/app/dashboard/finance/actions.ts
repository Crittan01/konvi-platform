'use server'

import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'
import { revalidatePath } from 'next/cache'
import { bogotaLocalToUTC } from '@/lib/date-window'
import { ok, fail, type ActionResult } from '@/lib/action-result'
import { EXPENSE_CATEGORY_KEYS } from './lib/pnl'

/**
 * addExpense — registra un gasto operativo vía API auditada (F4 2026-07-04).
 *
 * ANTES: tragaba TODOS los fallos (403/500/timeout/sin token) con early-returns
 * silenciosos y `catch { /* non-fatal *\/ }`, y el operador SIEMPRE veía
 * "Guardado" aunque el gasto no se creara. Cero señal en prod.
 *
 * AHORA: contrato ActionResult (nunca throw enmascarado), verifica res.ok,
 * loguea la causa, y ancla la fecha a hora Colombia (el gasto "de hoy" ya no
 * cae en el mes previo por el desfase UTC-5).
 */
export async function addExpense(formData: FormData): Promise<ActionResult> {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const m = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }

  // RBAC: Finanzas es owner-only (matriz 2026-07-02) — misma regla que el guard
  // de page.tsx. Antes esta action aceptaba 'manager', que ni siquiera puede ver
  // la página (drift): un manager creaba gastos que no podía leer.
  if (!m.tenant_id) return fail('Tu usuario no está asociado a ningún negocio.')
  if (m.role !== 'owner') return fail('Solo el propietario puede registrar gastos.')

  const category = (formData.get('category') as string | null)?.trim() ?? ''
  const description = (formData.get('description') as string | null)?.trim() ?? ''
  const amountStr = (formData.get('amount') as string | null) ?? ''
  const dateInput = (formData.get('expense_date') as string | null) ?? ''

  if (!description) return fail('La descripción es obligatoria.')
  if (!EXPENSE_CATEGORY_KEYS.includes(category)) return fail('Selecciona una categoría válida.')

  const amount = parseFloat(amountStr)
  if (!Number.isFinite(amount) || amount <= 0) return fail('El monto debe ser un número mayor a 0.')

  // Fecha: el <input type=date> da 'YYYY-MM-DD' (wall-clock). La anclamos al
  // mediodía hora Colombia para que caiga inequívocamente en ese día calendario
  // en la ventana del P&L. Sin fecha → ahora.
  const expenseISO = dateInput
    ? bogotaLocalToUTC(`${dateInput}T12:00`) ?? new Date().toISOString()
    : new Date().toISOString()

  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
  if (!token) return fail('Tu sesión expiró. Vuelve a iniciar sesión.')

  try {
    const ctrl = new AbortController()
    const timeout = setTimeout(() => ctrl.abort(), 15000)
    let res: Response
    try {
      res = await fetch(`${CORE_API_URL}/api/v1/expenses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ category, description, amount, expense_date: expenseISO }),
        signal: ctrl.signal,
      })
    } finally {
      clearTimeout(timeout)
    }

    if (!res.ok) {
      const body = await res.text().catch(() => '')
      console.error(`[finance.addExpense] API ${res.status} tenant=${m.tenant_id}: ${body.slice(0, 300)}`)
      if (res.status === 403) return fail('No tienes permiso para registrar gastos.')
      if (res.status === 422) return fail('Datos del gasto inválidos. Revisa monto y categoría.')
      return fail('No se pudo registrar el gasto. Intenta de nuevo en unos segundos.')
    }
  } catch (e) {
    const aborted = e instanceof DOMException && e.name === 'AbortError'
    console.error(`[finance.addExpense] ${aborted ? 'timeout' : 'network'} tenant=${m.tenant_id}:`, e)
    return fail(
      aborted
        ? 'El registro tardó demasiado. Verifica en la tabla antes de reintentar para no duplicar.'
        : 'Error de red al registrar el gasto. Intenta de nuevo.',
    )
  }

  revalidatePath('/dashboard/finance')
  return ok('Gasto registrado.')
}
