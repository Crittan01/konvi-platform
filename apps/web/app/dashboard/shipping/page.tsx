import { createClient } from '@/utils/supabase/server'
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

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

const STATUS_COLORS: Record<string, string> = {
  quoted:     'bg-yellow-100 text-yellow-800',
  labeled:    'bg-blue-100 text-blue-800',
  picked_up:  'bg-purple-100 text-purple-800',
  in_transit: 'bg-indigo-100 text-indigo-800',
  delivered:  'bg-green-100 text-green-800',
  cancelled:  'bg-red-100 text-red-800',
}

const STATUS_LABELS: Record<string, string> = {
  quoted:     'Cotizado',
  labeled:    'Etiquetado',
  picked_up:  'Recolectado',
  in_transit: 'En tránsito',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

export default async function ShippingPage() {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'

  let shipments: Shipment[] = []
  let enviaConnected = false

  if (tenantId) {
    const [shipmentsRes, integrationRes] = await Promise.all([
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
    ])
    shipments = (shipmentsRes.data as Shipment[]) || []
    enviaConnected = integrationRes.data?.status === 'connected'
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Envíos</h1>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      {/* Banner de estado de Envia */}
      {!enviaConnected && (
        <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
          <p className="text-sm font-medium text-yellow-800">Envia no está conectado</p>
          <p className="text-xs text-yellow-700 mt-1">
            Ve a <a href="/dashboard/integrations" className="underline font-medium">Integraciones</a> para configurar tu API key de Envia antes de cotizar envíos.
          </p>
        </div>
      )}

      {/* Cotización — solo cuando Envia está conectado */}
      {enviaConnected && (
        <Card>
          <CardHeader>
            <CardTitle>Cotizar Envío</CardTitle>
            <CardDescription>
              Ingresa los datos del paquete y destino para obtener tarifas de carriers disponibles.
              La cotización se guarda automáticamente en el historial.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="p-4 bg-muted rounded-lg text-sm text-muted-foreground">
              <p className="font-medium mb-1">Formulario de cotización</p>
              <p>El formulario interactivo de cotización (con selección de carrier y confirmación) se implementa en Fase 11 como Client Component con estado dinámico.</p>
              <p className="mt-2">Para cotizar via API directamente:</p>
              <code className="block mt-1 text-xs bg-background p-2 rounded border">
                POST /api/v1/shipping/quote
              </code>
            </div>
          </CardContent>
        </Card>
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
              const colorClass = STATUS_COLORS[s.status] || 'bg-gray-100 text-gray-800'
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
                        <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full ${colorClass}`}>
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
