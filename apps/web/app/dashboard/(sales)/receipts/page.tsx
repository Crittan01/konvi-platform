import Link from 'next/link'
import { createClient } from '@/utils/supabase/server'
import { FileText, ReceiptText } from 'lucide-react'
import { PageHeader } from '@/components/ui/page-header'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { cop, fechaCO, estadoEntrega, type Receipt } from './_lib/receipt'

const POR_PAGINA = 25

export const metadata = { title: 'Comprobantes' }

/**
 * Comprobantes de compra emitidos.
 *
 * Lee `order_receipts` con el cliente de SESIÓN (nunca service_role): RLS aísla por tenant
 * y `authenticated` tiene SELECT pero no escritura — un comprobante es prueba de una
 * operación de consumo y no se edita desde la consola. El filtro explícito por tenant_id
 * se mantiene igual, que es la convención del repo aunque RLS ya aísle.
 */
export default async function ReceiptsPage(props: {
  searchParams: Promise<{ page?: string }>
}) {
  const sp = await props.searchParams
  const { getCachedUser, getCachedTenantMeta } = await import('@/utils/supabase/cached-user')
  await getCachedUser()
  const { tenantId } = await getCachedTenantMeta()
  const supabase = await createClient()

  const parsed = parseInt(sp.page ?? '1', 10)
  const page = Number.isFinite(parsed) && parsed > 0 ? parsed : 1
  const offset = (page - 1) * POR_PAGINA

  let receipts: Receipt[] = []
  let total = 0
  let loadError: string | null = null

  if (tenantId) {
    const { data, count, error } = await supabase
      .from('order_receipts')
      .select(
        'id, numero, issued_at, voided_at, void_reason, ack_sent_at, ack_skipped_reason, ' +
          'email_sent_at, email_skipped_reason, snapshot',
        { count: 'exact' },
      )
      .eq('tenant_id', tenantId)
      .order('issued_at', { ascending: false })
      .range(offset, offset + POR_PAGINA - 1)
    if (error) loadError = error.message
    receipts = (data as Receipt[] | null) ?? []
    total = count ?? 0
  }

  const paginas = Math.max(1, Math.ceil(total / POR_PAGINA))

  return (
    <div className="p-4 md:p-6 space-y-4">
      {/* Cabecera de módulo con identidad (firma Kaiu, T7.12) */}
      <PageHeader
        icon={FileText}
        title="Comprobantes de compra"
        description="Documento no fiscal que se le entrega al comprador. No es una factura de venta."
      />

      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          No se pudieron cargar los comprobantes: {loadError}
        </div>
      )}

      {!loadError && receipts.length === 0 && (
        <EmptyState
          icon={ReceiptText}
          description="Todavía no hay comprobantes. Se emiten solos unos minutos después de que un pedido queda confirmado."
        />
      )}

      {receipts.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-3 py-2">Número</th>
                <th className="text-left font-medium px-3 py-2">Emitido</th>
                <th className="text-right font-medium px-3 py-2 tabular-nums">Total</th>
                <th className="text-left font-medium px-3 py-2">Entrega al comprador</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {receipts.map((r) => {
                const entrega = estadoEntrega(r)
                const anulado = Boolean(r.voided_at)
                return (
                  <tr key={r.id} className="border-t border-border">
                    <td className="px-3 py-2 font-mono">
                      {r.numero}
                      {anulado && (
                        <Badge variant="destructive" className="ml-2 align-middle">
                          Anulado
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{fechaCO(r.issued_at)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {cop(r.snapshot?.totales?.total)}
                    </td>
                    <td
                      className={`px-3 py-2 ${
                        entrega.alerta ? 'text-amber-700' : 'text-muted-foreground'
                      }`}
                    >
                      {entrega.texto}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Link
                        href={`/dashboard/receipts/${r.id}`}
                        className="text-primary hover:underline"
                      >
                        Ver e imprimir
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {paginas > 1 && (
        <div className="flex items-center gap-3 text-sm">
          {page > 1 && (
            <Link href={`/dashboard/receipts?page=${page - 1}`} className="text-primary hover:underline">
              Anterior
            </Link>
          )}
          <span className="text-muted-foreground">
            Página {page} de {paginas}
          </span>
          {page < paginas && (
            <Link href={`/dashboard/receipts?page=${page + 1}`} className="text-primary hover:underline">
              Siguiente
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
