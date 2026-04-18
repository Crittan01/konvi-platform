'use client'

import { useState } from 'react'
import { Loader2, Package, ChevronDown, ChevronUp, Check, MapPin, Box } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface ShippingOrigin {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string
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
  onQuoted?: () => void
}

// ─── AddressFields ────────────────────────────────────────────────────────────

function AddressFields({
  prefix, title, defaults = {},
}: {
  prefix: string
  title: React.ReactNode
  defaults?: Record<string, string>
}) {
  const defaultDpto = DEPARTAMENTOS.find(d => d.nombre === defaults.state) ?? null
  const [dptoCode, setDptoCode]           = useState(defaultDpto?.codigo ?? '')
  const [city, setCity]                   = useState(defaults.city ?? '')
  const [municipioCodigo, setMuniCodigo]  = useState('')

  const municipios = dptoCode ? getMunicipiosByDpto(dptoCode) : []
  const dptoNombre = DEPARTAMENTOS.find(d => d.codigo === dptoCode)?.nombre ?? ''
  // Código DANE 8 dígitos: código municipio (5) + "000"
  const daneCode = municipioCodigo ? `${municipioCodigo}000` : ''

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-foreground flex items-center gap-1.5">{title}</p>
      <div className="grid grid-cols-2 gap-2">

        <div className="space-y-1">
          <Label className="text-xs">Nombre</Label>
          <Input name={`${prefix}_name`} defaultValue={defaults.name ?? ''} placeholder="Juan Pérez" className="h-8 text-xs" required />
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Teléfono</Label>
          <Input name={`${prefix}_phone`} defaultValue={defaults.phone ?? ''} placeholder="+573000000000" className="h-8 text-xs" required />
        </div>

        <div className="col-span-2 space-y-1">
          <Label className="text-xs">Dirección (Calle/Cra)</Label>
          <Input name={`${prefix}_street`} defaultValue={defaults.street ?? ''} placeholder="Cra 15 # 100-20" className="h-8 text-xs" required />
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Número / Apto</Label>
          <Input name={`${prefix}_number`} defaultValue={defaults.number ?? ''} placeholder="Apto 201" className="h-8 text-xs" />
        </div>

        {/* postalCode se deriva del código DANE al seleccionar municipio */}

        {/* Departamento — select DANE */}
        <div className="space-y-1">
          <Label className="text-xs">Departamento</Label>
          <input type="hidden" name={`${prefix}_state`} value={dptoNombre} />
          <Select value={dptoCode} onValueChange={(v) => { setDptoCode(v); setCity('') }}>
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

        {/* Ciudad / Municipio — select DANE dependiente */}
        <div className="space-y-1">
          <Label className="text-xs">Ciudad / Municipio</Label>
          <input type="hidden" name={`${prefix}_city`} value={city} />
          <input type="hidden" name={`${prefix}_dane_code`} value={daneCode} />
          <Select
            value={city}
            onValueChange={(v) => {
              const muni = municipios.find(m => m.nombre === v)
              setCity(v)
              setMuniCodigo(muni?.codigo ?? '')
            }}
            disabled={!dptoCode}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder={dptoCode ? 'Seleccionar...' : 'Elige dpto. primero'} />
            </SelectTrigger>
            <SelectContent>
              {municipios.map(m => (
                <SelectItem key={m.codigo} value={m.nombre}>{m.nombre}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Código DANE</Label>
          <Input readOnly value={daneCode} placeholder="Auto desde municipio" className="h-8 text-xs text-muted-foreground bg-muted cursor-default" />
        </div>

        <div className="space-y-1">
          <Label className="text-xs">País</Label>
          <input type="hidden" name={`${prefix}_country`} value="CO" />
          <Input readOnly value="Colombia" className="h-8 text-xs text-muted-foreground bg-muted cursor-default" />
        </div>

      </div>
    </div>
  )
}

function readAddress(formData: FormData, prefix: string) {
  const daneCode = formData.get(`${prefix}_dane_code`) as string
  return {
    name:       formData.get(`${prefix}_name`)    as string,
    phone:      formData.get(`${prefix}_phone`)   as string,
    street:     formData.get(`${prefix}_street`)  as string,
    number:     formData.get(`${prefix}_number`)  as string,
    city:       formData.get(`${prefix}_city`)    as string,
    state:      formData.get(`${prefix}_state`)   as string,
    country:    formData.get(`${prefix}_country`) as string,
    postalCode: daneCode,  // Para CO: código DANE (ej. "11001000")
    dane_code:  daneCode,
    company:    formData.get(`${prefix}_company`) as string || undefined,
  }
}

// ─── Componente ───────────────────────────────────────────────────────────────

export default function ShippingQuoteForm({ shippingOrigin, onQuoted = () => {} }: Props) {
  const [open, setOpen]           = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [result, setResult]       = useState<{ shipmentId: string; rates: Rate[] } | null>(null)
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null)
  const [saving, setSaving]       = useState(false)
  const [saved, setSaved]         = useState(false)

  const originDefaults: Record<string, string> = shippingOrigin ? {
    name:       shippingOrigin.name        ?? '',
    phone:      shippingOrigin.phone       ?? '',
    street:     shippingOrigin.street      ?? '',
    city:       shippingOrigin.city        ?? '',
    state:      shippingOrigin.state       ?? '',
    postalCode: shippingOrigin.postal_code ?? '',
    country:    shippingOrigin.country     ?? 'CO',
    company:    shippingOrigin.company     ?? '',
  } : {}

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    setResult(null)
    setSelectedIdx(null)
    setSaved(false)

    const formData = new FormData(e.currentTarget)

    const origin = readAddress(formData, 'origin')
    const dest   = readAddress(formData, 'dest')

    if (!origin.state || !origin.city) { setError('Completa el departamento y ciudad de origen.'); setSubmitting(false); return }
    if (!dest.state   || !dest.city)   { setError('Completa el departamento y ciudad de destino.'); setSubmitting(false); return }

    const payload = {
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
        setResult({ shipmentId: data.shipment_id, rates: ratesList })
      }
    } catch {
      setError('Error de red. Verifica la conexión.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSelectRate = async (idx: number) => {
    if (!result) return
    setSelectedIdx(idx)
    setSaving(true)
    setSaved(false)

    const rate     = result.rates[idx]
    const supabase = createClient()

    await supabase.from('shipments').update({
      selected_rate:      rate,
      carrier:            String(rate.carrier  ?? ''),
      service:            String(rate.service  ?? ''),
      estimated_delivery: rate.delivery_date ? String(rate.delivery_date) : null,
    }).eq('id', result.shipmentId)

    setSaving(false)
    setSaved(true)
    onQuoted()
  }

  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Cotizar Envío</CardTitle>
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
            <AddressFields prefix="origin" title={<><Package className="h-4 w-4 shrink-0" /> Origen — desde dónde envías</>} defaults={originDefaults} />

            <hr className="border-border" />

            <AddressFields prefix="dest" title={<><MapPin className="h-4 w-4 shrink-0" /> Destino — a dónde envías</>} />

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
              {submitting ? (
                <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Cotizando...</>
              ) : (
                <><Package className="h-4 w-4 mr-2" /> Obtener tarifas</>
              )}
            </Button>
          </form>

          {result && result.rates.length === 0 && (
            <div className="mt-4 p-3 rounded-lg bg-muted text-sm text-muted-foreground text-center">
              No hay carriers disponibles para esta ruta. Verifica las direcciones e intenta de nuevo.
            </div>
          )}

          {result && result.rates.length > 0 && (
            <div className="mt-5 space-y-3">
              <p className="text-sm font-medium text-foreground">
                {result.rates.length} opciones disponibles
                {saved && <span className="ml-2 text-xs text-primary">✓ Tarifa seleccionada guardada</span>}
              </p>
              {result.rates.map((rate, idx) => (
                <div
                  key={idx}
                  className={`rounded-lg border p-3 cursor-pointer transition-all ${
                    selectedIdx === idx
                      ? 'border-primary bg-primary/10'
                      : 'border-border hover:border-primary/40'
                  }`}
                  onClick={() => handleSelectRate(idx)}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium">{String(rate.carrier ?? 'Carrier')}</p>
                      <p className="text-xs text-muted-foreground">{String(rate.service ?? 'Servicio estándar')}</p>
                      {rate.delivery_date && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          Entrega est.: {String(rate.delivery_date)}
                        </p>
                      )}
                    </div>
                    <div className="text-right">
                      {rate.total_price != null && (
                        <p className="text-lg font-bold text-primary">
                          ${Number(rate.total_price).toFixed(2)}{' '}
                          <span className="text-xs font-normal text-muted-foreground">{String(rate.currency ?? '')}</span>
                        </p>
                      )}
                      {selectedIdx === idx && (
                        saving ? (
                          <Loader2 className="h-4 w-4 animate-spin text-primary ml-auto mt-1" />
                        ) : saved ? (
                          <Check className="h-4 w-4 text-primary ml-auto mt-1" />
                        ) : null
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}
