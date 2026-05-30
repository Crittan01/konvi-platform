/**
 * Inbox — Server Component thin (refactor paso 2/10, 2026-05-29).
 *
 * Auth + tenant check + delega render a `<InboxManager />` (Client).
 *
 * Patrón canónico del codebase (mismo que claims/orders/contacts/finance):
 *   - page.tsx Server: getCachedUser + getCachedTenantMeta + redirect.
 *   - _components/inbox-manager.tsx Client: orquesta state + Realtime + UI.
 */
import { redirect } from 'next/navigation'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import InboxManager from './_components/inbox-manager'

export default async function InboxPage() {
  // Sem 5 perf: getCachedUser/getCachedTenantMeta cachean por request.
  const user = await getCachedUser()
  if (!user) redirect('/login')

  const { tenantId, role } = await getCachedTenantMeta()
  if (!tenantId) redirect('/login')

  // RBAC: operator+manager+owner pueden ver Inbox; viewers no.
  // (Si el codebase tiene un rol viewer no autorizado, ajustar aquí.)
  if (role && !['owner', 'manager', 'operator'].includes(role)) {
    redirect('/dashboard')
  }

  return <InboxManager />
}
