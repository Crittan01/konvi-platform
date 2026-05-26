'use client'

/**
 * Aveonline — Cómo funciona. Rev. 108.
 *
 * Componente educacional para que el dueño del tenant entienda:
 *  - Crédito (pago online vía Wompi) vs COD (recauda el courier)
 *  - Quién cobra qué, cuándo se liquida el dinero
 *  - Cómo se manejan novedades, devoluciones, cancelaciones
 *  - Qué partes son automáticas vs manuales
 *
 * Fuentes (todas validadas):
 *  - Dossier §7 (COD), §8 (cancelación), §9 (devoluciones)
 *  - Contrato Aveonline: app.aveonline.co/app/contrato/terminosCondiciones.html
 *  - Sitio comercial: aveonline.co/servicios-pago-contraentrega/
 */
import { useState } from 'react'
import {
  CreditCard, Coins, Package, RefreshCcw, AlertTriangle,
  ChevronDown, ChevronRight, ExternalLink,
} from 'lucide-react'

type Section = {
  id: string
  title: string
  Icon: typeof CreditCard
  color: string
  content: React.ReactNode
}

const SECTIONS: Section[] = [
  {
    id: 'credito',
    title: '1. Pago anticipado (crédito) — vía Wompi',
    Icon: CreditCard,
    color: 'text-blue-700 bg-blue-50 border-blue-200',
    content: (
      <div className="space-y-3 text-sm text-foreground">
        <p>
          El cliente paga por adelantado con tarjeta / PSE / Nequi /
          Bancolombia Transfer vía <strong>Wompi</strong> antes de que
          generes la guía. Es el flujo predeterminado.
        </p>
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">Cuándo recibes el dinero</div>
          <div className="text-muted-foreground">
            Wompi liquida a tu cuenta bancaria <strong>al siguiente día hábil</strong> después
            de la aprobación (T+1). Comisión Wompi: ~2.99% + IVA por
            transacción (varía por método de pago).
          </div>
        </div>
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">Quién paga el envío</div>
          <div className="text-muted-foreground">
            Tú asumes el costo del envío y lo cobras al cliente como parte
            del precio total (transparente en el carrito antes de pagar).
          </div>
        </div>
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">Si el cliente devuelve</div>
          <div className="text-muted-foreground">
            Pagas el flete de devolución (mismo costo que el envío original).
            El reembolso al cliente lo procesas tú (Wompi soporta refunds
            parciales/totales — pendiente UI en Konvi).
          </div>
        </div>
      </div>
    ),
  },
  {
    id: 'cod',
    title: '2. Pago contraentrega (COD) — recauda el courier',
    Icon: Coins,
    color: 'text-emerald-700 bg-emerald-50 border-emerald-200',
    content: (
      <div className="space-y-3 text-sm text-foreground">
        <p>
          El courier entrega el pedido y <strong>recauda el dinero al cliente</strong>
          en el momento de la entrega. Aveonline te liquida después según el carrier.
        </p>

        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs space-y-1.5">
          <div className="font-medium text-amber-900">⚠️ Requiere activación per-carrier</div>
          <div className="text-amber-800">
            En la pestaña <strong>Carriers</strong> activa el toggle "Pago
            contraentrega" para cada transportadora que aceptes COD. La decisión
            comercial depende de tu contrato Aveonline.
          </div>
        </div>

        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-2">
          <div className="font-medium text-foreground">Plazos de liquidación (dossier §7.2)</div>
          <table className="w-full">
            <thead className="text-muted-foreground">
              <tr>
                <th className="text-left font-normal pb-1">Carrier</th>
                <th className="text-left font-normal pb-1">Días hábiles</th>
                <th className="text-left font-normal pb-1">Día de pago</th>
              </tr>
            </thead>
            <tbody className="text-muted-foreground">
              <tr><td>TCC / Domina</td><td>4–6</td><td>Martes y viernes</td></tr>
              <tr><td>Coordinadora</td><td>5–11 (contrato)</td><td>Variable</td></tr>
              <tr><td>Servientrega</td><td>7–11</td><td>Viernes</td></tr>
              <tr><td>Envía</td><td>7–11 (contrato 9–15)</td><td>Viernes</td></tr>
              <tr><td>Interrapidísimo</td><td>7–11 (contrato 13–19)</td><td>Viernes</td></tr>
              <tr><td>Saferbo</td><td>7–11</td><td>Viernes</td></tr>
            </tbody>
          </table>
        </div>

        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">Comisión Aveonline COD</div>
          <div className="text-muted-foreground">
            Desde <strong>2.40% sobre el monto recaudado</strong>, varía por
            carrier según tu contrato. La comisión se cobra
            <strong> incluso si el envío se devuelve </strong>
            (cláusula contractual).
          </div>
        </div>

        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs">
          <div className="font-medium text-amber-900 mb-1">⚠️ Reconciliación manual</div>
          <div className="text-amber-800">
            La API de Aveonline <strong>NO expone</strong> endpoints para consultar
            liquidaciones COD. Tendrás que revisar el panel{' '}
            <a
              href="https://app.aveonline.co/wallet"
              target="_blank"
              rel="noopener noreferrer"
              className="underline inline-flex items-center gap-1"
            >
              app.aveonline.co/wallet <ExternalLink className="h-3 w-3" />
            </a>{' '}
            semanalmente para conciliar manualmente con tus pedidos.
          </div>
        </div>

        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">Si el cliente rechaza el paquete</div>
          <div className="text-muted-foreground">
            No hay recaudo (no cobras al cliente). Pero:
            <ul className="ml-4 mt-1 list-disc space-y-0.5">
              <li>Aveonline cobra la comisión COD igualmente.</li>
              <li>Tú pagas el flete devolución.</li>
              <li><strong>Envía y Coordinadora</strong> cobran flete devolución; los demás no.</li>
            </ul>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: 'novedades',
    title: '3. Novedades en la entrega',
    Icon: AlertTriangle,
    color: 'text-amber-700 bg-amber-50 border-amber-200',
    content: (
      <div className="space-y-3 text-sm text-foreground">
        <p>
          Si el courier no logra entregar (dirección errónea, cliente ausente,
          rechazo, etc.), reporta una <strong>novedad</strong>.
        </p>
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-2">
          <div className="font-medium text-foreground">Plazos del contrato (dossier §9)</div>
          <ul className="text-muted-foreground ml-4 list-disc space-y-1">
            <li>
              Tienes <strong>3 días hábiles</strong> para resolver una novedad.
              Si no se resuelve → devolución automática al remitente.
            </li>
            <li>
              <strong>Daños/averías</strong>: reclamar dentro de <strong>16 horas</strong>
              con evidencia fotográfica.
            </li>
            <li>
              <strong>Extravíos</strong>: reportar tras <strong>3 días sin actualización</strong> de tracking.
            </li>
            <li>
              Cambio de dirección post-creación: requiere PQR a{' '}
              <a href="mailto:pqr@aveonline.co" className="underline">pqr@aveonline.co</a>{' '}
              (cobro adicional).
            </li>
          </ul>
        </div>
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">Qué hace Konvi automáticamente</div>
          <div className="text-muted-foreground">
            Cuando Aveonline reporta una novedad vía webhook, el cliente recibe
            un WhatsApp + email "⚠️ Novedad con tu envío" para que te conteste
            con la solución. Tu operador ve la conversación en el Inbox.
          </div>
        </div>
      </div>
    ),
  },
  {
    id: 'devoluciones',
    title: '4. Devoluciones (RMA)',
    Icon: RefreshCcw,
    color: 'text-purple-700 bg-purple-50 border-purple-200',
    content: (
      <div className="space-y-3 text-sm text-foreground">
        <p>
          Si el cliente recibe el pedido y quiere devolverlo, hay 3 caminos:
        </p>
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">
            (a) Boomerang — guía ida + vuelta automática
          </div>
          <div className="text-muted-foreground">
            Aveonline soporta el parámetro <code className="font-mono text-[10px] bg-background px-1">cartaporte=1</code>
            que genera una guía que <strong>cubre los 2 viajes</strong>: tu bodega → cliente,
            y si el cliente rechaza → cliente → tu bodega. La misma guía. No tienes
            que hacer trámite adicional. Validar cobertura con tu contrato — algunos
            carriers como Coordinadora y Servientrega lo aceptan, otros no.
          </div>
        </div>
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">
            (b) Guía nueva con origen/destino invertidos
          </div>
          <div className="text-muted-foreground">
            Generas una guía nueva con origen=cliente, destino=tu bodega.
            Tú pagas. Útil cuando el cliente ya recibió y devuelve después.
          </div>
        </div>
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">
            (c) PQR manual
          </div>
          <div className="text-muted-foreground">
            Email a <a href="mailto:pqr@aveonline.co" className="underline">pqr@aveonline.co</a>{' '}
            con número de guía + motivo + evidencia. Último recurso cuando
            (a) y (b) no aplican.
          </div>
        </div>
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs">
          <div className="font-medium text-amber-900 mb-0.5">⚠️ Pendiente en Konvi</div>
          <div className="text-amber-800">
            El tool de devoluciones 1-click aún no está implementado. Hoy
            tu operador debe usar caminos (b) o (c) manualmente desde el Inbox.
          </div>
        </div>
      </div>
    ),
  },
  {
    id: 'cancelacion',
    title: '5. Cancelación de guías',
    Icon: Package,
    color: 'text-red-700 bg-red-50 border-red-200',
    content: (
      <div className="space-y-3 text-sm text-foreground">
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">Antes de recoger</div>
          <div className="text-muted-foreground">
            Aveonline permite "eliminar relación de envíos" — desactiva la guía
            lógicamente. La integración Konvi no lo expone aún en UI; contacta
            soporte para esto.
          </div>
        </div>
        <div className="rounded-md bg-muted/40 p-3 text-xs space-y-1.5">
          <div className="font-medium text-foreground">Después de recogida</div>
          <div className="text-muted-foreground">
            <strong>No se puede cancelar una guía ya recogida</strong> — Aveonline
            no expone endpoint. Si necesitas detener el envío, debes esperar
            a que llegue al cliente y luego procesar como devolución (sección 4),
            o escalar a <a href="mailto:pqr@aveonline.co" className="underline">pqr@aveonline.co</a>.
          </div>
        </div>
      </div>
    ),
  },
]

export default function AveonlineHowItWorks() {
  const [open, setOpen] = useState<Set<string>>(new Set(['credito']))

  const toggle = (id: string) => {
    setOpen(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-border bg-card p-5">
        <h3 className="font-semibold text-foreground mb-1">Cómo funciona la operación</h3>
        <p className="text-sm text-muted-foreground">
          Guía operativa para entender el flujo real con Aveonline:
          quién cobra qué, cuándo te liquidan, cómo manejar novedades.
          Datos basados en el contrato oficial y la página comercial.
        </p>
      </div>

      {SECTIONS.map(s => {
        const isOpen = open.has(s.id)
        return (
          <div
            key={s.id}
            className={`rounded-lg border ${s.color.split(' ').slice(2).join(' ')} bg-card overflow-hidden`}
          >
            <button
              type="button"
              onClick={() => toggle(s.id)}
              className="w-full px-5 py-4 flex items-center justify-between gap-3 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-md ${s.color.split(' ').slice(0, 2).join(' ')}`}>
                  <s.Icon className="h-4 w-4" />
                </div>
                <span className="font-medium text-foreground text-left">{s.title}</span>
              </div>
              {isOpen ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
            {isOpen && (
              <div className="px-5 pb-5 pt-1 border-t border-border">{s.content}</div>
            )}
          </div>
        )
      })}

      <div className="rounded-lg border border-border bg-muted/20 p-4 text-xs text-muted-foreground">
        <strong className="text-foreground">¿Dudas operativas concretas?</strong>{' '}
        Tu asesor logístico (definido en Setup) y{' '}
        <a href="mailto:desarrollo1@aveonline.co" className="underline">
          desarrollo1@aveonline.co
        </a>{' '}
        son los contactos para confirmar condiciones de tu contrato específico.
      </div>
    </div>
  )
}
