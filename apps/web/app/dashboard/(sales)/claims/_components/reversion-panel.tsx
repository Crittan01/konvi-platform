'use client'

/**
 * La reversión del pago dentro del reclamo.
 *
 * NO es el reembolso que está arriba en esta misma pantalla. Acá el dinero lo devuelve el
 * emisor del medio de pago del comprador, no nosotros; lo único que nos toca —y es
 * obligatorio— es emitir la constancia de la queja con fecha y causal (Decreto 1074
 * art. 2.2.2.51.4). El comprador la necesita para notificar a su banco (art. 2.2.2.51.7
 * num. 6): sin ella, no puede ejercer el derecho.
 *
 * Por eso el panel se ve incluso cuando no hay nada radicado: si el operador no sabe que
 * esta figura existe, no la usa, y el incumplimiento es silencioso.
 */

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, FileText, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

import {
  obtenerReversion, registrarMovimientoReversion, registrarReversion,
  type ConstanciaReversion,
} from '../actions'
import {
  CAUSALES, admiteReversion, causalLabel, cop, estadoConstancia, estadoDinero, fechaCO,
} from '../_lib/reversion'

type Props = {
  claimId: string
  formaPago: string | null | undefined
  totalPedido: number | null | undefined
  canWrite: boolean
}

export default function ReversionPanel({ claimId, formaPago, totalPedido, canWrite }: Props) {
  const [rev, setRev] = useState<ConstanciaReversion | null>(null)
  const [cargando, setCargando] = useState(true)
  const [abierto, setAbierto] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [causal, setCausal] = useState('producto_defectuoso')
  const [razones, setRazones] = useState('')
  const [valor, setValor] = useState('')
  const [instrumento, setInstrumento] = useState('')
  const [bienADisposicion, setBien] = useState(false)

  const cargar = useCallback(async () => {
    setCargando(true)
    const r = await obtenerReversion(claimId)
    if (!r.error) setRev(r.data ?? null)
    setCargando(false)
  }, [claimId])

  useEffect(() => { void cargar() }, [cargar])

  const procede = admiteReversion(formaPago)

  const radicar = async () => {
    const monto = parseFloat(valor)
    if (!Number.isFinite(monto) || monto <= 0) {
      setError('Indica el valor sobre el que se pide la reversión.')
      return
    }
    if (razones.trim().length < 3) {
      setError('Transcribe las razones que dio el comprador (art. 2.2.2.51.5 num. 1).')
      return
    }
    setEnviando(true)
    setError(null)
    const r = await registrarReversion(claimId, {
      causal,
      razones: razones.trim(),
      valor: monto,
      instrumento: instrumento.trim() || undefined,
      // Parcial cuando no se pide el total: el art. 2.2.2.51.3 obliga a que el valor
      // quede claro, y un monto menor sin decir que es parcial parece un error de cuentas.
      es_parcial: typeof totalPedido === 'number' ? monto < totalPedido : false,
      bien_a_disposicion: bienADisposicion,
    })
    setEnviando(false)
    if (r.error) { setError(r.error); return }
    setRev(r.data ?? null)
    setAbierto(false)
    toast.success(`Constancia ${r.data?.radicado ?? ''} emitida y en camino al comprador`)
  }

  const marcarMovimiento = async (via: 'reembolso_directo' | 'reversion_emisor') => {
    if (!rev) return
    const r = await registrarMovimientoReversion(claimId, via, rev.valor)
    if (r.error) { toast.error(r.error); return }
    setRev(r.data ?? rev)
    if (r.data?.doble_pago_detectado_at) {
      toast.error('El dinero salió DOS veces — hay que contactar al comprador')
    }
  }

  if (cargando) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Revisando reversión del pago…
      </div>
    )
  }

  // ── Ya radicada: se muestra la constancia y en qué va ────────────────────
  if (rev) {
    const constancia = estadoConstancia(rev)
    const dinero = estadoDinero(rev)
    return (
      <section className="rounded-lg border border-border p-3">
        <header className="flex items-center justify-between gap-2 mb-2">
          <h4 className="text-sm font-medium flex items-center gap-1.5">
            <FileText className="w-4 h-4" /> Reversión del pago · {rev.radicado}
          </h4>
        </header>

        <dl className="text-sm space-y-1">
          <div>
            <dt className="inline text-muted-foreground">Presentada: </dt>
            <dd className="inline">{fechaCO(rev.presentada_at)}</dd>
          </div>
          <div>
            <dt className="inline text-muted-foreground">Causal: </dt>
            <dd className="inline">{causalLabel(rev.causal)}</dd>
          </div>
          <div>
            <dt className="inline text-muted-foreground">Valor: </dt>
            <dd className="inline tabular-nums">
              {cop(rev.valor)}{rev.es_parcial ? ' (parcial)' : ''}
            </dd>
          </div>
          {rev.instrumento && (
            <div>
              <dt className="inline text-muted-foreground">Medio de pago: </dt>
              <dd className="inline">{rev.instrumento}</dd>
            </div>
          )}
        </dl>

        <p className={`mt-2 text-xs ${constancia.alerta ? 'text-amber-800' : 'text-muted-foreground'}`}>
          {constancia.alerta && <AlertTriangle className="w-3.5 h-3.5 inline mr-1" />}
          Constancia: {constancia.texto}
        </p>
        <p className={`mt-1 text-xs ${dinero.alerta ? 'text-red-700 font-medium' : 'text-muted-foreground'}`}>
          {dinero.alerta && <AlertTriangle className="w-3.5 h-3.5 inline mr-1" />}
          {dinero.texto}
        </p>

        {canWrite && (
          <div className="flex flex-wrap gap-2 mt-3">
            <Button
              size="sm" variant="outline"
              disabled={Boolean(rev.reembolso_directo_at)}
              onClick={() => void marcarMovimiento('reembolso_directo')}
            >
              Le reembolsamos directo
            </Button>
            <Button
              size="sm" variant="outline"
              disabled={Boolean(rev.reversion_confirmada_at)}
              onClick={() => void marcarMovimiento('reversion_emisor')}
            >
              El emisor reversó
            </Button>
          </div>
        )}
      </section>
    )
  }

  // ── Sin radicar ─────────────────────────────────────────────────────────
  return (
    <section className="rounded-lg border border-dashed border-border p-3">
      <h4 className="text-sm font-medium mb-1">Reversión del pago</h4>
      {!procede ? (
        <p className="text-xs text-muted-foreground">
          No aplica: la reversión solo procede sobre pagos electrónicos. En contra entrega
          el camino es el reembolso (Decreto 1074 art. 2.2.2.51.1).
        </p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground mb-2">
            Si el comprador pidió que le devuelvan el cargo, radícalo acá. La devolución la
            hace el emisor de su medio de pago; nosotros debemos entregarle la constancia
            con fecha y causal, que es lo que él le presenta a su banco.
          </p>
          {canWrite && (
            <Button size="sm" onClick={() => { setAbierto(true); setError(null) }}>
              Radicar reversión
            </Button>
          )}
        </>
      )}

      <Dialog open={abierto} onOpenChange={setAbierto}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>Radicar reversión del pago</DialogTitle>
          </DialogHeader>

          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="causal">Causal que invocó el comprador</Label>
              <Select value={causal} onValueChange={setCausal}>
                <SelectTrigger id="causal"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CAUSALES.map(c => (
                    <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                La escoge él, no la deducimos: la norma exige indicar la causal.
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="razones">Lo que dijo, en sus palabras</Label>
              <Textarea
                id="razones" value={razones} rows={3}
                onChange={e => setRazones(e.target.value)}
                placeholder="Transcribe lo que escribió el comprador"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="valor">Valor a reversar</Label>
              <Input
                id="valor" type="number" min="1" value={valor}
                onChange={e => setValor(e.target.value)}
                placeholder={typeof totalPedido === 'number' ? String(totalPedido) : ''}
              />
              {typeof totalPedido === 'number' && (
                <p className="text-xs text-muted-foreground">
                  Total del pedido: {cop(totalPedido)}. Un valor menor se radica como
                  reversión parcial.
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="instrumento">Medio de pago (opcional)</Label>
              <Input
                id="instrumento" value={instrumento} maxLength={120}
                onChange={e => setInstrumento(e.target.value)}
                placeholder="Visa terminada en 4242"
              />
              <p className="text-xs text-muted-foreground">
                Solo el descriptor. Nunca el número completo de la tarjeta.
              </p>
            </div>

            <label className="flex items-start gap-2 text-sm">
              <Checkbox
                checked={bienADisposicion}
                onCheckedChange={v => setBien(v === true)}
              />
              <span>
                El comprador dejó el producto a disposición para recogerlo
                <span className="block text-xs text-muted-foreground">
                  Con eso se entiende satisfecha su obligación de devolverlo.
                </span>
              </span>
            </label>

            {error && <p className="text-sm text-red-700">{error}</p>}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAbierto(false)} disabled={enviando}>
              Cancelar
            </Button>
            <Button onClick={() => void radicar()} disabled={enviando}>
              {enviando ? 'Radicando…' : 'Radicar y emitir constancia'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
