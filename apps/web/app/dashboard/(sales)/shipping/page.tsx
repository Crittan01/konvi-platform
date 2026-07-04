import { createClient } from '@/utils/supabase/server'
import { Truck, Package, AlertCircle, ExternalLink, Clock } from 'lucide-react'
import ShippingQuoteForm from './shipping-quote-form'
import Link from 'next/link'

type Shipment = {
  id: string
  status: string
  carrier: string | null
  service: string | null
  tracking_number: string | null
  estimated_delivery: string | null
  created_at: string
  order_id: string | null
}

type ShippingOrigin = {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string; dane_code?: string
}

const STATUS_COLORS: Record<string, string> = {
  quoted:     'bg-yellow-500/15 text-yellow-700 border-yellow-700/30',
  labeled:    'bg-blue-500/15 text-blue-700 border-blue-700/30',
  picked_up:  'bg-purple-500/15 text-purple-400 border-purple-500/30',
  in_transit: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  delivered:  'bg-green-500/15 text-green-700 border-green-700/30',
  cancelled:  'bg-red-500/15 text-red-700 border-red-700/30',
}

const STATUS_LABELS: Record<string, string> = {
  quoted:     'Cotizado',
  labeled:    'Etiquetado',
  picked_up:  'Recolectado',
  in_transit: 'En tránsito',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

export default async function ShippingPage(
  props: {
    searchParams?: Promise<{ order?: string }>
  }
) {
  const searchParams = await props.searchParams;
  const normalizeDaneCode = (raw?: string | null) => {
    const digits = String(raw ?? '').replace(/\D/g, '')
    if (digits.length === 8 && digits.endsWith('000')) return digits.slice(0, 5)
    return digits.slice(0, 5)
  }

  // Sem 5 perf: cached.
  const { getCachedUser, getCachedTenantMeta } = await import('@/utils/supabase/cached-user')
  await getCachedUser()
  const { tenantId, role } = await getCachedTenantMeta()
  const canWrite = role === 'owner' || role === 'manager'
  const supabase = await createClient()

  let shipments: Shipment[] = []
  const activeProvider = 'aveonline' as const
  let activeProviderConnected = false
  let shippingOrigin: ShippingOrigin | null = null
  let destDefaults: Record<string, string> | null = null

  // KPI counters
  let inTransitCount = 0
  let deliveredCount = 0

  if (tenantId) {
    // Rev. 109: Aveonline es el provider único activo (ADR-0019).
    // Envia eliminado del runtime. Para agregar Courier N+1 ver ADR-0023.
    const baseQueries = Promise.all([
      supabase
        .from('shipments')
        .select('id, status, carrier, service, tracking_number, estimated_delivery, created_at, order_id')
        .eq('tenant_id', tenantId)
        .order('created_at', { ascending: false })
        .limit(50),
      supabase
        .from('tenant_integrations')
        .select('provider, status')
        .eq('tenant_id', tenantId)
        .eq('provider', 'aveonline'),
      supabase
        .from('tenants')
        .select('shipping_origin')
        .eq('id', tenantId)
        .single(),
    ])

    const [shipmentsRes, integrationsRes, tenantRes] = await baseQueries

    shipments      = (shipmentsRes.data as Shipment[]) || []
    shippingOrigin = (tenantRes.data?.shipping_origin as ShippingOrigin) ?? null
    inTransitCount = shipments.filter(s => s.status === 'in_transit').length
    deliveredCount = shipments.filter(s => s.status === 'delivered').length

    // ¿Está conectado Aveonline?
    const integrationsList = (integrationsRes.data ?? []) as Array<{
      provider: string; status: string
    }>
    activeProviderConnected = integrationsList.some(
      i => i.provider === 'aveonline' && i.status === 'connected',
    )

    // Si viene de un pedido, buscar la dirección del contacto
    if (searchParams?.order) {
      const orderRes = await supabase
        .from('orders')
        .select('contacts(name, phone, address)')
        .eq('id', searchParams.order)
        .eq('tenant_id', tenantId)
        .single()
      const raw     = orderRes.data as { contacts: unknown } | null
      const contact = raw?.contacts
        ? (Array.isArray(raw.contacts) ? raw.contacts[0] : raw.contacts) as { name?: string; phone?: string; address?: Record<string, string> }
        : null
      if (contact?.address?.street) {
        destDefaults = {
          name:      contact.name               ?? '',
          phone:     contact.phone              ?? '',
          street:    contact.address.street     ?? '',
          number:    contact.address.number     ?? '',
          city:      contact.address.city       ?? '',
          state:     contact.address.state      ?? '',
          dane_code: normalizeDaneCode(contact.address.dane_code),
          country:   'CO',
        }
      }
    }
  }

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Truck className="h-5 w-5 text-primary" /> Cotizador de envíos
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {shipments.length} cotizaciones · {inTransitCount} en tránsito · {deliveredCount} entregados
          </p>
        </div>
      </div>

      {/* Banner Aveonline desconectado (provider único shipping ADR-0019). */}
      {!activeProviderConnected && (
        <div className="flex items-start gap-3 p-4 rounded-xl border border-amber-700/30 bg-amber-500/10">
          <AlertCircle className="h-4 w-4 text-amber-700 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-700">
              Aveonline no está conectado
            </p>
            <p className="text-xs text-amber-700/80 mt-0.5">
              Ve a{' '}
              <Link
                href="/dashboard/integrations/aveonline"
                className="underline font-medium"
              >
                Integraciones → Aveonline
              </Link>
              {' '}para configurar tus credenciales antes de cotizar envíos.
            </p>
          </div>
        </div>
      )}

      {/* KPIs rápidas */}
      {shipments.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-2xl font-bold text-primary">{shipments.length}</p>
            <p className="text-xs text-muted-foreground mt-1">Total envíos</p>
          </div>
          <div className={`rounded-xl border bg-card p-4 text-center ${inTransitCount > 0 ? 'border-indigo-500/30' : 'border-border'}`}>
            <p className={`text-2xl font-bold ${inTransitCount > 0 ? 'text-indigo-400' : 'text-primary'}`}>{inTransitCount}</p>
            <p className="text-xs text-muted-foreground mt-1">En tránsito</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-2xl font-bold text-emerald-700">{deliveredCount}</p>
            <p className="text-xs text-muted-foreground mt-1">Entregados</p>
          </div>
        </div>
      )}

      {/* Formulario de cotización — habilitado si provider activo está connected. */}
      {activeProviderConnected && canWrite && (
        <ShippingQuoteForm
          shippingOrigin={shippingOrigin}
          orderId={searchParams?.order ?? null}
          destDefaults={destDefaults}
        />
      )}

      {/* Historial */}
      <div>
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-widest mb-3">
          Historial de envíos
        </h2>
        {shipments.length === 0 ? (
          <div className="flex flex-col items-center py-16 rounded-xl border border-dashed border-border text-center">
            <Package className="h-10 w-10 text-muted-foreground/40 mb-3" />
            <p className="text-muted-foreground text-sm">
              {activeProviderConnected
                ? 'No hay envíos aún. Usa el formulario de cotización.'
                : `Conecta ${activeProvider === 'aveonline' ? 'Aveonline' : 'Envia'} para comenzar a crear envíos.`}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {shipments.map((s) => {
              const colorClass = STATUS_COLORS[s.status] || 'bg-muted text-muted-foreground border-border'
              return (
                <div key={s.id} className="rounded-xl border border-border bg-card p-4 hover:border-primary/30 hover:shadow-sm transition-all">
                  <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                    {/* Info principal */}
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-muted-foreground">#...{s.id.slice(-8)}</span>
                        <span className="text-xs text-muted-foreground flex items-center gap-0.5">
                          <Clock className="h-3 w-3" />
                          {new Date(s.created_at).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })}
                        </span>
                      </div>
                      <p className="font-medium text-sm">{s.carrier ?? 'Carrier por confirmar'}</p>
                      {s.service && <p className="text-xs text-muted-foreground">{s.service}</p>}
                      {s.tracking_number && (
                        <p className="text-xs font-mono text-muted-foreground">
                          Tracking: <span className="text-foreground">{s.tracking_number}</span>
                        </p>
                      )}
                      {s.order_id && (
                        <Link href={`/dashboard/orders`}
                          className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                          <ExternalLink className="h-3 w-3" /> Pedido #{s.order_id.slice(-8)}
                        </Link>
                      )}
                    </div>
                    {/* Status + fecha estimada */}
                    <div className="text-left sm:text-right space-y-1">
                      <span className={`inline-flex items-center text-xs font-medium px-2.5 py-1 rounded-full border ${colorClass}`}>
                        {STATUS_LABELS[s.status] ?? s.status}
                      </span>
                      {s.estimated_delivery && (
                        <p className="text-xs text-muted-foreground">
                          Est: {new Date(s.estimated_delivery).toLocaleDateString('es-CO', { day: '2-digit', month: 'short' })}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
