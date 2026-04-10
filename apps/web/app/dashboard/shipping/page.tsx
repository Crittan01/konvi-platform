import { createClient } from '@/utils/supabase/server'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import ShippingQuoteForm from './shipping-quote-form'

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
  state?: string; postal_code?: string; country?: string; phone?: string
}

const STATUS_COLORS: Record<string, string> = {
  quoted:     'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  labeled:    'bg-blue-500/15 text-blue-400 border-blue-500/30',
  picked_up:  'bg-purple-500/15 text-purple-400 border-purple-500/30',
  in_transit: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  delivered:  'bg-green-500/15 text-green-400 border-green-500/30',
  cancelled:  'bg-red-500/15 text-red-400 border-red-500/30',
}

const STATUS_LABELS: Record<string, string> = {
  quoted:     'Cotizado',
  labeled:    'Etiquetado',
  picked_up:  'Recolectado',
  in_transit: 'En tránsito',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

export default async function ShippingPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  let shipments: Shipment[] = []
  let enviaConnected = false
  let shippingOrigin: ShippingOrigin | null = null

  if (tenantId) {
    const [shipmentsRes, integrationRes, tenantRes] = await Promise.all([
      supabase
        .from('shipments')
        .select('id, status, carrier, service, tracking_number, estimated_delivery, created_at, order_id')
        .eq('tenant_id', tenantId)
        .order('created_at', { ascending: false })
        .limit(50),
      supabase
        .from('tenant_integrations')
        .select('status')
        .eq('tenant_id', tenantId)
        .eq('provider', 'envia')
        .maybeSingle(),
      supabase
        .from('tenants')
        .select('shipping_origin')
        .eq('id', tenantId)
        .single(),
    ])
    shipments = (shipmentsRes.data as Shipment[]) || []
    enviaConnected = integrationRes.data?.status === 'connected'
    shippingOrigin = (tenantRes.data?.shipping_origin as ShippingOrigin) ?? null
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Envíos</h1>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      {/* Banner de estado de Envia */}
      {!enviaConnected && (
        <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-lg">
          <p className="text-sm font-medium text-amber-400">Envia no está conectado</p>
          <p className="text-xs text-amber-400/80 mt-1">
            Ve a <a href="/dashboard/integrations" className="underline font-medium">Integraciones</a> para configurar tu API key de Envia antes de cotizar envíos.
          </p>
        </div>
      )}

      {/* Formulario de cotización — solo cuando Envia está conectado y tiene permisos */}
      {enviaConnected && canWrite && (
        <ShippingQuoteForm
          shippingOrigin={shippingOrigin}
          apiUrl={API_URL}
        />
      )}

      {/* Historial */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Historial de envíos</h2>
        {shipments.length === 0 ? (
          <div className="p-8 border rounded-lg border-dashed text-center">
            <p className="text-muted-foreground">No hay envíos registrados.</p>
            {enviaConnected && (
              <p className="text-sm text-muted-foreground mt-1">Las cotizaciones aparecerán aquí.</p>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {shipments.map((s) => {
              const colorClass = STATUS_COLORS[s.status] || 'bg-gray-500/15 text-gray-400'
              return (
                <Card key={s.id}>
                  <CardContent className="p-5">
                    <div className="flex justify-between items-start">
                      <div className="space-y-1">
                        <p className="text-xs text-muted-foreground font-mono">#{s.id.slice(-8)}</p>
                        <p className="font-medium">{s.carrier ?? 'Carrier pendiente'}</p>
                        {s.service && <p className="text-sm text-muted-foreground">{s.service}</p>}
                        {s.tracking_number && (
                          <p className="text-xs font-mono text-muted-foreground">
                            Tracking: {s.tracking_number}
                          </p>
                        )}
                        {s.order_id && (
                          <p className="text-xs text-muted-foreground">
                            Pedido: #{s.order_id.slice(-8)}
                          </p>
                        )}
                      </div>
                      <div className="text-right shrink-0 ml-4 space-y-1">
                        <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full border ${colorClass}`}>
                          {STATUS_LABELS[s.status] ?? s.status}
                        </span>
                        {s.estimated_delivery && (
                          <p className="text-xs text-muted-foreground">
                            Est: {new Date(s.estimated_delivery).toLocaleDateString('es-MX')}
                          </p>
                        )}
                        <p className="text-xs text-muted-foreground">
                          {new Date(s.created_at).toLocaleDateString('es-MX')}
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
