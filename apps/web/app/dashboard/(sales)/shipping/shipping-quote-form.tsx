'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Loader2, Package, ChevronDown, ChevronUp, Check, MapPin, Box, Zap, DollarSign, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
// Label e Input se usan en la sección de paquete
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'
import { createIdempotencyKey } from '@/lib/idempotency'
import { normalizeDaneCode, resolveFastestIdx } from './_lib/shipping-rates'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface ShippingOrigin {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string; dane_code?: string
}

interface Rate {
  rate_id?: string
  id?: string
  carrier?: string
  service?: string
  total_price?: number
  currency?: string
  delivery_date?: string
  // Rev. 107 — campos extendidos Aveonline (provider único activo, ADR-0019).
  delivery_days?: number | null
  delivery_estimate?: string
  carrier_logo_url?: string | null
  carrier_logo_url_alt?: string | null
  route_type?: string | null
  weight_real_kg?: number | null
  weight_volumetric_kg?: number | null
  units?: number | null
  declared_value_cop?: number | null
  valuation_percent?: number | null
  freight_total_cop?: number | null
  handling_cop?: number | null
  cod_extras_cop?: number | null
  subtotal_cop?: number | null
  cod_supported?: boolean
  provider?: string
  [key: string]: unknown
}

interface Props {
  shippingOrigin: ShippingOrigin | null
  orderId?:       string | null
  destDefaults?:  Record<string, string> | null
  // Valor declarado por defecto: order.total_amount cuando se cotiza sobre un
  // pedido; null → default de cotización libre ($50.000). Ver decisión F2.
  defaultDeclaredValue?: number | null
  onQuoted?:      () => void
}

// Default de cotización libre (sin pedido). Debe coincidir con el fallback del
// backend (services/api/routers/shipping.py: `declared_total ... or 50000`)
// para que el estimado mostrado no diverja de la guía real que factura Aveonline.
const FREE_QUOTE_DECLARED_VALUE = 50000

// ─── GeoSelector — solo departamento + ciudad (mínimo para cotizar) ──────────

function GeoSelector({
  prefix, defaults = {},
}: {
  prefix: string
  defaults?: Record<string, string>
}) {
  const initDane     = normalizeDaneCode(defaults.dane_code)
  const initDpto     = DEPARTAMENTOS.find(d => d.nombre === defaults.state)?.codigo ?? ''
  const initMunis    = initDpto ? getMunicipiosByDpto(initDpto) : []
  const initMuniCode = initMunis.find(m => m.codigo === initDane || m.nombre === defaults.city)?.codigo ?? ''

  const [dptoCode, setDptoCode]          = useState(initDpto)
  const [city, setCity]                  = useState(defaults.city ?? '')
  const [municipioCodigo, setMuniCodigo] = useState(initMuniCode)

  const municipios = dptoCode ? getMunicipiosByDpto(dptoCode) : []
  const dptoNombre = DEPARTAMENTOS.find(d => d.codigo === dptoCode)?.nombre ?? ''
  const daneCode   = municipioCodigo || (city ? initDane : '')

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      <input type="hidden" name={`${prefix}_state`}     value={dptoNombre} />
      <input type="hidden" name={`${prefix}_city`}      value={city} />
      <input type="hidden" name={`${prefix}_dane_code`} value={daneCode} />
      <input type="hidden" name={`${prefix}_country`}   value="CO" />

      <div className="space-y-1">
        <Label className="text-xs">Departamento</Label>
        <Select
          value={dptoCode || undefined}
          onValueChange={v => { setDptoCode(v); setCity(''); setMuniCodigo('') }}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder="Seleccionar..." />
          </SelectTrigger>
          <SelectContent>
            {DEPARTAMENTOS.map(d => (
              <SelectItem key={d.codigo} value={d.codigo}>{d.nombre}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <Label className="text-xs">Ciudad / Municipio</Label>
        <Select
          value={city || undefined}
          onValueChange={v => {
            const muni = municipios.find(m => m.nombre === v)
            setCity(v)
            setMuniCodigo(muni?.codigo ?? '')
          }}
          disabled={!dptoCode}
        >
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder={dptoCode ? 'Seleccionar...' : 'Elige dpto.'} />
          </SelectTrigger>
          <SelectContent>
            {municipios.map(m => (
              <SelectItem key={m.codigo} value={m.nombre}>{m.nombre}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}

function readGeo(formData: FormData, prefix: string) {
  const daneCode = normalizeDaneCode(formData.get(`${prefix}_dane_code`) as string)
  return {
    city:       formData.get(`${prefix}_city`)    as string,
    state:      formData.get(`${prefix}_state`)   as string,
    country:    formData.get(`${prefix}_country`) as string || 'CO',
    postalCode: daneCode,
    dane_code:  daneCode,
  }
}

// ─── Componente ───────────────────────────────────────────────────────────────

export default function ShippingQuoteForm({ shippingOrigin, orderId = null, destDefaults = null, defaultDeclaredValue = null, onQuoted = () => {} }: Props) {
  // Default del input de valor declarado: total del pedido (si aplica) o el
  // fallback de cotización libre. Opcional: el operador puede sobrescribirlo.
  const declaredValueDefault = defaultDeclaredValue && defaultDeclaredValue > 0
    ? Math.round(defaultDeclaredValue)
    : FREE_QUOTE_DECLARED_VALUE
  const [open, setOpen]               = useState(!!orderId)
  const [submitting, setSubmitting]   = useState(false)
  const [error, setError]             = useState<string | null>(null)
  const [result, setResult]           = useState<{ shipmentId: string | null; rates: Rate[]; highlights?: { cheapest?: Rate; fastest?: Rate } } | null>(null)
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null)
  const [saving, setSaving]           = useState(false)
  const [saved, setSaved]             = useState(false)
  const [saveError, setSaveError]     = useState<string | null>(null)

  const originGeo: Record<string, string> = shippingOrigin ? {
    city:      shippingOrigin.city        ?? '',
    state:     shippingOrigin.state       ?? '',
    dane_code: normalizeDaneCode(shippingOrigin.dane_code ?? shippingOrigin.postal_code),
    country:   shippingOrigin.country     ?? 'CO',
  } : {}

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    setResult(null)
    setSelectedIdx(null)
    setSaved(false)

    const formData = new FormData(e.currentTarget)
    const origin   = readGeo(formData, 'origin')
    const dest     = readGeo(formData, 'dest')

    if (!origin.state || !origin.city) { setError('Selecciona departamento y ciudad de origen.'); setSubmitting(false); return }
    if (!dest.state   || !dest.city)   { setError('Selecciona departamento y ciudad de destino.'); setSubmitting(false); return }
    if (!origin.dane_code || origin.dane_code.length !== 5) { setError('Origen inválido: selecciona una ciudad con código DANE válido.'); setSubmitting(false); return }
    if (!dest.dane_code   || dest.dane_code.length !== 5)   { setError('Destino inválido: selecciona una ciudad con código DANE válido.'); setSubmitting(false); return }

    // Valor declarado: input opcional. Vacío o inválido → cae al default
    // (total del pedido o $50.000). El backend reparte declaredValueCop y usa
    // 50000 si viene 0/ausente, así que enviamos siempre un entero positivo.
    const declaredRaw = parseInt(formData.get('declared_value') as string, 10)
    const declaredValueCop = Number.isFinite(declaredRaw) && declaredRaw > 0
      ? declaredRaw
      : declaredValueDefault

    const payload = {
      order_id:    orderId,
      origin,
      destination: dest,
      parcels: [{
        weight:          parseFloat(formData.get('weight') as string)  || 1,
        length:          parseFloat(formData.get('length') as string)  || 10,
        width:           parseFloat(formData.get('width')  as string)  || 10,
        height:          parseFloat(formData.get('height') as string)  || 10,
        insuranceAmount: 0,
        declaredValueCop,
      }],
    }

    try {
      const quoteKey = createIdempotencyKey('shipping.quote')
      const res = await fetch('/api/shipping/quote', {
        method:  'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': quoteKey,
        },
        body:    JSON.stringify(payload),
        signal:  AbortSignal.timeout(35000),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Error desconocido' }))
        setError(err.detail || 'No se pudo obtener la cotización')
      } else {
        const data = await res.json()
        const rawRates = data.rates
        let ratesList: Rate[] = []
        if (Array.isArray(rawRates)) {
          ratesList = rawRates
        } else if (rawRates && typeof rawRates === 'object') {
          const nested = (rawRates as Record<string, unknown>).data
          ratesList = Array.isArray(nested) ? nested as Rate[] : []
        }
        // 7. Ordenar por precio ascendente (más económico primero)
        ratesList.sort((a, b) => (Number(a.total_price) || 999999) - (Number(b.total_price) || 999999))
        const highlights = (data.highlights ?? undefined) as { cheapest?: Rate; fastest?: Rate } | undefined
        const shipmentId = (data.shipment_id ?? null) as string | null
        setResult({ shipmentId, rates: ratesList, highlights })
        // El insert de la fila shipment va en try/except en el backend y puede
        // responder 201 con shipment_id=null (columna faltante, RLS, etc.). Sin
        // este aviso el operador cree que guardó y al seleccionar tarifa haría
        // PATCH a /api/shipping/null/rate → 404 silencioso.
        if (!shipmentId && ratesList.length > 0) {
          setError('Se obtuvieron tarifas pero no se pudo guardar la cotización. Podrás comparar precios, pero para dejar la tarifa registrada vuelve a cotizar.')
        }
      }
    } catch {
      setError('Tiempo de espera agotado o error de red. Intenta de nuevo.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSelectRate = async (idx: number) => {
    if (!result) return
    // Guard: sin shipmentId el PATCH iría a /api/shipping/null/rate → 404.
    // No dejamos que el operador crea que guardó algo que no persistió.
    if (!result.shipmentId) {
      setSaveError('No se puede guardar: la cotización no quedó registrada. Vuelve a cotizar.')
      toast.error('La cotización no quedó registrada. Vuelve a cotizar.')
      return
    }
    setSelectedIdx(idx)
    setSaving(true)
    setSaved(false)
    setSaveError(null)
    const rate = result.rates[idx]
    try {
      const rateKey = createIdempotencyKey('shipping.rate.confirm')
      const res = await fetch(`/api/shipping/${result.shipmentId}/rate`, {
        method:  'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': rateKey,
        },
        body:    JSON.stringify(rate),
        signal:  AbortSignal.timeout(10000),
      })
      if (res.ok) {
        setSaved(true)
        toast.success('Tarifa guardada')
        onQuoted()
      } else {
        const err = await res.json().catch(() => ({ detail: '' }))
        const msg = err.detail || 'No se pudo guardar la tarifa. Intenta de nuevo.'
        setSaveError(msg)
        toast.error(msg)
      }
    } catch {
      const msg = 'Error de red al guardar la tarifa. Intenta de nuevo.'
      setSaveError(msg)
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  // Destacado "Más rápido": usar los highlights que YA calcula el backend
  // (shipping.py _build_rate_highlights vía delivery_estimate). El frontend
  // NO recalcula con rate.delivery_date — Aveonline nunca emite ese campo, así
  // que el cálculo previo daba siempre -1 y la card jamás aparecía.
  const fastestIdx = result ? resolveFastestIdx(result.rates, result.highlights) : -1

  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none"
        onClick={() => setOpen(o => !o)}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        aria-label={open ? 'Contraer cotizador de envío' : 'Expandir cotizador de envío'}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(o => !o) }
        }}
      >
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex flex-wrap items-center gap-2">
              Cotizar Envío
              {orderId && (
                <span className="text-xs font-normal px-2 py-0.5 rounded-full bg-primary/15 text-primary border border-primary/30">
                  Pedido #{orderId.slice(-8)}
                </span>
              )}
            </CardTitle>
            <CardDescription>Origen, destino, paquete → tarifas de carriers</CardDescription>
          </div>
          {open ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        </div>
      </CardHeader>

      {open && (
        <CardContent>
          {!shippingOrigin && (
            <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-700/30 text-xs text-amber-700">
              No tienes dirección de origen configurada. Ve a{' '}
              <a href="/dashboard/settings" className="underline font-medium">Configuración</a>{' '}
              y completa la sección &quot;Dirección de origen&quot;.
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">

            {/* Origen — resumen del tenant, selector geográfico */}
            <div className="space-y-2">
              <p className="text-sm font-medium text-foreground flex items-center gap-1.5">
                <Package className="h-4 w-4 shrink-0" /> Origen
              </p>
              {shippingOrigin?.city ? (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/50 border border-border text-xs text-muted-foreground">
                  <MapPin className="h-3 w-3 shrink-0" />
                  {shippingOrigin.city}{shippingOrigin.state ? `, ${shippingOrigin.state}` : ''} — Colombia
                </div>
              ) : null}
              <GeoSelector prefix="origin" defaults={originGeo} />
            </div>

            <hr className="border-border" />

            {/* Destino — solo geográfico */}
            <div className="space-y-2">
              <p className="text-sm font-medium text-foreground flex items-center gap-1.5">
                <MapPin className="h-4 w-4 shrink-0" /> Destino
              </p>
              <GeoSelector prefix="dest" defaults={destDefaults ?? {}} />
            </div>

            <hr className="border-border" />

            <div className="space-y-3">
              <p className="text-sm font-medium text-foreground flex items-center gap-1.5"><Box className="h-4 w-4 shrink-0" /> Paquete</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Peso (kg)</Label>
                  <Input name="weight" type="number" step="0.1" min="0.1" defaultValue="1" className="h-8 text-xs" required />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Largo (cm)</Label>
                  <Input name="length" type="number" step="1" min="1" defaultValue="20" className="h-8 text-xs" required />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Ancho (cm)</Label>
                  <Input name="width" type="number" step="1" min="1" defaultValue="15" className="h-8 text-xs" required />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Alto (cm)</Label>
                  <Input name="height" type="number" step="1" min="1" defaultValue="10" className="h-8 text-xs" required />
                </div>
              </div>

              {/* Valor declarado — opcional. Default: total del pedido (si se
                  cotiza sobre uno) o $50.000 en cotización libre. Reduce la
                  divergencia entre el estimado y la guía real de Aveonline
                  (que valora sobre este monto). */}
              <div className="space-y-1">
                <Label htmlFor="declared_value" className="text-xs flex items-center gap-1.5">
                  <DollarSign className="h-3 w-3 shrink-0" /> Valor declarado (COP)
                </Label>
                <Input
                  id="declared_value"
                  name="declared_value"
                  type="number"
                  step="1000"
                  min="0"
                  inputMode="numeric"
                  defaultValue={declaredValueDefault}
                  className="h-8 text-xs"
                />
                <p className="text-[11px] text-muted-foreground">
                  {orderId
                    ? 'Tomado del total del pedido. Ajústalo si el contenido asegurable difiere.'
                    : 'Base del seguro/valoración del transportador. Por defecto $50.000.'}
                </p>
              </div>
            </div>

            {error && <p className="text-xs text-red-700">{error}</p>}

            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting
                ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Cotizando...</>
                : <><Package className="h-4 w-4 mr-2" /> Obtener tarifas</>
              }
            </Button>
          </form>

          {result && result.rates.length === 0 && (
            <div className="mt-4 p-3 rounded-lg bg-muted text-sm text-muted-foreground text-center">
              No hay carriers disponibles para esta ruta. Verifica las direcciones e intenta de nuevo.
            </div>
          )}

          {result && result.rates.length > 0 && (() => {
            const cheapest = result.rates[0]
            const fastest  = fastestIdx >= 0 ? result.rates[fastestIdx] : null
            const showFastestSeparate = fastestIdx > 0

            const RateCard = ({ rate, idx, accent, label, icon }: {
              rate: Rate; idx: number
              accent?: 'green' | 'blue'
              label?: string
              icon?: React.ReactNode
            }) => (
              <div
                onClick={() => handleSelectRate(idx)}
                role="button"
                tabIndex={0}
                aria-pressed={selectedIdx === idx}
                aria-label={`Seleccionar tarifa ${String(rate.carrier ?? 'carrier')}${
                  rate.total_price != null ? ` por $${Number(rate.total_price).toLocaleString('es-CO')}` : ''
                }`}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleSelectRate(idx) }
                }}
                className={`rounded-lg border p-3 cursor-pointer transition-all focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                  selectedIdx === idx
                    ? 'border-primary bg-primary/10'
                    : accent === 'green'
                    ? 'border-emerald-700/40 bg-emerald-500/5 hover:border-emerald-700/60'
                    : accent === 'blue'
                    ? 'border-blue-700/40 bg-blue-500/5 hover:border-blue-700/60'
                    : 'border-border hover:border-primary/40'
                }`}
              >
                {label && (
                  <div className="flex items-center gap-1 mb-1.5">
                    <span className={`inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${
                      accent === 'green'
                        ? 'bg-emerald-500/15 text-emerald-700 border-emerald-700/30'
                        : 'bg-blue-500/15 text-blue-700 border-blue-700/30'
                    }`}>
                      {icon} {label}
                    </span>
                  </div>
                )}
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex items-start gap-3 min-w-0 flex-1">
                    {/* Logo carrier (Rev. 107 Aveonline) */}
                    {rate.carrier_logo_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={rate.carrier_logo_url}
                        alt={`${rate.carrier} logo`}
                        className="h-10 w-10 rounded-md object-contain bg-white border border-border shrink-0"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center flex-wrap gap-1.5">
                        <p className="text-sm font-medium">{String(rate.carrier ?? 'Carrier')}</p>
                        {/* COD badge */}
                        {rate.cod_supported && (
                          <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border bg-amber-700/15 text-amber-700 border-amber-700/30 font-medium">
                            COD
                          </span>
                        )}
                        {/* ETA días badge */}
                        {rate.delivery_days != null && (
                          <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded-full border bg-primary/10 text-primary border-primary/30 font-medium">
                            {rate.delivery_days}d
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {String(rate.service ?? 'Servicio estándar')}
                        {rate.route_type ? ` · ${rate.route_type}` : ''}
                      </p>
                      {rate.delivery_date && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          Entrega: {new Date(rate.delivery_date as string).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })}
                        </p>
                      )}
                      {/* Breakdown costos Aveonline (si disponible).
                          stopPropagation: el div padre tiene onClick que
                          selecciona el rate; sin esto el click en "Ver
                          desglose" caería en el card y NO expandiría. */}
                      {(rate.freight_total_cop != null || rate.handling_cop != null) && (
                        <details
                          className="mt-1.5 text-xs"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <summary
                            className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors select-none"
                            onClick={(e) => e.stopPropagation()}
                          >
                            Ver desglose
                          </summary>
                          <dl className="mt-1.5 space-y-0.5 pl-2 border-l-2 border-border">
                            {rate.freight_total_cop != null && (
                              <div className="flex justify-between gap-3">
                                <dt className="text-muted-foreground">Flete</dt>
                                <dd className="font-mono">${Number(rate.freight_total_cop).toLocaleString('es-CO')}</dd>
                              </div>
                            )}
                            {rate.handling_cop != null && rate.handling_cop > 0 && (
                              <div className="flex justify-between gap-3">
                                <dt className="text-muted-foreground">Manejo</dt>
                                <dd className="font-mono">${Number(rate.handling_cop).toLocaleString('es-CO')}</dd>
                              </div>
                            )}
                            {rate.valuation_percent != null && rate.valuation_percent > 0 && (
                              <div className="flex justify-between gap-3">
                                <dt className="text-muted-foreground">
                                  Valoración {rate.valuation_percent}% sobre ${Number(rate.declared_value_cop ?? 0).toLocaleString('es-CO')}
                                </dt>
                                <dd className="font-mono">—</dd>
                              </div>
                            )}
                            {rate.weight_real_kg != null && rate.weight_volumetric_kg != null && (
                              <div className="flex justify-between gap-3 pt-1 border-t border-border/50 mt-1">
                                <dt className="text-muted-foreground">
                                  Peso real / volumétrico
                                </dt>
                                <dd className="font-mono">
                                  {rate.weight_real_kg}kg / {rate.weight_volumetric_kg}kg
                                </dd>
                              </div>
                            )}
                          </dl>
                        </details>
                      )}
                    </div>
                  </div>
                  <div className="text-left sm:text-right shrink-0">
                    {rate.total_price != null && (
                      <p className="text-lg font-bold text-primary">
                        ${Number(rate.total_price).toLocaleString('es-CO')}{' '}
                        <span className="text-xs font-normal text-muted-foreground">{String(rate.currency ?? '')}</span>
                      </p>
                    )}
                    {selectedIdx === idx && (
                      saving
                        ? <Loader2 className="h-4 w-4 animate-spin text-primary ml-auto mt-1" />
                        : saved ? <Check className="h-4 w-4 text-primary ml-auto mt-1" /> : null
                    )}
                  </div>
                </div>
              </div>
            )

            return (
              <div className="mt-5 space-y-4">
                {saveError && (
                  <div className="flex items-start gap-2 p-3 rounded-lg border border-red-700/30 bg-red-500/5 text-xs text-red-700">
                    <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                    <span>{saveError}</span>
                  </div>
                )}
                {/* Destacados */}
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-widest mb-2">Destacados</p>
                  <div className={`grid gap-2 ${showFastestSeparate ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1'}`}>
                    <RateCard
                      rate={cheapest} idx={0}
                      accent="green" label="Más económico"
                      icon={<DollarSign className="h-2.5 w-2.5" />}
                    />
                    {showFastestSeparate && fastest && (
                      <RateCard
                        rate={fastest} idx={fastestIdx}
                        accent="blue" label="Más rápido"
                        icon={<Zap className="h-2.5 w-2.5" />}
                      />
                    )}
                  </div>
                </div>

                {/* Lista completa */}
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-widest mb-2">
                    Todas las opciones ({result.rates.length})
                    {saved && <span className="ml-2 normal-case text-primary">✓ Guardada</span>}
                  </p>
                  <div className="space-y-2">
                    {result.rates.map((rate, idx) => (
                      <RateCard key={idx} rate={rate} idx={idx} />
                    ))}
                  </div>
                </div>

              </div>
            )
          })()}
        </CardContent>
      )}
    </Card>
  )
}
