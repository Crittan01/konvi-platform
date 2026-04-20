'use client'

import { useState } from 'react'
import { Loader2, Package, ChevronDown, ChevronUp, Check, MapPin, Box, Zap, DollarSign } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
// Label e Input se usan en la sección de paquete
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface ShippingOrigin {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string; dane_code?: string
}

interface Rate {
  carrier?: string
  service?: string
  total_price?: number
  currency?: string
  delivery_date?: string
  [key: string]: unknown
}

interface Props {
  shippingOrigin: ShippingOrigin | null
  orderId?:       string | null
  destDefaults?:  Record<string, string> | null
  onQuoted?:      () => void
}

function normalizeDaneCode(raw?: string): string {
  const digits = String(raw ?? '').replace(/\D/g, '')
  if (digits.length === 8 && digits.endsWith('000')) return digits.slice(0, 5)
  return digits.slice(0, 5)
}

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
    <div className="grid grid-cols-2 gap-2">
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

export default function ShippingQuoteForm({ shippingOrigin, orderId = null, destDefaults = null, onQuoted = () => {} }: Props) {
  const [open, setOpen]               = useState(!!orderId)
  const [submitting, setSubmitting]   = useState(false)
  const [error, setError]             = useState<string | null>(null)
  const [result, setResult]           = useState<{ shipmentId: string; rates: Rate[] } | null>(null)
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null)
  const [saving, setSaving]           = useState(false)
  const [saved, setSaved]             = useState(false)

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
      }],
    }

    try {
      const res = await fetch('/api/shipping/quote', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
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
        setResult({ shipmentId: data.shipment_id, rates: ratesList })
      }
    } catch {
      setError('Tiempo de espera agotado o error de red. Intenta de nuevo.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSelectRate = async (idx: number) => {
    if (!result) return
    setSelectedIdx(idx)
    setSaving(true)
    setSaved(false)
    const rate = result.rates[idx]
    try {
      const res = await fetch(`/api/shipping/${result.shipmentId}/rate`, {
        method:  'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(rate),
        signal:  AbortSignal.timeout(10000),
      })
      if (res.ok) { setSaved(true); onQuoted() }
    } finally {
      setSaving(false)
    }
  }

  // Índice del más rápido (fecha de entrega más próxima, ignorando nulls)
  const fastestIdx = result
    ? result.rates.reduce((best, r, i) => {
        if (!r.delivery_date) return best
        if (best === -1) return i
        return r.delivery_date < result.rates[best].delivery_date! ? i : best
      }, -1)
    : -1

  return (
    <Card>
      <CardHeader className="cursor-pointer select-none" onClick={() => setOpen(o => !o)}>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
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
            <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-xs text-amber-400">
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
              <div className="grid grid-cols-2 gap-2">
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
            </div>

            {error && <p className="text-xs text-red-400">{error}</p>}

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
                className={`rounded-lg border p-3 cursor-pointer transition-all ${
                  selectedIdx === idx
                    ? 'border-primary bg-primary/10'
                    : accent === 'green'
                    ? 'border-emerald-500/40 bg-emerald-500/5 hover:border-emerald-500/60'
                    : accent === 'blue'
                    ? 'border-blue-500/40 bg-blue-500/5 hover:border-blue-500/60'
                    : 'border-border hover:border-primary/40'
                }`}
              >
                {label && (
                  <div className="flex items-center gap-1 mb-1.5">
                    <span className={`inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${
                      accent === 'green'
                        ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                        : 'bg-blue-500/15 text-blue-400 border-blue-500/30'
                    }`}>
                      {icon} {label}
                    </span>
                  </div>
                )}
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{String(rate.carrier ?? 'Carrier')}</p>
                    <p className="text-xs text-muted-foreground">{String(rate.service ?? 'Servicio estándar')}</p>
                    {rate.delivery_date && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Entrega: {new Date(rate.delivery_date as string).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: 'numeric' })}
                      </p>
                    )}
                  </div>
                  <div className="text-right shrink-0">
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
                {/* Destacados */}
                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-widest mb-2">Destacados</p>
                  <div className={`grid gap-2 ${showFastestSeparate ? 'grid-cols-2' : 'grid-cols-1'}`}>
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
