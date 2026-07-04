/**
 * ActionResult — contrato canónico de server actions (F1 2026-07-04).
 *
 * Fuente única del tipo que antes estaba duplicado en purchases/contacts/
 * settings. Toda server action de mutación devuelve ActionResult en vez de
 * throw (un throw se enmascara en prod y el operador nunca ve la causa).
 *
 * Uso:
 *   'use server'
 *   import { ok, fail, type ActionResult } from '@/lib/action-result'
 *   export async function guardar(fd: FormData): Promise<ActionResult> {
 *     const { error } = await supabase.from('x').update(...)
 *     if (error) return fail('No se pudo guardar: ' + error.message)
 *     revalidatePath('/dashboard/x')
 *     return ok()
 *   }
 */
export type ActionResult = { ok: boolean; error?: string; message?: string }

export const ok = (message?: string): ActionResult => ({ ok: true, message })
export const fail = (error: string): ActionResult => ({ ok: false, error })
