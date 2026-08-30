import Link from 'next/link'
import { notFound } from 'next/navigation'
import {
  ArrowLeft, Package, Clock, MapPin, CreditCard, Truck, User, Phone, XCircle, FileText,
} from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import { createClient } from '@/utils/supabase/server'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { OrderStatusLive } from './_components/order-status-live'

export const metadata = { title: 'Pedido' }

// ─── Contrato de estados (espejo del listado / orders.py VALID_STATUSES) ──────
const STATUS_LABELS: Record<string, string> = {
  pending: 'Pendiente',
  pending_payment: 'Esperando pago',
  confirmed: 'Confirmado',
  processing: 'En proceso',
  shipped: 'Enviado',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
}
const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-warning-bg text-warning-fg border-warning-border',
  pending_payment: 'bg-warning-bg text-warning-fg border-warning-border',
  confirmed: 'bg-info-bg text-info-fg border-info-border',
  processing: 'bg-ai-bg text-ai-fg border-ai-border',
  shipped: 'bg-ai-bg text-ai-fg border-ai-border',
  delivered: 'bg-success-bg text-success-fg border-success-border',
  cancelled: 'bg-danger-bg text-danger-fg border-danger-border',
}
const PAYMENT_STATUS_LABELS: Record<string, string> = {
  pending: 'Pendiente', approved: 'Aprobado', declined: 'Rechazado',
  voided: 'Anulado', error: 'Error',
}

const cop = (n: number) => `$${(n || 0).toLocaleString('es-CO', { minimumFractionDigits: 0 })}`
const fmtDate = (s: string) =>
  new Date(s).toLocaleString('es-CO', { timeZone: 'America/Bogota', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

type OrderItem = { id: string; title: string; unit_price: number; quantity: number }
type Contact = { name: string | null; phone: string } | null

/**
 * D6 — Vista de detalle del pedido. Consumidor natural de los deep-links por id
 * (Reclamos, Contactos). Da hogar persistente al desglose de pago, al tracking
 * de envío (antes sólo mensaje transitorio) y a la auditoría de cancelación.
 *
 * Lectura tenant-scoped explícita (.eq('tenant_id')) sobre el cliente de sesión
 * (RLS activa) — mismo patrón que el listado; no expone dinero ni PII cross-tenant.
 */
export default async function OrderDetailPage(props: { params: Promise<{ id: string }> }) {
  const { id } = await props.params
  const { getCachedTenantMeta } = await import('@/utils/supabase/cached-user')
  const { tenantId } = await getCachedTenantMeta()
  if (!tenantId) notFound()

  const supabase = await createClient()

  const { data: order, error } = await supabase
    .from('orders')
    .select('id, status, total_amount, discount_amount, shipping_cost, notes, created_at, payment_method, cancellation_id, contacts(name, phone), order_items(id, title, unit_price, quantity)')
    .eq('id', id)
    .eq('tenant_id', tenantId)
    .limit(1)
    .maybeSingle()

  if (error) {
    return (
      <div className="max-w-3xl space-y-4">
        <BackLink />
        <Alert variant="destructive">
          <XCircle className="h-4 w-4" />
          <AlertDescription>No se pudo cargar el pedido. Reintenta en unos segundos.</AlertDescription>
        </Alert>
      </div>
    )
  }
  if (!order) notFound()

  // Cargas asociadas (best-effort; tenant-scoped). Un fallo aquí no oculta el pedido.
  // Track9/A7: payments quedó owner-only; esta página (cualquier miembro) lee la vista
  // proyectada payments_safe — mismas columnas operativas, sin raw_webhook (PII del pagador).
  const [{ data: payments }, { data: shipments }, { data: cancellation }] = await Promise.all([
    supabase.from('payments_safe')
      .select('provider, checkout_url, amount_in_cents, status, wompi_status, created_at')
      .eq('order_id', id).eq('tenant_id', tenantId)
      .order('created_at', { ascending: false }),
    supabase.from('shipments')
      .select('carrier, service, status, tracking_number, tracking_url, label_url, estimated_delivery, created_at')
      .eq('order_id', id).eq('tenant_id', tenantId)
      .order('created_at', { ascending: false }),
    order.cancellation_id
      ? supabase.from('order_cancellations')
          .select('reason_code, reason_text, refund_method, refund_status, amount_refunded_cents, stock_restored, created_at')
          .eq('id', order.cancellation_id).eq('tenant_id', tenantId).maybeSingle()
      : Promise.resolve({ data: null }),
  ])

  const contact = (Array.isArray(order.contacts) ? order.contacts[0] : order.contacts) as Contact
  const items = (order.order_items ?? []) as OrderItem[]
  const subtotal = items.reduce((a, i) => a + i.unit_price * i.quantity, 0)
  const shipping = order.shipping_cost ?? 0
  const discount = order.discount_amount ?? 0
  const total = order.total_amount ?? Math.max(0, subtotal + shipping - discount)
  const shipment = (shipments ?? [])[0] as
    | { carrier: string | null; service: string | null; status: string; tracking_number: string | null; tracking_url: string | null; label_url: string | null; estimated_delivery: string | null }
    | undefined
  const cancel = cancellation as
    | { reason_code: string; reason_text: string | null; refund_method: string | null; refund_status: string; amount_refunded_cents: number; stock_restored: boolean; created_at: string }
    | null

  return (
    <div className="max-w-3xl space-y-5">
      <BackLink />

      {/* T7.4 — isla realtime: celebra confirmed/delivered y refresca la data
          sin F5 (antes el detalle quedaba estático tras el pago). */}
      <OrderStatusLive orderId={order.id} />

      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12) — badges y
          total a la derecha (slot de acciones). */}
      <PageHeader
        icon={Package}
        title={`Pedido ${order.id.split('-')[0].toUpperCase()}`}
        description={
          <>
            {contact ? (contact.name || contact.phone || 'Cliente anónimo') : 'Cliente anónimo'}
            {' · '}
            <Clock className="inline h-3 w-3" /> Creado {fmtDate(order.created_at)}
          </>
        }
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border ${STATUS_COLORS[order.status] ?? 'bg-muted text-muted-foreground'}`}>
              {STATUS_LABELS[order.status] ?? order.status}
            </span>
            {order.payment_method === 'cod' && (
              <Badge variant="outline" className="text-[11px] text-success-fg border-success-border">💵 Contraentrega</Badge>
            )}
            <p className="text-2xl font-bold text-primary tabular-nums">{cop(total)}</p>
          </div>
        }
      />

      {/* Contacto */}
      <section className="rounded-xl border border-border bg-card p-4">
        <h2 className="text-sm font-semibold flex items-center gap-2 mb-2"><User className="h-4 w-4 text-muted-foreground" /> Cliente</h2>
        {contact ? (
          <div className="text-sm space-y-0.5">
            <p className="font-medium">{contact.name || 'Sin nombre'}</p>
            <p className="text-muted-foreground flex items-center gap-1"><Phone className="h-3 w-3" /> {contact.phone}</p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Cliente anónimo</p>
        )}
      </section>

      {/* Ítems + desglose */}
      <section className="rounded-xl border border-border bg-card p-4">
        <h2 className="text-sm font-semibold flex items-center gap-2 mb-3"><FileText className="h-4 w-4 text-muted-foreground" /> Detalle</h2>
        <div className="space-y-1.5 text-sm">
          {items.map(it => (
            <div key={it.id} className="flex justify-between gap-2">
              <span className="text-muted-foreground truncate">{it.quantity}x {it.title}</span>
              <span className="font-mono tabular-nums shrink-0">{cop(it.unit_price * it.quantity)}</span>
            </div>
          ))}
          <div className="flex justify-between gap-2 pt-2 mt-1 border-t border-border/50 text-muted-foreground">
            <span>Subtotal</span><span className="font-mono tabular-nums">{cop(subtotal)}</span>
          </div>
          {shipping > 0 && (
            <div className="flex justify-between gap-2 text-muted-foreground">
              <span className="flex items-center gap-1"><MapPin className="h-3 w-3" /> Envío</span>
              <span className="font-mono tabular-nums">{cop(shipping)}</span>
            </div>
          )}
          {discount > 0 && (
            <div className="flex justify-between gap-2 text-success-fg">
              <span>Descuento</span><span className="font-mono tabular-nums">−{cop(discount)}</span>
            </div>
          )}
          <div className="flex justify-between gap-2 pt-2 mt-1 border-t border-border font-semibold">
            <span>Total</span><span className="font-mono tabular-nums">{cop(total)}</span>
          </div>
        </div>
        {order.notes && (
          <p className="mt-3 pt-3 border-t border-border/50 text-xs text-muted-foreground italic">&quot;{order.notes}&quot;</p>
        )}
      </section>

      {/* Pagos */}
      {(payments ?? []).length > 0 && (
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-semibold flex items-center gap-2 mb-3"><CreditCard className="h-4 w-4 text-muted-foreground" /> Pagos</h2>
          <div className="space-y-2">
            {(payments ?? []).map((p, i) => (
              <div key={i} className="flex items-center justify-between gap-3 text-sm rounded-lg bg-muted/30 px-3 py-2">
                <div className="min-w-0">
                  <p className="font-medium capitalize">{p.provider}</p>
                  <p className="text-xs text-muted-foreground">{fmtDate(p.created_at)}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-mono tabular-nums">{cop((p.amount_in_cents ?? 0) / 100)}</p>
                  <Badge variant="outline" className="text-[10px]">{PAYMENT_STATUS_LABELS[p.status] ?? p.status}</Badge>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Envío / tracking persistente */}
      {shipment && (
        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="text-sm font-semibold flex items-center gap-2 mb-3"><Truck className="h-4 w-4 text-muted-foreground" /> Envío</h2>
          <div className="text-sm space-y-1">
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Transportadora</span>
              <span>{shipment.carrier || '—'}{shipment.service ? ` · ${shipment.service}` : ''}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-muted-foreground">Guía</span>
              <span className="font-mono">{shipment.tracking_number || 'Pendiente'}</span>
            </div>
            {shipment.estimated_delivery && (
              <div className="flex justify-between gap-2">
                <span className="text-muted-foreground">Entrega estimada</span>
                <span>{new Date(shipment.estimated_delivery).toLocaleDateString('es-CO', { timeZone: 'America/Bogota' })}</span>
              </div>
            )}
            {shipment.tracking_url && (
              <a href={shipment.tracking_url} target="_blank" rel="noopener noreferrer" className="inline-block mt-1 text-xs text-primary hover:underline">
                Rastrear envío →
              </a>
            )}
          </div>
        </section>
      )}

      {/* Auditoría de cancelación */}
      {cancel && (
        <section className="rounded-xl border border-danger-border bg-danger-bg p-4">
          <h2 className="text-sm font-semibold flex items-center gap-2 mb-3 text-danger-fg"><XCircle className="h-4 w-4" /> Cancelación</h2>
          <div className="text-sm space-y-1">
            <div className="flex justify-between gap-2"><span className="text-muted-foreground">Motivo</span><span>{cancel.reason_text || cancel.reason_code}</span></div>
            <div className="flex justify-between gap-2"><span className="text-muted-foreground">Reembolso</span><span>{cancel.refund_method ? `${cancel.refund_method} · ${cancel.refund_status}` : 'No aplica'}</span></div>
            {cancel.amount_refunded_cents > 0 && (
              <div className="flex justify-between gap-2"><span className="text-muted-foreground">Monto reembolsado</span><span className="font-mono tabular-nums">{cop(cancel.amount_refunded_cents / 100)}</span></div>
            )}
            <div className="flex justify-between gap-2"><span className="text-muted-foreground">Inventario repuesto</span><span>{cancel.stock_restored ? 'Sí' : 'No'}</span></div>
            <p className="text-xs text-muted-foreground pt-1">{fmtDate(cancel.created_at)}</p>
          </div>
        </section>
      )}
    </div>
  )
}

function BackLink() {
  return (
    <Link href="/dashboard/orders" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" /> Volver a Pedidos
    </Link>
  )
}
