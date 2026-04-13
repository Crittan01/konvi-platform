'use server'

import { createClient } from '@/utils/supabase/server'
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

  await supabase.from('expenses').insert({
    tenant_id: m.tenant_id,
    category,
    description: description.trim(),
    amount,
    expense_date: new Date(expense_date).toISOString()
  })

  revalidatePath('/dashboard/finance')
}
