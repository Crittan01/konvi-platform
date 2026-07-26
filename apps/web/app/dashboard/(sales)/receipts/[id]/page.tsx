import Link from 'next/link'
import { notFound } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import {
  cop,
  fechaCO,
  formaPago,
  lineasComprador,
  lineasVendedor,
  type Receipt,
} from '../_lib/receipt'

export const metadata = { title: 'Comprobante' }

/**
 * Comprobante imprimible.  ADR-0040.
 *
 * Ley 1480 art. 50 lit. d) obliga a poner a disposición del comprador un resumen del
 * pedido "imprimible y/o descargable". Esta página lo cumple con Cmd+P → Guardar como PDF:
 * CERO dependencias nuevas, que es la decisión que el repo ya tomó para el reporte de
 * Habeas Data (services/api/routers/data_subject_request.py).
 *
 * Todo sale del SNAPSHOT CONGELADO. No se consulta ni el pedido ni el catálogo ni el perfil
 * del tenant: si el documento cambiara al editar el perfil, no sería un comprobante sino
 * una vista.
 */
export default async function ReceiptPage(props: { params: Promise<{ id: string }> }) {
  const { id } = await props.params
  const { getCachedUser, getCachedTenantMeta } = await import('@/utils/supabase/cached-user')
  await getCachedUser()
  const { tenantId } = await getCachedTenantMeta()
  const supabase = await createClient()

  if (!tenantId) notFound()

  const { data } = await supabase
    .from('order_receipts')
    .select(
      'id, numero, issued_at, voided_at, void_reason, ack_sent_at, ack_skipped_reason, ' +
        'email_sent_at, email_skipped_reason, snapshot',
    )
    .eq('id', id)
    // RLS ya aísla; el filtro explícito es la convención del repo.
    .eq('tenant_id', tenantId)
    .maybeSingle()

  if (!data) notFound()
  const r = data as unknown as Receipt
  const s = r.snapshot ?? {}
  const t = s.totales ?? {}
  const items = s.items ?? []
  const anulado = Boolean(r.voided_at)
  const descuento = Number(t.descuento ?? 0)

  return (
    <>
      {/*
        Impresión: se ocultan los controles y se fija el tamaño de página. Tailwind 4 trae
        la variante `print:` nativa; el `@page` va en un <style> local porque es una regla
        at-rule que no tiene equivalente en utilidades.
      */}
      <style>{`
        @page { size: letter; margin: 14mm; }
        @media print {
          body { background: #fff !important; }
          /* El layout del dashboard (barra lateral, cabecera) no va en el documento. */
          aside, nav, header, footer { display: none !important; }
        }
      `}</style>

      <div className="p-4 md:p-6 max-w-3xl mx-auto">
        {/* Controles — fuera del documento impreso. */}
        <div className="flex items-center justify-between mb-6 print:hidden">
          <Link href="/dashboard/receipts" className="text-sm text-primary hover:underline">
            ← Comprobantes
          </Link>
          <p className="text-xs text-muted-foreground">
            Usa Imprimir (Ctrl/Cmd + P) y elige “Guardar como PDF”.
          </p>
        </div>

        <article className="rounded-md border border-border bg-card p-6 print:border-0 print:p-0">
          <header className="mb-5">
            <h1 className="text-xl font-semibold text-foreground">
              Comprobante de compra {r.numero}
            </h1>
            <p className="text-xs text-muted-foreground mt-1">
              Documento no fiscal · No es una factura de venta · Emitido el{' '}
              {fechaCO(r.issued_at)}
            </p>
          </header>

          {anulado && (
            <div className="mb-5 rounded-md border border-destructive/40 bg-destructive/5 p-3">
              <p className="text-sm font-semibold text-destructive">Comprobante anulado</p>
              <p className="text-xs text-destructive/90 mt-0.5">
                {r.void_reason ?? 'Sin motivo registrado'} · {fechaCO(r.voided_at)}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Este documento ya no da cuenta de una compra vigente.
              </p>
            </div>
          )}

          {s.vendedor?.completa === false && (
            <div className="mb-5 rounded-md border border-amber-700/40 bg-amber-50 p-3 print:hidden">
              <p className="text-sm text-amber-800">
                Faltan datos de identificación del vendedor
                {s.vendedor?.faltantes?.length ? `: ${s.vendedor.faltantes.join(', ')}` : ''}.
              </p>
              <p className="text-xs text-amber-700 mt-0.5">
                La Ley 1480 (art. 50 lit. a) exige que el comprador pueda identificar a quién
                le compró. Se completan en Configuración.
              </p>
            </div>
          )}

          <div className="grid gap-5 sm:grid-cols-2 mb-5">
            <section>
              {lineasVendedor(s).map(([rot, val]) => (
                <p key={rot} className="text-sm">
                  <span className="text-muted-foreground">{rot}: </span>
                  <span className="text-foreground">{val}</span>
                </p>
              ))}
            </section>
            <section>
              {lineasComprador(s).map(([rot, val]) => (
                <p key={rot} className="text-sm">
                  <span className="text-muted-foreground">{rot}: </span>
                  <span className="text-foreground">{val}</span>
                </p>
              ))}
              <p className="text-sm">
                <span className="text-muted-foreground">Forma de pago: </span>
                <span className="text-foreground">{formaPago(s)}</span>
              </p>
            </section>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="text-left font-medium py-2">Producto</th>
                  <th className="text-center font-medium py-2 w-16">Cant.</th>
                  <th className="text-right font-medium py-2 w-28 tabular-nums">Unitario</th>
                  <th className="text-right font-medium py-2 w-28 tabular-nums">Total</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-3 text-muted-foreground">
                      Sin ítems registrados
                    </td>
                  </tr>
                )}
                {items.map((i, n) => (
                  <tr key={n} className="border-b border-border/60">
                    <td className="py-2 text-foreground">{i.titulo}</td>
                    <td className="py-2 text-center tabular-nums">{i.cantidad}</td>
                    <td className="py-2 text-right tabular-nums">{cop(i.precio_unitario)}</td>
                    <td className="py-2 text-right tabular-nums">{cop(i.total_linea)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 ml-auto max-w-xs text-sm">
            <div className="flex justify-between py-1">
              <span className="text-muted-foreground">Subtotal</span>
              <span className="tabular-nums">{cop(t.subtotal)}</span>
            </div>
            {/* El descuento solo aparece si lo hubo: una línea "Descuento $0" es ruido. */}
            {descuento > 0 && (
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground">Descuento</span>
                <span className="tabular-nums text-emerald-700">− {cop(descuento)}</span>
              </div>
            )}
            {/* Art. 50 lit. c): los gastos de envío, informados POR SEPARADO. */}
            <div className="flex justify-between py-1">
              <span className="text-muted-foreground">Envío</span>
              <span className="tabular-nums">{cop(t.envio)}</span>
            </div>
            <div className="flex justify-between py-2 mt-1 border-t-2 border-foreground font-semibold">
              <span>Total</span>
              <span className="tabular-nums">
                {cop(t.total)} {t.moneda ?? 'COP'}
              </span>
            </div>
          </div>

          <footer className="mt-6 pt-4 border-t border-border text-xs text-muted-foreground space-y-1">
            <p>
              <strong className="text-foreground">Garantía.</strong> Los productos nuevos
              tienen garantía legal de un año desde la entrega, salvo que se informe un plazo
              mayor.
            </p>
            <p>
              Comprobante de compra no fiscal. Para efectos tributarios, solicita la factura
              al vendedor.
            </p>
          </footer>
        </article>
      </div>
    </>
  )
}
