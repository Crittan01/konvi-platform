import { createClient } from '@/utils/supabase/server'
import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
import { redirect } from 'next/navigation'
import { AlertCircle } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import ClaimsManager from './_components/claims-manager'
import { CORE_API_URL } from '@/lib/runtime-env'

export const metadata = { title: 'Reclamos' }

// Cap de lectura alineado con el límite del router API (claims.py: limit<=200).
// Evita el full-table-fetch del tenant en tenants con historial largo.
const CLAIMS_LIMIT = 200
const ORDERS_LIMIT = 100

// Fila del REST de dominio (GET /api/v1/claims/ — M2.4): columnas + embeds.
type ClaimRow = {
  id: string
  ticket_number: number | null
  status: string
  reason: string
  reason_detail: string | null
  requested_amount: number | null
  refunded_amount: number | null
  refunded_at: string | null
  resolution_notes: string | null
  created_at: string
  orders: { id: string; total_amount: number | null; payment_method: string | null } | { id: string; total_amount: number | null; payment_method: string | null }[] | null
  contacts: { id: string; name: string | null; phone: string | null } | { id: string; name: string | null; phone: string | null }[] | null
}

export default async function ClaimsPage() {
  // Sem 5 perf: cached.
  const user = await getCachedUser()
  if (!user) redirect('/login')

  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite   = ['owner', 'manager', 'operator'].includes(role)
  const canResolve = ['owner', 'manager'].includes(role)
  // Reapertura de terminales (F2): restringida a owner (coincide con el guard del API).
  const canReopen  = role === 'owner'

  // Sin tenant no hay nada que consultar: NO pintar el empty state (que se leería
  // como "tenant sin reclamos") — es un error de sesión/rol y debe surfacearse.
  if (!tenantId) {
    return <ClaimsError message="No se pudo determinar tu organización. Cierra sesión y vuelve a entrar; si persiste, contacta soporte." />
  }

  const supabase = await createClient()

  // M2.4 (Track 5): el listado de reclamos viene del domain service vía REST
  // (GET /api/v1/claims/ — filtros y embeds orders/contacts + reason_detail
  // viven en konvi_domain.claims) — UNA fuente de verdad compartida; antes esta
  // página consultaba PostgREST directo. Los pedidos recientes del selector de
  // "Nuevo Reclamo" siguen directos (lectura del dominio orders — su REST de
  // listado existe desde M2.1 pero pagina distinto a lo que el selector necesita).
  const fetchClaims = async (): Promise<ClaimRow[] | null> => {
    const { data: { session: s } } = await supabase.auth.getSession()
    const token = s?.access_token
    if (!token) return null
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      const res = await fetch(`${CORE_API_URL}/api/v1/claims/?limit=${CLAIMS_LIMIT}`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store', // datos transaccionales — nunca cachear
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
      if (!res.ok) return null
      return (await res.json()) as ClaimRow[]
    } catch {
      return null
    }
  }

  const [claimsData, { data: ordersData, error: ordersError }] = await Promise.all([
    fetchClaims(),
    // Fetch recent orders for the "New Claim" selector (con contacto para etiquetarlos)
    supabase
      .from('orders')
      .select('id, status, total_amount, contact_id, created_at, contacts ( name, phone )')
      .eq('tenant_id', tenantId)
      .order('created_at', { ascending: false })
      .limit(ORDERS_LIMIT),
  ])

  // Un fallo de lectura NO es "no hay reclamos": surfacear un estado de error
  // con retry, no un empty state engañoso.
  if (!claimsData) {
    console.error('[claims] read error (REST domain service)', { tenantId })
    return <ClaimsError message="No pudimos cargar los reclamos. Reintenta en unos segundos." />
  }
  if (ordersError) {
    console.error('[claims] orders read error', { tenantId, code: ordersError.code, message: ordersError.message })
  }

  // Map to flat structures
  const claims = (claimsData || []).map(c => ({
    id: c.id,
    ticket_number: c.ticket_number ?? null,
    order:    Array.isArray(c.orders)   ? (c.orders[0]   ?? null) : (c.orders   ?? null),
    customer: Array.isArray(c.contacts) ? (c.contacts[0] ?? null) : (c.contacts ?? null),
    status: c.status,
    reason: c.reason,
    reason_detail: c.reason_detail ?? null,
    requested_amount: c.requested_amount,
    refunded_amount: c.refunded_amount ?? null,
    refunded_at: c.refunded_at ?? null,
    resolution_notes: c.resolution_notes,
    created_at: c.created_at
  }))

  const recentOrders = (ordersData || []).map(o => {
    const contact = Array.isArray(o.contacts) ? (o.contacts[0] ?? null) : (o.contacts ?? null)
    return {
      id: o.id,
      status: o.status,
      total_amount: o.total_amount,
      contact_id: o.contact_id,
      created_at: o.created_at,
      customer_name: (contact as { name?: string | null; phone?: string | null } | null)?.name
        ?? (contact as { phone?: string | null } | null)?.phone
        ?? null,
    }
  })

  return (
    <div className="space-y-6 max-w-7xl flex-1 h-full overflow-hidden flex flex-col">
      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12). ClaimsError
          (rama de error) NO lleva PageHeader: las ramas de error/EmptyState
          quedan intactas por decisión del rollout. */}
      <PageHeader
        icon={AlertCircle}
        title="Centro de Reclamos"
        description="Visualiza, investiga y resuelve disputas, devoluciones y solicitudes de garantías ligadas a pedidos existentes. El cliente recibe su número de ticket por WhatsApp y puede consultar el estado con el bot; tus notas de resolución también le llegan por ese canal."
        className="flex-none"
      />

      <div className="flex-1 min-h-0">
        <ClaimsManager claims={claims} recentOrders={recentOrders} canWrite={canWrite} canResolve={canResolve} canReopen={canReopen} />
      </div>
    </div>
  )
}

// Estado de error de ruta: distinto del empty state, con guía de recuperación.
function ClaimsError({ message }: { message: string }) {
  return (
    <div className="space-y-6 max-w-7xl">
      <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
        <AlertCircle className="h-5 w-5 text-primary" /> Centro de Reclamos
      </h1>
      <div className="rounded-xl border border-danger-border bg-danger-bg p-6 flex items-start gap-3">
        <AlertCircle className="h-5 w-5 text-danger-fg shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-medium text-danger-fg">No se pudieron cargar los reclamos</p>
          <p className="text-sm text-muted-foreground">{message}</p>
        </div>
      </div>
    </div>
  )
}
