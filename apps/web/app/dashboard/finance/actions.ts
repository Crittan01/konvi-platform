'use server'

import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'
import { revalidatePath } from 'next/cache'

export async function addExpense(formData: FormData) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const m = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return

  const category = formData.get('category') as string
  const description = formData.get('description') as string
  const amountStr = formData.get('amount') as string
  const expense_date = formData.get('expense_date') as string || new Date().toISOString()
  
  const amount = parseFloat(amountStr)

  if (!description || !category || isNaN(amount) || amount <= 0) return

  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token
  if (!token) return

  // F2.2: registrar gasto vía API (audita el registro financiero + RBAC server-side).
  try {
    const ctrl = new AbortController()
    const timeout = setTimeout(() => ctrl.abort(), 15000)
    await fetch(`${CORE_API_URL}/api/v1/expenses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({
        category,
        description: description.trim(),
        amount,
        expense_date: new Date(expense_date).toISOString(),
      }),
      signal: ctrl.signal,
    })
    clearTimeout(timeout)
  } catch { /* non-fatal */ }

  revalidatePath('/dashboard/finance')
}
